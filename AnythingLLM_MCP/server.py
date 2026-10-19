"""AnythingLLM MCP Server (Streamable HTTP).

单工具 MVP：基于第一个工作区的文档做 RAG 检索，回答用户提问。
MCP 协议：2026-07-28；传输：Streamable HTTP（非 stdio）。
"""
import os

import httpx
from mcp.server.mcpserver import MCPServer

# 配置：环境变量优先，localhost 本地用提供默认值
ANYTHINGLLM_BASE_URL = os.getenv("ANYTHINGLLM_BASE_URL", "http://localhost:3001/api")
ANYTHINGLLM_API_KEY = os.getenv("ANYTHINGLLM_API_KEY", "V53PXSX-EGNMHT0-JX65W10-9PW5GJE")
MCP_HOST = os.getenv("MCP_HOST", "127.0.0.1")
MCP_PORT = int(os.getenv("MCP_PORT", "8766"))

_HEADERS = {
    "Authorization": f"Bearer {ANYTHINGLLM_API_KEY}",
    "Content-Type": "application/json",
}

mcp = MCPServer("AnythingLLM")


@mcp.tool()
def ask_first_workspace(question: str) -> str:
    """基于第一个工作区中的文档（RAG 检索，mode=query）回答用户提问。

    Args:
        question: 向第一个工作区提出的问题。
    """
    with httpx.Client(base_url=ANYTHINGLLM_BASE_URL, headers=_HEADERS, timeout=120.0) as client:
        # 1. 取第一个工作区的 slug
        resp = client.get("/v1/workspaces")
        resp.raise_for_status()
        workspaces = resp.json().get("workspaces", [])
        if not workspaces:
            raise ValueError("AnythingLLM 中没有任何工作区")
        first = workspaces[0]
        slug = first["slug"]
        name = first.get("name", slug)

        # 2. 用 query 模式做 RAG 提取回答
        resp = client.post(
            f"/v1/workspace/{slug}/chat",
            json={"message": question, "mode": "query"},
        )
        resp.raise_for_status()
        data = resp.json()

    if data.get("error"):
        raise RuntimeError(f"AnythingLLM 返回错误: {data['error']}")

    text = (data.get("textResponse") or "").strip()
    sources = data.get("sources", []) or []
    lines = [f"工作区: {name}", "", text]
    titles = [s.get("title") for s in sources if s.get("title")]
    if titles:
        lines += ["", "引用来源:"]
        lines += [f"- {t}" for t in titles]
    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host=MCP_HOST, port=MCP_PORT)
