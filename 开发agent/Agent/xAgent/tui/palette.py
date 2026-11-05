# -*- coding: utf-8 -*-
"""
xAgent.tui.palette —— 斜杠命令补全面板。

行为
    输入框内容以 / 开头且还没敲空格时，面板出现在输入框上方；
    ↑↓ 移动、回车执行、Esc 收起。敲空格进入参数后自动收起。

样式
    只有选中行有底色（$boost），其余留白 —— 和整体极简风格一致。
"""

from __future__ import annotations

from typing import List, Optional

from rich.text import Text
from textual.widgets import Static

from .commands import SlashCommand, filter_commands


class CommandPalette(Static):
    """命令补全面板。"""

    DEFAULT_CSS = """
    CommandPalette {
        height: 0;
        max-height: 9;
        width: 100%;
        overflow: hidden;
        background: $panel;
        border: none;
        border-left: thick $primary;
        padding: 0 2;
        margin: 0 0 0 1;
    }
    CommandPalette.-visible {
        height: auto;
    }
    """

    def __init__(self, content=None, **kwargs) -> None:
        # 必须给一个初始 renderable：空 Static（content=None）+ height:auto
        # 会让 Textual 在首帧布局时拿到 visual=None 直接抛异常
        super().__init__(content if content is not None else Text(""), **kwargs)
        self._items: List[SlashCommand] = []
        self._index = 0
        #: 上一次真正高亮过的命令（回车时用它补全）
        self.selection: Optional[SlashCommand] = None

    # ---------- 状态 ----------

    @property
    def is_open(self) -> bool:
        return self.has_class("-visible")

    @property
    def items(self) -> List[SlashCommand]:
        return list(self._items)

    def refresh_items(self, prefix: str) -> List[SlashCommand]:
        """按输入前缀刷新候选；没有候选就自动收起。"""
        self._items = filter_commands(prefix)
        self._index = 0
        if not self._items:
            self.hide()
            return []
        self.selection = self._items[0]
        self.add_class("-visible")
        self._render_items()
        return self._items

    def hide(self) -> None:
        self.remove_class("-visible")
        self._items = []
        self._index = 0

    def move(self, delta: int) -> Optional[SlashCommand]:
        """↑↓ 移动高亮项（循环）。"""
        if not self._items:
            return None
        self._index = (self._index + delta) % len(self._items)
        self.selection = self._items[self._index]
        self._render_items()
        return self.selection

    def current(self) -> Optional[SlashCommand]:
        if not self._items:
            return None
        return self._items[self._index]

    # ---------- 渲染 ----------

    def _render_items(self) -> None:
        # 主题色从当前 Theme 里取，不在代码里写死颜色
        try:
            primary = str(self.app.theme_variables.get("primary", "green"))
        except Exception:  # 还没挂到 App 上（单元测试）
            primary = "green"

        lines = Text()
        usage_width = max((len(c.display_usage) for c in self._items), default=0)
        for position, command in enumerate(self._items):
            selected = position == self._index
            if position:
                lines.append("\n")
            if selected:
                lines.append("▸ ", style=f"bold {primary}")
            else:
                lines.append("  ")
            usage = f"{command.display_usage:<{usage_width}}"
            lines.append(usage, style="bold" if selected else "default")
            lines.append("  ")
            lines.append(command.description, style="dim" if selected else "italic dim")
        self.update(lines)
