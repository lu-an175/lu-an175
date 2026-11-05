# xAgent — 多端文件操作 Agent

基于 Practice02/chat-stream-tool-fileops.py 重构，采用 **Core / UI 彻底分离** 的
软件工程分层架构，支持未来扩展 Web / Desktop / Mobile 等任意前端。

## 目录结构

```
xAgent/
├── core/                   纯逻辑层（零 UI 依赖）
│   ├── types.py            ToolResult / ToolInfo dataclass
│   ├── tools.py            10 个文件操作纯函数（仅标准库）
│   ├── registry.py         ToolService 门面 + call_tool + TOOLS 注册表
│   └── __init__.py         统一入口
├── tui/                    Textual 终端界面（仅依赖 core）
│   ├── app.py              XAgentApp（Header / 对话流 / 侧栏 / 输入 / 状态栏）
│   ├── theme.py            绿色主题（xagent-green）+ install_theme()
│   └── __init__.py
├── tests/                  独立单元测试
│   ├── test_tool_service.py
│   └── __init__.py
├── main.py                 统一 CLI 入口（TUI / demo / list / run）
└── __init__.py
```

## 设计原则

| 原则 | 说明 |
|------|------|
| **单向依赖** | 所有前端（tui/web/desktop/mobile）只 import `core.ToolService`，反向依赖禁止 |
| **core 纯净** | `tools.py` 只用 `os/pathlib/shutil/mimetypes` 标准库，不知任何 UI 存在 |
| **门面模式** | UI 层只通过 `ToolService` 调用，不直接触碰 `tools.py` 内部函数 |
| **dataclass 契约** | `ToolResult` / `ToolInfo` 是前后端间的唯一数据契约，支持 JSON 序列化 |
| **向后兼容** | 保留 `TOOLS` dict 和 `call_tool()` 函数，Practice02 旧代码无需改动 |

## 分层架构图

```
┌─────────────────────────────────────────────────────────┐
│                    前端层（可替换）                       │
│  tui/  web/  desktop/  mobile/    ← 互相独立，互不依赖    │
└────────────┬────────────────────────────────────────────┘
             │ 只 import ToolService.call() / .list_tools()
             ▼
┌─────────────────────────────────────────────────────────┐
│  core/registry.py          ToolService 门面              │
│                            （参数校验、类型转换、异常包装） │
└────────────┬────────────────────────────────────────────┘
             │ 内部调用
             ▼
┌─────────────────────────────────────────────────────────┐
│  core/tools.py             10 个纯函数                    │
│  core/types.py             ToolResult / ToolInfo          │
└─────────────────────────────────────────────────────────┘
```

## CLI 用法

```bash
# 启动 Textual TUI
python xAgent/main.py

# 跑 core 层烟雾测试（无 UI 依赖）
python xAgent/main.py --demo

# 列出所有工具及参数
python xAgent/main.py --list

# 直接调用某个工具（shell 友好）
python xAgent/main.py --run get_current_working_directory
python xAgent/main.py --run create_file file_path=new.txt content=hello
python xAgent/main.py --run list_directory path=.
```

## 编程调用

```python
from xAgent.core import ToolService, call_tool

# 推荐：门面类，返回 ToolResult
result = ToolService.call("read_file", file_path="test.txt")
if result.success:
    print(result.data["content"])

# 兼容旧版：直接返回 dict
r = call_tool("rename_item", source_path="a.txt", new_name="b.txt")
print(r["success"], r.get("message"))
```

## 新增前端配方（Web 为例）

整个流程**零修改 core 层**：

```bash
# 1. 创建目录
mkdir -p xAgent/web
touch xAgent/web/__init__.py
```

```python
# xAgent/web/app.py —— 以 Flask 为例
from flask import Flask, jsonify, request
from xAgent.core import ToolService

app = Flask(__name__)

@app.post("/api/tool/<name>")
def run_tool(name):
    params = request.get_json(force=True) or {}
    result = ToolService.call(name, **params)
    return jsonify(result.to_dict())

@app.get("/api/tools")
def list_tools():
    return jsonify([t.to_dict() for t in ToolService.list_tools()])

if __name__ == "__main__":
    app.run(port=8080)
```

启动：
```bash
pip install flask
python xAgent/web/app.py
curl -X POST http://localhost:8080/api/tool/get_current_working_directory
```

Desktop（PySide6）、Mobile（Kivy）同理 —— 只需新建目录，import `xAgent.core.ToolService`，
把 ToolInfo 渲染成 UI 表单即可。

## 测试

```bash
# 新架构独立测试
python -m unittest discover -s xAgent/tests -v

# 原 Practice02 58 个测试（回归）
cd Practice02 && python -m unittest test_fileops -v
```

## 10 个工具清单

| # | 名称 | 功能 |
|---|------|------|
| 1 | `get_current_working_directory` | 获取当前工作目录 |
| 2 | `list_directory` | 列出目录内容 |
| 3 | `get_file_type` | 获取文件类型/MIME |
| 4 | `read_file` | 读取纯文本文件（二进制拒绝） |
| 5 | `create_file` | 创建文件（自动级联创建父目录） |
| 6 | `write_file` | 覆盖 / 追加写入 |
| 7 | `create_directory` | 创建目录（级联） |
| 8 | `delete_directory` | 删除目录（force 可删非空） |
| 9 | `delete_file` | 删除文件 |
| 10 | `rename_item` | 重命名文件 / 目录（保守拒绝覆盖） |

## 安全约束（tools.py 已内置）

- 二进制文件拒绝读取
- 不能删除当前工作目录或其祖先目录
- `rename_item` 拒绝含路径分隔符的新名称（防止越权）
- `rename_item` 目标已存在时**拒绝覆盖**，不做自动编号
- `delete_directory` 默认 `force=True`，`force=False` 时非空目录被拒
