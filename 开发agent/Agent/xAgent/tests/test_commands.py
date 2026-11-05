# -*- coding: utf-8 -*-
"""
斜杠命令表测试 —— 补全匹配 / 别名 / 帮助文本一致性。

这层是纯数据，没有 UI 依赖，改命令最容易出事，所以单独测。
"""

import unittest

from xAgent.tui.commands import (
    COMMANDS,
    all_commands,
    filter_commands,
    find_command,
    help_text,
)


class TestFindCommand(unittest.TestCase):
    def test_exact_name(self):
        self.assertEqual(find_command("/new").name, "/new")

    def test_alias(self):
        self.assertEqual(find_command("/clear").name, "/new")
        self.assertEqual(find_command("/exit").name, "/quit")
        self.assertEqual(find_command("/sessions").name, "/resume")
        self.assertEqual(find_command("/?").name, "/help")

    def test_case_insensitive(self):
        self.assertEqual(find_command("/HELP").name, "/help")

    def test_with_argument(self):
        self.assertEqual(find_command("/new 我的会话").name, "/new")

    def test_unknown(self):
        self.assertIsNone(find_command("/nope"))

    def test_not_a_command(self):
        self.assertIsNone(find_command("你好"))


class TestFilterCommands(unittest.TestCase):
    def test_bare_slash_lists_all(self):
        items = filter_commands("/", limit=50)
        self.assertEqual(len(items), len(COMMANDS))

    def test_prefix_match(self):
        names = [c.name for c in filter_commands("/co")]
        self.assertIn("/compact", names)
        self.assertIn("/config", names)
        self.assertNotIn("/new", names)

    def test_single_letter_prefix(self):
        names = [c.name for c in filter_commands("/n")]
        self.assertEqual(names[0], "/new")

    def test_description_fallback(self):
        names = [c.name for c in filter_commands("/服务器")]
        self.assertIn("/mcp", names)

    def test_limit(self):
        self.assertLessEqual(len(filter_commands("/", limit=3)), 3)

    def test_no_match(self):
        self.assertEqual(filter_commands("/zzzz"), [])

    def test_space_closes_palette(self):
        self.assertEqual(filter_commands("/new "), [])

    def test_not_slash(self):
        self.assertEqual(filter_commands("new"), [])


class TestHelpText(unittest.TestCase):
    def test_every_command_listed(self):
        text = help_text()
        for command in COMMANDS:
            self.assertIn(command.name, text)

    def test_mentions_resume_and_save(self):
        text = help_text()
        self.assertIn("/resume", text)
        self.assertIn("/save", text)

    def test_commands_are_unique(self):
        names = [c.name for c in all_commands()]
        self.assertEqual(len(names), len(set(names)))

    def test_required_commands_exist(self):
        names = {c.name for c in COMMANDS}
        for required in ("/new", "/resume", "/save", "/quit", "/help", "/compact"):
            self.assertIn(required, names)


if __name__ == "__main__":
    unittest.main()
