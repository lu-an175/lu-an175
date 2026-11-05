# -*- coding: utf-8 -*-
"""
xAgent 配置层单元测试 —— 模板生成 / 解析 / 脏值兜底 / 旧配置迁移。

全部在临时目录里跑，不触碰真实 config.ini。
"""

import configparser
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from xAgent.core import config as config_mod
from xAgent.core.config import (
    AppConfig,
    ensure_config_file,
    load_config,
    write_default_config,
)


class TestEnsureConfigFile(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.path = self.root / "config.ini"
        # 默认把「包内旧配置」指到一个不存在的位置，避免本机真实 key 干扰断言
        self._legacy_patch = mock.patch.object(
            config_mod, "LEGACY_CONFIG_INI", self.root / "no-legacy.ini"
        )
        self._legacy_patch.start()

    def tearDown(self):
        self._legacy_patch.stop()
        self._tmp.cleanup()

    def test_creates_file_when_missing(self):
        bootstrap = ensure_config_file(self.path)
        self.assertTrue(bootstrap.created)
        self.assertTrue(self.path.is_file())
        self.assertIsNone(bootstrap.seeded_from)

        text = self.path.read_text(encoding="utf-8")
        for section in ("[llm]", "[agent]", "[context]", "[session]", "[ui]", "[mcp]"):
            self.assertIn(section, text)

    def test_template_is_mock_by_default(self):
        ensure_config_file(self.path)
        cfg = load_config(self.path)
        self.assertEqual(cfg.provider, "mock")
        self.assertEqual(cfg.api_key, "")
        self.assertTrue(cfg.use_mock)
        self.assertEqual(cfg.model, "mock")

    def test_template_parses_without_errors(self):
        ensure_config_file(self.path)
        parser = configparser.ConfigParser(interpolation=None)
        parser.read(self.path, encoding="utf-8")
        self.assertTrue(parser.has_section("mcp:demo"))
        self.assertEqual(parser.get("context", "compact_threshold"), "0.7")

    def test_template_has_demo_mcp_server(self):
        ensure_config_file(self.path)
        cfg = load_config(self.path)
        self.assertEqual(len(cfg.mcp_servers), 1)
        server = cfg.mcp_servers[0]
        self.assertEqual(server.name, "demo")
        self.assertEqual(server.transport, "stdio")
        self.assertEqual(server.args, ["-m", "xAgent.mcp_servers.demo_server"])

    def test_second_call_does_not_overwrite(self):
        ensure_config_file(self.path)
        self.path.write_text("[llm]\nprovider = qianfan\n", encoding="utf-8")
        bootstrap = ensure_config_file(self.path)
        self.assertFalse(bootstrap.created)
        self.assertIn("qianfan", self.path.read_text(encoding="utf-8"))

    def test_seeds_key_from_legacy_config(self):
        legacy = self.root / "legacy.ini"
        legacy.write_text(
            "[qianfan]\nbaidu_qianfan_api_key = bce-v3/ALTAK-legacy/key\n",
            encoding="utf-8",
        )
        with mock.patch.object(config_mod, "LEGACY_CONFIG_INI", legacy):
            bootstrap = ensure_config_file(self.path)
        self.assertTrue(bootstrap.created)
        self.assertEqual(bootstrap.seeded_from, legacy)

        cfg = load_config(self.path)
        self.assertEqual(cfg.api_key, "bce-v3/ALTAK-legacy/key")
        self.assertEqual(cfg.provider, "qianfan")
        self.assertFalse(cfg.use_mock)


class TestLoadConfig(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.path = self.root / "config.ini"

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, text: str) -> None:
        self.path.write_text(text, encoding="utf-8")

    def test_missing_file_returns_defaults(self):
        cfg = load_config(self.root / "nope.ini")
        self.assertTrue(cfg.use_mock)
        self.assertEqual(cfg.max_model_calls, 8)
        self.assertEqual(cfg.compact_threshold, 0.7)
        self.assertEqual(cfg.archive_dir, ".agents/context")
        self.assertTrue(cfg.warnings)

    def test_reads_all_sections(self):
        self._write(
            """
[llm]
provider = qianfan
api_key = abc
base_url = https://example.test/v2
model = ernie-5.1
timeout = 30

[agent]
max_model_calls = 3

[context]
window = 32000
compact_threshold = 0.5
target_tokens = 2000
archive_dir = data/ctx

[session]
dir = data/sessions
auto_save = false
agents_md = false
agents_md_file = RULES.md

[ui]
sidebar_width = 50
card_preview_chars = 200
show_command_palette = false

[mcp]
enabled = false
timeout = 9

[mcp:alpha]
transport = stdio
command = python
args = -m, my.server, --flag
env = A=1,B=2
"""
        )
        cfg = load_config(self.path)
        self.assertEqual(cfg.provider, "qianfan")
        self.assertEqual(cfg.api_key, "abc")
        self.assertEqual(cfg.timeout, 30)
        self.assertEqual(cfg.max_model_calls, 3)
        self.assertEqual(cfg.context_window, 32000)
        self.assertEqual(cfg.compact_threshold, 0.5)
        self.assertEqual(cfg.compact_target_tokens, 2000)
        self.assertEqual(cfg.archive_dir, "data/ctx")
        self.assertEqual(cfg.session_dir, "data/sessions")
        self.assertFalse(cfg.auto_save)
        self.assertFalse(cfg.agents_md_enabled)
        self.assertEqual(cfg.agents_md_file, "RULES.md")
        self.assertEqual(cfg.sidebar_width, 50)
        self.assertEqual(cfg.card_preview_chars, 200)
        self.assertFalse(cfg.show_command_palette)
        self.assertFalse(cfg.mcp_enabled)
        self.assertEqual(cfg.mcp_timeout, 9)

        self.assertEqual(len(cfg.mcp_servers), 1)
        server = cfg.mcp_servers[0]
        self.assertEqual(server.name, "alpha")
        self.assertEqual(server.args, ["-m", "my.server", "--flag"])
        self.assertEqual(server.env, {"A": "1", "B": "2"})

    def test_servers_option_filters_sections(self):
        self._write(
            """
[mcp]
servers = beta

[mcp:alpha]
command = python

[mcp:beta]
command = python
"""
        )
        cfg = load_config(self.path)
        self.assertEqual([s.name for s in cfg.mcp_servers], ["beta"])

    def test_missing_server_section_warns(self):
        self._write("[mcp]\nservers = ghost\n")
        cfg = load_config(self.path)
        self.assertEqual(cfg.mcp_servers, [])
        self.assertTrue(any("ghost" in w for w in cfg.warnings))

    def test_dirty_values_fall_back_to_defaults(self):
        self._write(
            """
[agent]
max_model_calls = 八次

[ui]
sidebar_width = abc

[context]
compact_threshold = 很满

[session]
auto_save = 也许
"""
        )
        cfg = load_config(self.path)
        self.assertEqual(cfg.max_model_calls, 8)
        self.assertEqual(cfg.sidebar_width, 42)
        self.assertEqual(cfg.compact_threshold, 0.7)
        self.assertTrue(cfg.auto_save)
        self.assertGreaterEqual(len(cfg.warnings), 4)

    def test_sidebar_width_is_clamped(self):
        self._write("[ui]\nsidebar_width = 1000\n")
        cfg = load_config(self.path)
        self.assertLessEqual(cfg.sidebar_width, 120)

    def test_old_qianfan_section_still_reads(self):
        self._write("[qianfan]\nbaidu_qianfan_api_key = old-key\n")
        cfg = load_config(self.path)
        self.assertEqual(cfg.api_key, "old-key")
        self.assertEqual(cfg.provider, "qianfan")

    def test_env_var_overrides_key(self):
        self._write("[llm]\napi_key = from-file\n")
        with mock.patch.dict("os.environ", {"QIANFAN_API_KEY": "from-env"}):
            cfg = load_config(self.path)
        self.assertEqual(cfg.api_key, "from-env")

    def test_write_default_config_marks_provider(self):
        write_default_config(self.path, {"api_key": "k1"})
        cfg = load_config(self.path)
        self.assertEqual(cfg.provider, "qianfan")
        self.assertEqual(cfg.api_key, "k1")


class TestAppConfig(unittest.TestCase):
    def test_use_mock_without_key(self):
        self.assertTrue(AppConfig().use_mock)

    def test_use_mock_with_key(self):
        cfg = AppConfig(provider="qianfan", api_key="k", model="ernie-5.1")
        self.assertFalse(cfg.use_mock)
        self.assertEqual(cfg.llm_label, "ernie-5.1")


if __name__ == "__main__":
    unittest.main()
