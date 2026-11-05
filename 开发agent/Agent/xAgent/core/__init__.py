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
from .config import (
    AppConfig,
    ConfigBootstrap,
    ensure_config_file,
    get_config,
    load_config,
    primary_config_path,
    reload_config,
    resolve_config_path,
)
from .mcp import (
    MCPError,
    MCPManager,
    MCPServerConfig,
    MCPServerState,
    MCPTool,
)
from .session import (
    KIND_AGENTS_MD,
    KIND_MESSAGE,
    SessionMeta,
    build_agents_md_message,
    delete_session,
    find_agents_md,
    list_sessions,
    load_agents_md,
    load_session,
    new_session_id,
    save_session,
    session_root_with,
)
from .context import (
    ARCHIVE_ROOT,
    COMPACT_THRESHOLD,
    COMPACT_TARGET_TOKENS,
    CompactionResult,
    ContextUsage,
    archive_dir,
    build_compaction_messages,
    compact_messages,
    estimate_messages_tokens,
    estimate_tokens,
    format_tokens,
    list_archives,
    load_archive,
    measure_usage,
    new_archive_id,
    recall_context,
    resolve_context_window,
    save_archive,
)

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
    # 上下文管理
    "ARCHIVE_ROOT",
    "COMPACT_THRESHOLD",
    "COMPACT_TARGET_TOKENS",
    "CompactionResult",
    "ContextUsage",
    "archive_dir",
    "build_compaction_messages",
    "compact_messages",
    "estimate_messages_tokens",
    "estimate_tokens",
    "format_tokens",
    "list_archives",
    "load_archive",
    "measure_usage",
    "new_archive_id",
    "recall_context",
    "resolve_context_window",
    "save_archive",
    # 配置
    "AppConfig",
    "ConfigBootstrap",
    "ensure_config_file",
    "get_config",
    "load_config",
    "primary_config_path",
    "reload_config",
    "resolve_config_path",
    # 会话
    "KIND_AGENTS_MD",
    "KIND_MESSAGE",
    "SessionMeta",
    "build_agents_md_message",
    "delete_session",
    "find_agents_md",
    "list_sessions",
    "load_agents_md",
    "load_session",
    "new_session_id",
    "save_session",
    "session_root_with",
    # MCP
    "MCPError",
    "MCPManager",
    "MCPServerConfig",
    "MCPServerState",
    "MCPTool",
]
