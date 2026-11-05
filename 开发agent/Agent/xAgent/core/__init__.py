# -*- coding: utf-8 -*-
"""
xAgent.core —— 核心逻辑层，零 UI 依赖。

对外暴露 ToolService 门面，以及 TOOLS / call_tool 两个兼容旧入口。
"""

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
from .skills import (
    SkillInfo,
    SkillRegistry,
    build_skill_prompt,
    discover_skills,
    get_skill_registry,
    load_skill,
    reset_skill_registry,
)
from .registry import TOOLS, call_tool, ToolService

__all__ = [
    # 类型
    "ToolResult",
    "ToolInfo",
    # 工具函数
    "get_current_working_directory",
    "list_directory",
    "get_file_type",
    "read_file",
    "create_file",
    "write_file",
    "create_directory",
    "delete_directory",
    "delete_file",
    "rename_item",
    "search_web",
    "fetch_web",
    "run_cli",
    # Skill
    "SkillInfo",
    "SkillRegistry",
    "discover_skills",
    "get_skill_registry",
    "reset_skill_registry",
    "build_skill_prompt",
    "load_skill",
    # 注册表 & 门面
    "TOOLS",
    "call_tool",
    "ToolService",
]
