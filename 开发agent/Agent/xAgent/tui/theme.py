# -*- coding: utf-8 -*-
"""
xAgent.tui.theme —— 界面主题（墨绿 / 极简）。

设计原则
    1. 只有一个强调色：薄荷绿（primary）。其余全是低饱和的墨绿灰阶。
    2. 结构靠留白和细线区分，不靠粗边框 —— border 只在"需要被注意"的地方出现。
    3. 绿色只出现在四处：标题、区块标签、工具卡片左侧竖条、输入框聚焦态。

用法
    from xAgent.tui.theme import install_theme
    install_theme(self)      # 在 App.on_mount 里调用
"""

from __future__ import annotations

from textual.theme import Theme

# ------------------------------------------------------------
# 色板
# ------------------------------------------------------------

GREEN_THEME_NAME = "xagent-green"

XAGENT_GREEN = Theme(
    name=GREEN_THEME_NAME,
    dark=True,
    # 唯一强调色：薄荷绿
    primary="#3ddc97",
    # 深绿：用于次级强调（滚动条、非聚焦边框）
    secondary="#1f6f52",
    # 浅绿：标题 / 区块标签，保证在深底上可读
    accent="#8ff0b8",
    # 中性前景：带一点绿调的灰白，避免纯白刺眼
    foreground="#d6e7de",
    # 三级背景：底 → 面板 → 卡片，靠明度差分层，不靠边框
    background="#0a1410",
    surface="#0f1d18",
    panel="#142720",
    boost="#1b352b",
    success="#3ddc97",
    warning="#e3b341",
    error="#ff7b72",
    # 让 derived 颜色（surface-darken-N 等）的跨度更收敛
    luminosity_spread=0.12,
    text_alpha=0.95,
)


def install_theme(app) -> None:
    """注册并切换到 xAgent 绿色主题。"""
    app.register_theme(XAGENT_GREEN)
    app.theme = GREEN_THEME_NAME
