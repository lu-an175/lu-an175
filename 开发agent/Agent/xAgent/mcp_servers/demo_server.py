# -*- coding: utf-8 -*-
"""
xAgent.mcp_servers.demo_server —— 自带的最小 MCP 服务器示例。

用途
    1. 让侧栏的「MCP 服务器」区域开箱就有内容，不用先装 node/npx
    2. 当模板：想看一个 MCP 服务器长什么样，读这一个文件就够了

传输
    stdio：标准输入一行一个 JSON-RPC 消息，标准输出一行一个响应。
    注意 stdout 只能写协议消息，日志一律走 stderr。

实现的方法
    initialize               握手
    notifications/initialized 客户端初始化完成（通知，不回复）
    tools/list               列出工具
    tools/call               调用工具
    ping                     心跳

启动
    python -m xAgent.mcp_servers.demo_server
"""

from __future__ import annotations

import json
import sys
from datetime import datetime

SERVER_INFO = {"name": "xagent-demo", "version": "1.0.0"}
PROTOCOL_VERSION = "2025-06-18"

TOOLS = [
    {
        "name": "echo",
        "description": "原样返回输入文本（用来验证链路是否打通）",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string", "description": "要回显的文本"}},
            "required": ["text"],
        },
    },
    {
        "name": "now",
        "description": "返回服务器当前的本地时间",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "count_chars",
        "description": "统计一段文本的字符数与行数",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string", "description": "待统计的文本"}},
            "required": ["text"],
        },
    },
]


def _text(value: str) -> dict:
    return {"content": [{"type": "text", "text": value}]}


def call_tool(name: str, arguments: dict) -> dict:
    if name == "echo":
        return _text(str(arguments.get("text", "")))
    if name == "now":
        return _text(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    if name == "count_chars":
        text = str(arguments.get("text", ""))
        lines = text.count("\n") + 1 if text else 0
        return _text(f"字符数 {len(text)}，行数 {lines}")
    return {"content": [{"type": "text", "text": f"未知工具：{name}"}], "isError": True}


def handle(message: dict) -> dict | None:
    """处理一条消息；通知类返回 None（不回复）。"""
    method = message.get("method")
    request_id = message.get("id")

    if method == "initialize":
        result = {
            "protocolVersion": message.get("params", {}).get(
                "protocolVersion", PROTOCOL_VERSION
            ),
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
        }
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        params = message.get("params") or {}
        result = call_tool(params.get("name", ""), params.get("arguments") or {})
    elif method == "ping":
        result = {}
    elif method and method.startswith("notifications/"):
        return None  # 通知不需要回复
    else:
        if request_id is None:
            return None
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": f"method not found: {method}"},
        }

    if request_id is None:
        return None
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            print(f"bad json: {line[:80]}", file=sys.stderr, flush=True)
            continue

        response = handle(message)
        if response is None:
            continue
        sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
