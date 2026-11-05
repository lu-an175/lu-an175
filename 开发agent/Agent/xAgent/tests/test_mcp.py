# -*- coding: utf-8 -*-
"""
xAgent MCP 客户端测试 —— 用自带的 demo 服务器跑真实子进程。

不联网、不依赖 node；只验证「拉起进程 → 握手 → 列工具 → 调工具」这条链路。
"""

import os
import sys
import time
import unittest
from pathlib import Path

from xAgent.core.mcp import (
    MCPManager,
    MCPServerConfig,
    MCPStdioClient,
    content_to_text,
    qualified_name,
)

#: 包根目录（Agent/），子进程要在这里才能 import xAgent
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _demo_config(**overrides) -> MCPServerConfig:
    data = dict(
        name="demo",
        transport="stdio",
        command=sys.executable,
        args=["-m", "xAgent.mcp_servers.demo_server"],
        timeout=15,
    )
    data.update(overrides)
    return MCPServerConfig(**data)


class MCPTestBase(unittest.TestCase):
    def setUp(self):
        self._cwd = os.getcwd()
        os.chdir(PROJECT_ROOT)

    def tearDown(self):
        os.chdir(self._cwd)


class TestStdioClient(MCPTestBase):
    def test_handshake_and_list_tools(self):
        client = MCPStdioClient(_demo_config())
        try:
            client.start()
            self.assertEqual(client.server_info.get("name"), "xagent-demo")
            tools = client.list_tools()
            self.assertEqual({t.name for t in tools}, {"echo", "now", "count_chars"})
            echo = next(t for t in tools if t.name == "echo")
            self.assertEqual(echo.input_schema["required"], ["text"])
        finally:
            client.close()

    def test_call_tool(self):
        client = MCPStdioClient(_demo_config())
        try:
            client.start()
            result = client.call_tool("echo", {"text": "你好"})
            self.assertEqual(content_to_text(result), "你好")
        finally:
            client.close()

    def test_unknown_tool_returns_error_content(self):
        client = MCPStdioClient(_demo_config())
        try:
            client.start()
            result = client.call_tool("nope", {})
            self.assertTrue(result.get("isError"))
        finally:
            client.close()


class TestManager(MCPTestBase):
    def test_connect_all_and_call(self):
        manager = MCPManager([_demo_config()])
        manager.connect_all()
        try:
            states = manager.states()
            self.assertEqual(len(states), 1)
            self.assertEqual(states[0].status, "ready")
            self.assertEqual(states[0].tool_count, 3)

            tools = manager.all_tools()
            self.assertEqual(len(tools), 3)
            self.assertIn(qualified_name("demo", "echo"), [t[2] for t in tools])

            result = manager.call("mcp__demo__echo", {"text": "hi"})
            self.assertTrue(result.success)
            self.assertEqual(result.data.get("content"), "hi")
        finally:
            manager.close()

    def test_unknown_tool_fails_gracefully(self):
        manager = MCPManager([_demo_config()])
        manager.connect_all()
        try:
            result = manager.call("mcp__demo__nope", {})
            self.assertFalse(result.success)
            self.assertIn("未知的 MCP 工具", result.error)
        finally:
            manager.close()

    def test_bad_command_becomes_error_state(self):
        manager = MCPManager(
            [_demo_config(name="broken", command="definitely-not-a-real-command-xyz")]
        )
        manager.connect_all()
        states = manager.states()
        self.assertEqual(states[0].status, "error")
        self.assertTrue(states[0].error)

    def test_disabled_server_is_not_started(self):
        manager = MCPManager([_demo_config(enabled=False)])
        manager.connect_all()
        states = manager.states()
        self.assertEqual(states[0].status, "disabled")
        self.assertEqual(manager.all_tools(), [])

    def test_async_start_notifies_and_finishes(self):
        seen = []
        manager = MCPManager([_demo_config()])
        manager.start_async(lambda name: seen.append(name))
        manager.join(timeout=20)
        try:
            self.assertIn("demo", seen)
            self.assertEqual(manager.states()[0].status, "ready")
        finally:
            manager.close()

    def test_tool_schema_shape(self):
        manager = MCPManager([_demo_config()])
        manager.connect_all()
        try:
            server, tool, _ = manager.all_tools()[0]
            schema = manager.tool_schema(server, tool)
            self.assertEqual(schema["type"], "function")
            self.assertTrue(schema["function"]["name"].startswith("mcp__demo__"))
            self.assertEqual(schema["function"]["parameters"]["type"], "object")
        finally:
            manager.close()


class TestHelpers(unittest.TestCase):
    def test_qualified_name_sanitizes(self):
        self.assertEqual(qualified_name("my server", "do.thing"), "mcp__my_server__do_thing")

    def test_content_to_text_mixed_blocks(self):
        text = content_to_text(
            {
                "content": [
                    {"type": "text", "text": "第一段"},
                    {"type": "resource", "resource": {"text": "第二段"}},
                ]
            }
        )
        self.assertEqual(text, "第一段\n第二段")

    def test_content_to_text_empty(self):
        self.assertEqual(content_to_text({}), "")

    def test_python_command_resolved(self):
        cfg = MCPServerConfig(name="x", command="python")
        self.assertTrue(cfg.resolved_command())


if __name__ == "__main__":
    unittest.main()
