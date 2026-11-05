# -*- coding: utf-8 -*-
"""
xAgent 会话持久化测试 —— 保存 / 恢复 / 列表 / AGENTS.md 注入。

全部在临时目录里跑。
"""

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from xAgent.core.llm import LLMMessage, ToolCall
from xAgent.core.session import (
    KIND_AGENTS_MD,
    build_agents_md_message,
    delete_session,
    find_agents_md,
    list_sessions,
    load_agents_md,
    load_session,
    new_session_id,
    read_meta,
    save_session,
)


def _sample() -> list:
    return [
        LLMMessage(role="system", content="你是 xAgent"),
        LLMMessage(role="user", content="列出当前目录"),
        LLMMessage(
            role="assistant",
            content="",
            tool_calls=[
                ToolCall(id="call_0001", name="list_directory", arguments={"path": "."})
            ],
        ),
        LLMMessage(
            role="tool",
            content=json.dumps({"success": True, "entries": ["a.txt"]}, ensure_ascii=False),
            tool_call_id="call_0001",
        ),
        LLMMessage(role="assistant", content="目录里有 a.txt"),
    ]


class TestSessionStore(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_new_session_id_unique_in_same_second(self):
        now = datetime(2026, 11, 5, 11, 27, 0)
        first = new_session_id(now, self.root)
        save_session([LLMMessage(role="user", content="hi")], first, self.root)
        second = new_session_id(now, self.root)
        self.assertNotEqual(first, second)
        self.assertTrue(second.startswith(first))

    def test_save_creates_dir_and_file(self):
        path = save_session(_sample(), "20261105-112700", self.root)
        self.assertTrue(path.is_file())
        self.assertEqual(path.parent.name, "sessions")
        self.assertEqual(path.parent.parent.name, ".agents")

    def test_roundtrip_keeps_tool_calls_and_order(self):
        save_session(_sample(), "s1", self.root)
        meta = load_session("s1", self.root)
        self.assertIsNotNone(meta)
        self.assertEqual(meta.message_count, 5)
        self.assertEqual([m.role for m in meta.messages],
                         ["system", "user", "assistant", "tool", "assistant"])

        assistant = meta.messages[2]
        self.assertEqual(len(assistant.tool_calls), 1)
        self.assertEqual(assistant.tool_calls[0].name, "list_directory")
        self.assertEqual(assistant.tool_calls[0].arguments, {"path": "."})
        self.assertEqual(meta.messages[3].tool_call_id, "call_0001")

    def test_meta_fields(self):
        save_session(_sample(), "s1", self.root, model="ernie-5.1", title="列目录")
        meta = read_meta(self.root / ".agents" / "sessions" / "s1.jsonl")
        self.assertEqual(meta["id"], "s1")
        self.assertEqual(meta["model"], "ernie-5.1")
        self.assertEqual(meta["title"], "列目录")
        self.assertEqual(meta["message_count"], 5)
        self.assertIn("列出当前目录", meta["preview"])

    def test_agents_md_kind_is_persisted(self):
        messages = _sample()
        messages.insert(1, build_agents_md_message("# 规则\n必须写测试"))
        kinds = ["message", KIND_AGENTS_MD, "message", "message", "message", "message"]
        save_session(messages, "s1", self.root, kinds=kinds)

        meta = load_session("s1", self.root)
        self.assertTrue(meta.has_agents_md)
        self.assertIn("必须写测试", meta.messages[1].content)

        raw = read_meta(self.root / ".agents" / "sessions" / "s1.jsonl")
        self.assertTrue(raw["has_agents_md"])

    def test_resave_keeps_created_at_and_kinds(self):
        messages = [LLMMessage(role="user", content="hi")]
        save_session(messages, "s1", self.root)
        first = read_meta(self.root / ".agents" / "sessions" / "s1.jsonl")

        messages = [build_agents_md_message("# 规则"), *messages]
        save_session(messages, "s1", self.root, kinds=[KIND_AGENTS_MD, "message"])
        second = read_meta(self.root / ".agents" / "sessions" / "s1.jsonl")

        self.assertEqual(second["created_at"], first["created_at"])
        self.assertTrue(second["has_agents_md"])

    def test_list_sessions_newest_first(self):
        save_session([LLMMessage(role="user", content="旧的")], "a-old", self.root)
        save_session([LLMMessage(role="user", content="新的")], "b-new", self.root)

        # 手工改一下 updated_at，避免同秒排序不稳
        path = self.root / ".agents" / "sessions" / "b-new.jsonl"
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        records[0]["updated_at"] = "2030-01-01 00:00:00"
        path.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
            encoding="utf-8",
        )

        items = list_sessions(self.root)
        self.assertEqual([s.id for s in items], ["b-new", "a-old"])

    def test_load_missing_returns_none(self):
        self.assertIsNone(load_session("nope", self.root))

    def test_list_empty_dir(self):
        self.assertEqual(list_sessions(self.root), [])

    def test_delete_session(self):
        save_session([LLMMessage(role="user", content="hi")], "s1", self.root)
        self.assertTrue(delete_session("s1", self.root))
        self.assertFalse(delete_session("s1", self.root))

    def test_custom_subdir(self):
        path = save_session(
            [LLMMessage(role="user", content="hi")], "s1", self.root, subdir="data/s"
        )
        self.assertEqual(path.parent, self.root / "data" / "s")


class TestAgentsMd(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_find_missing(self):
        self.assertIsNone(find_agents_md(self.root))
        self.assertIsNone(load_agents_md(self.root))

    def test_find_exact_name(self):
        path = self.root / "AGENTS.md"
        path.write_text("# 规则", encoding="utf-8")
        self.assertEqual(find_agents_md(self.root), path)

    def test_find_case_insensitive(self):
        path = self.root / "agents.md"
        path.write_text("# 规则", encoding="utf-8")
        self.assertEqual(find_agents_md(self.root), path)

    def test_load_returns_content(self):
        (self.root / "AGENTS.md").write_text("# 规则\n必须写测试", encoding="utf-8")
        found = load_agents_md(self.root)
        self.assertIsNotNone(found)
        path, content = found
        self.assertIn("必须写测试", content)

    def test_empty_file_is_ignored(self):
        (self.root / "AGENTS.md").write_text("   \n", encoding="utf-8")
        self.assertIsNone(load_agents_md(self.root))

    def test_build_message_wraps_content(self):
        message = build_agents_md_message("# 规则\n用中文回答", "AGENTS.md")
        self.assertEqual(message.role, "user")
        self.assertIn("<project_instructions>", message.content)
        self.assertIn("用中文回答", message.content)
        self.assertIn("AGENTS.md", message.content)


if __name__ == "__main__":
    unittest.main()
