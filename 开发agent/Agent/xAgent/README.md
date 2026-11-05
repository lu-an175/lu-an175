# xAgent — 多端文件操作 Agent

基于 Practice02/chat-stream-tool-fileops.py 重构，采用 **Core / UI 彻底分离** 的
软件工程分层架构，支持未来扩展 Web / Desktop / Mobile 等任意前端。

## 目录结构

```
xAgent/
├── core/                   纯逻辑层（零 UI 依赖）
│   ├── types.py            ToolResult / ToolInfo dataclass
│   ├── tools.py            文件操作 + 联网 + CLI 的纯函数
│   ├── config.py           配置解析 / 首次运行生成 config.ini / 默认值兜底
│   ├── context.py          上下文计量 / 归档 / 检索 / 压缩
│   ├── session.py          会话保存 / 列表 / 恢复 / AGENTS.md 注入
│   ├── mcp.py              MCP stdio 客户端 + 多服务器管理器（异步加载）
│   ├── registry.py         ToolService 门面 + call_tool + TOOLS 注册表
│   └── __init__.py         统一入口
├── tui/                    Textual 终端界面（仅依赖 core）
│   ├── app.py              XAgentApp（Header / 对话流 / 侧栏 / 输入 / 状态栏）
│   ├── commands.py         斜杠命令表 + 补全匹配（纯数据）
│   ├── palette.py          命令补全面板
│   ├── dialogs.py          模态框（首次运行提示 / 历史会话选择）
│   ├── theme.py            绿色主题（xagent-green）+ install_theme()
│   └── __init__.py
├── mcp_servers/
│   └── demo_server.py      自带的示例 MCP 服务器（echo / now / count_chars）
├── tests/                  独立单元测试
│   ├── test_tool_service.py
│   ├── test_context.py     上下文压缩 / 归档 / 检索
│   ├── test_config.py      配置解析 / 模板生成 / 迁移
│   ├── test_session.py     会话保存 / 恢复 / AGENTS.md
│   ├── test_mcp.py         MCP 客户端（起真实子进程）
│   ├── test_commands.py    斜杠命令补全匹配
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

## 配置文件

配置跟着项目走：**运行时当前目录下的 `config.ini`**（环境变量 `XAGENT_CONFIG` 可指定别处）。

首次在某个目录启动时，如果那里没有 `config.ini`，xAgent 会自动生成一份完整的模板
（mock 值，无需联网），并弹窗提示「改完重启」。当前目录有旧版
`core/config.ini` 时会把 API Key 迁移过去，免得升级一次 key 就丢了。

```ini
[llm]        provider / api_key / base_url / model / search_url / search_model / timeout
[agent]      max_model_calls            ; 单轮最多调几次模型（防工具死循环）
[context]    window / compact_threshold / target_tokens / archive_dir
[session]    dir / auto_save / agents_md / agents_md_file
[ui]         sidebar_width / card_preview_chars / show_command_palette
[mcp]        enabled / servers / timeout
[mcp:名称]   transport / command / args / env / enabled / timeout
```

代码里只剩「默认值」这一份兜底（`core/config.py: DEFAULTS`），
没有任何行为参数写死在 UI 里；脏值会被吃掉并在 `/config` 里列出来。

## 斜杠命令

输入 `/` 会弹出**补全面板**：↑↓ 选择、Enter 执行、Esc 收起，敲空格自动收起进参数。

| 命令 | 作用 |
|------|------|
| `/help` | 帮助（直接从命令表生成，不会实现与文档不一致） |
| `/new [标题]` | 新建会话，**自动保存当前会话**（别名 `/clear`） |
| `/save [标题]` | 把当前会话写进 `.agents/sessions/<编号>.jsonl` |
| `/resume` | 历史会话面板：↑↓ 选择、Enter 恢复、Esc 取消（别名 `/sessions`） |
| `/compact` | 压缩上下文（归档 + 摘要） |
| `/tools` | 列出本地工具 + 已连上的 MCP 工具 |
| `/mcp [reload]` | 查看 MCP 服务器状态；`reload` 重连 |
| `/agents` | 查看 AGENTS.md 注入状态 |
| `/model` | 当前模型 / 接口 / 上下文窗口 / 阈值 |
| `/config` | 配置文件路径与关键配置项 |
| `/cwd` | 当前工作目录 |
| `/export [路径]` | 导出为 Markdown（默认 `.agents/exports/<时间>.md`） |
| `/quit` | 保存会话、关闭 MCP 子进程后退出 |

快捷键：`Ctrl+B` 侧栏 · `Ctrl+K` 压缩 · `Ctrl+N` 新会话 · `Ctrl+R` 历史会话 · `Ctrl+Q` 退出。

## 会话（保存 / 恢复）

```
<项目根>/.agents/sessions/20261105-114517.jsonl
```

第一行 meta（编号 / 创建时间 / 更新时间 / 模型 / 标题 / 预览 / 条数 / 是否含项目指令），
之后一行一条消息，字段与上下文归档一致，工具调用的参数和 `tool_call_id` 都保留。
写盘走 `.tmp` + `os.replace` 原子替换。

- 每轮对话结束自动保存（`[session] auto_save` 可关）
- `/new` 前会把当前会话存下来，所以「新建」不会丢东西
- `/resume` 恢复后按原顺序把对话画回界面（工具调用显示为一行摘要）

## AGENTS.md：一次注入，全程复用

项目根放一个 `AGENTS.md`，**会话首次加载时**把它作为一条 user 消息插进聊天历史
（紧跟在 System Prompt 之后），并随会话一起写进事件日志。

```
[0] system   ← Skill 清单
[1] user     ← <project_instructions>…AGENTS.md 全文…</project_instructions>
[2] user     ← 用户真正的第一句话
```

之后每一轮请求都直接复用这条消息，历史前缀不变，模型的 prompt cache 才有机会命中；
`/resume` 恢复时不会重复注入（事件日志里已经记着），`/compact` 之后会自动补回来。
改了 AGENTS.md 需要 `/new` 才生效。

## MCP 服务器

侧栏有独立的「MCP 服务器」区域：服务器名、连接状态、可用工具一栏列全。

- **异步加载**：进界面时先显示「连接中…」，每连上一台就刷新一次侧栏，启动不卡住
- **传输**：stdio（子进程 + 一行一个 JSON-RPC）
- **工具命名**：`mcp__<服务器>__<工具>`，和本地工具一起进 `tools` 定义，模型可直接调用
- 没配置服务器时侧栏显示「未配置服务器」，不会留空白

自带一个示例服务器，开箱就能看到效果：

```ini
[mcp]
enabled = true
servers = demo

[mcp:demo]
transport = stdio
command = python
args = -m xAgent.mcp_servers.demo_server
```

## 上下文压缩与历史检索

长任务迟早会把上下文窗口撑满。xAgent 的做法很朴素：**先把原始对话存档，再把摘要放回对话里**。
不引入向量库、不用 Embedding，全部是标准库 + 一个 JSONL 文件目录。

### 三个动作

| 动作 | 触发 | 说明 |
|------|------|------|
| 计量 | 每次模型响应后 / 每次用户输入前 | 状态栏显示 `上下文 96k/128k 75.0%`，优先用 API 返回的 `usage`，拿不到才本地估算 |
| 告警 | 用量 ≥ 窗口 70% | 输入框上方出现告警条并**锁住普通输入**，只放行命令 |
| 压缩 | `/compact` 或 `Ctrl+K` | 归档 → LLM 出摘要（约 5000 Tokens）→ 用摘要替换历史 |

### 归档

```
<项目根>/.agents/context/20261105-110748.jsonl
```

第一行是 meta（编号 / 时间 / 模型 / 条数 / 估算 Token），之后每条消息一行，
保留 `role`、`content`、`tool_calls`（含参数）、`tool_call_id` 和原始顺序。
**归档写成功才允许压缩**，写失败直接中止，上下文一个字节都不动。

### 压缩后长什么样

```
[0] system      ← 原封不动（含 Skill 清单）
[1] user        ← 摘要 + 「已于 xxx 完成压缩，原文在编号 yyy 的归档里」
[2] assistant   ← 「已理解摘要，继续」
```

工具定义不落进历史，每轮由 `_build_tools_schema()` 重新生成，所以压缩不会削弱能力。

### recallContext

摘要里没写全的细节，模型可以自己回头翻归档：

```json
{"name": "recallContext",
 "arguments": {"text": "config.ini", "id": "20261105-110748"}}
```

- `text`（必需）：关键词，多个词空格分隔，大小写不敏感
- `id`（可选）：只查某个归档；不传则扫全部归档
- 返回命中片段、归档编号、消息下标、角色；结果按 `max_chars` 截断，避免又撑爆上下文

### 相关配置

| 配置项（config.ini） | 含义 |
|------|------|
| `[context] window` | 手动指定窗口大小（0 = 按模型名查表，查不到用 128k 并标「默认」） |
| `[context] compact_threshold` | 告警阈值，默认 0.7 |
| `[context] target_tokens` | 摘要目标长度，默认 5000 |
| `[context] archive_dir` | 归档目录，默认 `.agents/context` |
| `XAGENT_CONTEXT_WINDOW` 环境变量 | 临时覆盖窗口大小 |
| `core/context.py: MODEL_CONTEXT_WINDOWS` | 已知模型的窗口表 |

### 自己动手验证

```bash
python -m unittest xAgent.tests.test_context -v    # 计量 / 归档 / 检索 / 压缩
python -m unittest xAgent.tests.test_session -v    # 会话保存 / 恢复 / AGENTS.md
python -m unittest xAgent.tests.test_mcp -v        # MCP 客户端（真实子进程）
python -m unittest xAgent.tests.test_config -v     # 配置解析 / 模板 / 迁移
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
# 新架构独立测试（166 个用例；其中 fetchWeb 两个用例依赖 trafilatura）
python -m unittest discover -s xAgent/tests -v

# 原 Practice02 58 个测试（回归）
cd Practice02 && python -m unittest test_fileops -v
```

## 工具清单

### 文件操作（10 个）

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

### 其它（5 个）

| 名称 | 功能 |
|------|------|
| `searchWeb` | 联网搜索（千帆 ai_search，需 `[llm] api_key`） |
| `fetchWeb` | 抓网页正文（依赖 `trafilatura`） |
| `runCli` | 执行本地命令（参数列表 + 超时） |
| `loadSkill` | 加载 Skill 全文 / 附加文件 |
| `recallContext` | 在 `.agents/context/` 归档里做关键词检索 |

MCP 服务器上的工具会以 `mcp__<服务器>__<工具>` 的形式追加到这张表里。

## 安全约束（tools.py 已内置）

- 二进制文件拒绝读取
- 不能删除当前工作目录或其祖先目录
- `rename_item` 拒绝含路径分隔符的新名称（防止越权）
- `rename_item` 目标已存在时**拒绝覆盖**，不做自动编号
- `delete_directory` 默认 `force=True`，`force=False` 时非空目录被拒
