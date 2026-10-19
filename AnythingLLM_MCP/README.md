# AnythingLLM MCP Server

基于本机 AnythingLLM 的 MCP Server（MVP），MCP 协议 **2026-07-28**，传输方式 **Streamable HTTP**（非 stdio）。

## 功能

只提供一个工具：

- **`ask_first_workspace(question)`**：取 AnythingLLM 第一个工作区的文档，用 `mode=query`（纯 RAG 检索）回答提问。返回 AI 回答文本与引用来源标题。

## 前置条件

- 本机已安装并运行 AnythingLLM（默认 `http://localhost:3001`）
- Python 3.11+（本机为 3.14）

## 安装

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 启动 MCP 服务

```powershell
.\.venv\Scripts\python.exe server.py
```

启动后监听：`http://127.0.0.1:8766/mcp`

## 停止 MCP 服务

在运行 `server.py` 的终端按 `Ctrl+C`。

> 如果是后台进程，可在任务管理器结束 `python.exe`（PID 见启动日志），或用 `Stop-Process`：
> ```powershell
> Get-NetTCPConnection -LocalPort 8766 | Select-Object -ExpandProperty OwningProcess | Stop-Process -Force
> ```

## 配置（项目级 MCP）

项目根目录已配置 [`.mcp.json`](file:///d:/LLM/.mcp.json)，Trae 会自动识别：

```json
{
  "mcpServers": {
    "anythingllm": {
      "url": "http://127.0.0.1:8766/mcp"
    }
  }
}
```

在 Trae 中加载本目录后，MCP 服务会以 `anythingllm` 名称出现。**注意：HTTP 类型 MCP 需要先启动 `server.py`，Trae 才能连上。**

## 配置项（环境变量，均可选）

| 变量 | 默认值 | 说明 |
|---|---|---|
| `ANYTHINGLLM_BASE_URL` | `http://localhost:3001/api` | AnythingLLM API 地址 |
| `ANYTHINGLLM_API_KEY` | 内置本机 key | AnythingLLM API Key |
| `MCP_HOST` | `127.0.0.1` | MCP 监听地址 |
| `MCP_PORT` | `8766` | MCP 监听端口 |

覆盖示例：
```powershell
$env:ANYTHINGLLM_API_KEY = "你的key"; .\.venv\Scripts\python.exe server.py
```

## 说明

- `mode=query` 是纯 RAG：仅当第一个工作区有已嵌入的相关文档时才回答，否则返回“无相关信息”。如需用 LLM 通用知识兜底回答，可把 `server.py` 中 `mode` 改为 `"chat"`。
- 端口选 8766 是为避免与已存在的 `pet-hospital`（8765）冲突。
