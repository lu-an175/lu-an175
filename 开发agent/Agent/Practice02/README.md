# 文件操作工具集（File Operations Toolkit）

基于 `chat-stream-tool-isLeapYear.py` 模板开发的本地文件操作工具集合，提供 **10 个本地文件操作 function**，并通过统一的分发器 `call_tool()` 进行调用。

## 📁 项目结构

```
Agent/Practice02/
├── chat-stream-tool-isLeapYear.py   # 模板示例（闰年判断）
├── chat-stream-tool-fileops.py      # 主项目（10 个文件操作工具）
├── test_fileops.py                  # 单元测试（58 个用例）
├── architecture.mmd                 # Mermaid 代码架构图
└── README.md                        # 本文件
```

## 🔧 功能清单（10 个工具）

| # | 函数名 | 功能描述 |
|---|--------|---------|
| 1 | `get_current_working_directory()` | 获取当前工作目录 |
| 2 | `list_directory(path=".")` | 列出指定目录下所有文件和子目录 |
| 3 | `get_file_type(file_path)` | 获取指定文件的文件类型 |
| 4 | `read_file(file_path)` | 读取文件内容（仅支持纯文本格式） |
| 5 | `create_file(file_path, content="")` | 创建新文件（自动创建父目录链） |
| 6 | `write_file(file_path, content, mode)` | 编辑文件内容（覆盖 / 追加） |
| 7 | `create_directory(dir_path)` | 创建新目录（支持级联创建） |
| 8 | `delete_directory(dir_path, force=True)` | 删除目录（支持非空强制删除） |
| 9 | `delete_file(file_path)` | 删除文件 |
| 10 | `rename_item(source_path, new_name)` | 重命名文件或目录 |

## 🏗️ 代码架构

整体分为四层（详见 [architecture.mmd](file:///d:/Yk123-wuta/新建文件夹/Agent/Practice02/architecture.mmd)）：

```
入口层        main() / run_demo() / call_tool()
                ↓
注册层        TOOLS 字典（工具名 → 函数元数据）
                ↓
工具层        10 个独立的文件操作函数
                ↓
系统依赖层    os / pathlib / shutil / mimetypes / json
```

**统一返回结构**：所有工具函数返回 `dict`，包含 `success`、`message` / `error` 以及功能特定字段。

## 🚀 使用方式

### 1. 交互模式

```bash
python chat-stream-tool-fileops.py
```

按提示输入工具调用：

```
> get_current_working_directory
> list_directory path=./some_dir
> create_file file_path=new.txt content=hello
> rename_item source_path=old.txt new_name=new.txt
> help   # 查看所有可用工具
> q      # 退出
```

### 2. 演示模式（一键跑通 9 个核心功能）

```bash
python chat-stream-tool-fileops.py --demo
```

### 3. 编程调用

```python
from chat_stream_tool_fileops import call_tool

result = call_tool("list_directory", path=".")
result = call_tool("read_file", file_path="test.txt")
result = call_tool("rename_item", source_path="a.txt", new_name="b.txt")
```

## 🧪 单元测试

```bash
python -m unittest test_fileops -v
```

**测试覆盖**：11 个测试类 / **58 个用例**，每个函数覆盖正常路径、边界条件与异常场景。

| 测试类 | 用例数 |
|--------|-------|
| TestGetCurrentWorkingDirectory | 2 |
| TestListDirectory | 5 |
| TestGetFileType | 6 |
| TestReadFile | 5 |
| TestCreateFile | 4 |
| TestWriteFile | 7 |
| TestCreateDirectory | 4 |
| TestDeleteDirectory | 6 |
| TestDeleteFile | 3 |
| TestRenameItem | 8 |
| TestCallToolDispatcher | 8 |

## 🔐 安全约束

- `read_file` / `write_file` 仅支持纯文本格式，二进制文件被拒绝
- `delete_directory` 不能删除当前工作目录或其上级目录
- `rename_item` 的 `new_name` 不允许含路径分隔符（防止越权）
- `rename_item` 目标已存在时**保守拒绝覆盖**，不做自动编号

## 📦 依赖

仅使用 Python 标准库：`os` / `pathlib` / `shutil` / `mimetypes` / `json` / `unittest`，无第三方依赖。
