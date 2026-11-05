# -*- coding: utf-8 -*-
"""
xAgent 上下文管理单元测试 —— 覆盖计量 / 归档 / 检索 / 压缩四条主线。

全部用临时目录 + 假 Provider，不联网、不碰真实 .agents 目录。
"""

import json
import os
import re
import tempfile
import unittest
from pathlib import Path

from xAgent.core import ToolService
from xAgent.core.context import (
    COMPACTION_SYSTEM_PROMPT,
    DEFAULT_CONTEXT_WINDOW,
    archive_dir,
    build_compaction_messages,
    build_transcript,
    compact_messages,
    estimate_messages_tokens,
    estimate_tokens,
    list_archives,
    load_archive,
    measure_usage,
    new_archive_id,
    recall_context,
    replace_messages,
    resolve_context_window,
    save_archive,
)
from xAgent.core.llm import LLMMessage, ToolCall


class _FakeProvider:
    """假的 LLM：要么返回固定摘要，要么抛异常，方便测失败路径。"""

    def __init__(self, reply: str = "## 摘要\n- 完成了 X", error: Exception | None = None):
        self.reply = reply
        self.error = error
        self.calls: list = []
        self.last_usage = {"prompt_tokens": 123, "completion_tokens": 45}

    def chat(self, messages, tools_schema):
        self.calls.append({
            "count": len(messages),
            "tools": list(tools_schema),
            "messages": list(messages),
        })
        if self.error is not None:
            raise self.error
        return LLMMessage(role="assistant", content=self.reply)


def _sample_messages() -> list:
    """一段有工具调用的完整历史。"""
    return [
        LLMMessage(role="system", content="你是 xAgent，可以操作文件。"),
        LLMMessage(role="user", content="帮我读一下 config.ini 里有哪些配置"),
        LLMMessage(
            role="assistant",
            content="",
            tool_calls=[ToolCall(id="call_0001", name="read_file",
                                 arguments={"file_path": "core/config.ini"})],
        ),
        LLMMessage(
            role="tool",
            content=json.dumps({"success": True, "content": "baidu_qianfan_api_key = xxx"},
                              ensure_ascii=False),
            tool_call_id="call_0001",
        ),
        LLMMessage(role="assistant", content="配置里只有一个键：baidu_qianfan_api_key。"),
        LLMMessage(role="user", content="那把模型改成 ernie-5.1"),
    ]


class TestTokenEstimate(unittest.TestCase):
    """Token 估算 & 窗口解析。"""

    def test_empty_text_is_zero(self):
        self.assertEqual(estimate_tokens(""), 0)

    def test_chinese_costs_more_than_ascii(self):
        zh = estimate_tokens("上下文压缩功能")
        en = estimate_tokens("abcdef")
        self.assertGreater(zh, en)

    def test_messages_tokens_include_tools_and_tool_calls(self):
        msgs = _sample_messages()
        without_tools = estimate_messages_tokens(msgs)
        with_tools = estimate_messages_tokens(
            msgs, [{"type": "function", "function": {"name": "read_file"}}]
        )
        self.assertGreater(with_tools, without_tools)
        # 工具调用参数也应被算进去
        self.assertGreater(without_tools, estimate_messages_tokens(msgs[:2]))

    def test_resolve_window_known_model(self):
        window, is_default = resolve_context_window("ernie-5.1")
        self.assertEqual(window, 128_000)
        self.assertFalse(is_default)

    def test_resolve_window_unknown_falls_back(self):
        window, is_default = resolve_context_window("some-unknown-model")
        self.assertEqual(window, DEFAULT_CONTEXT_WINDOW)
        self.assertTrue(is_default)

    def test_resolve_window_override(self):
        window, is_default = resolve_context_window("ernie-5.1", override=32_000)
        self.assertEqual(window, 32_000)
        self.assertFalse(is_default)

    def test_measure_prefers_api_usage(self):
        usage = measure_usage(_sample_messages(), "ernie-5.1", api_prompt_tokens=900)
        self.assertEqual(usage.tokens, 900)
        self.assertEqual(usage.source, "api")
        self.assertIn("/128k", usage.format_meter())
        self.assertIn("%", usage.format_meter())

    def test_measure_default_window_marks_default(self):
        usage = measure_usage(_sample_messages(), "unknown-model")
        self.assertTrue(usage.is_default_window)
        self.assertIn("(默认)", usage.format_meter())
        self.assertEqual(usage.source, "estimate")

    def test_over_threshold_flag(self):
        usage = measure_usage([LLMMessage(role="user", content="x")], "ernie-5.1",
                              api_prompt_tokens=100_000)
        self.assertTrue(usage.over_threshold)
        usage2 = measure_usage([LLMMessage(role="user", content="x")], "ernie-5.1",
                               api_prompt_tokens=10_000)
        self.assertFalse(usage2.over_threshold)


class TestArchive(unittest.TestCase):
    """归档落盘 / 读取 / 列表。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_archive_id_format(self):
        self.assertRegex(new_archive_id(), r"^\d{8}-\d{6}$")

    def test_archive_dir_under_project_root(self):
        self.assertEqual(archive_dir(self.root), self.root / ".agents" / "context")

    def test_save_archive_preserves_order_and_fields(self):
        msgs = _sample_messages()
        path = save_archive(msgs, project_root=self.root, model="ernie-5.1")
        self.assertTrue(path.is_file())
        self.assertTrue(str(path).endswith(".jsonl"))

        lines = path.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), len(msgs) + 1)  # meta + 每条消息

        meta = json.loads(lines[0])
        self.assertEqual(meta["type"], "meta")
        self.assertEqual(meta["message_count"], len(msgs))
        self.assertEqual(meta["model"], "ernie-5.1")

        records = load_archive(path)
        bodies = [r for r in records if r["type"] == "message"]
        self.assertEqual([r["index"] for r in bodies], list(range(len(msgs))))
        self.assertEqual([r["role"] for r in bodies], [m.role for m in msgs])
        # 工具调用参数、工具返回结果、tool_call_id 都要在
        self.assertEqual(bodies[2]["tool_calls"][0]["name"], "read_file")
        self.assertEqual(bodies[2]["tool_calls"][0]["arguments"]["file_path"],
                         "core/config.ini")
        self.assertEqual(bodies[3]["tool_call_id"], "call_0001")
        self.assertIn("baidu_qianfan_api_key", bodies[3]["content"])

    def test_repeated_save_does_not_overwrite(self):
        p1 = save_archive(_sample_messages(), project_root=self.root, archive_id="20260101-000000")
        p2 = save_archive(_sample_messages(), project_root=self.root, archive_id="20260101-000000")
        self.assertNotEqual(p1, p2)
        self.assertTrue(p1.is_file() and p2.is_file())

    def test_list_archives(self):
        self.assertEqual(list_archives(self.root), [])
        save_archive(_sample_messages(), project_root=self.root, archive_id="20260101-000000")
        save_archive(_sample_messages(), project_root=self.root, archive_id="20260202-000000")
        ids = [m["id"] for m in list_archives(self.root)]
        self.assertEqual(len(ids), 2)
        self.assertIn("20260101-000000", ids)


class TestRecall(unittest.TestCase):
    """recallContext 的检索行为。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_recall_finds_keyword_with_location(self):
        save_archive(_sample_messages(), project_root=self.root, archive_id="20260101-101010")
        r = recall_context("config.ini", project_root=self.root)
        self.assertTrue(r["success"])
        self.assertGreaterEqual(r["total_matches"], 1)
        first = r["matches"][0]
        self.assertEqual(first["archive_id"], "20260101-101010")
        self.assertIn("role", first)
        self.assertIsInstance(first["index"], int)
        self.assertIn("config.ini", first["snippet"])

    def test_recall_scoped_by_id(self):
        save_archive(_sample_messages(), project_root=self.root, archive_id="20260101-101010")
        save_archive([LLMMessage(role="user", content="另一段无关的话")],
                     project_root=self.root, archive_id="20260202-202020")
        r = recall_context("config.ini", id="20260101-101010", project_root=self.root)
        self.assertTrue(r["success"])
        self.assertEqual(r["archives_scanned"], 1)
        self.assertTrue(all(m["archive_id"] == "20260101-101010" for m in r["matches"]))

        r2 = recall_context("config.ini", id="20260202-202020", project_root=self.root)
        self.assertEqual(r2["matches"], [])

    def test_recall_missing_archive(self):
        save_archive(_sample_messages(), project_root=self.root)
        r = recall_context("x", id="does-not-exist", project_root=self.root)
        self.assertFalse(r["success"])
        self.assertIn("归档不存在", r["error"])
        self.assertTrue(r["available"])

    def test_recall_empty_text(self):
        r = recall_context("   ", project_root=self.root)
        self.assertFalse(r["success"])

    def test_recall_no_archive_dir(self):
        r = recall_context("anything", project_root=self.root)
        self.assertTrue(r["success"])
        self.assertEqual(r["matches"], [])
        self.assertEqual(r["archives_scanned"], 0)

    def test_recall_truncates_long_result(self):
        big = [LLMMessage(role="user", content="关键词 " * 500 + f"条目{i}") for i in range(8)]
        save_archive(big, project_root=self.root, archive_id="20260303-000000")
        r = recall_context("关键词", project_root=self.root, max_matches=8, max_chars=200)
        self.assertTrue(r["success"])
        self.assertLessEqual(len(r["matches"]), 8)
        total = sum(len(m["snippet"]) for m in r["matches"])
        self.assertLessEqual(total, 200 + 80 * len(r["matches"]))
        self.assertTrue(r.get("truncated"))

    def test_recall_tool_registered(self):
        names = [t.name for t in ToolService.list_tools()]
        self.assertIn("recallContext", names)
        info = ToolService.get_tool_info("recallContext")
        self.assertIn("text", info.parameters)
        self.assertIn("id", info.parameters)


class TestCompaction(unittest.TestCase):
    """压缩流程：归档 → 摘要 → 替换，以及各失败分支。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_compaction_prompt_is_the_designed_one(self):
        self.assertIn("上下文管理助手", COMPACTION_SYSTEM_PROMPT)
        self.assertIn("5,000 Tokens", COMPACTION_SYSTEM_PROMPT)
        self.assertIn("recallContext", COMPACTION_SYSTEM_PROMPT)

    def test_build_compaction_request_has_no_tools(self):
        request = build_compaction_messages(_sample_messages())
        self.assertEqual(request[0].role, "system")
        self.assertEqual(request[0].content, COMPACTION_SYSTEM_PROMPT)
        self.assertEqual(request[1].role, "user")
        self.assertIn("### [1] user", request[1].content)

    def test_transcript_keeps_tool_details(self):
        text = build_transcript(_sample_messages())
        self.assertIn("read_file", text)
        self.assertIn("call_0001", text)

    def test_compact_success(self):
        # 真实场景下上下文远大于摘要，这里先把历史堆到足够长
        msgs = _sample_messages() + [
            LLMMessage(role="user", content="继续补充第 %d 轮的细节：" % i + "很长的一段背景说明。" * 40)
            for i in range(6)
        ]
        provider = _FakeProvider(reply="## 用户目标\n把模型改成 ernie-5.1")
        result = compact_messages(msgs, provider, project_root=self.root, model="ernie-5.1")

        self.assertTrue(result.success, result.error)
        # 压缩期间只调一次 LLM，且不带任何工具
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(provider.calls[0]["tools"], [])

        # 归档先落盘
        self.assertTrue(Path(result.archive_path).is_file())
        self.assertRegex(result.archive_id, r"^\d{8}-\d{6}$")

        # System Prompt 保留，摘要 + 归档说明在，历史被替换
        self.assertEqual(result.messages[0].role, "system")
        self.assertEqual(result.messages[0].content, msgs[0].content)
        summary_msg = result.messages[1]
        self.assertIn("把模型改成 ernie-5.1", summary_msg.content)
        self.assertIn(result.archive_id, summary_msg.content)
        self.assertIn("完成压缩", summary_msg.content)
        self.assertIn("recallContext", summary_msg.content)
        self.assertEqual(len(result.messages), 3)  # system + 摘要 + 确认
        self.assertGreater(result.summary_tokens, 0)
        self.assertLess(result.tokens_after, result.tokens_before)

    def test_compact_failure_keeps_context(self):
        msgs = _sample_messages()
        provider = _FakeProvider(error=RuntimeError("HTTP 500"))
        result = compact_messages(msgs, provider, project_root=self.root)

        self.assertFalse(result.success)
        self.assertIn("摘要生成失败", result.error)
        self.assertEqual(result.messages, msgs)   # 原上下文不变
        # 归档在压缩前就该存下来，方便事后追
        self.assertTrue(Path(result.archive_path).is_file())

    def test_compact_empty_summary_is_failure(self):
        msgs = _sample_messages()
        result = compact_messages(msgs, _FakeProvider(reply="   "), project_root=self.root)
        self.assertFalse(result.success)
        self.assertIn("空摘要", result.error)
        self.assertEqual(result.messages, msgs)

    def test_archive_failure_aborts_before_llm(self):
        # 把一个普通文件当成项目根目录 → mkdir 必然失败
        blocker = self.root / "not-a-dir"
        blocker.write_text("x", encoding="utf-8")
        provider = _FakeProvider()
        result = compact_messages(_sample_messages(), provider, project_root=blocker)

        self.assertFalse(result.success)
        self.assertIn("归档保存失败", result.error)
        self.assertEqual(provider.calls, [])  # 没归档就绝不去调 LLM

    def test_replace_messages_without_system(self):
        msgs = [LLMMessage(role="user", content="hi")]
        new = replace_messages(msgs, LLMMessage(role="user", content="摘要"))
        self.assertEqual(len(new), 2)
        self.assertEqual(new[0].content, "摘要")
        self.assertEqual(new[1].role, "assistant")

    def test_compact_rejects_tool_call_response(self):
        class ToolCallProvider:
            last_usage = None

            def chat(self, messages, tools_schema):
                return LLMMessage(
                    role="assistant", content="",
                    tool_calls=[ToolCall(id="c1", name="read_file", arguments={})],
                )

        msgs = _sample_messages()
        result = compact_messages(msgs, ToolCallProvider(), project_root=self.root)
        self.assertFalse(result.success)
        self.assertIn("工具调用", result.error)
        self.assertEqual(result.messages, msgs)

    def test_mock_provider_can_produce_summary(self):
        from xAgent.core.llm import MockProvider

        request = build_compaction_messages(_sample_messages())
        response = MockProvider().chat(request, [])
        self.assertTrue((response.content or "").strip())
        self.assertIsNone(response.tool_calls)  # 压缩时绝不能返回工具调用


class TestRecallToolEndToEnd(unittest.TestCase):
    """走 ToolService 门面，验证工具参数能真正落到归档检索上。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = os.getcwd()
        os.chdir(self.tmp.name)
        save_archive(_sample_messages(), project_root=Path(self.tmp.name),
                     archive_id="20260404-040404")

    def tearDown(self):
        os.chdir(self.cwd)
        self.tmp.cleanup()

    def test_tool_call_returns_matches(self):
        result = ToolService.call("recallContext", text="config.ini")
        self.assertTrue(result.success, result.error)
        self.assertTrue(result.data["matches"])
        self.assertEqual(result.data["matches"][0]["archive_id"], "20260404-040404")

    def test_tool_call_with_id_filter(self):
        result = ToolService.call(
            "recallContext", text="config", id="20260404-040404"
        )
        self.assertTrue(result.success, result.error)
        self.assertEqual(result.data["archives_scanned"], 1)


if __name__ == "__main__":
    unittest.main()
