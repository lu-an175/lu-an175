# -*- coding: utf-8 -*-
"""
xAgent.tui.dialogs —— 模态对话框（配置提示 / 历史会话选择）。

都是 ModalScreen：压在当前界面之上，关闭后把结果 dismiss 回去。
"""

from __future__ import annotations

from typing import List, Optional, Sequence

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from xAgent.core.session import SessionMeta

_DIALOG_CSS = """
    %(screen)s {
        align: center middle;
        background: $background 70%%;
    }
    %(screen)s #dialog {
        width: 84;
        height: auto;
        max-height: 80%%;
        background: $panel;
        border: round $primary;
        padding: 1 2;
    }
    %(screen)s .dialog-title {
        color: $primary;
        text-style: bold;
        height: auto;
        margin-bottom: 1;
    }
    %(screen)s .dialog-body {
        height: auto;
        color: $foreground;
    }
    %(screen)s .dialog-hint {
        height: 1;
        margin-top: 1;
        color: $text-muted;
    }
"""


class InfoDialog(ModalScreen[None]):
    """一条消息 + 一个「知道了」。用于首次运行提示、错误说明。"""

    DEFAULT_CSS = _DIALOG_CSS % {"screen": "InfoDialog"}

    BINDINGS = [
        Binding("escape", "close", "关闭"),
        Binding("enter", "close", "关闭"),
    ]

    def __init__(self, title: str, body: str, hint: str = "按 Enter 或 Esc 关闭") -> None:
        super().__init__()
        self._title = title
        self._body = body
        self._hint = hint

    def compose(self) -> ComposeResult:
        with Container(id="dialog"):
            yield Static(self._title, classes="dialog-title")
            yield Static(self._body, classes="dialog-body")
            yield Static(self._hint, classes="dialog-hint")

    def action_close(self) -> None:
        self.dismiss(None)


class SessionPicker(ModalScreen[Optional[str]]):
    """
    历史会话列表：↑↓ 选择、回车恢复、Esc 取消。

    dismiss 的返回值是会话编号；取消时为 None。
    """

    DEFAULT_CSS = _DIALOG_CSS % {"screen": "SessionPicker"} + """
    SessionPicker OptionList {
        height: auto;
        max-height: 16;
        background: $surface;
        border: none;
    }
    SessionPicker OptionList > .option-list--option {
        padding: 0 1;
    }
    SessionPicker OptionList > .option-list--option-highlighted {
        background: $secondary;
        color: $foreground;
        text-style: bold;
    }
    /* 列表有焦点时 Textual 会用主题的 block-cursor 覆盖高亮，这里压回去 */
    SessionPicker OptionList:focus > .option-list--option-highlighted {
        background: $secondary;
        color: $foreground;
        text-style: bold;
    }
    """

    BINDINGS = [Binding("escape", "cancel", "取消")]

    def __init__(self, sessions: Sequence[SessionMeta], current_id: str = "") -> None:
        super().__init__()
        self._sessions: List[SessionMeta] = list(sessions)
        self._current_id = current_id

    def compose(self) -> ComposeResult:
        with Container(id="dialog"):
            yield Static(
                f"历史会话（{len(self._sessions)} 个）", classes="dialog-title"
            )
            yield OptionList(
                *[
                    Option(self._label(session), id=session.id)
                    for session in self._sessions
                ],
                id="session-list",
            )
            yield Static(
                "↑↓ 选择 · Enter 恢复 · Esc 取消", classes="dialog-hint"
            )

    def _label(self, session: SessionMeta) -> str:
        marker = "● " if session.id == self._current_id else "  "
        title = session.display_title
        if len(title) > 40:
            title = title[:39] + "…"
        time_text = (session.display_time or "")[5:16]  # 去掉年份
        return (
            f"{marker}{session.id}  {time_text}  "
            f"{session.message_count:>3d} 条  {title}"
        )

    def on_mount(self) -> None:
        option_list = self.query_one("#session-list", OptionList)
        option_list.focus()
        # 默认高亮当前会话（没有就高亮第一条）
        for index, session in enumerate(self._sessions):
            if session.id == self._current_id:
                option_list.highlighted = index
                break

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self.dismiss(str(event.option_id))

    def action_cancel(self) -> None:
        self.dismiss(None)
