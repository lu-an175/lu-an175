# -*- coding: utf-8 -*-
"""
xAgent/core 独立单元测试 —— 不依赖 Practice02 旧模块，
只通过 ToolService / ToolResult 门面验证新架构正确性。
"""

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from xAgent.core import ToolService, ToolResult, ToolInfo, TOOLS, call_tool
from xAgent.core.skills import (
    build_skill_prompt, discover_skills, reset_skill_registry,
)
from xAgent.core.types import ToolResult as TR, ToolInfo as TI
from xAgent.core.registry import TOOL_META, TOOL_FUNCS, ToolService as TS


class TestToolResult(unittest.TestCase):
    """ToolResult dataclass 序列化 / 反序列化 / 便捷构造。"""

    def test_ok_factory(self):
        r = ToolResult.ok(message="hi", file_path="/x")
        self.assertTrue(r.success)
        self.assertEqual(r.message, "hi")
        self.assertEqual(r.data["file_path"], "/x")

    def test_fail_factory(self):
        r = ToolResult.fail("oops")
        self.assertFalse(r.success)
        self.assertEqual(r.error, "oops")

    def test_to_dict_flat(self):
        r = ToolResult.ok(message="m", file_path="/p")
        d = r.to_dict()
        self.assertEqual(d["success"], True)
        self.assertEqual(d["message"], "m")
        self.assertEqual(d["file_path"], "/p")
        self.assertNotIn("data", d)

    def test_from_dict_round_trip(self):
        raw = {"success": True, "current_directory": "/tmp", "message": "ok"}
        r = ToolResult.from_dict(raw)
        self.assertTrue(r.success)
        self.assertEqual(r.data["current_directory"], "/tmp")
        # to_dict 应还原（去掉 data 包装）
        self.assertEqual(r.to_dict(), raw)

    def test_fail_round_trip(self):
        raw = {"success": False, "error": "no such file"}
        r = ToolResult.from_dict(raw)
        self.assertFalse(r.success)
        self.assertEqual(r.to_dict(), raw)


class TestToolInfo(unittest.TestCase):
    """ToolInfo 元数据完整性。"""

    def test_all_tools_have_metadata(self):
        all_tools = {
            "get_current_working_directory", "list_directory", "get_file_type",
            "read_file", "create_file", "write_file", "create_directory",
            "delete_directory", "delete_file", "rename_item", "searchWeb",
            "fetchWeb", "runCli", "loadSkill", "recallContext",
        }
        self.assertEqual(set(TOOL_META.keys()), all_tools)
        self.assertEqual(set(TOOL_FUNCS.keys()), all_tools)

    def test_tool_info_fields(self):
        for name, info in TOOL_META.items():
            self.assertIsInstance(info, ToolInfo)
            self.assertEqual(info.name, name)
            self.assertTrue(len(info.description) > 0)

    def test_params_property(self):
        info = TOOL_META["read_file"]
        self.assertEqual(info.param_names, ["file_path"])
        info_none = TOOL_META["get_current_working_directory"]
        self.assertEqual(info_none.param_names, [])


class TestToolServiceFacade(unittest.TestCase):
    """ToolService 门面正确性。"""

    def test_list_tools(self):
        tools = ToolService.list_tools()
        self.assertEqual(len(tools), 15)
        self.assertTrue(all(isinstance(t, ToolInfo) for t in tools))

    def test_get_tool_info(self):
        self.assertIsNotNone(ToolService.get_tool_info("rename_item"))
        self.assertIsNone(ToolService.get_tool_info("not_exist"))

    def test_call_unknown_tool(self):
        r = ToolService.call("no_such_tool")
        self.assertFalse(r.success)
        self.assertIn("未知工具", r.error)

    def test_call_dict_compatibility(self):
        r_dict = ToolService.call_dict("get_current_working_directory")
        self.assertIsInstance(r_dict, dict)
        self.assertTrue(r_dict["success"])
        self.assertIn("current_directory", r_dict)


class TestToolsIndividually(unittest.TestCase):
    """对 10 个工具逐个调用 ToolService.call()，验证核心逻辑无回归。"""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.work = Path(self._tmp) / "work"
        self.work.mkdir()

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_get_cwd(self):
        r = ToolService.call("get_current_working_directory")
        self.assertTrue(r.success)
        self.assertTrue(os.path.isdir(r.data["current_directory"]))

    def test_list_directory_empty(self):
        r = ToolService.call("list_directory", path=str(self.work))
        self.assertTrue(r.success)
        self.assertEqual(r.data["files"], [])
        self.assertEqual(r.data["directories"], [])

    def test_create_directory_and_list(self):
        sub = self.work / "sub1"
        r = ToolService.call("create_directory", dir_path=str(sub))
        self.assertTrue(r.success)
        self.assertTrue(sub.is_dir())

        # 级联创建
        deep = self.work / "a" / "b" / "c"
        r = ToolService.call("create_directory", dir_path=str(deep))
        self.assertTrue(r.success)
        self.assertTrue(deep.is_dir())

        # list
        r = ToolService.call("list_directory", path=str(self.work))
        self.assertEqual(r.data["directory_count"], 2)  # sub1, a

    def test_create_and_read_file(self):
        f = self.work / "hello.txt"
        r = ToolService.call("create_file", file_path=str(f), content="Hello 世界")
        self.assertTrue(r.success)
        self.assertTrue(f.is_file())

        r = ToolService.call("read_file", file_path=str(f))
        self.assertTrue(r.success)
        self.assertEqual(r.data["content"], "Hello 世界")

    def test_get_file_type(self):
        f = self.work / "a.py"
        f.write_text("print(1)")
        r = ToolService.call("get_file_type", file_path=str(f))
        self.assertTrue(r.success)
        self.assertEqual(r.data["extension"], ".py")
        self.assertIn("Python", r.data["file_type"])

    def test_write_file_overwrite_and_append(self):
        f = self.work / "note.txt"
        f.write_text("initial")

        r = ToolService.call("write_file", file_path=str(f), content="OVERWRITTEN")
        self.assertTrue(r.success)
        self.assertEqual(f.read_text(), "OVERWRITTEN")

        r = ToolService.call("write_file", file_path=str(f), content="APPENDED", mode="append")
        self.assertTrue(r.success)
        self.assertIn("APPENDED", f.read_text())

    def test_delete_file(self):
        f = self.work / "trash.txt"
        f.write_text("bye")
        r = ToolService.call("delete_file", file_path=str(f))
        self.assertTrue(r.success)
        self.assertFalse(f.exists())

    def test_delete_directory_non_empty(self):
        d = self.work / "nested"
        d.mkdir()
        (d / "f.txt").write_text("content")
        r = ToolService.call("delete_directory", dir_path=str(d), force="true")
        self.assertTrue(r.success)
        self.assertFalse(d.exists())

    def test_delete_directory_refuse_nonempty_without_force(self):
        d = self.work / "nested"
        d.mkdir()
        (d / "f.txt").write_text("content")
        r = ToolService.call("delete_directory", dir_path=str(d), force="false")
        self.assertFalse(r.success)
        self.assertTrue(d.exists())  # 目录仍在

    def test_rename_file(self):
        f = self.work / "old.txt"
        f.write_text("hi")
        r = ToolService.call("rename_item", source_path=str(f), new_name="new.txt")
        self.assertTrue(r.success)
        self.assertFalse(f.exists())
        self.assertTrue((self.work / "new.txt").exists())

    def test_rename_directory(self):
        d = self.work / "old_dir"
        d.mkdir()
        r = ToolService.call("rename_item", source_path=str(d), new_name="new_dir")
        self.assertTrue(r.success)
        self.assertFalse(d.exists())
        self.assertTrue((self.work / "new_dir").exists())

    def test_rename_rejects_existing_target(self):
        f1 = self.work / "a.txt"; f1.write_text("1")
        f2 = self.work / "b.txt"; f2.write_text("2")
        r = ToolService.call("rename_item", source_path=str(f1), new_name="b.txt")
        self.assertFalse(r.success)
        # 两边都不受影响
        self.assertTrue(f1.exists())
        self.assertTrue(f2.exists())

    def test_rename_rejects_path_separator(self):
        f = self.work / "a.txt"; f.write_text("x")
        r = ToolService.call("rename_item", source_path=str(f), new_name="sub/bad.txt")
        self.assertFalse(r.success)
        self.assertTrue(f.exists())

    def test_delete_cwd_rejected(self):
        """不能删除当前工作目录本身。"""
        r = ToolService.call("delete_directory", dir_path=os.getcwd())
        self.assertFalse(r.success)
        self.assertIn("当前工作目录", r.error)

    def test_read_binary_rejected(self):
        f = self.work / "bin.dat"
        f.write_bytes(b"\x00\x01\x02\xff")
        r = ToolService.call("read_file", file_path=str(f))
        self.assertFalse(r.success)
        self.assertIn("二进制", r.error)


class TestCompatibility(unittest.TestCase):
    """验证 TOOLS dict / call_tool 与旧版 Practice02 接口兼容。"""

    def test_old_tools_dict_format(self):
        self.assertIn("rename_item", TOOLS)
        entry = TOOLS["rename_item"]
        self.assertIn("func", entry)
        self.assertIn("description", entry)
        self.assertIn("parameters", entry)

    def test_old_call_tool_returns_dict(self):
        r = call_tool("get_current_working_directory")
        self.assertIsInstance(r, dict)
        self.assertTrue(r["success"])


class TestSearchWeb(unittest.TestCase):
    """searchWeb 工具：配置缺失 / 网络失败 / API 错误 / 正常解析。"""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.ini = Path(self._tmp) / "config.ini"
        self.patches = []
        for target, value in (
            ("xAgent.core.tools.CONFIG_INI", self.ini),
            ("xAgent.core.config.CONFIG_INI", self.ini),
            ("xAgent.core.tools.QIANFAN_SEARCH_URL", "https://example.test/search"),
        ):
            patcher = mock.patch(target, value)
            patcher.start()
            self.patches.append(patcher)

    def tearDown(self):
        for patcher in self.patches:
            patcher.stop()
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _write_ini(self, text):
        self.ini.write_text(text, encoding="utf-8")

    def test_empty_query(self):
        r = ToolService.call("searchWeb", query="   ")
        self.assertFalse(r.success)
        self.assertIn("不能为空", r.error)

    def test_missing_ini_file(self):
        r = ToolService.call("searchWeb", query="天气")
        self.assertFalse(r.success)
        self.assertIn("缺少配置文件", r.error)

    def test_missing_key_option(self):
        self._write_ini("[qianfan]\n")
        r = ToolService.call("searchWeb", query="天气")
        self.assertFalse(r.success)
        self.assertIn("api_key", r.error)

    def test_network_failure(self):
        self._write_ini("[qianfan]\nbaidu_qianfan_api_key = test-key\n")
        with mock.patch(
            "urllib.request.urlopen", side_effect=urllib.error.URLError("boom")
        ):
            r = ToolService.call("searchWeb", query="天气")
        self.assertFalse(r.success)
        self.assertIn("网络请求失败", r.error)

    def test_api_http_error(self):
        self._write_ini("[qianfan]\nbaidu_qianfan_api_key = test-key\n")
        err = urllib.error.HTTPError(
            "https://example.test/search", 401, "Unauthorized", {},
            io.BytesIO(b'{"error":{"code":"invalid_appId","message":"no perm"}}'),
        )
        with mock.patch("urllib.request.urlopen", side_effect=err):
            r = ToolService.call("searchWeb", query="天气")
        self.assertFalse(r.success)
        self.assertIn("HTTP 401", r.error)
        self.assertIn("invalid_appId", r.error)

    def test_api_business_error(self):
        self._write_ini("[qianfan]\nbaidu_qianfan_api_key = test-key\n")
        body = json.dumps({"code": "17", "message": "每日额度已用完"}).encode()
        with mock.patch("urllib.request.urlopen", return_value=_FakeResponse(body)):
            r = ToolService.call("searchWeb", query="天气")
        self.assertFalse(r.success)
        self.assertIn("每日额度已用完", r.error)

    def test_success_parsing(self):
        self._write_ini("[qianfan]\nbaidu_qianfan_api_key = test-key\n")
        body = json.dumps({
            "choices": [{"message": {"content": "今天晴，25℃"}}],
            "references": [
                {"id": "1", "title": "天气预报", "url": "https://a.com",
                 "website": "a.com", "date": "2026-10-26", "content": "晴"},
                {"id": "2", "title": "", "url": "", "content": "无效"},
            ],
        }).encode()
        with mock.patch("urllib.request.urlopen", return_value=_FakeResponse(body)):
            r = ToolService.call("searchWeb", query="天气", top_k="5")
        self.assertTrue(r.success)
        self.assertEqual(r.data["summary"], "今天晴，25℃")
        self.assertEqual(r.data["reference_count"], 1)
        self.assertEqual(r.data["references"][0]["url"], "https://a.com")


class TestFetchWeb(unittest.TestCase):
    """fetchWeb 工具：curl 失败 / 依赖缺失 / 正文为空 / 正常提取。"""

    HTML = b"""<!DOCTYPE html>
<html><head><title>Traefik \xe6\xa1\x88\xe4\xbe\x8b\xe6\x96\x87\xe7\xab\xa0</title></head>
<body>
<nav><a href="/">\xe9\xa6\x96\xe9\xa1\xb5</a><a href="/about">\xe5\x85\xb3\xe4\xba\x8e</a></nav>
<div class="ad">\xe5\xb9\xbf\xe5\x91\x8a\xe4\xbd\x8d</div>
<article>
<h1>Traefik \xe6\xa1\x88\xe4\xbe\x8b\xe6\x96\x87\xe7\xab\xa0</h1>
<p>\xe8\xbf\x99\xe6\x98\xaf\xe6\xad\xa3\xe6\x96\x87\xe7\x9a\x84\xe7\xac\xac\xe4\xb8\x80\xe6\xae\xb5\xef\xbc\x8c\xe5\x8c\x85\xe5\x90\xab\xe4\xb8\x80\xe4\xb8\xaa<a href="https://example.com/link">\xe9\x93\xbe\xe6\x8e\xa5</a>\xe3\x80\x82\xe8\xbf\x99\xe6\xae\xb5\xe6\x96\x87\xe5\xad\x97\xe4\xb8\xbb\xe8\xa6\x81\xe7\x94\xa8\xe4\xba\x8e\xe8\xae\xa9\xe6\xad\xa3\xe6\x96\x87\xe5\x86\x85\xe5\xae\xb9\xe8\xb6\xb3\xe5\xa4\x9f\xe9\x95\xbf\xef\xbc\x8c\xe4\xbb\xa5\xe4\xbe\xbf\xe6\x8f\x90\xe5\x8f\x96\xe5\x99\xa8\xe8\x83\xbd\xe6\xad\xa3\xe7\xa1\xae\xe8\xaf\x86\xe5\x88\xab\xe3\x80\x82</p>
<p>\xe7\xac\xac\xe4\xba\x8c\xe6\xae\xb5\xe7\xbb\xa7\xe7\xbb\xad\xe8\xa1\xa5\xe5\x85\x85\xe6\x9b\xb4\xe5\xa4\x9a\xe7\x9a\x84\xe6\xad\xa3\xe6\x96\x87\xe5\x86\x85\xe5\xae\xb9\xef\xbc\x8c\xe6\x95\x85\xe6\x84\x8f\xe5\x9c\xb0\xe6\x8b\x89\xe9\x95\xbf\xe5\x8f\xa5\xe5\xad\x90\xef\xbc\x8c\xe4\xbb\xa5\xe4\xbd\xbf\xe6\x96\x87\xe7\xab\xa0\xe5\x9c\xa8\xe5\x86\x85\xe5\xae\xb9\xe5\x88\xa4\xe5\xae\x9a\xe6\x97\xb6\xe8\xa2\xab\xe8\xa7\x86\xe4\xb8\xba\xe4\xb8\xbb\xe4\xbd\x93\xe5\x86\x85\xe5\xae\xb9\xe3\x80\x82</p>
<ul><li>\xe7\xac\xac\xe4\xb8\x80\xe9\xa1\xb9</li><li>\xe7\xac\xac\xe4\xba\x8c\xe9\xa1\xb9</li></ul>
<table><tr><th>\xe5\x88\x971</th><th>\xe5\x88\x972</th></tr><tr><td>A</td><td>B</td></tr></table>
</article>
<footer>\xe7\x89\x88\xe6\x9d\x83\xe6\x89\x80\xe6\x9c\x89</footer>
</body></html>
"""

    def _completed(self, stdout: bytes = b"", stderr: bytes = b"", code: int = 0):
        return subprocess.CompletedProcess(args=[], returncode=code,
                                           stdout=stdout, stderr=stderr)

    def test_empty_url(self):
        r = ToolService.call("fetchWeb", url="   ")
        self.assertFalse(r.success)
        self.assertIn("不能为空", r.error)

    def test_unsupported_scheme(self):
        r = ToolService.call("fetchWeb", url="file:///C:/Windows/win.ini")
        self.assertFalse(r.success)
        self.assertIn("不支持", r.error)

    def test_curl_missing(self):
        with mock.patch("xAgent.core.tools.shutil.which", return_value=None):
            r = ToolService.call("fetchWeb", url="https://example.com")
        self.assertFalse(r.success)
        self.assertIn("未找到 curl", r.error)

    def test_curl_timeout(self):
        with mock.patch("xAgent.core.tools.shutil.which", return_value="curl"), \
             mock.patch("xAgent.core.tools.subprocess.run",
                        side_effect=subprocess.TimeoutExpired(cmd="curl", timeout=30)):
            r = ToolService.call("fetchWeb", url="https://example.com")
        self.assertFalse(r.success)
        self.assertIn("超时", r.error)

    def test_curl_nonzero_exit(self):
        with mock.patch("xAgent.core.tools.shutil.which", return_value="curl"), \
             mock.patch("xAgent.core.tools.subprocess.run",
                        return_value=self._completed(
                            stderr=b"curl: (22) The requested URL returned error: 404",
                            code=22)):
            r = ToolService.call("fetchWeb", url="https://example.com/404")
        self.assertFalse(r.success)
        self.assertIn("404", r.error)

    def test_empty_response(self):
        with mock.patch("xAgent.core.tools.shutil.which", return_value="curl"), \
             mock.patch("xAgent.core.tools.subprocess.run",
                        return_value=self._completed()):
            r = ToolService.call("fetchWeb", url="https://example.com")
        self.assertFalse(r.success)
        self.assertIn("未返回任何内容", r.error)

    def test_missing_trafilatura(self):
        with mock.patch("xAgent.core.tools.shutil.which", return_value="curl"), \
             mock.patch("xAgent.core.tools.subprocess.run",
                        return_value=self._completed(stdout=self.HTML)), \
             mock.patch("xAgent.core.tools._load_trafilatura", return_value=None):
            r = ToolService.call("fetchWeb", url="https://example.com")
        self.assertFalse(r.success)
        self.assertIn("trafilatura", r.error)

    def test_extract_failed(self):
        with mock.patch("xAgent.core.tools.shutil.which", return_value="curl"), \
             mock.patch("xAgent.core.tools.subprocess.run",
                        return_value=self._completed(
                            stdout=b"<html><body><script>nothing</script></body></html>")), \
             mock.patch("xAgent.core.tools._load_trafilatura") as fake:
            fake.return_value.extract.return_value = None
            r = ToolService.call("fetchWeb", url="https://example.com")
        self.assertFalse(r.success)
        self.assertIn("正文提取失败", r.error)

    def test_success_markdown(self):
        with mock.patch("xAgent.core.tools.shutil.which", return_value="curl"), \
             mock.patch("xAgent.core.tools.subprocess.run",
                        return_value=self._completed(stdout=self.HTML)) as run:
            r = ToolService.call("fetchWeb", url="https://example.com/post")

        self.assertTrue(r.success)
        self.assertEqual(r.data["url"], "https://example.com/post")
        self.assertIn("正文", r.data["markdown"])
        self.assertIn("https://example.com/link", r.data["markdown"])   # 链接保留
        self.assertNotIn("广告位", r.data["markdown"])                    # 广告去除
        self.assertFalse(r.data["truncated"])
        self.assertGreater(r.data["char_count"], 0)

        # curl 必须以参数列表方式调用，且不使用 shell
        args, kwargs = run.call_args
        self.assertIsInstance(args[0], list)
        self.assertNotIn("shell", kwargs)

    def test_truncation(self):
        with mock.patch("xAgent.core.tools.shutil.which", return_value="curl"), \
             mock.patch("xAgent.core.tools.subprocess.run",
                        return_value=self._completed(stdout=self.HTML)), \
             mock.patch("xAgent.core.tools._MAX_MARKDOWN_CHARS", 80):
            r = ToolService.call("fetchWeb", url="https://example.com/post")
        self.assertTrue(r.success)
        self.assertTrue(r.data["truncated"])
        self.assertIn("已截断", r.data["markdown"])


class TestRunCli(unittest.TestCase):
    """runCli 工具：参数列表执行 / 退出码 / stderr / 超时 / 输出截断。"""

    def _py(self, code: str) -> list:
        return ["-c", code]

    def test_empty_command(self):
        r = ToolService.call("runCli", command="   ")
        self.assertFalse(r.success)
        self.assertIn("不能为空", r.error)

    def test_missing_program(self):
        r = ToolService.call("runCli", command="xagent-no-such-program-xyz")
        self.assertFalse(r.success)
        self.assertIn("未找到可执行程序", r.error)

    def test_success_stdout(self):
        r = ToolService.call(
            "runCli", command=sys.executable, args=self._py("print('hello-cli')")
        )
        self.assertTrue(r.success)
        self.assertEqual(r.data["exitcode"], 0)
        self.assertIn("hello-cli", r.data["stdout"])

    def test_nonzero_exit(self):
        r = ToolService.call(
            "runCli", command=sys.executable,
            args=self._py("import sys; sys.exit(3)"),
        )
        self.assertFalse(r.success)
        self.assertEqual(r.data["exitcode"], 3)
        self.assertIn("退出码 3", r.error)

    def test_stderr_captured(self):
        r = ToolService.call(
            "runCli", command=sys.executable,
            args=self._py("import sys; sys.stderr.write('boom')"),
        )
        self.assertTrue(r.success)      # 退出码为 0
        self.assertIn("boom", r.data["stderr"])

    def test_timeout(self):
        r = ToolService.call(
            "runCli", command=sys.executable,
            args=self._py("import time; time.sleep(10)"),
            timeout=1,
        )
        self.assertFalse(r.success)
        self.assertTrue(r.data["timed_out"])
        self.assertIn("超时", r.error)

    def test_args_as_json_string(self):
        r = ToolService.call(
            "runCli", command=sys.executable, args='["-c", "print(42)"]'
        )
        self.assertTrue(r.success)
        self.assertIn("42", r.data["stdout"])

    def test_output_truncated(self):
        with mock.patch("xAgent.core.tools._CLI_MAX_STREAM_CHARS", 50):
            r = ToolService.call(
                "runCli", command=sys.executable,
                args=self._py("print('x' * 200)"),
            )
        self.assertTrue(r.success)
        self.assertTrue(r.data["stdout_truncated"])
        self.assertIn("已截断", r.data["stdout"])

    def test_shell_false_with_arg_list(self):
        fake = subprocess.CompletedProcess(args=[], returncode=0, stdout=b"ok", stderr=b"")
        with mock.patch("xAgent.core.tools.subprocess.run", return_value=fake) as run:
            r = ToolService.call("runCli", command="git", args=["status", "--short"])
        self.assertTrue(r.success)
        call_args, call_kwargs = run.call_args
        self.assertEqual(call_args[0], ["git", "status", "--short"])
        self.assertIs(call_kwargs["shell"], False)


class TestSkillTools(unittest.TestCase):
    """Skill 发现 / System Prompt 注入 / loadSkill 文件解析与目录限制。"""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.root = Path(self._tmp)
        self.skills_dir = self.root / ".agents" / "skills"
        self.demo = self.skills_dir / "demo-skill"
        self.demo.mkdir(parents=True)
        (self.demo / "SKILL.md").write_text(
            "---\n"
            "name: demo-skill\n"
            "description: >\n"
            "  Demo skill used for tests.\n"
            "  Provides helper instructions.\n"
            "---\n"
            "# Demo\n\nUse me.\n",
            encoding="utf-8",
        )
        (self.demo / "docs").mkdir()
        (self.demo / "docs" / "guide.md").write_text("guide body", encoding="utf-8")
        (self.demo / "extra").mkdir()
        (self.demo / "extra" / "guide.md").write_text("extra guide", encoding="utf-8")
        (self.demo / "plain.md").write_text("plain body", encoding="utf-8")

        # 缺少 frontmatter 的 Skill 应被忽略
        bad = self.skills_dir / "bad-skill"
        bad.mkdir()
        (bad / "SKILL.md").write_text("no frontmatter\n", encoding="utf-8")

        (self.root / "secret.txt").write_text("secret", encoding="utf-8")

        self.registry = discover_skills(self.root)

    def tearDown(self):
        reset_skill_registry()
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_discovery_loads_metadata_only(self):
        self.assertEqual(self.registry.names(), ["demo-skill"])
        info = self.registry.get("demo-skill")
        self.assertEqual(
            info.description,
            "Demo skill used for tests. Provides helper instructions.",
        )
        self.assertEqual(info.skill_file.name, "SKILL.md")
        self.assertEqual(len(self.registry.warnings), 1)
        self.assertIn("bad-skill", self.registry.warnings[0])

    def test_skill_prompt_injection(self):
        prompt = build_skill_prompt(self.registry)
        self.assertIn("You have access to the following skills:", prompt)
        self.assertIn("'demo-skill'", prompt)
        self.assertIn("loadSkill", prompt)
        self.assertIn("you MUST call loadSkill", prompt)
        self.assertEqual(build_skill_prompt(discover_skills(self.root)), prompt)

    def test_skill_prompt_empty_without_skills(self):
        empty = discover_skills(self.root / "no-skills-here")
        self.assertEqual(build_skill_prompt(empty), "")
        discover_skills(self.root)

    def test_load_skill_name_only(self):
        r = ToolService.call("loadSkill", name="demo-skill")
        self.assertTrue(r.success)
        self.assertEqual(r.data["relative_path"], "SKILL.md")
        self.assertIn("# Demo", r.data["content"])
        self.assertIn("name: demo-skill", r.data["content"])

    def test_load_skill_filename_relative_to_skill_dir(self):
        r = ToolService.call("loadSkill", name="demo-skill", filename="docs/guide.md")
        self.assertTrue(r.success)
        self.assertEqual(r.data["content"], "guide body")
        self.assertEqual(r.data["relative_path"], "docs/guide.md")

    def test_load_skill_project_relative_path(self):
        r = ToolService.call(
            "loadSkill", name="demo-skill",
            filename=".agents/skills/demo-skill/plain.md",
        )
        self.assertTrue(r.success)
        self.assertEqual(r.data["content"], "plain body")

    def test_load_skill_absolute_path(self):
        target = self.demo / "docs" / "guide.md"
        r = ToolService.call("loadSkill", name="demo-skill", filename=str(target))
        self.assertTrue(r.success)
        self.assertEqual(r.data["content"], "guide body")

    def test_load_skill_rejects_outside_absolute_path(self):
        r = ToolService.call(
            "loadSkill", name="demo-skill",
            filename=str(self.root / "secret.txt"),
        )
        self.assertFalse(r.success)
        self.assertIn("不在 Skill", r.error)

    def test_load_skill_filename_does_not_reload_skill_md(self):
        r = ToolService.call("loadSkill", name="demo-skill", filename="plain.md")
        self.assertTrue(r.success)
        self.assertEqual(r.data["content"], "plain body")
        self.assertNotIn("# Demo", r.data["content"])

    def test_load_skill_basename_unique_match(self):
        r = ToolService.call("loadSkill", name="demo-skill", filename="plain.md")
        self.assertTrue(r.success)
        self.assertEqual(r.data["relative_path"], "plain.md")

    def test_load_skill_duplicate_basename_returns_candidates(self):
        r = ToolService.call("loadSkill", name="demo-skill", filename="guide.md")
        self.assertFalse(r.success)
        self.assertEqual(
            r.data["candidates"], ["docs/guide.md", "extra/guide.md"]
        )
        self.assertIn("2 个同名文件", r.error)

    def test_load_skill_missing_file(self):
        r = ToolService.call("loadSkill", name="demo-skill", filename="nope.md")
        self.assertFalse(r.success)
        self.assertIn("未找到文件", r.error)

    def test_load_skill_unknown_name(self):
        r = ToolService.call("loadSkill", name="not-exist")
        self.assertFalse(r.success)
        self.assertIn("未找到 Skill", r.error)
        self.assertEqual(r.data["available_skills"], ["demo-skill"])


class _FakeResponse:
    """urlopen 的假响应对象。"""

    def __init__(self, body: bytes):
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


if __name__ == "__main__":
    unittest.main()
