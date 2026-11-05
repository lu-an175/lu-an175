# -*- coding: utf-8 -*-
"""允许 `python -m xAgent` 直接启动 TUI。"""

from xAgent.main import main

if __name__ == "__main__":
    raise SystemExit(main())
