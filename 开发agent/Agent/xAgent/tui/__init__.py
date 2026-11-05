# -*- coding: utf-8 -*-
"""
xAgent.tui —— 基于 Textual 的终端界面层。

只依赖 xAgent.core（ToolService），不依赖 tools.py 内部函数。
"""

from .app import XAgentApp

# 兼容别名
FileOpsApp = XAgentApp

__all__ = ["XAgentApp", "FileOpsApp"]
