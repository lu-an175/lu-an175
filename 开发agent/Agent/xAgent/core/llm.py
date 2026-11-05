# -*- coding: utf-8 -*-
"""
xAgent.core.llm —— LLM Provider 抽象层（可选）。

接口设计：Provider 只负责接收 messages 返回 response，不关心 tools 怎么调用。
tui 层在收到 response 后自行决定如何渲染工具调用卡片。

三种模式：
  MockProvider       默认 —— 根据用户输入的关键词自动选择本地工具
  DeepSeekProvider   deepseek-chat（/v1/chat/completions，含 tool_calls）
  OpenAIProvider     openai-compatible（同上）
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol


# ---------- 数据模型 ----------

@dataclass
class ToolCall:
    """LLM 请求调用的工具。"""
    id: str          # tool_call_id（用于后续回传结果）
    name: str
    arguments: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMMessage:
    """对话历史中的一条消息。"""
    role: str                       # "user" / "assistant" / "tool" / "system"
    content: str = ""
    tool_calls: Optional[List[ToolCall]] = None      # assistant 消息带工具请求
    tool_call_id: Optional[str] = None               # tool 消息关联哪个请求


# ---------- Provider 接口 ----------

class LLMProvider(Protocol):
    """LLM 提供者抽象协议。"""

    def chat(
        self,
        messages: List[LLMMessage],
        tools_schema: List[Dict[str, Any]],
    ) -> LLMMessage:
        """发送完整对话历史给 LLM，返回 assistant 回复。"""
        ...


# ---------- Mock Provider（默认，不需要 API key） ----------

class MockProvider:
    """
    关键词匹配模式 —— 根据用户输入自动选择本地工具。
    
    匹配规则（简化版，够 demo 用）：
      "工作目录" / "cwd"                  → get_current_working_directory
      "列出" / "目录" / "list"              → list_directory
      "类型" / "file type"                  → get_file_type
      "读取" / "内容" / "read"              → read_file
      "创建文件" / "新建文件" / "create"    → create_file
      "写" / "编辑" / "write"               → write_file
      "创建目录" / "新文件夹"               → create_directory
      "删目录" / "删除文件夹"               → delete_directory
      "删文件" / "remove file"              → delete_file
      "重命名" / "rename"                   → rename_item
      "搜索" / "search" / "最新"            → searchWeb
      "获取网页" / "抓取" / 含网址           → fetchWeb
      "执行命令" / "运行命令" / "命令行"     → runCli
      否则                                  → 直接回复文本，不调工具
    """

    KEYWORD_TOOL_MAP: Dict[str, str] = {
        # 网页正文抓取优先：消息里出现 URL 时优先走 fetchWeb
        "fetchWeb": "fetchWeb",
        "获取网页": "fetchWeb",
        "网页正文": "fetchWeb",
        "抓取": "fetchWeb",
        "fetch": "fetchWeb",
        "http://": "fetchWeb",
        "https://": "fetchWeb",
        # 本地命令执行
        "runCli": "runCli",
        "执行命令": "runCli",
        "运行命令": "runCli",
        "命令行": "runCli",
        "执行程序": "runCli",
        # 联网搜索优先匹配，避免被 "读取/内容" 等关键词截走
        "searchWeb": "searchWeb",
        "搜索": "searchWeb",
        "搜一下": "searchWeb",
        "搜一搜": "searchWeb",
        "查一下": "searchWeb",
        "联网": "searchWeb",
        "上网": "searchWeb",
        "新闻": "searchWeb",
        "search": "searchWeb",
        "cwd": "get_current_working_directory",
        "工作目录": "get_current_working_directory",
        "list": "list_directory",
        "列出": "list_directory",
        "目录内容": "list_directory",
        "类型": "get_file_type",
        "mime": "get_file_type",
        "read": "read_file",
        "读取": "read_file",
        "内容": "read_file",
        "create_file": "create_file",
        "创建文件": "create_file",
        "新建文件": "create_file",
        "write": "write_file",
        "编辑": "write_file",
        "写": "write_file",
        "create_directory": "create_directory",
        "创建目录": "create_directory",
        "新文件夹": "create_directory",
        "delete_directory": "delete_directory",
        "删目录": "delete_directory",
        "删除文件夹": "delete_directory",
        "delete_file": "delete_file",
        "删文件": "delete_file",
        "rename": "rename_item",
        "重命名": "rename_item",
    }

    def __init__(self) -> None:
        self._counter = 0

    def chat(
        self,
        messages: List[LLMMessage],
        tools_schema: List[Dict[str, Any]],
    ) -> LLMMessage:
        # 取最后一条 user 消息做关键词匹配
        last_user = ""
        for m in reversed(messages):
            if m.role == "user":
                last_user = m.content
                break

        tool_name: Optional[str] = None
        lower = last_user.lower()
        for kw, tname in self.KEYWORD_TOOL_MAP.items():
            if kw.lower() in lower:
                tool_name = tname
                break

        self._counter += 1
        call_id = f"call_{self._counter:04d}"

        if tool_name is None:
            # 纯文本回复 —— 做一些内置小工具（Practice01 风格）
            inp = last_user.strip()

            # isLeapYear 快速计算
            if any(k in lower for k in ("闰年", "leap", "isyear")):
                year = None
                import re as _re
                ym = _re.search(r"(\d{4})", inp)
                if ym:
                    year = int(ym.group(1))
                else:
                    from datetime import date
                    year = date.today().year
                leap = (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)
                ans = f"{year} 年{'是' if leap else '不是'}闰年。"
                return LLMMessage(role="assistant", content=ans)

            # cwd 快速回答
            if any(k in lower for k in ("你是谁", "who are you", "介绍一下", "你好", "hello", "hi")):
                return LLMMessage(
                    role="assistant",
                    content=(
                        "我是 xAgent，一个文件操作 Agent。\n\n"
                        "我能做：\n"
                        "  · 列出目录 / 读取文件 / 获取类型\n"
                        "  · 创建 / 编辑 / 重命名 / 删除 文件\n"
                        "  · 创建 / 删除 目录\n\n"
                        "试试：'列出当前目录'、'读取 README.md 的内容'、"
                        "'重命名 a.txt 为 b.txt'。\n"
                        "或者输入 /help 查看全部命令。"
                    ),
                )

            # 通用兜底
            return LLMMessage(
                role="assistant",
                content=(
                    "我是 xAgent MockProvider。没有匹配到工具关键词，我也不会凭空编答案。\n\n"
                    "试试：'列出当前目录'、'读取 xxx.txt 的内容'、"
                    "'创建文件 test.txt'、'重命名 abc.txt 为 xyz.txt'。"
                ),
            )

        # 触发工具调用
        args: Dict[str, Any] = {}
        # 对有 file_path / dir_path 参数的工具，尝试从用户话里抓路径
        if tool_name in ("read_file", "delete_file", "get_file_type", "rename_item"):
            import re
            m = re.search(r'[\w./\\\-]+\.[a-zA-Z0-9]+', last_user)
            if m:
                args["file_path"] = m.group(0)
        if tool_name == "rename_item":
            args.pop("file_path", None)
            # 找两个路径
            parts = re.split(r'重命名|rename|为|->|到', last_user, maxsplit=1)
            if len(parts) == 2:
                m1 = re.search(r'[\w./\\\-]+\.[a-zA-Z0-9]+', parts[0])
                m2 = re.search(r'[\w./\\\-]+', parts[1])
                if m1:
                    args["source_path"] = m1.group(0)
                if m2:
                    args["new_name"] = m2.group(0).strip()
        if tool_name == "searchWeb":
            args.setdefault("query", last_user.strip())
        if tool_name == "fetchWeb":
            import re
            m = re.search(r'https?://[^\s"\'<>）)]+', last_user)
            if m:
                args["url"] = m.group(0).rstrip('.,;，。')
        if tool_name == "runCli":
            import re
            import shlex as _shlex
            cleaned = re.sub(
                r'执行命令|运行命令|命令行|执行程序|runcli', ' ', last_user, flags=re.I
            ).strip()
            try:
                tokens = _shlex.split(cleaned)
            except ValueError:
                tokens = cleaned.split()
            if tokens:
                args["command"] = tokens[0]
                args["args"] = tokens[1:]
        if tool_name == "list_directory" and "path" not in last_user.lower() and "目录" not in last_user:
            args["path"] = "."

        # 给必填参数做默认填充（不然 ToolService 会报参数错误）
        for param, default in _DEFAULT_ARG_FALLBACK.get(tool_name, {}).items():
            args.setdefault(param, default)

        return LLMMessage(
            role="assistant",
            content="",
            tool_calls=[ToolCall(id=call_id, name=tool_name, arguments=args)],
        )


_DEFAULT_ARG_FALLBACK: Dict[str, Dict[str, Any]] = {
    "list_directory": {"path": "."},
    "get_file_type": {"file_path": "."},
    "read_file": {"file_path": "."},
    "create_file": {"file_path": "new.txt", "content": ""},
    "write_file": {"file_path": "new.txt", "content": ""},
    "create_directory": {"dir_path": "new_dir"},
    "delete_directory": {"dir_path": "new_dir", "force": "true"},
    "delete_file": {"file_path": "new.txt"},
    "rename_item": {"source_path": "old.txt", "new_name": "new.txt"},
    "searchWeb": {"query": ""},
    "fetchWeb": {"url": ""},
    "runCli": {"command": "", "args": []},
}


# ---------- OpenAI-compatible Provider（占位，用真实 API key 时启用） ----------

class OpenAICompatibleProvider:
    """
    openai-compatible endpoint（deepseek、openrouter、ollama 都走这个协议）。

    用法：
      provider = OpenAICompatibleProvider(
          api_key="sk-xxx",
          base_url="https://api.deepseek.com/v1",
          model="deepseek-chat",
      )
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.deepseek.com/v1",
        model: str = "deepseek-chat",
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model

    def chat(
        self,
        messages: List[LLMMessage],
        tools_schema: List[Dict[str, Any]],
    ) -> LLMMessage:
        import urllib.error
        import urllib.request

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": [_to_api_msg(m) for m in messages],
            "tools": tools_schema,
            "tool_choice": "auto",
        }
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        req = urllib.request.Request(url, data=data, headers=headers)
        try:
            with urllib.request.urlopen(req) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "ignore")[:400]
            raise RuntimeError(
                f"HTTP {exc.code} {exc.reason} | {detail}"
            ) from exc

        choice = body["choices"][0]["message"]
        tool_calls: List[ToolCall] | None = None
        if choice.get("tool_calls"):
            tool_calls = [
                ToolCall(
                    id=tc["id"],
                    name=tc["function"]["name"],
                    arguments=json.loads(tc["function"]["arguments"]),
                )
                for tc in choice["tool_calls"]
            ]
        return LLMMessage(
            role="assistant",
            content=choice.get("content") or "",
            tool_calls=tool_calls,
        )


def _to_api_msg(m: LLMMessage) -> Dict[str, Any]:
    """内部 LLMMessage → OpenAI API 格式。"""
    base: Dict[str, Any] = {"role": m.role}
    if m.content:
        base["content"] = m.content
    if m.role == "assistant" and m.tool_calls:
        base["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.name,
                    "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                },
            }
            for tc in m.tool_calls
        ]
    if m.role == "tool" and m.tool_call_id:
        base["tool_call_id"] = m.tool_call_id
    # 空 content 也要传（API 要求）
    base.setdefault("content", "")
    return base
