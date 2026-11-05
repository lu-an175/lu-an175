# -*- coding: utf-8 -*-
"""
xAgent.tui.commands —— 斜杠命令清单与补全匹配（纯数据，不依赖 Textual）。

放在这里的好处：
    命令补全面板、/help 输出、文档三处共用同一份定义，
    不会出现「help 里写了但没实现」那种尴尬。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class SlashCommand:
    """一条斜杠命令。"""

    name: str                     # 主名，含斜杠，如 "/new"
    description: str              # 一句话说明（补全面板里显示）
    usage: str = ""               # 用法，如 "/new [标题]"
    aliases: Tuple[str, ...] = () # 别名（含斜杠）
    group: str = "通用"

    @property
    def display_usage(self) -> str:
        return self.usage or self.name


#: 命令总表 —— 顺序即补全面板的默认顺序
COMMANDS: Tuple[SlashCommand, ...] = (
    SlashCommand(
        "/help", "显示帮助与全部命令", "/help", ("/?",), "通用",
    ),
    SlashCommand(
        "/new", "新建会话（自动保存当前会话）", "/new [标题]", ("/clear",), "会话",
    ),
    SlashCommand(
        "/save", "保存当前会话到 .agents/sessions/", "/save [标题]", (), "会话",
    ),
    SlashCommand(
        "/resume", "列出历史会话，↑↓ 选择、回车恢复、Esc 取消", "/resume", ("/sessions",), "会话",
    ),
    SlashCommand(
        "/quit", "退出 xAgent", "/quit", ("/exit", "/q"), "会话",
    ),
    SlashCommand(
        "/compact", "压缩上下文（归档原始记录 + 生成摘要）", "/compact", (), "上下文",
    ),
    SlashCommand(
        "/tools", "列出全部可用工具（含 MCP 工具）", "/tools", (), "上下文",
    ),
    SlashCommand(
        "/mcp", "查看 MCP 服务器与可用工具；/mcp reload 重连", "/mcp [reload]", (), "上下文",
    ),
    SlashCommand(
        "/agents", "查看 AGENTS.md 的项目指令注入状态", "/agents", (), "上下文",
    ),
    SlashCommand(
        "/model", "查看当前模型、接口与上下文窗口", "/model", (), "信息",
    ),
    SlashCommand(
        "/config", "查看配置文件路径与关键配置项", "/config", (), "信息",
    ),
    SlashCommand(
        "/cwd", "显示当前工作目录", "/cwd", (), "信息",
    ),
    SlashCommand(
        "/export", "把当前会话导出为 Markdown", "/export [文件路径]", (), "会话",
    ),
)


def all_commands() -> Tuple[SlashCommand, ...]:
    return COMMANDS


def find_command(text: str) -> Optional[SlashCommand]:
    """按名字或别名精确查找（忽略大小写与首尾空格）。"""
    head = (text or "").strip().split(maxsplit=1)[0].lower() if (text or "").strip() else ""
    if not head.startswith("/"):
        return None
    for command in COMMANDS:
        if head == command.name.lower():
            return command
        if head in (alias.lower() for alias in command.aliases):
            return command
    return None


def filter_commands(prefix: str, limit: int = 8) -> List[SlashCommand]:
    """
    补全面板用：按前缀匹配命令。

    排序规则：名字前缀命中 > 别名前缀命中 > 描述里包含，越长越靠后。
    """
    text = (prefix or "").strip().lower()
    if not text.startswith("/"):
        return []
    # 已经敲空格 = 在填参数了，别再弹补全（这里要看原文，不能先 strip）
    if " " in (prefix or ""):
        return []
    if text == "/":
        return list(COMMANDS)[:limit]

    exact_prefix: List[SlashCommand] = []
    alias_prefix: List[SlashCommand] = []
    contains: List[SlashCommand] = []

    for command in COMMANDS:
        if command.name.lower().startswith(text):
            exact_prefix.append(command)
            continue
        if any(alias.lower().startswith(text) for alias in command.aliases):
            alias_prefix.append(command)
            continue
        if text[1:] and text[1:] in command.description.lower():
            contains.append(command)

    return (exact_prefix + alias_prefix + contains)[:limit]


def help_text() -> str:
    """/help 的正文 —— 直接从命令表生成，避免和实现走样。"""
    lines = [
        "xAgent 帮助",
        "",
        "使用方式：直接输入自然语言，我会自动选择工具；输入 / 会弹出命令补全。",
        "",
        "命令：",
    ]
    width = max(len(cmd.display_usage) for cmd in COMMANDS)
    for command in COMMANDS:
        alias = ""
        if command.aliases:
            alias = f"（别名 {', '.join(command.aliases)}）"
        lines.append(
            f"  {command.display_usage:<{width}}  {command.description}{alias}"
        )

    lines += [
        "",
        "上下文说明：",
        "  · 状态栏实时显示「上下文 已用/窗口 百分比」，超过阈值会自动锁住输入",
        "  · 压缩后原始对话存在 .agents/context/<编号>.jsonl，可用 recallContext 检索",
        "  · 会话历史存在 .agents/sessions/<编号>.jsonl，/resume 可恢复",
        "",
        "快捷键：Ctrl+B 侧栏 · Ctrl+K 压缩 · Ctrl+N 新建会话 · Ctrl+R 恢复会话 · Ctrl+Q 退出",
    ]
    return "\n".join(lines)
