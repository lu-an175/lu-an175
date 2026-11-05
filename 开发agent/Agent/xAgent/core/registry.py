# -*- coding: utf-8 -*-
"""
xAgent.core.registry —— 工具注册表 + 分发器 + 门面类。

设计要点：
  - ToolService 是给 UI 层用的**唯一入口**，UI 不应直接 import tools.py 的函数
  - TOOLS dict 和 call_tool 保留以兼容旧代码
  - 类型转换 / 参数校验 / 异常捕获都在此层完成，tools.py 保持纯净
"""

from __future__ import annotations

import json
import shlex
from typing import Any, Callable, Dict, List

from .types import ToolResult, ToolInfo
from .tools import (
    get_current_working_directory,
    list_directory,
    get_file_type,
    read_file,
    create_file,
    write_file,
    create_directory,
    delete_directory,
    delete_file,
    rename_item,
    search_web,
    fetch_web,
    run_cli,
)
from .skills import load_skill


# ---------- 工具注册表（兼容旧版 dict-of-dict 结构） ----------

TOOL_META: Dict[str, ToolInfo] = {
    "get_current_working_directory": ToolInfo(
        name="get_current_working_directory",
        description="获取当前工作目录",
        parameters={},
    ),
    "list_directory": ToolInfo(
        name="list_directory",
        description="列出指定目录下所有文件和子目录",
        parameters={"path": "str: 目录路径（可选，默认为当前目录）"},
    ),
    "get_file_type": ToolInfo(
        name="get_file_type",
        description="获取指定文件的文件类型",
        parameters={"file_path": "str: 文件路径（必需）"},
    ),
    "read_file": ToolInfo(
        name="read_file",
        description="获取指定文件的内容（仅支持纯文本格式文件）",
        parameters={"file_path": "str: 文件路径（必需）"},
    ),
    "create_file": ToolInfo(
        name="create_file",
        description="创建指定的目录和文件名创建新文件",
        parameters={
            "file_path": "str: 文件路径（必需）",
            "content": "str: 文件初始内容（可选，默认为空）",
        },
    ),
    "write_file": ToolInfo(
        name="write_file",
        description="编辑指定文件的内容（仅支持纯文本格式文件）",
        parameters={
            "file_path": "str: 文件路径（必需）",
            "content": "str: 要写入的新内容（必需）",
            "mode": "str: 写入模式 'overwrite' 或 'append'（可选，默认 overwrite）",
        },
    ),
    "create_directory": ToolInfo(
        name="create_directory",
        description="创建新目录",
        parameters={"dir_path": "str: 目录路径（必需）"},
    ),
    "delete_directory": ToolInfo(
        name="delete_directory",
        description="删除目录（非空）",
        parameters={
            "dir_path": "str: 目录路径（必需）",
            "force": "bool: 是否强制删除非空目录（可选，默认 True）",
        },
    ),
    "delete_file": ToolInfo(
        name="delete_file",
        description="删除文件",
        parameters={"file_path": "str: 文件路径（必需）"},
    ),
    "rename_item": ToolInfo(
        name="rename_item",
        description="重命名文件或目录",
        parameters={
            "source_path": "str: 源文件或目录路径（必需）",
            "new_name": "str: 新名称，只提供名称不含路径（必需）",
        },
    ),
    "searchWeb": ToolInfo(
        name="searchWeb",
        description="联网搜索，获取互联网最新信息（返回摘要与参考来源）",
        parameters={
            "query": "str: 搜索关键词或问题（必需）",
            "top_k": "int: 返回网页条数，1-10（可选，默认 10）",
        },
    ),
    "fetchWeb": ToolInfo(
        name="fetchWeb",
        description="获取指定网页的正文内容（提取正文并转为 Markdown，返回正文与原始 URL）",
        parameters={
            "url": "str: 网页地址，必须以 http:// 或 https:// 开头（必需）",
        },
    ),
    "runCli": ToolInfo(
        name="runCli",
        description="执行本地命令行程序（返回标准输出、标准错误与退出码）",
        parameters={
            "command": "str: 程序名称或路径，如 python、git、curl（必需）",
            "args": 'list[str]: 参数列表，如 ["-c", "print(1)"]（可选，默认空）',
            "timeout": "int: 超时秒数，1-120（可选，默认 30）",
        },
    ),
    "loadSkill": ToolInfo(
        name="loadSkill",
        description=(
            "加载 Skill 的完整说明：仅提供 name 时返回该 Skill 的 SKILL.md 全文；"
            "提供 filename 时读取该 Skill 目录内的附加文件（不重复加载 SKILL.md）"
        ),
        parameters={
            "name": "str: Skill 名称（必需）",
            "filename": "str: 需要加载的 Skill 文件路径或名称（可选）",
        },
    ),
}

# 工具函数绑定
TOOL_FUNCS: Dict[str, Callable[..., dict]] = {
    "get_current_working_directory": get_current_working_directory,
    "list_directory": list_directory,
    "get_file_type": get_file_type,
    "read_file": read_file,
    "create_file": create_file,
    "write_file": write_file,
    "create_directory": create_directory,
    "delete_directory": delete_directory,
    "delete_file": delete_file,
    "rename_item": rename_item,
    "searchWeb": search_web,
    "fetchWeb": fetch_web,
    "runCli": run_cli,
    "loadSkill": load_skill,
}

# 兼容旧版 TOOLS dict 格式
TOOLS: Dict[str, Dict[str, Any]] = {
    name: {
        "func": TOOL_FUNCS[name],
        "description": meta.description,
        "parameters": dict(meta.parameters),
    }
    for name, meta in TOOL_META.items()
}


# ---------- 类型转换 ----------

def _convert_kwargs(tool_name: str, kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """根据 ToolInfo.parameters 声明的类型字符串做轻量转换。"""
    meta = TOOL_META[tool_name]
    converted: Dict[str, Any] = {}
    for key, value in kwargs.items():
        param_type = meta.parameters.get(key, "")
        if "list" in param_type.lower():
            converted[key] = _to_list(value)
        elif "bool" in param_type.lower():
            if isinstance(value, str):
                converted[key] = value.lower() in ('true', '1', 'yes')
            else:
                converted[key] = bool(value)
        elif "int" in param_type.lower():
            try:
                converted[key] = int(value)
            except (ValueError, TypeError):
                converted[key] = value
        else:
            converted[key] = value
    return converted


def _to_list(value: Any) -> list:
    """把 LLM 传来的 list 参数归一化：支持 list / JSON 数组字符串 / 空格分隔字符串。"""
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    return [str(item) for item in parsed]
            except json.JSONDecodeError:
                pass
        try:
            return shlex.split(text)
        except ValueError:
            return text.split()
    return value


# ---------- 旧版 call_tool 入口（dict -> dict） ----------

def call_tool(tool_name: str, **kwargs: Any) -> dict:
    """调用工具，返回 dict（与旧版接口完全兼容）。"""
    result = call_tool_result(tool_name, **kwargs)
    return result.to_dict()


def call_tool_result(tool_name: str, **kwargs: Any) -> ToolResult:
    """调用工具，返回 ToolResult（UI 层推荐用这个）。"""
    if tool_name not in TOOL_FUNCS:
        return ToolResult.fail(f"未知工具: {tool_name}")

    try:
        converted = _convert_kwargs(tool_name, kwargs)
        raw = TOOL_FUNCS[tool_name](**converted)
        # tools.py 函数已经返回 dict，直接转 ToolResult
        return ToolResult.from_dict(raw)
    except TypeError as e:
        return ToolResult.fail(f"参数错误: {str(e)}")
    except Exception as e:
        return ToolResult.fail(str(e))


# ---------- ToolService 门面（UI 层唯一入口） ----------

class ToolService:
    """
    面向 UI 层的工具服务门面。

    未来 web / desktop / mobile 都只 import 这个类，
    不依赖 TOOLS / call_tool / 任何 tools.py 内部函数。
    """

    @staticmethod
    def list_tools() -> List[ToolInfo]:
        """获取所有工具的元数据列表（用于渲染工具选择器、参数表单）。"""
        return list(TOOL_META.values())

    @staticmethod
    def get_tool_info(name: str) -> ToolInfo | None:
        """按名称查工具元数据。"""
        return TOOL_META.get(name)

    @staticmethod
    def call(tool_name: str, **kwargs: Any) -> ToolResult:
        """调用工具，返回 ToolResult。"""
        return call_tool_result(tool_name, **kwargs)

    @staticmethod
    def call_dict(tool_name: str, **kwargs: Any) -> dict:
        """调用工具，返回 dict（序列化到网络时用）。"""
        return call_tool(tool_name, **kwargs)
