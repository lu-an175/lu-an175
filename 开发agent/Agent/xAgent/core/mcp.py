# -*- coding: utf-8 -*-
"""
xAgent.core.mcp —— 极简 MCP（Model Context Protocol）客户端。

只做三件事，够用就好：
    1. 按 config.ini 的 [mcp:名称] 段拉起服务器子进程（stdio 传输）
    2. initialize 握手 → tools/list 拿工具清单
    3. 把工具调用转发成 tools/call，并把结果转成 ToolResult

为什么不用官方 SDK
    传输层就是「一行一个 JSON」的 JSON-RPC，标准库里 subprocess + json 足够，
    多一层依赖反而让学生看不懂整个链路。

异步加载
    MCPManager.start_async() 每台服务器一个线程，连上就回调通知 UI，
    TUI 先显示、连上后动态刷新侧栏，不会卡在启动画面。
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .types import ToolResult

#: 客户端声明的协议版本（服务器会回它自己支持的版本，不强制相等）
PROTOCOL_VERSION = "2025-06-18"

CLIENT_INFO = {"name": "xAgent", "version": "1.0.0"}


class MCPError(RuntimeError):
    """MCP 通信/协议错误。"""


# ============================================================
# 数据模型
# ============================================================

@dataclass
class MCPServerConfig:
    """一台 MCP 服务器的启动配置（来自 config.ini 的 [mcp:名称] 段）。"""

    name: str
    transport: str = "stdio"
    command: str = ""
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    url: str = ""
    enabled: bool = True
    timeout: int = 20

    def resolved_command(self) -> str:
        """command 写 python/py 时换成本进程的解释器（Windows 上 PATH 常常没有 python）。"""
        text = (self.command or "").strip()
        if text.lower() in ("python", "python3", "py"):
            return sys.executable or text
        return text


@dataclass
class MCPTool:
    """服务器上的一个工具。"""

    name: str
    description: str = ""
    input_schema: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MCPServerState:
    """一台服务器的运行时状态（侧栏就画这个）。"""

    name: str
    status: str = "pending"          # pending | connecting | ready | error | disabled
    tools: List[MCPTool] = field(default_factory=list)
    error: str = ""
    transport: str = "stdio"
    elapsed_ms: int = 0

    @property
    def tool_count(self) -> int:
        return len(self.tools)

    @property
    def status_label(self) -> str:
        return {
            "pending": "等待连接",
            "connecting": "连接中…",
            "ready": f"已连接 · {self.tool_count} 个工具",
            "error": "连接失败",
            "disabled": "已禁用",
        }.get(self.status, self.status)


# ============================================================
# stdio 客户端
# ============================================================

class MCPStdioClient:
    """通过子进程 stdin/stdout 走 JSON-RPC（MCP stdio 传输）。"""

    def __init__(self, config: MCPServerConfig) -> None:
        self.config = config
        self.timeout = max(3, int(config.timeout or 20))
        self._proc: Optional[subprocess.Popen] = None
        self._queue: "queue.Queue[Optional[dict]]" = queue.Queue()
        self._stderr_tail: List[str] = []
        self._next_id = 0
        self._lock = threading.Lock()
        self.server_info: Dict[str, Any] = {}

    # ---------- 生命周期 ----------

    def start(self) -> None:
        """拉起子进程并完成 initialize 握手。"""
        command = self.config.resolved_command()
        if not command:
            raise MCPError("没有配置 command")

        env = os.environ.copy()
        env.update({str(k): str(v) for k, v in self.config.env.items()})
        env.setdefault("PYTHONIOENCODING", "utf-8")
        env.setdefault("PYTHONUNBUFFERED", "1")
        # 让 `command = python` + `-m xAgent.xxx` 在任意工作目录都能找到包
        package_root = str(Path(__file__).resolve().parents[2])
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = (
            package_root + (os.pathsep + existing if existing else "")
        )

        try:
            self._proc = subprocess.Popen(
                [command, *self.config.args],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=env,
                cwd=os.getcwd(),
            )
        except OSError as exc:
            raise MCPError(f"启动命令失败：{command} ({exc})") from exc

        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

        result = self._request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": CLIENT_INFO,
            },
        )
        self.server_info = result.get("serverInfo", {}) if isinstance(result, dict) else {}
        self._notify("notifications/initialized", {})

    def close(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
        except OSError:
            pass
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            try:
                proc.kill()
            except OSError:
                pass
        # 读线程可能还在 iterate，关管道失败无所谓（进程已经没了）
        for stream in (proc.stdout, proc.stderr):
            try:
                if stream is not None:
                    stream.close()
            except Exception:
                pass

    # ---------- 后台读 ----------

    def _read_stdout(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        try:
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    self._queue.put(json.loads(line))
                except json.JSONDecodeError:
                    # 服务器往 stdout 打了日志，丢掉就行（stdout 只能放协议消息）
                    continue
        finally:
            self._queue.put(None)  # 哨兵：进程结束

    def _read_stderr(self) -> None:
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        for line in proc.stderr:
            text = line.rstrip()
            if not text:
                continue
            self._stderr_tail.append(text)
            if len(self._stderr_tail) > 20:
                del self._stderr_tail[0]

    def _stderr_hint(self) -> str:
        return " | ".join(self._stderr_tail[-3:])

    # ---------- JSON-RPC ----------

    def _send(self, message: Dict[str, Any]) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None:
            raise MCPError("服务器未启动")
        try:
            proc.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
            proc.stdin.flush()
        except (OSError, ValueError) as exc:
            raise MCPError(f"写入失败：{exc}") from exc

    def _notify(self, method: str, params: Dict[str, Any]) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def _request(self, method: str, params: Optional[Dict[str, Any]] = None) -> Any:
        with self._lock:
            self._next_id += 1
            request_id = self._next_id
            self._send(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": method,
                    "params": params or {},
                }
            )
            deadline = time.time() + self.timeout
            while True:
                remain = deadline - time.time()
                if remain <= 0:
                    hint = self._stderr_hint()
                    raise MCPError(
                        f"{method} 超时（{self.timeout}s）" + (f"：{hint}" if hint else "")
                    )
                try:
                    message = self._queue.get(timeout=remain)
                except queue.Empty:
                    continue
                if message is None:
                    hint = self._stderr_hint()
                    raise MCPError("服务器已退出" + (f"：{hint}" if hint else ""))
                if message.get("id") != request_id:
                    # 服务器发来的请求：我们不支持，礼貌回一个错误
                    if "method" in message and "id" in message:
                        try:
                            self._send(
                                {
                                    "jsonrpc": "2.0",
                                    "id": message["id"],
                                    "error": {"code": -32601, "message": "not supported"},
                                }
                            )
                        except MCPError:
                            pass
                    continue
                if "error" in message:
                    err = message["error"] or {}
                    raise MCPError(
                        f"{method} 失败：{err.get('message') or err}"
                    )
                return message.get("result")

    # ---------- 协议方法 ----------

    def list_tools(self) -> List[MCPTool]:
        result = self._request("tools/list") or {}
        tools: List[MCPTool] = []
        for raw in result.get("tools", []) or []:
            name = (raw.get("name") or "").strip()
            if not name:
                continue
            tools.append(
                MCPTool(
                    name=name,
                    description=(raw.get("description") or "").strip(),
                    input_schema=raw.get("inputSchema") or {},
                )
            )
        return tools

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        result = self._request(
            "tools/call", {"name": name, "arguments": arguments or {}}
        ) or {}
        return result


def content_to_text(result: Dict[str, Any]) -> str:
    """把 tools/call 的 content 数组压成一段文本。"""
    blocks = result.get("content") or []
    parts: List[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            parts.append(str(block))
            continue
        kind = block.get("type")
        if kind == "text":
            parts.append(str(block.get("text") or ""))
        elif kind == "resource":
            resource = block.get("resource") or {}
            parts.append(str(resource.get("text") or resource.get("uri") or ""))
        else:
            parts.append(json.dumps(block, ensure_ascii=False))
    return "\n".join(part for part in parts if part)


# ============================================================
# 管理器：多台服务器 + 异步加载
# ============================================================

def qualified_name(server: str, tool: str) -> str:
    """工具在 xAgent 里的全名，避免和本地工具 / 其它服务器重名。"""
    safe_server = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in server)
    safe_tool = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in tool)
    return f"mcp__{safe_server}__{safe_tool}"


class MCPManager:
    """
    MCP 服务器池。

    - start_async(on_change)：立即返回，后台逐台连接
    - 连接状态变化时回调 on_change()，UI 据此刷新侧栏
    - 线程安全：状态在锁里改，回调在锁外触发（避免回调里再读状态被自己锁住）
    """

    def __init__(self, servers: Sequence[MCPServerConfig], enabled: bool = True) -> None:
        self._lock = threading.RLock()
        self._clients: Dict[str, MCPStdioClient] = {}
        self._tool_index: Dict[str, Tuple[str, str]] = {}   # 全名 -> (服务器, 真实工具名)
        self._states: List[MCPServerState] = []
        self._threads: List[threading.Thread] = []
        self.enabled = enabled
        self._server_configs: List[MCPServerConfig] = [cfg for cfg in servers if cfg.enabled]

        for cfg in servers:
            if not cfg.enabled:
                self._states.append(
                    MCPServerState(name=cfg.name, status="disabled", transport=cfg.transport)
                )
            else:
                self._states.append(
                    MCPServerState(name=cfg.name, status="pending", transport=cfg.transport)
                )

    # ---------- 查询 ----------

    def states(self) -> List[MCPServerState]:
        with self._lock:
            return [
                MCPServerState(
                    name=state.name,
                    status=state.status,
                    tools=list(state.tools),
                    error=state.error,
                    transport=state.transport,
                    elapsed_ms=state.elapsed_ms,
                )
                for state in self._states
            ]

    @property
    def server_count(self) -> int:
        return len(self._states)

    @property
    def ready_count(self) -> int:
        return sum(1 for s in self.states() if s.status == "ready")

    def all_tools(self) -> List[Tuple[str, MCPTool, str]]:
        """[(服务器名, MCPTool, 全名)] —— 只返回已连上的。"""
        with self._lock:
            out: List[Tuple[str, MCPTool, str]] = []
            for state in self._states:
                if state.status != "ready":
                    continue
                for tool in state.tools:
                    out.append((state.name, tool, qualified_name(state.name, tool.name)))
            return out

    def tool_schema(self, server: str, tool: MCPTool) -> Dict[str, Any]:
        """转成 OpenAI tools 格式。"""
        schema = tool.input_schema if isinstance(tool.input_schema, dict) else {}
        if not schema or schema.get("type") != "object":
            schema = {"type": "object", "properties": {}}
        return {
            "type": "function",
            "function": {
                "name": qualified_name(server, tool.name),
                "description": f"[MCP:{server}] {tool.description or tool.name}",
                "parameters": schema,
            },
        }

    # ---------- 连接 ----------

    def start_async(self, on_change: Optional[Callable[[str], None]] = None) -> None:
        """后台连接所有服务器，连一台通知一次。"""
        if not self.enabled:
            return
        for cfg in self._configs():
            thread = threading.Thread(
                target=self._connect_one, args=(cfg, on_change), daemon=True
            )
            thread.start()
            self._threads.append(thread)

    def connect_all(self, on_change: Optional[Callable[[str], None]] = None) -> None:
        """同步连接（CLI / 测试用）。"""
        for cfg in self._configs():
            self._connect_one(cfg, on_change)

    def join(self, timeout: float = 30.0) -> None:
        deadline = time.time() + timeout
        for thread in list(self._threads):
            remain = deadline - time.time()
            if remain <= 0:
                break
            thread.join(timeout=remain)

    def _configs(self) -> List[MCPServerConfig]:
        return list(self._server_configs)

    def _connect_one(
        self,
        cfg: MCPServerConfig,
        on_change: Optional[Callable[[str], None]],
    ) -> None:
        self._update(cfg.name, status="connecting")
        if on_change:
            on_change(cfg.name)

        started = time.time()
        client = MCPStdioClient(cfg)
        try:
            client.start()
            tools = client.list_tools()
        except Exception as exc:  # 网络/进程/协议，全兜住
            client.close()
            self._update(
                cfg.name,
                status="error",
                error=str(exc),
                elapsed_ms=int((time.time() - started) * 1000),
            )
            if on_change:
                on_change(cfg.name)
            return

        with self._lock:
            self._clients[cfg.name] = client
            for tool in tools:
                self._tool_index[qualified_name(cfg.name, tool.name)] = (cfg.name, tool.name)
        self._update(
            cfg.name,
            status="ready",
            tools=tools,
            error="",
            elapsed_ms=int((time.time() - started) * 1000),
        )
        if on_change:
            on_change(cfg.name)

    def _update(self, name: str, **changes: Any) -> None:
        with self._lock:
            for state in self._states:
                if state.name != name:
                    continue
                for key, value in changes.items():
                    setattr(state, key, value)
                return

    # ---------- 调用 ----------

    def call(self, name: str, arguments: Dict[str, Any]) -> ToolResult:
        with self._lock:
            target = self._tool_index.get(name)
            client = self._clients.get(target[0]) if target else None
        if target is None or client is None:
            return ToolResult.fail(
                f"未知的 MCP 工具：{name}（服务器可能还没连上，用 /mcp 查看状态）"
            )

        server_name, tool_name = target
        try:
            raw = client.call_tool(tool_name, arguments or {})
        except Exception as exc:
            return ToolResult.fail(f"MCP 工具 {name} 调用失败：{exc}")

        text = content_to_text(raw)
        if raw.get("isError"):
            return ToolResult.fail(text or "MCP 工具返回错误")
        return ToolResult.ok(message=text or "（无返回内容）", content=text, server=server_name, tool=tool_name)

    def close(self) -> None:
        with self._lock:
            clients = list(self._clients.values())
            self._clients.clear()
        for client in clients:
            client.close()
