# -*- coding: utf-8 -*-
"""
xAgent —— 文件操作 Agent 多端架构。

目录结构：
  xAgent/
  ├── core/        # 纯逻辑层（零 UI 依赖）
  │   ├── types.py       ToolResult / ToolInfo dataclass
  │   ├── tools.py       10 个文件操作纯函数
  │   ├── registry.py    TOOLS / call_tool / ToolService 门面
  │   └── __init__.py
  ├── tui/         # Textual 终端界面（仅依赖 core）
  │   ├── app.py         FileOpsApp
  │   └── __init__.py
  ├── main.py      # 统一入口
  └── __init__.py  # 预留 web/desktop/mobile 等前端层

设计原则：
  - core 不知道任何 UI 的存在；各前端只 import core.ToolService
  - 新增前端（web/desktop/mobile）只需新建目录，零修改 core
  - 旧版 Practice02/chat-stream-tool-fileops.py 仍可通过
    xAgent.core.call_tool / xAgent.core.TOOLS 兼容调用
"""

from .core import ToolService, ToolResult, ToolInfo, TOOLS, call_tool

__all__ = ["ToolService", "ToolResult", "ToolInfo", "TOOLS", "call_tool"]
