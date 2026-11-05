# -*- coding: utf-8 -*-
"""
xAgent.tui.app —— 对话式 LLM Agent（老师样式对齐版）。

老师界面结构：
  ┌─────────────────────────────────────────────────────────────────────────┐
  │ xAgent · 12 个工具 · deepseek-chat · /Users/...                        │ ← 自定义 Header
  │   Enter 发送 /help 命令 Esc 中断 Ctrl+B 侧栏 Ctrl+N 新会话             │
  ├──────────────────────────────────────────┬────────────────────────────┤
  │                                          │ 会话  deepseek-chat          │
  │ 对话流 VerticalScroll                     │ 模型  mock                   │
  │  [dim]你[/dim]                           │ 接口  https://api.deepseek   │
  │    xxx                                    │ 目录  /Users/...             │
  │  ┌─ ▸ isLeapYear(year=2026) · 2 ms ──┐  │ 会话  e9e7b179               │
  │  │ ▼ 参数 { "year": 2026 }            │  │ 轮次  1                      │
  │  │   结果 2026 年不是闰年...          │  │ 上限  8 次模型调用/轮        │
  │  └───────────────────────────────────┘  │ 状态  就绪                   │
  │  [dim]xAgent[/dim]                       │ ──────────────────────────── │
  │    不是...                                │ 工具                         │
  │                                          │ · getDate  获取当前...       │
  ├──────────────────────────────────────────┴────────────────────────────┤
  │ 输入问题后 Enter 发送 · /help Esc 中断生成                             │
  ├─────────────────────────────────────────────────────────────────────────┤
  │ 就绪 · 1 轮 · mock · 工具 2 次 · 2.9s · Esc 中断 · Ctrl+H · Ctrl+Q   │ ← StatusBar
  ├─────────────────────────────────────────────────────────────────────────┤
  │ q 退出 · ~ 清屏 · n 新会话 · b 侧栏 · f1 帮助 · p palette              │ ← Footer
  └─────────────────────────────────────────────────────────────────────────┘

配色：墨绿极简，唯一强调色为薄荷绿 —— 定义在 tui/theme.py 的 xagent-green，
      这里只写 $primary / $accent / $panel 这类语义变量，不写死颜色值。
"""

from __future__ import annotations

import json
import os
import time
import unicodedata
from typing import Any, Dict, List, Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical, Horizontal, VerticalScroll
from textual.reactive import reactive
from textual.widgets import (
    Static, Input, Label,
)

from xAgent.core import ToolService, ToolResult
from xAgent.core.skills import (
    build_skill_prompt, discover_skills, get_skill_registry,
)
from xAgent.core.config import (
    QIANFAN_API_KEY, QIANFAN_BASE_URL, QIANFAN_MODEL,
)
from xAgent.core.llm import (
    LLMMessage, ToolCall, MockProvider, OpenAICompatibleProvider,
)
from xAgent.tui.theme import install_theme


# ============================================================
# 自定义 Header（老师样式：两行 Static）
# ============================================================

class CustomHeader(Vertical):
    """老师样式的顶部 Header —— 两行 Static。"""

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
        tool_count = len(ToolService.list_tools())
        cwd = os.getcwd()
        # 老师显示完整路径，太长就截断末尾
        if len(cwd) > 45:
            cwd = "..." + cwd[-42:]
        self._line1 = Static(
            f"xAgent · {tool_count} 个工具 · mock · {cwd}",
            classes="line1",
        )
        self._line2 = Static(
            "Enter 发送 · Esc 清空 · Ctrl+B 侧栏",
            classes="line2",
        )

    def compose(self) -> ComposeResult:
        yield self._line1
        yield self._line2

    def set_model(self, model: str) -> None:
        tool_count = len(ToolService.list_tools())
        cwd = os.getcwd()
        if len(cwd) > 45:
            cwd = "..." + cwd[-42:]
        self._line1.update(f"xAgent · {tool_count} 个工具 · {model} · {cwd}")


# ============================================================
# 紧凑可折叠工具卡片（老师样式）
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
    ) -> None:
        super().__init__()
        self._call_id = call_id
        self._tool_name = tool_name
        self._args = args
        self._result = result
        self._elapsed_ms = elapsed_ms
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

    def _build_body(self, result: ToolResult) -> str:
        """构造展开后的参数 + 结果文本。"""
        args_json = json.dumps(self._args, ensure_ascii=False)
        flat = result.to_dict()
        # 结果内容做截断，老师截图里结果是单行/双行
        result_content: str
        if result.success:
            if "content" in flat and isinstance(flat["content"], str):
                result_content = flat["content"]
                if len(result_content) > 120:
                    result_content = result_content[:117] + "..."
            else:
                result_content = json.dumps(flat, ensure_ascii=False)
                if len(result_content) > 120:
                    result_content = result_content[:117] + "..."
        else:
            result_content = flat.get("error", str(flat))
            if len(result_content) > 120:
                result_content = result_content[:117] + "..."

        return f"[dim]参数[/dim]  {args_json}\n[dim]结果[/dim]  {result_content}"

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
    ConversationFlow .msg-body {
        width: 100%;
        color: $foreground;
        padding: 0 0 0 2;
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

    def clear_all(self) -> None:
        self.remove_children()


# ============================================================
# 右侧侧栏（老师样式：kv + 工具列表带灰色描述）
# ============================================================

# 侧栏 width 42 - 左边框 1 - 内边距 2 = 39 列；文本按实际可用宽度自动换行
_SIDEBAR_CONTENT = 39


class Sidebar(VerticalScroll):
    """右侧会话信息 + 工具列表（内容超高时可滚动）。"""

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
    Sidebar .divider {
        height: 1;
        color: $panel;
    }
    Sidebar .section-label {
        color: $primary;
        text-style: bold;
        height: 1;
        margin-top: 1;
    }
    Sidebar .tool-row {
        color: $foreground;
    }
    Sidebar .tool-row .tname {
        color: $foreground;
    }
    Sidebar .tool-row .tdesc {
        color: $text-muted;
    }
    Sidebar #side-mini {
        color: $primary;
        height: 1;
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

    _collapsed: bool = False

    # (控件 id, 前缀, 初始值) —— 只保留真正有值的行，占位符一律不展示
    _INFO_ROWS = (
        ("side-model", "模型  ", "mock"),
        ("side-api", "接口  ", "-"),
        ("side-cwd", "目录  ", ""),
        ("side-skills", "技能  ", "-"),
        ("side-round", "轮次  ", "1"),
        ("side-limit", "上限  ", "8 次模型调用/轮"),
        ("side-status", "状态  ", "就绪"),
    )

    def compose(self) -> ComposeResult:
        yield Label("▾", id="side-mini")

        # 内容宽度依赖运行时容器宽度（滚动条会占列），统一在 _refresh_width 里渲染
        self._loaded_skills: set[str] = set()
        self._skill_total = len(get_skill_registry().skills)
        self._info: Dict[str, List[str]] = {}
        for wid, prefix, value in self._INFO_ROWS:
            if wid == "side-cwd":
                value = os.getcwd()
            elif wid == "side-skills":
                value = self._skill_display()
            self._info[wid] = [prefix, value]
            yield Label("", classes="kv", id=wid)

        yield Label("工具", classes="section-label")

        self._tool_rows: List[tuple] = []
        for index, t in enumerate(ToolService.list_tools(), start=1):
            name_label = Label("", classes="kv")
            desc_label = Label("", classes="kv tdesc-line") if t.description else None
            self._tool_rows.append(
                (name_label, desc_label, index, t.name, t.description or "")
            )
            yield name_label
            if desc_label is not None:
                yield desc_label

    def on_mount(self) -> None:
        self.call_after_refresh(self._refresh_width)

    def on_resize(self, event) -> None:
        self.call_after_refresh(self._refresh_width)

    def _avail_width(self) -> int:
        """可用内容列数（扣除占位的垂直滚动条，避免文字被滚动条压住）。"""
        width = self.size.width - self.scrollbar_size_vertical
        return width if width > 0 else _SIDEBAR_CONTENT

    def _refresh_width(self) -> None:
        """按真实可用宽度重排所有文本，避免被容器硬切。"""
        if not self.is_mounted or self._collapsed:
            return
        avail = self._avail_width()
        if avail <= 0:
            return

        # 文本不再截断，超出宽度由底部横向滚动条查看
        for wid, (prefix, value) in self._info.items():
            raw = value
            if wid == "side-api" and raw not in ("", "-"):
                raw = raw.replace("https://", "").replace("http://", "").rstrip("/")
            self.query_one(f"#{wid}", Label).update(f"{prefix}{raw}")

        # 工具名独占一行（带序号），描述另起一行；两者都按宽度自动换行，不做截断
        for name_label, desc_label, index, name, desc in self._tool_rows:
            name_label.update(f"{index:>2d}. {name}")
            if desc_label is not None:
                desc_label.display = True
                desc_label.update(f"    {desc}" if desc else "")

    def _set_value(self, wid: str, value: str) -> None:
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

    # ---------- Skill 加载角标 ----------

    def _skill_display(self) -> str:
        """技能角标：已加载数/总数，以及已加载的技能名。"""
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
        """记录一次成功的 loadSkill，并在侧栏显示加载角标。"""
        if not name or name in self._loaded_skills:
            return
        self._loaded_skills.add(name)
        self._set_value("side-skills", self._skill_display())

    def reset_skill_loaded(self) -> None:
        self._loaded_skills.clear()
        self._set_value("side-skills", self._skill_display())

    # ---------- 最小化 / 展开 ----------

    def toggle_collapsed(self) -> None:
        """在完整侧栏与最小化竖条之间切换。"""
        self._collapsed = not self._collapsed
        self.set_class(self._collapsed, "-collapsed")
        for child in self.children:
            if child.id != "side-mini":
                child.display = not self._collapsed
        self.query_one("#side-mini", Label).update("▸" if self._collapsed else "▾")
        if not self._collapsed:
            # 等布局按新宽度重算后再重排文本
            self.call_after_refresh(self._refresh_width)

    def on_click(self) -> None:
        """最小化状态下点击竖条任意位置恢复侧栏。"""
        if self._collapsed:
            self.toggle_collapsed()


# ============================================================
# 底部 StatusBar（老师样式：就绪 · N轮 · model · 工具 N次 · Ns · 快捷键）
# ============================================================

class StatusBar(Static):
    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        width: 100%;
        color: $text-muted;
        background: $surface;
        padding: 0 2;
    }
    """

    def update_status(
        self,
        ready: bool = True,
        round_no: int = 1,
        model: str = "mock",
        tool_calls: int = 0,
        elapsed_ms: int = 0,
    ) -> None:
        parts = []
        parts.append("就绪" if ready else "生成中")
        parts.append(f"{round_no} 轮")
        parts.append(model)
        parts.append(f"工具 {tool_calls} 次")
        if elapsed_ms:
            # 老师用 Ns 格式
            parts.append(f"{elapsed_ms / 1000:.1f}s")
        # 快捷键统一放 Footer，这里只留状态数据，避免两行重复
        self.update(" · ".join(parts))


# ============================================================
# 自定义 Footer（老师样式：快捷键提示）
# ============================================================

class CustomFooter(Static):
    """底部快捷键栏。"""

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
        # 只列真实存在的命令，别写没实现的
        yield Static(
            "/help 帮助 · /clear 清屏 · /new 新会话 · /quit 退出",
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
    """对话式 LLM Agent（老师样式对齐版）。"""

    # Textual App 元信息（不用默认 Header/Footer）
    TITLE = "xAgent"

    # Ctrl+B：输入框有焦点时也能触发（单个 b 会被输入框吃掉）
    BINDINGS = [
        Binding("ctrl+b", "toggle_sidebar", "侧栏"),
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
    """

    round_no = reactive(1)
    tool_calls_total = reactive(0)

    _messages: List[LLMMessage] = []
    _provider: Any
    _model_label: str = "mock"
    _skill_prompt: str = ""

    def compose(self) -> ComposeResult:
        # 自定义 Header（老师样式）
        yield CustomHeader()

        # 主区
        with Container(id="main-row"):
            yield ConversationFlow(id="conversation")
            yield Sidebar(id="sidebar")

        # 底部输入框
        with Container(id="prompt-row"):
            yield Input(
                placeholder="问点什么 · Enter 发送 · /help 查看命令 · Esc 清空",
                id="prompt",
                restrict=None,
            )

        # 状态栏
        yield StatusBar("就绪 · 1 轮 · mock · 工具 0 次")

        # 自定义 Footer
        yield CustomFooter()

    def on_mount(self) -> None:
        # 主题必须在查控件之前装好，否则首帧会闪一下默认蓝色
        install_theme(self)

        self._conversation = self.query_one("#conversation", ConversationFlow)
        self._sidebar = self.query_one("#sidebar", Sidebar)
        self._prompt = self.query_one("#prompt", Input)
        self._status = self.query_one(StatusBar)
        self._header = self.query_one(CustomHeader)

        # 按 config 初始化 LLM
        self._init_provider()

        # Skill 发现：以启动时的工作目录为项目根目录，只加载 name / description
        registry = discover_skills()
        self._skill_prompt = build_skill_prompt(registry)
        self._sidebar.set_skill_total(len(registry.skills))

        # 欢迎消息
        self._conversation.add_assistant_message(
            "你好，我是 xAgent。我可以帮你操作文件系统。\n\n"
            "试试：'列出当前目录'、'读取 README.md 的内容'、"
            "'创建文件 demo.txt' 或者输入 /help。"
        )
        self._prompt.focus()

    # ---------- LLM 初始化 ----------

    def _init_provider(self) -> None:
        """有 Key 用千帆，无 Key 回落本地 Mock。"""
        if QIANFAN_API_KEY:
            self._provider = OpenAICompatibleProvider(
                api_key=QIANFAN_API_KEY,
                base_url=QIANFAN_BASE_URL,
                model=QIANFAN_MODEL,
            )
            self._model_label = QIANFAN_MODEL
            api_label = QIANFAN_BASE_URL
        else:
            self._provider = MockProvider()
            self._model_label = "mock"
            api_label = "-"

        self._header.set_model(self._model_label)
        self._sidebar.set_model(self._model_label)
        self._sidebar.set_api(api_label)

    # ---------- 输入处理 ----------

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return
        if text.startswith("/"):
            self._handle_command(text)
        else:
            self._run_user_turn(text)

    def _handle_command(self, cmd: str) -> None:
        parts = cmd.split(maxsplit=1)
        head = parts[0].lower()

        if head in ("/help", "/?"):
            self._conversation.add_assistant_message(
                """xAgent 帮助

使用方式：直接输入自然语言，我会自动选择工具。

命令：
  /help              显示此帮助
  /clear             清空对话
  /new               新建会话
  /tools             列出所有工具
  /cwd               显示当前目录
  /model             查看当前模型与接口
  /quit              退出程序"""
            )
        elif head == "/clear":
            self._conversation.clear_all()
        elif head == "/new":
            self._conversation.clear_all()
            self._messages = []
            self.round_no = 1
            self.tool_calls_total = 0
            self._sidebar.set_round(1)
            self._sidebar.reset_skill_loaded()
            self._conversation.add_assistant_message("新会话已创建。")
        elif head == "/tools":
            lines = []
            for t in ToolService.list_tools():
                lines.append(f"  · {t.name:<20} {t.description}")
            self._conversation.add_assistant_message("可用工具：\n" + "\n".join(lines))
        elif head == "/cwd":
            self._conversation.add_assistant_message(f"当前目录：{os.getcwd()}")
        elif head == "/model":
            self._conversation.add_assistant_message(
                f"模型：{self._model_label}\n"
                f"接口：{QIANFAN_BASE_URL if QIANFAN_API_KEY else '-'}"
            )
        elif head in ("/quit", "/exit", "/q"):
            self.exit()
        else:
            self._conversation.add_assistant_message(f"未知命令：{cmd}。输入 /help 查看可用命令。")

    # ---------- 核心：一轮对话 ----------

    _MAX_MODEL_CALLS = 8  # 单轮最多模型调用次数，防止工具死循环

    def _ensure_skill_prompt(self) -> None:
        """把 Skill 清单注入 System Prompt；/new 清空历史后重新注入。"""
        if not self._skill_prompt:
            return
        if self._messages and self._messages[0].role == "system":
            return
        self._messages.insert(
            0, LLMMessage(role="system", content=self._skill_prompt)
        )

    def _run_user_turn(self, user_text: str) -> None:
        self._ensure_skill_prompt()
        self._conversation.add_user_message(user_text)
        self._messages.append(LLMMessage(role="user", content=user_text))

        model_label = self._model_label
        self._status.update_status(
            ready=False, round_no=self.round_no, model=model_label
        )
        self._sidebar.set_status("生成中")

        tools_schema = self._build_tools_schema()

        t0 = time.time()
        try:
            self._run_model_loop(tools_schema)
        except Exception as exc:
            self._conversation.add_assistant_message(f"LLM 调用失败：{exc}")
            self._status.update_status(
                ready=True, round_no=self.round_no, model=model_label
            )
            self._sidebar.set_status("就绪")
            return

        total_ms = int((time.time() - t0) * 1000)
        self._status.update_status(
            ready=True, round_no=self.round_no, model=model_label,
            tool_calls=self.tool_calls_total, elapsed_ms=total_ms,
        )

        self.round_no += 1
        self._sidebar.set_round(self.round_no)
        self._sidebar.set_status("就绪")

    def _run_model_loop(self, tools_schema: List[Dict[str, Any]]) -> None:
        """
        反复调用模型直到不再请求工具。

        关键：assistant 的每个 tool_call 都必须有对应的 tool 消息回传，
        否则下一轮请求会被千帆判为消息格式错误
        （Message format error, index[i] should be [tool] but is [user]）。
        """
        for _ in range(self._MAX_MODEL_CALLS):
            response = self._provider.chat(self._messages, tools_schema)
            self._messages.append(response)

            if not response.tool_calls:
                if response.content:
                    self._conversation.add_assistant_message(response.content.strip())
                return

            for tc in response.tool_calls:
                card, tool_msg = self._execute_tool(tc)
                if card:
                    self._conversation.add_tool_card(card)
                self._messages.append(tool_msg)
                self.tool_calls_total += 1

        self._conversation.add_assistant_message(
            f"（已达到单轮 {self._MAX_MODEL_CALLS} 次模型调用上限，停止继续调用工具）"
        )

    def _execute_tool(self, tc: ToolCall) -> tuple[Optional[ToolCallCard], LLMMessage]:
        t0 = time.time()
        result = ToolService.call(tc.name, **tc.arguments)
        elapsed_ms = int((time.time() - t0) * 1000)

        # loadSkill 成功后在侧栏点亮技能加载角标
        if tc.name == "loadSkill" and result.success:
            loaded_name = result.data.get("name")
            if loaded_name:
                self._sidebar.mark_skill_loaded(str(loaded_name))

        card = ToolCallCard(
            call_id=tc.id,
            tool_name=tc.name,
            args=tc.arguments,
            result=result,
            elapsed_ms=elapsed_ms,
        )
        tool_msg = LLMMessage(
            role="tool",
            content=json.dumps(result.to_dict(), ensure_ascii=False),
            tool_call_id=tc.id,
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
        return schemas

    # ---------- 快捷键 ----------

    def action_quit(self) -> None:
        self.exit()

    def action_toggle_sidebar(self) -> None:
        self._sidebar.toggle_collapsed()

    def action_help(self) -> None:
        self._handle_command("/help")
        self._prompt.focus()

    def action_clear(self) -> None:
        self._handle_command("/clear")

    def action_new_session(self) -> None:
        self._handle_command("/new")

    def on_key(self, event) -> None:
        if event.key == "escape" and self._prompt.has_focus:
            self._prompt.value = ""
            event.stop()
