# -*- coding: utf-8 -*-
"""
xAgent.tui.app —— 对话式 LLM Agent（Textual TUI）。

界面结构：
  ┌─────────────────────────────────────────────────────────────────────────┐
  │ xAgent · 15 个工具 · ernie-5.1 · D:\\work\\demo                            │ ← Header
  │   Enter 发送 · / 命令 · ↑↓ 补全 · Esc 清空 · Ctrl+B 侧栏                  │
  ├──────────────────────────────────────────┬────────────────────────────┤
  │                                          │ 模型  ernie-5.1              │
  │ 对话流 VerticalScroll                     │ 接口  qianfan.baidubce.com   │
  │   你                                      │ 目录  D:\\work\\demo          │
  │     帮我看看这个项目                        │ 会话  20261105-112700        │
  │   ▸ read_file(path="README.md") · 3 ms   │ 轮次  1                      │
  │   xAgent                                  │ 状态  就绪                   │
  │     这是一个……                            │ ─────────────────────────── │
  │                                          │ MCP 服务器                   │
  │                                          │ ● demo 已连接 · 3 个工具      │
  │                                          │    · echo 原样返回……          │
  │                                          │ ─────────────────────────── │
  │                                          │ 工具                         │
  │                                          │  1. list_directory ……        │
  ├──────────────────────────────────────────┴────────────────────────────┤
  │ ⚠ 上下文已用到 96k/128k 75.0%，请执行 /compact 压缩后再继续            │ ← 告警条
  │   /new        新建会话（自动保存当前会话）                              │ ← 命令补全面板
  │   /resume     列出历史会话……                                           │
  │ 请输入 · Enter 发送 · / 查看命令                                         │
  ├─────────────────────────────────────────────────────────────────────────┤
  │ 上下文 12k/128k 9.4% · 就绪 · 1 轮 · ernie-5.1 · 工具 2 次             │ ← StatusBar
  ├─────────────────────────────────────────────────────────────────────────┤
  │ /help · /new · /resume · /save · /compact · /mcp · /quit                │ ← Footer
  └─────────────────────────────────────────────────────────────────────────┘

配色：墨绿极简，唯一强调色为薄荷绿 —— 定义在 tui/theme.py 的 xagent-green，
      这里只写 $primary / $accent / $panel 这类语义变量，不写死颜色值。
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.widgets import Static, Input, Label

from xAgent.core import ToolService, ToolResult
from xAgent.core.skills import (
    build_skill_prompt, discover_skills, get_skill_registry,
)
from xAgent.core.config import (
    AppConfig,
    ensure_config_file,
    get_bootstrap,
    get_config,
    reload_config,
)
from xAgent.core.context import (
    ContextUsage,
    compact_messages,
    estimate_messages_tokens,
    format_tokens,
    measure_usage,
)
from xAgent.core.llm import (
    LLMMessage, ToolCall, MockProvider, OpenAICompatibleProvider,
)
from xAgent.core.mcp import MCPManager, MCPServerState
from xAgent.core.session import (
    KIND_AGENTS_MD,
    KIND_MESSAGE,
    build_agents_md_message,
    list_sessions,
    load_agents_md,
    load_session,
    new_session_id,
    save_session,
)
from xAgent.tui.commands import find_command, help_text
from xAgent.tui.dialogs import InfoDialog, SessionPicker
from xAgent.tui.palette import CommandPalette
from xAgent.tui.theme import install_theme


#: AGENTS.md 注入消息的识别标记（不额外存状态，靠内容判断）
_AGENTS_MD_MARK = "<project_instructions>"


def _is_agents_md(message: LLMMessage) -> bool:
    return message.role == "user" and _AGENTS_MD_MARK in (message.content or "")


# ============================================================
# 自定义 Header
# ============================================================

class CustomHeader(Vertical):
    """顶部 Header —— 两行 Static。"""

    DEFAULT_CSS = """
    CustomHeader {
        width: 100%;
        height: auto;
        padding: 1 2 0 2;
        margin: 0;
        border: none;
        background: $surface;
    }
    CustomHeader .line1 {
        height: 1;
        color: $primary;
        text-style: bold;
    }
    CustomHeader .line2 {
        height: 1;
        color: $text-muted;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._tool_count = len(ToolService.list_tools())
        self._model = "mock"
        self._line1 = Static("", classes="line1")
        self._line2 = Static(
            "Enter 发送 · / 命令 · ↑↓ 补全 · Esc 清空 · Ctrl+B 侧栏",
            classes="line2",
        )
        self._refresh()

    def compose(self) -> ComposeResult:
        yield self._line1
        yield self._line2

    def _refresh(self) -> None:
        cwd = os.getcwd()
        if len(cwd) > 45:
            cwd = "..." + cwd[-42:]
        self._line1.update(
            f"xAgent · {self._tool_count} 个工具 · {self._model} · {cwd}"
        )

    def set_model(self, model: str) -> None:
        self._model = model
        self._refresh()

    def set_tool_count(self, count: int) -> None:
        self._tool_count = count
        self._refresh()


# ============================================================
# 紧凑可折叠工具卡片
# ============================================================

class ToolCallCard(Vertical):
    """
    工具调用卡片：左侧一条竖线 + 一行摘要，点一下展开参数和结果。
      ▸ isLeapYear(year=2026) · 2 ms     ← 折叠态（默认）
      ▼ isLeapYear(year=2026) · 2 ms     ← 展开态
          参数  { "year": 2026 }
          结果  2026 年不是闰年...
    竖线颜色：绿色=成功，红色=失败。
    """

    DEFAULT_CSS = """
    ToolCallCard {
        width: 100%;
        height: auto;
        margin: 0 0 1 2;
        padding: 0;
        background: $panel;
        border: none;
        border-left: solid $primary;
    }
    ToolCallCard.-error {
        border-left: solid $error;
    }
    ToolCallCard .summary {
        width: 100%;
        height: 1;
        color: $accent;
        background: transparent;
        border: none;
        padding: 0 1;
    }
    ToolCallCard:hover .summary {
        color: $primary;
    }
    ToolCallCard .body {
        width: 100%;
        margin-top: 0;
        padding: 0 2;
        color: $text-muted;
    }
    ToolCallCard .body.hidden {
        height: 0;
        min-height: 0;
        overflow: hidden;
    }
    """

    def __init__(
        self,
        call_id: str,
        tool_name: str,
        args: Dict[str, Any],
        result: ToolResult,
        elapsed_ms: int,
        preview_chars: int = 120,
    ) -> None:
        super().__init__()
        self._call_id = call_id
        self._tool_name = tool_name
        self._args = args
        self._result = result
        self._elapsed_ms = elapsed_ms
        self._preview_chars = max(40, int(preview_chars or 120))
        self._expanded = False

        args_str = ", ".join(
            f"{k}={json.dumps(v, ensure_ascii=False)}" for k, v in args.items()
        ) or "(无)"
        self._summary_collapsed = f"▸ {tool_name}({args_str}) · {elapsed_ms} ms"
        self._summary_expanded = self._summary_collapsed.replace("▸", "▼", 1)
        self._body_text = self._build_body(result)
        # 失败的工具调用左侧竖条转红，扫一眼就能定位
        if not result.success:
            self.add_class("-error")

    def _clip(self, text: str) -> str:
        if len(text) > self._preview_chars:
            return text[: self._preview_chars - 3] + "..."
        return text

    def _build_body(self, result: ToolResult) -> str:
        """构造展开后的参数 + 结果文本。"""
        args_json = json.dumps(self._args, ensure_ascii=False)
        flat = result.to_dict()
        result_content: str
        if result.success:
            if "content" in flat and isinstance(flat["content"], str):
                result_content = flat["content"]
            else:
                result_content = json.dumps(flat, ensure_ascii=False)
        else:
            result_content = flat.get("error", str(flat))

        return (
            f"[dim]参数[/dim]  {args_json}\n"
            f"[dim]结果[/dim]  {self._clip(result_content)}"
        )

    def compose(self) -> ComposeResult:
        self._summary = Static(self._summary_collapsed, classes="summary")
        self._body = Static(self._body_text, classes="body hidden")
        yield self._summary
        yield self._body

    def on_click(self) -> None:
        """点卡片任意位置折叠/展开。"""
        self._toggle()

    def _toggle(self) -> None:
        self._expanded = not self._expanded
        if self._expanded:
            self._summary.update(self._summary_expanded)
            self._body.remove_class("hidden")
        else:
            self._summary.update(self._summary_collapsed)
            self._body.add_class("hidden")


# ============================================================
# 对话流容器
# ============================================================

class ConversationFlow(VerticalScroll):
    """左侧主对话区。"""

    DEFAULT_CSS = """
    ConversationFlow {
        width: 1fr;
        border: none;
        padding: 1 2 1 1;
        background: $background;
        scrollbar-color: $secondary;
        scrollbar-color-hover: $primary;
        scrollbar-color-active: $primary;
        scrollbar-background: $background;
        scrollbar-size-vertical: 1;
    }
    ConversationFlow .role-badge {
        color: $text-muted;
        height: 1;
        margin-top: 1;
        padding: 0 0 0 2;
        text-style: bold;
    }
    ConversationFlow .role-badge.user {
        color: $accent;
    }
    ConversationFlow .role-badge.assistant {
        color: $primary;
    }
    ConversationFlow .role-badge.system {
        color: $text-muted;
    }
    ConversationFlow .msg-body {
        width: 100%;
        color: $foreground;
        padding: 0 0 0 2;
    }
    ConversationFlow .msg-body.dim {
        color: $text-muted;
    }
    ConversationFlow .msg-body.tool-line {
        color: $text-muted;
        padding: 0 0 0 3;
    }
    """

    def add_user_message(self, text: str) -> None:
        badge = Static("你", classes="role-badge user")
        body = Static(text, classes="msg-body")
        self.mount_all([badge, body])
        self.scroll_end(animate=False)

    def add_tool_card(self, card: ToolCallCard) -> None:
        self.mount(card)
        self.scroll_end(animate=False)

    def add_assistant_message(self, text: str) -> None:
        badge = Static("xAgent", classes="role-badge assistant")
        body = Static(text, classes="msg-body")
        self.mount_all([badge, body])
        self.scroll_end(animate=False)

    def add_system_note(self, text: str) -> None:
        """灰色小字提示（项目指令、恢复会话等），不占对话语义。"""
        self.mount(Static(text, classes="msg-body dim"))
        self.scroll_end(animate=False)

    def add_tool_note(self, name: str, args: Dict[str, Any]) -> None:
        """恢复历史时用的轻量工具行（旧卡片里的结果不再展开）。"""
        args_str = ", ".join(
            f"{k}={json.dumps(v, ensure_ascii=False)}" for k, v in (args or {}).items()
        ) or "无参数"
        self.mount(Static(f"▸ {name}({args_str})", classes="msg-body tool-line"))
        self.scroll_end(animate=False)

    def clear_all(self) -> None:
        self.remove_children()


# ============================================================
# 右侧侧栏
# ============================================================

class MCPSection(Vertical):
    """
    侧栏里的「MCP 服务器」区域。

    内容随异步加载结果重建：连接中 → 已连接（列工具）/ 失败（列原因）。
    """

    DEFAULT_CSS = """
    MCPSection {
        height: auto;
        width: 100%;
    }
    MCPSection .mcp-row {
        height: auto;
        width: 100%;
        color: $foreground;
        text-wrap: wrap;
    }
    MCPSection .mcp-row.-ready {
        color: $success;
    }
    MCPSection .mcp-row.-error {
        color: $error;
        text-wrap: wrap;
    }
    MCPSection .mcp-row.-pending {
        color: $warning;
    }
    MCPSection .mcp-tool {
        height: auto;
        width: 100%;
        color: $text-muted;
        padding: 0 0 0 2;
        text-wrap: wrap;
    }
    MCPSection .mcp-empty {
        height: auto;
        width: 100%;
        color: $text-muted;
        text-wrap: wrap;
    }
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._pending: Optional[List[MCPServerState]] = None
        self._pending_enabled = True

    def render_states(self, states: List[MCPServerState], enabled: bool = True) -> None:
        """重建内容；还没挂载就先记下来，挂载后再画。"""
        if not self.is_mounted:
            self._pending = states
            self._pending_enabled = enabled
            return
        self.remove_children()

        if not enabled:
            self.mount(Static("未启用（config.ini [mcp] enabled = false）", classes="mcp-empty"))
            return

        if not states:
            self.mount(Static("未配置服务器（config.ini [mcp] servers）", classes="mcp-empty"))
            return

        widgets: List[Static] = []
        for state in states:
            css_class = {
                "ready": "mcp-row -ready",
                "error": "mcp-row -error",
                "disabled": "mcp-row",
            }.get(state.status, "mcp-row -pending")
            mark = {
                "ready": "●",
                "error": "✕",
                "disabled": "○",
            }.get(state.status, "◌")
            cost = f" · {state.elapsed_ms}ms" if state.elapsed_ms else ""
            widgets.append(
                Static(f"{mark} {state.name}  {state.status_label}{cost}", classes=css_class)
            )
            if state.status == "error" and state.error:
                widgets.append(Static(f"    {state.error[:120]}", classes="mcp-tool"))
            for tool in state.tools:
                widgets.append(Static(f"· {tool.name}", classes="mcp-tool"))
        self.mount_all(widgets)

    def on_mount(self) -> None:
        if self._pending is not None:
            states, self._pending = self._pending, None
            self.render_states(states, self._pending_enabled)


class Sidebar(VerticalScroll):
    """右侧会话信息 + MCP 服务器 + 工具列表（内容超高时可滚动）。"""

    DEFAULT_CSS = """
    Sidebar {
        width: 42;
        background: $surface;
        border: none;
        border-left: solid $panel;
        padding: 1 1;
        overflow-x: auto;
        overflow-y: auto;
        scrollbar-size-horizontal: 1;
        scrollbar-size-vertical: 1;
        scrollbar-color: $secondary;
        scrollbar-color-hover: $primary;
        scrollbar-color-active: $primary;
        scrollbar-background: $surface;
    }
    Sidebar .kv {
        color: $text-muted;
        width: 1fr;
        height: auto;
        text-wrap: wrap;
    }
    Sidebar .section-label {
        color: $primary;
        text-style: bold;
        height: 1;
        margin-top: 1;
    }
    Sidebar .tdesc-line {
        color: $text-muted;
        width: 1fr;
        height: auto;
        text-wrap: wrap;
    }
    Sidebar.-collapsed {
        width: 4;
    }
    """

    # (控件 id, 前缀, 初始值) —— 只保留真正有值的行，占位符一律不展示
    _INFO_ROWS = (
        ("side-model", "模型  ", "mock"),
        ("side-api", "接口  ", "-"),
        ("side-cwd", "目录  ", ""),
        ("side-session", "会话  ", "-"),
        ("side-skills", "技能  ", "-"),
        ("side-round", "轮次  ", "1"),
        ("side-limit", "上限  ", "8 次模型调用/轮"),
        ("side-status", "状态  ", "就绪"),
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._collapsed = False
        self._loaded_skills: set[str] = set()
        self._skill_total = 0
        self._info: Dict[str, List[str]] = {}
        self._tool_rows: List[tuple] = []
        self._mcp_section: Optional[MCPSection] = None

    def compose(self) -> ComposeResult:
        yield Label("▾", id="side-mini")

        self._skill_total = len(get_skill_registry().skills)
        for wid, prefix, value in self._INFO_ROWS:
            if wid == "side-cwd":
                value = os.getcwd()
            elif wid == "side-skills":
                value = self._skill_display()
            self._info[wid] = [prefix, value]
            yield Label("", classes="kv", id=wid)

        yield Label("MCP 服务器", classes="section-label")
        self._mcp_section = MCPSection(id="mcp-section")
        yield self._mcp_section

        yield Label("工具", classes="section-label")
        for index, tool in enumerate(ToolService.list_tools(), start=1):
            name_label = Label("", classes="kv")
            desc_label = Label("", classes="kv tdesc-line") if tool.description else None
            self._tool_rows.append(
                (name_label, desc_label, index, tool.name, tool.description or "")
            )
            yield name_label
            if desc_label is not None:
                yield desc_label

    def on_mount(self) -> None:
        self.call_after_refresh(self._refresh_width)

    def on_resize(self, event) -> None:
        self.call_after_refresh(self._refresh_width)

    def _refresh_width(self) -> None:
        if not self.is_mounted or self._collapsed:
            return

        for wid, (prefix, value) in self._info.items():
            raw = value
            if wid == "side-api" and raw not in ("", "-"):
                raw = raw.replace("https://", "").replace("http://", "").rstrip("/")
            self.query_one(f"#{wid}", Label).update(f"{prefix}{raw}")

        # 工具名独占一行（带序号），描述另起一行；按宽度自动换行，不做截断
        for name_label, desc_label, index, name, desc in self._tool_rows:
            name_label.update(f"{index:>2d}. {name}")
            if desc_label is not None:
                desc_label.display = True
                desc_label.update(f"    {desc}" if desc else "")

    def _set_value(self, wid: str, value: str) -> None:
        if wid not in self._info:
            return
        self._info[wid] = [self._info[wid][0], value]
        self._refresh_width()

    def set_status(self, text: str) -> None:
        self._set_value("side-status", text)

    def set_round(self, n: int) -> None:
        self._set_value("side-round", str(n))

    def set_model(self, text: str) -> None:
        self._set_value("side-model", text)

    def set_api(self, text: str) -> None:
        self._set_value("side-api", text)

    def set_session(self, text: str) -> None:
        self._set_value("side-session", text)

    def set_limit(self, text: str) -> None:
        self._set_value("side-limit", text)

    # ---------- MCP ----------

    def set_mcp(self, states: List[MCPServerState], enabled: bool = True) -> None:
        if self._mcp_section is not None:
            self._mcp_section.render_states(states, enabled)

    # ---------- Skill 加载角标 ----------

    def _skill_display(self) -> str:
        if self._skill_total <= 0:
            return "未发现"
        if not self._loaded_skills:
            return f"0/{self._skill_total}"
        names = "、".join(sorted(self._loaded_skills))
        return f"{len(self._loaded_skills)}/{self._skill_total} {names}"

    def set_skill_total(self, total: int) -> None:
        self._skill_total = total
        self._set_value("side-skills", self._skill_display())

    def mark_skill_loaded(self, name: str) -> None:
        if not name or name in self._loaded_skills:
            return
        self._loaded_skills.add(name)
        self._set_value("side-skills", self._skill_display())

    def reset_skill_loaded(self) -> None:
        self._loaded_skills.clear()
        self._set_value("side-skills", self._skill_display())

    # ---------- 最小化 / 展开 ----------

    def toggle_collapsed(self) -> None:
        self._collapsed = not self._collapsed
        self.set_class(self._collapsed, "-collapsed")
        for child in self.children:
            if child.id != "side-mini":
                child.display = not self._collapsed
        self.query_one("#side-mini", Label).update("▸" if self._collapsed else "▾")
        if not self._collapsed:
            self.call_after_refresh(self._refresh_width)

    def on_click(self) -> None:
        if self._collapsed:
            self.toggle_collapsed()


# ============================================================
# 底部状态栏
# ============================================================

class ContextBanner(Static):
    """上下文告警条 —— 只在超过阈值时出现，压完就消失。"""

    DEFAULT_CSS = """
    ContextBanner {
        height: 1;
        width: 100%;
        display: none;
        color: $warning;
        background: $panel;
        padding: 0 2;
    }
    ContextBanner.-visible {
        display: block;
    }
    """

    def show_message(self, text: str) -> None:
        self.update(text)
        self.add_class("-visible")

    def hide_message(self) -> None:
        self.remove_class("-visible")


class StatusBar(Static):
    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        width: 100%;
        color: $text-muted;
        background: $surface;
        padding: 0 2;
    }
    StatusBar.-warn {
        color: $warning;
        text-style: bold;
    }
    """

    def update_status(
        self,
        ready: bool = True,
        round_no: int = 1,
        model: str = "mock",
        tool_calls: int = 0,
        elapsed_ms: int = 0,
        usage: ContextUsage | None = None,
        compacting: bool = False,
    ) -> None:
        parts = []
        # 上下文用量放最左边：这是最该被盯住的一个数
        if usage is not None:
            parts.append(f"上下文 {usage.format_meter()}")
        if compacting:
            parts.append("压缩中")
        elif usage is not None and usage.over_threshold:
            parts.append("等待压缩")
        else:
            parts.append("就绪" if ready else "生成中")
        parts.append(f"{round_no} 轮")
        parts.append(model)
        parts.append(f"工具 {tool_calls} 次")
        if elapsed_ms:
            parts.append(f"{elapsed_ms / 1000:.1f}s")
        self.update(" · ".join(parts))


class CustomFooter(Static):
    """底部命令提示栏。"""

    DEFAULT_CSS = """
    CustomFooter {
        height: 1;
        width: 100%;
        color: $text-muted;
        background: $surface;
        padding: 0 2;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static(
            "/help 帮助 · /new 新会话 · /resume 恢复 · /save 保存 · "
            "/compact 压缩 · /mcp 服务器 · /quit 退出",
            markup=False,
        )


# ============================================================
# 主 App
# ============================================================

def _param_schema(pdesc: str) -> Dict[str, Any]:
    """按参数描述前缀（str / int / bool / list）生成对应的 JSON Schema。"""
    low = pdesc.lower()
    if low.startswith("list"):
        return {"type": "array", "items": {"type": "string"}, "description": pdesc}
    if low.startswith("int"):
        return {"type": "integer", "description": pdesc}
    if low.startswith("bool"):
        return {"type": "boolean", "description": pdesc}
    return {"type": "string", "description": pdesc}


class XAgentApp(App):
    """对话式 LLM Agent。"""

    TITLE = "xAgent"

    # Ctrl 组合键：输入框有焦点时也能触发（单字母会被输入框吃掉）
    BINDINGS = [
        Binding("ctrl+b", "toggle_sidebar", "侧栏"),
        Binding("ctrl+k", "compact", "压缩上下文"),
        Binding("ctrl+n", "new_session", "新会话"),
        Binding("ctrl+r", "resume", "历史会话"),
        Binding("ctrl+q", "quit", "退出"),
    ]

    CSS = """
    Screen { layout: vertical; background: $background; }
    #main-row { layout: horizontal; height: 1fr; }
    #prompt-row { layout: horizontal; height: auto; padding: 0 2 1 1; }
    #prompt {
        width: 100%;
        border: round $panel;
        background: $surface;
        padding: 0 1;
    }
    #prompt:focus { border: round $primary; }
    #prompt.-locked { border: round $warning; }
    """

    round_no = reactive(1)
    tool_calls_total = reactive(0)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        # 每个实例各自一份的状态，必须在这里初始化：
        # 写成类属性会在多实例（测试里很常见）之间串数据
        super().__init__(*args, **kwargs)
        self.cfg: AppConfig = get_config()
        self._messages: List[LLMMessage] = []
        self._usage: Optional[ContextUsage] = None
        self._project_root: str = os.getcwd()
        self._session_id: str = ""
        self._session_title: str = ""
        self._input_locked = False
        self._compacting = False
        self._generating = False
        self._skill_prompt = ""
        self._model_label = "mock"
        self._provider: Any = MockProvider()
        self._mcp: Optional[MCPManager] = None

    # ---------- 布局 ----------

    def compose(self) -> ComposeResult:
        yield CustomHeader()

        with Container(id="main-row"):
            yield ConversationFlow(id="conversation")
            yield Sidebar(id="sidebar")

        # 上下文告警条（默认隐藏，超过阈值才出现）
        yield ContextBanner(id="ctx-banner")

        # 斜杠命令补全（默认隐藏，输入 / 时出现）
        yield CommandPalette(id="palette")

        with Container(id="prompt-row"):
            yield Input(
                placeholder="请输入 · Enter 发送 · / 查看命令 · Esc 清空",
                id="prompt",
                restrict=None,
            )

        yield StatusBar("就绪 · 1 轮 · mock · 工具 0 次")
        yield CustomFooter()

    def on_mount(self) -> None:
        # 主题必须在查控件之前装好，否则首帧会闪一下默认蓝色
        install_theme(self)

        self._conversation = self.query_one("#conversation", ConversationFlow)
        self._sidebar = self.query_one("#sidebar", Sidebar)
        self._prompt = self.query_one("#prompt", Input)
        self._status = self.query_one(StatusBar)
        self._header = self.query_one(CustomHeader)
        self._banner = self.query_one("#ctx-banner", ContextBanner)
        self._palette = self.query_one("#palette", CommandPalette)

        # 配置兜底：正常走 main() 时已经生成过；直接构造 App 也能自举
        bootstrap = ensure_config_file()
        if bootstrap.created:
            reload_config(bootstrap.path)

        # 配置在 App 构造时就定了；这里再确认一次，避免 main 里 reload 后不一致
        self.cfg = get_config()
        self._project_root = os.getcwd()

        self._sidebar.styles.width = self.cfg.sidebar_width
        self._sidebar.set_limit(f"{self.cfg.max_model_calls} 次模型调用/轮")

        # 按配置初始化 LLM
        self._init_provider()

        # Skill 发现：以启动时的工作目录为项目根目录，只加载 name / description
        registry = discover_skills()
        self._skill_prompt = build_skill_prompt(registry)
        self._sidebar.set_skill_total(len(registry.skills))

        # 新会话：编号 + System Prompt + 项目指令
        self._session_id = new_session_id(root=self._project_root, subdir=self.cfg.session_dir)
        self._sidebar.set_session(self._session_id)
        self._ensure_system_prompt()
        self._ensure_agents_md(announce=True)
        self._refresh_usage()

        # MCP 异步加载：先进界面，连上后动态刷新侧栏
        self._start_mcp()

        self._conversation.add_assistant_message(
            "你好，我是 xAgent。我可以帮你操作文件系统，也能调用 MCP 服务器上的工具。\n\n"
            "试试：'列出当前目录'、'读取 README.md 的内容'、"
            "'创建文件 demo.txt'；输入 / 会弹出命令补全。"
        )
        self._prompt.focus()

        self._maybe_show_config_dialog()

    # ---------- 首次运行提示 ----------

    def _maybe_show_config_dialog(self) -> None:
        """配置文件是这次刚生成的 → 弹窗告诉用户去改，否则只提示 mock 状态。"""
        bootstrap = get_bootstrap()
        if bootstrap is not None and bootstrap.created:
            if bootstrap.seeded_from:
                migrate = (
                    f"\n已从旧配置迁移 API Key：\n  {bootstrap.seeded_from}\n"
                    "重启后即可使用真实模型；也可以先改好其它配置项。"
                )
            else:
                migrate = (
                    "\n当前是 Mock 模式：能演示工具调用与命令，但不会真正调用大模型。"
                )

            self.push_screen(
                InfoDialog(
                    "已生成新的 config.ini",
                    f"检测到当前目录没有配置文件，已自动创建：\n\n"
                    f"  {bootstrap.path}\n\n"
                    "里面填的是 mock 信息（本地模拟，无需联网）。\n"
                    "要接入真实模型：打开该文件，填写 [llm] api_key，"
                    "保存后【重启 xAgent】才会生效。"
                    f"{migrate}",
                )
            )
            return

        if self.cfg.use_mock:
            self._conversation.add_system_note(
                "当前运行在 Mock 模式（config.ini 里没有 api_key），"
                "不会真正调用大模型。"
            )
        for warning in self.cfg.warnings[:3]:
            self._conversation.add_system_note(f"配置提示：{warning}")

    # ---------- LLM 初始化 ----------

    def _init_provider(self) -> None:
        """按配置选 provider；没有 key 就回落本地 Mock。"""
        if self.cfg.use_mock:
            self._provider = MockProvider()
            self._model_label = "mock"
            api_label = "-"
        else:
            self._provider = OpenAICompatibleProvider(
                api_key=self.cfg.api_key,
                base_url=self.cfg.base_url,
                model=self.cfg.model,
                timeout=self.cfg.timeout,
            )
            self._model_label = self.cfg.model
            api_label = self.cfg.base_url

        self._header.set_model(self._model_label)
        self._sidebar.set_model(self._model_label)
        self._sidebar.set_api(api_label)

    # ---------- MCP ----------

    def _start_mcp(self) -> None:
        """创建管理器并异步连接；侧栏先显示「连接中」。"""
        if self._mcp is not None:
            self._mcp.close()

        self._mcp = MCPManager(self.cfg.mcp_servers, enabled=self.cfg.mcp_enabled)
        self._sidebar.set_mcp(self._mcp.states(), enabled=self.cfg.mcp_enabled)
        if not self.cfg.mcp_enabled or not self.cfg.mcp_servers:
            self._sync_tool_count()
            return

        self._mcp.start_async(self._on_mcp_server_change)
        self._sync_tool_count()

    def _on_mcp_server_change(self, name: str) -> None:
        """MCP 工作线程回调 —— 必须切回 UI 线程再动控件。"""
        try:
            self.call_from_thread(self._refresh_mcp)
        except Exception:
            # App 已经退出 / 还没跑起来（headless 测试）时忽略
            pass

    def _refresh_mcp(self) -> None:
        if self._mcp is None:
            return
        self._sidebar.set_mcp(self._mcp.states(), enabled=self.cfg.mcp_enabled)
        self._sync_tool_count()

    def _sync_tool_count(self) -> None:
        mcp_tools = len(self._mcp.all_tools()) if self._mcp else 0
        self._header.set_tool_count(len(ToolService.list_tools()) + mcp_tools)

    # ---------- 上下文计量 / 压缩 ----------

    def _api_prompt_tokens(self) -> Optional[int]:
        usage = getattr(self._provider, "last_usage", None) or {}
        try:
            prompt = int(usage.get("prompt_tokens") or 0)
            completion = int(usage.get("completion_tokens") or 0)
        except (TypeError, ValueError):
            return None
        total = prompt + completion
        return total or None

    def _invalidate_api_usage(self) -> None:
        if hasattr(self._provider, "last_usage"):
            self._provider.last_usage = None

    def _refresh_usage(self, elapsed_ms: int = 0) -> None:
        self._usage = measure_usage(
            self._messages,
            self._model_label,
            self._build_tools_schema(),
            api_prompt_tokens=self._api_prompt_tokens(),
            window_override=self.cfg.context_window,
            threshold=self.cfg.compact_threshold,
        )
        self._apply_usage_ui(elapsed_ms)

    def _apply_usage_ui(self, elapsed_ms: int = 0) -> None:
        usage = self._usage
        if usage is None:
            return

        self._status.update_status(
            ready=not (self._compacting or self._generating),
            round_no=self.round_no,
            model=self._model_label,
            tool_calls=self.tool_calls_total,
            elapsed_ms=elapsed_ms,
            usage=usage,
            compacting=self._compacting,
        )
        over = usage.over_threshold
        self._status.set_class(over, "-warn")

        if self._compacting:
            self._banner.show_message("正在压缩上下文：归档原始记录 → 生成摘要…")
            self._set_input_locked(True)
            return

        if over:
            self._banner.show_message(
                f"⚠ 上下文已用到 {usage.format_meter()}，"
                f"请执行 /compact 压缩后再继续"
            )
        else:
            self._banner.hide_message()
        self._set_input_locked(over)

    def _set_input_locked(self, locked: bool) -> None:
        if locked == self._input_locked:
            return
        self._input_locked = locked
        self._prompt.set_class(locked, "-locked")
        self._prompt.placeholder = (
            "上下文已满 · 请先执行 /compact 压缩上下文"
            if locked
            else "请输入 · Enter 发送 · / 查看命令 · Esc 清空"
        )

    def _run_compact(self) -> None:
        """/compact：先归档（失败就中止）→ LLM 出摘要 → 摘要替换历史。"""
        if self._compacting:
            return
        if len(self._messages) <= 1:
            self._conversation.add_assistant_message("当前没有可压缩的对话内容。")
            return

        self._compacting = True
        self._sidebar.set_status("压缩中")
        self._apply_usage_ui()

        try:
            result = compact_messages(
                self._messages,
                self._provider,
                project_root=self._project_root,
                model=self._model_label,
                archive_subdir=self.cfg.archive_dir,
            )
        finally:
            self._compacting = False

        if not result.success:
            self._conversation.add_assistant_message(
                f"压缩失败：{result.error}\n\n上下文保持原样，可以直接重试 /compact。"
            )
            self._sidebar.set_status("就绪")
            self._refresh_usage()
            return

        # 压缩期间那次请求的 usage 是「旧上下文」的，必须作废
        self._invalidate_api_usage()
        self._messages = result.messages
        # 项目指令要跟着新上下文走（否则压缩一次就丢了）
        self._ensure_agents_md(announce=False)

        gain_note = ""
        if result.tokens_after >= result.tokens_before:
            gain_note = "\n  ⚠ 摘要比原文还长，这次压缩没有收益（上下文较短时属正常）"
        elif result.summary_tokens > self.cfg.compact_target_tokens * 2:
            gain_note = (
                f"\n  ⚠ 摘要偏长（约 {format_tokens(result.summary_tokens)}，"
                f"目标 {format_tokens(self.cfg.compact_target_tokens)}）"
            )

        try:
            shown_path = os.path.relpath(result.archive_path, self._project_root)
        except ValueError:  # Windows 跨盘符
            shown_path = result.archive_path

        self._conversation.add_assistant_message(
            "上下文已压缩：\n"
            f"  · 归档编号  {result.archive_id}\n"
            f"  · 归档文件  {shown_path}\n"
            f"  · 用量      {format_tokens(result.tokens_before)} → "
            f"{format_tokens(result.tokens_after)}{gain_note}\n"
            "  · System Prompt 与工具定义保持不变\n\n"
            "缺失的历史细节可以用 recallContext 工具从归档里检索。"
        )
        self._sidebar.set_status("就绪")
        self._refresh_usage()
        self._auto_save()

    # ---------- 会话 ----------

    def _message_kinds(self) -> List[str]:
        return [
            KIND_AGENTS_MD if _is_agents_md(message) else KIND_MESSAGE
            for message in self._messages
        ]

    def _has_conversation(self) -> bool:
        """有没有「真正的对话」—— 光有系统提示 / AGENTS.md 不算。"""
        for message in self._messages:
            if message.role == "assistant":
                return True
            if message.role == "user" and not _is_agents_md(message):
                return True
            if message.role == "tool":
                return True
        return False

    def _save_session(self, announce: bool = False, title: str = "") -> Optional[Path]:
        """把当前会话写盘；失败不抛异常（别因为存盘把对话打断）。"""
        if not self._has_conversation():
            if announce:
                self._conversation.add_assistant_message("当前会话还是空的，没有可保存的内容。")
            return None

        if title:
            self._session_title = title

        try:
            path = save_session(
                self._messages,
                self._session_id,
                self._project_root,
                subdir=self.cfg.session_dir,
                model=self._model_label,
                title=self._session_title,
                kinds=self._message_kinds(),
                estimated_tokens=estimate_messages_tokens(self._messages),
            )
        except OSError as exc:
            if announce:
                self._conversation.add_assistant_message(f"保存会话失败：{exc}")
            return None

        if announce:
            try:
                shown = os.path.relpath(path, self._project_root)
            except ValueError:
                shown = str(path)
            self._conversation.add_assistant_message(
                f"会话已保存：\n"
                f"  · 编号  {self._session_id}\n"
                f"  · 文件  {shown}\n"
                f"  · 消息  {len(self._messages)} 条\n"
                "用 /resume 可以随时恢复。"
            )
        return path

    def _auto_save(self) -> None:
        if self.cfg.auto_save:
            self._save_session(announce=False)

    def _reset_session_state(self, title: str = "") -> None:
        """清空运行时状态，准备开一个新会话（不动磁盘）。"""
        self._conversation.clear_all()
        self._messages = []
        self.round_no = 1
        self.tool_calls_total = 0
        self._invalidate_api_usage()
        self._session_title = title
        self._sidebar.set_round(1)
        self._sidebar.reset_skill_loaded()
        self._sidebar.set_status("就绪")
        self._prompt.value = ""
        self._palette.hide()

    def _new_session(self, title: str = "") -> None:
        """/new：自动保存当前会话 → 开新会话 → 重新注入 System Prompt 与项目指令。"""
        saved = self._save_session(announce=False, title=self._session_title)
        self._reset_session_state(title=title)
        self._session_id = new_session_id(root=self._project_root, subdir=self.cfg.session_dir)
        self._sidebar.set_session(self._session_id)

        self._ensure_system_prompt()
        self._ensure_agents_md(announce=True)
        self._refresh_usage()

        note = ""
        if saved is not None:
            note = "\n上一个会话已自动保存，可用 /resume 找回。"
        self._conversation.add_assistant_message(
            f"新会话已创建：{self._session_id}{note}"
        )

    def _resume_session(self, session_id: str) -> None:
        """恢复一个历史会话（先保存当前会话，避免白干）。"""
        meta = load_session(session_id, self._project_root, self.cfg.session_dir)
        if meta is None:
            self._conversation.add_assistant_message(f"恢复失败：找不到会话 {session_id}")
            return

        self._save_session(announce=False)
        self._conversation.clear_all()
        self._messages = list(meta.messages)
        self._session_id = meta.id
        self._session_title = meta.title
        self._invalidate_api_usage()
        self._sidebar.set_session(meta.id)
        self._sidebar.set_round(1)
        self._sidebar.set_status("就绪")
        self.round_no = 1
        self.tool_calls_total = 0
        self._prompt.value = ""
        self._palette.hide()

        self._ensure_system_prompt()
        self._ensure_agents_md(announce=False)
        self._render_history()
        self._refresh_usage()

        self._conversation.add_system_note(
            f"已恢复会话 {meta.id}（{meta.message_count} 条消息，"
            f"模型 {meta.model or '未知'}）。可以用 /new 另起一个会话。"
        )

    def _render_history(self) -> None:
        """把消息列表画回对话区（恢复会话时用）。"""
        self._conversation.clear_all()
        for message in self._messages:
            if message.role == "system":
                continue
            if message.role == "user":
                if _is_agents_md(message):
                    self._conversation.add_system_note(
                        "（历史记录）本项目已注入 AGENTS.md 项目指令"
                    )
                else:
                    self._conversation.add_user_message(message.content or "")
            elif message.role == "assistant":
                for call in (message.tool_calls or []):
                    self._conversation.add_tool_note(call.name, call.arguments)
                if (message.content or "").strip():
                    self._conversation.add_assistant_message(message.content.strip())
            # tool 消息不重复渲染：它的结果已经在工具行里体现过

    def _open_resume_dialog(self) -> None:
        """弹出历史会话列表；选中后恢复。"""
        sessions = list_sessions(self._project_root, self.cfg.session_dir)
        if not sessions:
            self._conversation.add_assistant_message(
                "还没有保存过任何会话。（每轮对话结束会自动保存；"
                "也可以用 /save 手动保存）"
            )
            return

        def _on_close(session_id: Optional[str]) -> None:
            if session_id:
                self._resume_session(session_id)
            self._prompt.focus()

        self.push_screen(SessionPicker(sessions, current_id=self._session_id), _on_close)

    def _export_session(self, target: str = "") -> None:
        """把当前会话导出成 Markdown。"""
        if not self._has_conversation():
            self._conversation.add_assistant_message("当前会话是空的，没有可导出的内容。")
            return

        if target.strip():
            path = Path(target.strip()).expanduser()
            if not path.is_absolute():
                path = Path(self._project_root) / path
        else:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            path = Path(self._project_root) / ".agents" / "exports" / f"{stamp}.md"

        lines = [
            f"# xAgent 会话 {self._session_id}",
            "",
            f"- 导出时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"- 模型：{self._model_label}",
            f"- 消息数：{len(self._messages)}",
            "",
        ]
        for message in self._messages:
            if message.role == "system":
                continue
            if message.role == "user":
                if _is_agents_md(message):
                    lines += ["## 项目指令（AGENTS.md）", "", message.content, ""]
                else:
                    lines += ["## 用户", "", message.content, ""]
            elif message.role == "assistant":
                if message.tool_calls:
                    for call in message.tool_calls:
                        args = json.dumps(call.arguments, ensure_ascii=False)
                        lines += [f"> 调用工具 `{call.name}` 参数 `{args}`", ""]
                if (message.content or "").strip():
                    lines += ["## xAgent", "", message.content.strip(), ""]
            elif message.role == "tool":
                lines += ["```json", (message.content or "")[:2000], "```", ""]

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("\n".join(lines), encoding="utf-8")
        except OSError as exc:
            self._conversation.add_assistant_message(f"导出失败：{exc}")
            return

        try:
            shown = os.path.relpath(path, self._project_root)
        except ValueError:
            shown = str(path)
        self._conversation.add_assistant_message(f"已导出为 Markdown：{shown}")

    # ---------- AGENTS.md ----------

    def _has_agents_md_message(self) -> bool:
        return any(_is_agents_md(message) for message in self._messages)

    def _ensure_agents_md(self, announce: bool = False) -> bool:
        """
        「一次注入，全程复用」：
            只在历史里没有项目指令时注入一次；之后每轮请求直接复用这条消息，
            前面的上下文不变，模型的 prompt cache 才有机会命中。
        """
        if not self.cfg.agents_md_enabled:
            return False
        if self._has_agents_md_message():
            return False

        found = load_agents_md(self._project_root, self.cfg.agents_md_file)
        if found is None:
            return False

        path, content = found
        try:
            rel = os.path.relpath(path, self._project_root)
        except ValueError:
            rel = str(path)

        message = build_agents_md_message(content, rel)
        # 紧跟在 system 之后，保证它在每一轮请求里都排在最前面
        position = 1 if (self._messages and self._messages[0].role == "system") else 0
        self._messages.insert(position, message)
        self._invalidate_api_usage()

        if announce:
            self._conversation.add_system_note(
                f"已加载项目指令 {rel}（{len(content)} 字符），本会话只注入一次。"
            )
        return True

    # ---------- 输入处理 ----------

    def on_input_changed(self, event: Input.Changed) -> None:
        """输入 / 时弹出命令补全面板。"""
        if not self.cfg.show_command_palette:
            return
        value = event.value
        if value.startswith("/") and " " not in value:
            self._palette.refresh_items(value)
        else:
            self._palette.hide()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        raw = event.value.strip()
        event.input.value = ""
        selected = self._palette.current()
        self._palette.hide()
        if not raw:
            return

        if raw.startswith("/"):
            # 只敲了前缀（/n）时用补全面板当前项补全
            if " " not in raw and find_command(raw) is None and selected is not None:
                raw = selected.name
            self._handle_command(raw)
            return

        if self._input_locked:
            percent = f"{self._usage.percent:.0f}%" if self._usage else "70%+"
            self._conversation.add_assistant_message(
                f"上下文已用到 {percent}，暂时不接受新任务。\n"
                "请先执行 /compact 压缩上下文 —— 压缩前的原始记录会归档，"
                "之后仍可用 recallContext 检索。"
            )
            return
        self._run_user_turn(raw)

    def _handle_command(self, cmd: str) -> None:
        parts = cmd.split(maxsplit=1)
        head = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        command = find_command(head)
        name = command.name if command else head

        if name == "/help":
            self._conversation.add_assistant_message(help_text())
        elif name == "/new":
            self._new_session(title=arg)
        elif name == "/save":
            self._save_session(announce=True, title=arg)
        elif name == "/resume":
            if arg:
                self._resume_session(arg)
            else:
                self._open_resume_dialog()
        elif name == "/quit":
            self._quit_app()
        elif name == "/compact":
            self._run_compact()
        elif name == "/tools":
            self._conversation.add_assistant_message(self._tools_report())
        elif name == "/mcp":
            if arg.lower() in ("reload", "refresh", "重连"):
                self._start_mcp()
                self._conversation.add_assistant_message("正在重新连接 MCP 服务器…")
            else:
                self._conversation.add_assistant_message(self._mcp_report())
        elif name == "/agents":
            self._conversation.add_assistant_message(self._agents_report())
        elif name == "/model":
            usage = self._usage
            window = f"{format_tokens(usage.window)}" if usage else "未知"
            if usage is not None and usage.is_default_window:
                window += "（默认）"
            self._conversation.add_assistant_message(
                f"模型：{self._model_label}\n"
                f"接口：{self.cfg.base_url if not self.cfg.use_mock else '-'}\n"
                f"上下文窗口：{window}\n"
                f"压缩阈值：{self.cfg.compact_threshold:.0%}"
            )
        elif name == "/config":
            self._conversation.add_assistant_message(self._config_report())
        elif name == "/cwd":
            self._conversation.add_assistant_message(f"当前目录：{os.getcwd()}")
        elif name == "/export":
            self._export_session(arg)
        else:
            self._conversation.add_assistant_message(
                f"未知命令：{cmd}。输入 /help 查看可用命令。"
            )

    def _tools_report(self) -> str:
        lines = ["本地工具："]
        for tool in ToolService.list_tools():
            lines.append(f"  · {tool.name:<28} {tool.description}")

        if self._mcp is not None and self.cfg.mcp_enabled:
            mcp_tools = self._mcp.all_tools()
            lines.append("")
            lines.append(f"MCP 工具（{len(mcp_tools)} 个）：")
            if not mcp_tools:
                lines.append("  · 暂无（服务器还没连上，用 /mcp 查看状态）")
            for server, tool, qualified in mcp_tools:
                lines.append(f"  · {qualified:<28} [{server}] {tool.description}")
        return "\n".join(lines)

    def _mcp_report(self) -> str:
        if not self.cfg.mcp_enabled:
            return "MCP 已禁用（config.ini [mcp] enabled = false）。"
        if self._mcp is None or not self._mcp.states():
            return "没有配置 MCP 服务器（config.ini [mcp] servers）。"

        states = self._mcp.states()
        ready = sum(1 for s in states if s.status == "ready")
        lines = [f"MCP 服务器（{ready}/{len(states)} 已连接）："]
        for state in states:
            cost = f"  {state.elapsed_ms}ms" if state.elapsed_ms else ""
            lines.append(f"  · {state.name:<12} {state.status_label}{cost}")
            if state.status == "error" and state.error:
                lines.append(f"      错误：{state.error[:160]}")
            for tool in state.tools:
                desc = f"  {tool.description}" if tool.description else ""
                lines.append(f"      - {tool.name}{desc}")
        lines.append("")
        lines.append("用 /mcp reload 可以重新连接。")
        return "\n".join(lines)

    def _agents_report(self) -> str:
        found = load_agents_md(self._project_root, self.cfg.agents_md_file)
        if not self.cfg.agents_md_enabled:
            return (
                f"AGENTS.md 注入已关闭（config.ini [session] agents_md = false）。\n"
                f"当前目录：{self.cfg.agents_md_file} 不存在也无所谓。"
            )
        if found is None:
            return (
                f"当前目录没有 {self.cfg.agents_md_file}。\n"
                "在项目根放一个 AGENTS.md，新会话首次加载时会自动注入项目指令。"
            )
        path, content = found
        injected = self._has_agents_md_message()
        return (
            f"文件：{path}\n"
            f"大小：{len(content)} 字符\n"
            f"状态：{'已注入当前会话（只注入一次，后续复用）' if injected else '尚未注入'}\n"
            "修改 AGENTS.md 后需要 /new 开新会话才会生效。"
        )

    def _config_report(self) -> str:
        cfg = self.cfg
        lines = [
            f"配置文件：{cfg.path}",
            f"模型：provider={cfg.provider} model={cfg.model}"
            f"{'（Mock 模式）' if cfg.use_mock else ''}",
            f"请求超时：{cfg.timeout}s",
            f"单轮模型调用上限：{cfg.max_model_calls}",
            "",
            f"上下文窗口：{cfg.context_window or '自动（查不到按 128k）'}",
            f"压缩阈值：{cfg.compact_threshold:.0%}",
            f"摘要目标：{cfg.compact_target_tokens} tokens",
            f"归档目录：{cfg.archive_dir}",
            "",
            f"会话目录：{cfg.session_dir}",
            f"自动保存：{'开' if cfg.auto_save else '关'}",
            f"注入 AGENTS.md：{'开' if cfg.agents_md_enabled else '关'}",
            "",
            f"边栏宽度：{cfg.sidebar_width}",
            f"MCP：{'启用' if cfg.mcp_enabled else '禁用'}"
            f" · {len(cfg.mcp_servers)} 台服务器 · 超时 {cfg.mcp_timeout}s",
        ]
        if cfg.warnings:
            lines.append("")
            lines.append("配置提示：")
            for warning in cfg.warnings[:5]:
                lines.append(f"  · {warning}")
        return "\n".join(lines)

    def _quit_app(self) -> None:
        """退出前保存会话、关掉 MCP 子进程。"""
        self._save_session(announce=False, title=self._session_title)
        if self._mcp is not None:
            self._mcp.close()
            self._mcp = None
        self.exit()

    # ---------- 核心：一轮对话 ----------

    def _ensure_system_prompt(self) -> None:
        """把 Skill 清单注入 System Prompt；/new 清空历史后重新注入。"""
        if not self._skill_prompt:
            return
        if self._messages and self._messages[0].role == "system":
            return
        self._messages.insert(0, LLMMessage(role="system", content=self._skill_prompt))

    def _run_user_turn(self, user_text: str) -> None:
        if self._compacting:
            return  # 压缩期间不接新任务
        self._ensure_system_prompt()
        self._conversation.add_user_message(user_text)
        self._messages.append(LLMMessage(role="user", content=user_text))

        self._status.update_status(
            ready=False, round_no=self.round_no, model=self._model_label, usage=self._usage
        )
        self._sidebar.set_status("生成中")

        tools_schema = self._build_tools_schema()

        t0 = time.time()
        self._generating = True
        try:
            self._run_model_loop(tools_schema)
        except Exception as exc:
            self._conversation.add_assistant_message(f"LLM 调用失败：{exc}")
        finally:
            self._generating = False

        total_ms = int((time.time() - t0) * 1000)
        self._refresh_usage(elapsed_ms=total_ms)

        self.round_no += 1
        self._sidebar.set_round(self.round_no)
        self._sidebar.set_status("就绪")
        self._auto_save()

    def _run_model_loop(self, tools_schema: List[Dict[str, Any]]) -> None:
        """
        反复调用模型直到不再请求工具。

        关键：assistant 的每个 tool_call 都必须有对应的 tool 消息回传，
        否则下一轮请求会被千帆判为消息格式错误。
        """
        for _ in range(self.cfg.max_model_calls):
            if self._compacting:
                return
            response = self._provider.chat(self._messages, tools_schema)
            self._messages.append(response)
            self._refresh_usage()

            if not response.tool_calls:
                if response.content:
                    self._conversation.add_assistant_message(response.content.strip())
                return

            for call in response.tool_calls:
                card, tool_msg = self._execute_tool(call)
                if card:
                    self._conversation.add_tool_card(card)
                self._messages.append(tool_msg)
                self.tool_calls_total += 1

        self._conversation.add_assistant_message(
            f"（已达到单轮 {self.cfg.max_model_calls} 次模型调用上限，停止继续调用工具）"
        )

    def _execute_tool(self, call: ToolCall) -> tuple[Optional[ToolCallCard], LLMMessage]:
        # 压缩期间禁止执行任何工具：只回一条失败的 tool 消息占位，保证消息序列合法
        if self._compacting:
            return None, LLMMessage(
                role="tool",
                content=json.dumps(
                    {"success": False, "error": "上下文压缩期间禁止执行工具"},
                    ensure_ascii=False,
                ),
                tool_call_id=call.id,
            )

        t0 = time.time()
        if call.name.startswith("mcp__") and self._mcp is not None:
            result = self._mcp.call(call.name, call.arguments)
        else:
            result = ToolService.call(call.name, **call.arguments)
        elapsed_ms = int((time.time() - t0) * 1000)

        # loadSkill 成功后在侧栏点亮技能加载角标
        if call.name == "loadSkill" and result.success:
            loaded_name = result.data.get("name")
            if loaded_name:
                self._sidebar.mark_skill_loaded(str(loaded_name))

        card = ToolCallCard(
            call_id=call.id,
            tool_name=call.name,
            args=call.arguments,
            result=result,
            elapsed_ms=elapsed_ms,
            preview_chars=self.cfg.card_preview_chars,
        )
        tool_msg = LLMMessage(
            role="tool",
            content=json.dumps(result.to_dict(), ensure_ascii=False),
            tool_call_id=call.id,
        )
        return card, tool_msg

    def _build_tools_schema(self) -> List[Dict[str, Any]]:
        schemas: List[Dict[str, Any]] = []
        for info in ToolService.list_tools():
            props: Dict[str, Any] = {}
            required: List[str] = []
            for pname, pdesc in info.parameters.items():
                props[pname] = _param_schema(pdesc)
                if "必需" in pdesc:
                    required.append(pname)
            schemas.append({
                "type": "function",
                "function": {
                    "name": info.name,
                    "description": info.description,
                    "parameters": {
                        "type": "object",
                        "properties": props,
                        "required": required,
                    },
                },
            })

        if self._mcp is not None:
            for server, tool, _qualified in self._mcp.all_tools():
                schemas.append(self._mcp.tool_schema(server, tool))
        return schemas

    # ---------- 快捷键 ----------

    def action_quit(self) -> None:
        self._quit_app()

    def action_toggle_sidebar(self) -> None:
        self._sidebar.toggle_collapsed()

    def action_help(self) -> None:
        self._handle_command("/help")
        self._prompt.focus()

    def action_new_session(self) -> None:
        self._new_session()

    def action_resume(self) -> None:
        self._open_resume_dialog()

    def action_compact(self) -> None:
        self._handle_command("/compact")

    def on_key(self, event) -> None:
        # 补全面板打开时，↑↓ 选命令、Esc 收起
        if self._palette.is_open:
            if event.key in ("up", "down"):
                self._palette.move(-1 if event.key == "up" else 1)
                event.stop()
                return
            if event.key == "escape":
                self._palette.hide()
                event.stop()
                return

        if event.key == "escape" and self._prompt.has_focus:
            if self._prompt.value:
                self._prompt.value = ""
            self._palette.hide()
            event.stop()

    def on_unmount(self) -> None:
        """窗口被直接关掉时也别把 MCP 子进程留成孤儿。"""
        if self._mcp is not None:
            self._mcp.close()
            self._mcp = None
