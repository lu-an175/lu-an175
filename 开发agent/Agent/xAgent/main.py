# -*- coding: utf-8 -*-
"""
xAgent 统一入口。

用法：
  python main.py              # 启动 Textual TUI
  python main.py --demo       # 运行 core 层烟雾测试（无 UI）
  python main.py --list       # 列出所有可用工具
  python main.py --run <tool> [key=val ...]   # 直接调用工具（shell 友好）
  python main.py --tui        # 显式启动 TUI（默认）
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# 自举：把 xAgent 的父目录加入 sys.path，使 `python xAgent/main.py` 也能正确 import 包
_HERE = Path(__file__).resolve().parent
if str(_HERE.parent) not in sys.path:
    sys.path.insert(0, str(_HERE.parent))

from xAgent.core import ToolService, call_tool


# ---------- 子命令实现 ----------

def cmd_list() -> int:
    for t in ToolService.list_tools():
        print(f"  {t.name}")
        print(f"    {t.description}")
        if t.parameters:
            for p, desc in t.parameters.items():
                print(f"      ├─ {p}: {desc}")
    return 0


def cmd_run(args: list[str]) -> int:
    if not args:
        print("用法: main.py --run <tool_name> [key=val ...]")
        return 2
    tool_name, *rest = args
    kwargs: dict[str, str] = {}
    for pair in rest:
        if "=" in pair:
            k, v = pair.split("=", 1)
            kwargs[k] = v
    result = call_tool(tool_name, **kwargs)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("success") else 1


def cmd_demo() -> int:
    """对所有 10 个工具跑一遍核心逻辑测试，不依赖任何 UI。"""
    import tempfile, os
    from xAgent.core import ToolService

    with tempfile.TemporaryDirectory() as tmp:
        work = os.path.join(tmp, "demo_root")
        os.makedirs(work)
        results = []

        # 1. cwd
        r = ToolService.call("get_current_working_directory")
        results.append(("get_current_working_directory", r.success))

        # 2. list_directory
        r = ToolService.call("list_directory", path=work)
        results.append(("list_directory", r.success))

        # 7. create_directory
        sub = os.path.join(work, "sub")
        r = ToolService.call("create_directory", dir_path=sub)
        results.append(("create_directory", r.success))

        # 5. create_file
        f = os.path.join(sub, "hello.txt")
        r = ToolService.call("create_file", file_path=f, content="hi")
        results.append(("create_file", r.success))

        # 3. get_file_type
        r = ToolService.call("get_file_type", file_path=f)
        results.append(("get_file_type", r.success))

        # 4. read_file
        r = ToolService.call("read_file", file_path=f)
        results.append(("read_file", r.success))

        # 6. write_file (append)
        r = ToolService.call("write_file", file_path=f, content="more", mode="append")
        results.append(("write_file", r.success))

        # 10. rename_item
        new = os.path.join(sub, "hello_renamed.txt")
        r = ToolService.call("rename_item", source_path=f, new_name="hello_renamed.txt")
        results.append(("rename_item", r.success))

        # 9. delete_file
        r = ToolService.call("delete_file", file_path=new)
        results.append(("delete_file", r.success))

        # 8. delete_directory
        r = ToolService.call("delete_directory", dir_path=work, force="true")
        results.append(("delete_directory", r.success))

    ok = all(s for _, s in results)
    for name, success in results:
        print(f"  {'✅' if success else '❌'} {name}")
    print(f"\n总计 {len(results)} 项，{'全部通过' if ok else '有失败'}")
    return 0 if ok else 1


def cmd_tui() -> int:
    from xAgent.tui import XAgentApp

    XAgentApp().run()
    return 0


def bootstrap_config() -> None:
    """
    启动前确保「当前目录」有 config.ini。

    没有就生成一份 mock 模板 —— TUI 会弹窗提示用户改完重启；
    这次运行照样能进界面（Mock 模式），不至于连程序都跑不起来。
    """
    from xAgent.core.config import ensure_config_file, reload_config

    bootstrap = ensure_config_file()
    reload_config(bootstrap.path if bootstrap.created else None)

    if bootstrap.error:
        print(f"[xAgent] {bootstrap.error}")
    elif bootstrap.created:
        print(f"[xAgent] 已创建配置文件：{bootstrap.path}")
        if bootstrap.seeded_from:
            print(f"[xAgent] 已从旧配置迁移 API Key：{bootstrap.seeded_from}")
        else:
            print("[xAgent] 当前为 Mock 模式，请填写 [llm] api_key 后重启以接入真实模型。")


# ---------- 入口 ----------

HELP_TEXT = """
xAgent — 文件操作 Agent（Core + TUI 架构）

用法:
  python main.py                 启动 Textual TUI（默认）
  python main.py --tui          显式启动 TUI
  python main.py --demo         运行 core 层烟雾测试
  python main.py --list         列出所有工具
  python main.py --run <tool> [key=val ...]   直接调用工具
  python main.py -h | --help    显示帮助

首次运行会在当前目录生成 config.ini（mock 配置），修改后重启生效。
"""


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]

    if argv and argv[0] in ("-h", "--help"):
        print(HELP_TEXT)
        return 0

    bootstrap_config()

    if not argv or argv[0] in ("--tui", "-tui"):
        return cmd_tui()
    if argv[0] == "--demo":
        return cmd_demo()
    if argv[0] == "--list":
        return cmd_list()
    if argv[0] == "--run":
        return cmd_run(argv[1:])
    print(f"未知参数: {argv[0]}")
    print(HELP_TEXT)
    return 2


if __name__ == "__main__":
    sys.exit(main())
