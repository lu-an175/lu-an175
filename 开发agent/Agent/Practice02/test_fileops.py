# -*- coding: utf-8 -*-
"""
chat-stream-tool-fileops.py 的单元测试
使用 Python 内置 unittest 框架
"""

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

# 被测模块文件名含连字符，不能直接 import，改用 importlib 加载
_MODULE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chat-stream-tool-fileops.py")
_spec = importlib.util.spec_from_file_location("fops", _MODULE_PATH)
fops = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fops)


class TestGetCurrentWorkingDirectory(unittest.TestCase):
    """测试 get_current_working_directory"""

    def test_returns_success_with_path(self):
        """正常返回当前工作目录"""
        result = fops.get_current_working_directory()
        self.assertTrue(result["success"])
        self.assertIn("current_directory", result)
        self.assertEqual(result["current_directory"], os.getcwd())

    def test_directory_path_exists(self):
        """返回的路径确实存在"""
        result = fops.get_current_working_directory()
        self.assertTrue(os.path.isdir(result["current_directory"]))


class TestListDirectory(unittest.TestCase):
    """测试 list_directory"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_list_empty_directory(self):
        """列出空目录"""
        result = fops.list_directory(str(self.base))
        self.assertTrue(result["success"])
        self.assertEqual(result["files"], [])
        self.assertEqual(result["directories"], [])
        self.assertEqual(result["file_count"], 0)
        self.assertEqual(result["directory_count"], 0)

    def test_list_with_files_and_dirs(self):
        """列出包含文件和子目录的目录"""
        (self.base / "a.txt").write_text("hello", encoding="utf-8")
        (self.base / "b.py").write_text("print(1)", encoding="utf-8")
        (self.base / "subdir").mkdir()

        result = fops.list_directory(str(self.base))
        self.assertTrue(result["success"])
        self.assertEqual(result["file_count"], 2)
        self.assertEqual(result["directory_count"], 1)
        self.assertIn("a.txt", result["files"])
        self.assertIn("b.py", result["files"])
        self.assertIn("subdir", result["directories"])

    def test_nonexistent_path(self):
        """不存在的路径"""
        result = fops.list_directory(str(self.base / "not_exist"))
        self.assertFalse(result["success"])
        self.assertIn("路径不存在", result["error"])

    def test_path_is_file_not_dir(self):
        """传入的是文件而不是目录"""
        file_path = self.base / "only_file.txt"
        file_path.write_text("x", encoding="utf-8")
        result = fops.list_directory(str(file_path))
        self.assertFalse(result["success"])
        self.assertIn("不是目录", result["error"])

    def test_default_path_is_dot(self):
        """默认参数 path='.'"""
        result = fops.list_directory()
        self.assertTrue(result["success"])


class TestGetFileType(unittest.TestCase):
    """测试 get_file_type"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_txt_file(self):
        """识别 .txt 文件类型"""
        p = self.base / "note.txt"
        p.write_text("hello", encoding="utf-8")
        result = fops.get_file_type(str(p))
        self.assertTrue(result["success"])
        self.assertEqual(result["extension"], ".txt")
        self.assertEqual(result["file_type"], "纯文本文件")
        self.assertEqual(result["mime_type"], "text/plain")
        self.assertEqual(result["size_bytes"], 5)

    def test_py_file(self):
        """识别 .py 文件类型"""
        p = self.base / "script.py"
        p.write_text("print(1)", encoding="utf-8")
        result = fops.get_file_type(str(p))
        self.assertTrue(result["success"])
        self.assertEqual(result["file_type"], "Python 源代码")

    def test_no_extension_file(self):
        """无扩展名文件"""
        p = self.base / "Makefile"
        p.write_text("all:", encoding="utf-8")
        result = fops.get_file_type(str(p))
        self.assertTrue(result["success"])
        self.assertEqual(result["extension"], "")
        self.assertEqual(result["file_type"], "无扩展名文件")

    def test_unknown_extension(self):
        """未知扩展名"""
        p = self.base / "data.xyz"
        p.write_text("?", encoding="utf-8")
        result = fops.get_file_type(str(p))
        self.assertTrue(result["success"])
        self.assertEqual(result["extension"], ".xyz")
        self.assertEqual(result["file_type"], "未知类型文件")

    def test_nonexistent_file(self):
        """不存在的文件"""
        result = fops.get_file_type(str(self.base / "ghost.txt"))
        self.assertFalse(result["success"])
        self.assertIn("文件不存在", result["error"])

    def test_pass_directory_as_file(self):
        """把目录当作文件传入"""
        result = fops.get_file_type(str(self.base))
        self.assertFalse(result["success"])
        self.assertIn("不是文件", result["error"])


class TestReadFile(unittest.TestCase):
    """测试 read_file"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_read_plain_text(self):
        """正常读取纯文本文件"""
        content = "hello\nworld\n这是第三行"
        p = self.base / "a.txt"
        p.write_text(content, encoding="utf-8")

        result = fops.read_file(str(p))
        self.assertTrue(result["success"])
        self.assertEqual(result["content"], content)
        self.assertEqual(result["line_count"], 3)
        self.assertEqual(result["char_count"], len(content))
        self.assertEqual(result["file_name"], "a.txt")

    def test_read_empty_file(self):
        """读取空文件"""
        p = self.base / "empty.txt"
        p.write_text("", encoding="utf-8")
        result = fops.read_file(str(p))
        self.assertTrue(result["success"])
        self.assertEqual(result["content"], "")
        self.assertEqual(result["char_count"], 0)
        self.assertEqual(result["line_count"], 1)  # split('\n') on "" -> [""]

    def test_nonexistent_file(self):
        """文件不存在"""
        result = fops.read_file(str(self.base / "nope.txt"))
        self.assertFalse(result["success"])
        self.assertIn("文件不存在", result["error"])

    def test_read_directory_rejected(self):
        """拒绝读取目录"""
        result = fops.read_file(str(self.base))
        self.assertFalse(result["success"])
        self.assertIn("不是文件", result["error"])

    def test_binary_file_rejected(self):
        """拒绝读取二进制文件"""
        p = self.base / "binary.bin"
        p.write_bytes(b"\x00\x01\x02\x03\x00\xff")
        result = fops.read_file(str(p))
        self.assertFalse(result["success"])
        self.assertIn("二进制", result["error"])


class TestCreateFile(unittest.TestCase):
    """测试 create_file"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_create_file_simple(self):
        """直接创建文件"""
        p = self.base / "new.txt"
        result = fops.create_file(str(p), content="hello")
        self.assertTrue(result["success"])
        self.assertTrue(p.exists())
        self.assertEqual(p.read_text(encoding="utf-8"), "hello")

    def test_create_file_default_content_empty(self):
        """默认空内容创建"""
        p = self.base / "empty.txt"
        result = fops.create_file(str(p))
        self.assertTrue(result["success"])
        self.assertEqual(p.read_text(encoding="utf-8"), "")

    def test_create_file_auto_creates_parent_dirs(self):
        """路径中有不存在的目录时自动创建"""
        p = self.base / "a" / "b" / "c" / "deep.txt"
        result = fops.create_file(str(p), content="deep")
        self.assertTrue(result["success"])
        self.assertTrue(p.exists())
        self.assertEqual(p.read_text(encoding="utf-8"), "deep")

    def test_create_existing_file_fails(self):
        """文件已存在时拒绝创建"""
        p = self.base / "exists.txt"
        p.write_text("original", encoding="utf-8")
        result = fops.create_file(str(p), content="new")
        self.assertFalse(result["success"])
        self.assertIn("已存在", result["error"])
        # 原内容应保留
        self.assertEqual(p.read_text(encoding="utf-8"), "original")


class TestWriteFile(unittest.TestCase):
    """测试 write_file"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.target = self.base / "target.txt"
        self.target.write_text("original", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_overwrite_mode(self):
        """覆盖模式写入"""
        result = fops.write_file(str(self.target), content="overwritten", mode="overwrite")
        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "覆盖")
        self.assertEqual(self.target.read_text(encoding="utf-8"), "overwritten")

    def test_default_mode_is_overwrite(self):
        """默认是 overwrite"""
        result = fops.write_file(str(self.target), content="replaced")
        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "覆盖")
        self.assertEqual(self.target.read_text(encoding="utf-8"), "replaced")

    def test_append_mode(self):
        """追加模式"""
        result = fops.write_file(str(self.target), content="APPEND", mode="append")
        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "追加")
        content = self.target.read_text(encoding="utf-8")
        self.assertTrue(content.endswith("APPEND"))
        self.assertIn("original", content)

    def test_append_without_leading_newline_adds_newline(self):
        """追加不以换行开头的内容时自动补换行"""
        fops.write_file(str(self.target), content="XYZ", mode="append")
        raw = self.target.read_bytes()
        self.assertTrue(raw.endswith(b"\nXYZ"))

    def test_append_with_leading_newline_no_extra_newline_added(self):
        """追加内容以换行开头时，源码不会再额外补一个换行"""
        fops.write_file(str(self.target), content="\nABC", mode="append")
        content = self.target.read_text(encoding="utf-8")
        # content 以 \n 开头 -> if content and not content.startswith('\n') 为 False -> 不补换行
        # 结果: "original" + "\nABC" = "original\nABC"
        self.assertEqual(content, "original\nABC")

    def test_nonexistent_file(self):
        """写入不存在的文件"""
        result = fops.write_file(str(self.base / "nope.txt"), content="x")
        self.assertFalse(result["success"])
        self.assertIn("文件不存在", result["error"])

    def test_write_to_directory_rejected(self):
        """不能把目录当作文件写入"""
        result = fops.write_file(str(self.base), content="x")
        self.assertFalse(result["success"])
        self.assertIn("不是文件", result["error"])


class TestCreateDirectory(unittest.TestCase):
    """测试 create_directory"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_create_new_directory(self):
        """创建全新目录"""
        target = self.base / "newdir"
        result = fops.create_directory(str(target))
        self.assertTrue(result["success"])
        self.assertTrue(result["created"])
        self.assertTrue(target.is_dir())

    def test_create_nested_directories(self):
        """级联创建多级目录"""
        target = self.base / "a" / "b" / "c"
        result = fops.create_directory(str(target))
        self.assertTrue(result["success"])
        self.assertTrue(target.is_dir())

    def test_already_exists_directory(self):
        """已存在的目录返回 created=False"""
        target = self.base / "already"
        target.mkdir()
        result = fops.create_directory(str(target))
        self.assertTrue(result["success"])
        self.assertFalse(result["created"])

    def test_path_conflicts_with_file(self):
        """路径上已有同名文件"""
        conflict = self.base / "conflict"
        conflict.write_text("x", encoding="utf-8")
        result = fops.create_directory(str(conflict))
        self.assertFalse(result["success"])
        self.assertIn("不是目录", result["error"])


class TestDeleteDirectory(unittest.TestCase):
    """测试 delete_directory"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_delete_empty_directory(self):
        """删除空目录"""
        d = self.base / "empty"
        d.mkdir()
        result = fops.delete_directory(str(d), force=False)
        self.assertTrue(result["success"])
        self.assertFalse(d.exists())

    def test_delete_nonempty_with_force(self):
        """force=True 删除非空目录"""
        d = self.base / "nonempty"
        d.mkdir()
        (d / "a.txt").write_text("x", encoding="utf-8")
        (d / "sub").mkdir()

        result = fops.delete_directory(str(d), force=True)
        self.assertTrue(result["success"])
        self.assertFalse(d.exists())
        self.assertTrue(result["was_non_empty"])
        self.assertTrue(result["force"])

    def test_delete_nonempty_without_force_rejected(self):
        """force=False 拒绝删除非空目录"""
        d = self.base / "nonempty"
        d.mkdir()
        (d / "a.txt").write_text("x", encoding="utf-8")

        result = fops.delete_directory(str(d), force=False)
        self.assertFalse(result["success"])
        self.assertIn("force=True", result["error"])
        self.assertTrue(d.exists())  # 目录应仍在

    def test_nonexistent_directory(self):
        """目录不存在"""
        result = fops.delete_directory(str(self.base / "ghost"))
        self.assertFalse(result["success"])
        self.assertIn("目录不存在", result["error"])

    def test_pass_file_as_directory(self):
        """把文件当作目录传入"""
        f = self.base / "f.txt"
        f.write_text("x", encoding="utf-8")
        result = fops.delete_directory(str(f))
        self.assertFalse(result["success"])
        self.assertIn("不是目录", result["error"])

    def test_cannot_delete_current_working_directory(self):
        """安全守卫：不能删除当前工作目录"""
        # 切换到测试目录
        original_cwd = os.getcwd()
        os.chdir(self.base)
        try:
            result = fops.delete_directory(str(self.base))
            self.assertFalse(result["success"])
            self.assertIn("当前工作目录", result["error"])
        finally:
            os.chdir(original_cwd)

    def test_cannot_delete_parent_of_cwd(self):
        """安全守卫：不能删除 cwd 的父目录"""
        child = self.base / "child"
        child.mkdir()
        original_cwd = os.getcwd()
        os.chdir(child)
        try:
            result = fops.delete_directory(str(self.base))
            self.assertFalse(result["success"])
            self.assertIn("上级目录", result["error"])
        finally:
            os.chdir(original_cwd)


class TestDeleteFile(unittest.TestCase):
    """测试 delete_file"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_delete_file_success(self):
        """正常删除文件"""
        f = self.base / "to_delete.txt"
        f.write_text("content", encoding="utf-8")
        size = f.stat().st_size

        result = fops.delete_file(str(f))
        self.assertTrue(result["success"])
        self.assertFalse(f.exists())
        self.assertEqual(result["deleted_file"], "to_delete.txt")
        self.assertEqual(result["file_size_bytes"], size)

    def test_nonexistent_file(self):
        """文件不存在"""
        result = fops.delete_file(str(self.base / "nope.txt"))
        self.assertFalse(result["success"])
        self.assertIn("文件不存在", result["error"])

    def test_delete_directory_rejected(self):
        """把目录当作文件删除时拒绝"""
        result = fops.delete_file(str(self.base))
        self.assertFalse(result["success"])
        self.assertIn("是目录不是文件", result["error"])


class TestRenameItem(unittest.TestCase):
    """测试 rename_item —— 新增的第 10 个工具"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_rename_file_success(self):
        """重命名文件"""
        old = self.base / "old.txt"
        old.write_text("hi", encoding="utf-8")
        result = fops.rename_item(str(old), "new.txt")
        self.assertTrue(result["success"])
        self.assertEqual(result["old_name"], "old.txt")
        self.assertEqual(result["new_name"], "new.txt")
        self.assertEqual(result["item_type"], "文件")
        self.assertFalse(old.exists())
        self.assertTrue((self.base / "new.txt").exists())
        self.assertEqual((self.base / "new.txt").read_text(encoding="utf-8"), "hi")

    def test_rename_directory_success(self):
        """重命名目录"""
        old = self.base / "old_dir"
        old.mkdir()
        (old / "child.txt").write_text("x", encoding="utf-8")

        result = fops.rename_item(str(old), "new_dir")
        self.assertTrue(result["success"])
        self.assertEqual(result["item_type"], "目录")
        self.assertFalse(old.exists())
        new = self.base / "new_dir"
        self.assertTrue(new.is_dir())
        self.assertTrue((new / "child.txt").exists())

    def test_nonexistent_source(self):
        """源路径不存在"""
        result = fops.rename_item(str(self.base / "ghost.txt"), "x.txt")
        self.assertFalse(result["success"])
        self.assertIn("不存在", result["error"])

    def test_empty_new_name_rejected(self):
        """新名称为空"""
        f = self.base / "a.txt"
        f.write_text("x", encoding="utf-8")
        result = fops.rename_item(str(f), "")
        self.assertFalse(result["success"])
        self.assertIn("不能为空", result["error"])

    def test_whitespace_new_name_rejected(self):
        """新名称全是空白"""
        f = self.base / "a.txt"
        f.write_text("x", encoding="utf-8")
        result = fops.rename_item(str(f), "   ")
        self.assertFalse(result["success"])

    def test_new_name_with_path_separator_rejected(self):
        """新名称含路径分隔符 —— 越权防护"""
        f = self.base / "a.txt"
        f.write_text("x", encoding="utf-8")
        result = fops.rename_item(str(f), "sub/b.txt")
        self.assertFalse(result["success"])
        self.assertIn("路径分隔符", result["error"])

    def test_rename_to_same_name_rejected(self):
        """新名称与原名相同"""
        f = self.base / "a.txt"
        f.write_text("x", encoding="utf-8")
        result = fops.rename_item(str(f), "a.txt")
        self.assertFalse(result["success"])
        self.assertIn("相同", result["error"])

    def test_target_already_exists_rejected(self):
        """目标已存在 —— 保守拒绝覆盖"""
        (self.base / "a.txt").write_text("A", encoding="utf-8")
        (self.base / "b.txt").write_text("B", encoding="utf-8")
        result = fops.rename_item(str(self.base / "a.txt"), "b.txt")
        self.assertFalse(result["success"])
        self.assertIn("已存在", result["error"])
        # 两个文件内容都应保持不变
        self.assertEqual((self.base / "a.txt").read_text(encoding="utf-8"), "A")
        self.assertEqual((self.base / "b.txt").read_text(encoding="utf-8"), "B")


class TestCallToolDispatcher(unittest.TestCase):
    """测试 call_tool 分发器逻辑"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_known_tool_invocation(self):
        """调用已知工具"""
        result = fops.call_tool("get_current_working_directory")
        self.assertTrue(result["success"])

    def test_unknown_tool_fails(self):
        """调用未知工具"""
        result = fops.call_tool("no_such_tool_xyz")
        self.assertFalse(result["success"])
        self.assertIn("未知工具", result["error"])

    def test_call_tool_with_positional_file_param(self):
        """通过 call_tool 调 create_file"""
        p = self.base / "via_tool.txt"
        result = fops.call_tool("create_file", file_path=str(p), content="hello")
        self.assertTrue(result["success"])
        self.assertTrue(p.exists())

    def test_bool_param_string_conversion(self):
        """force 参数字符串 'true' 应转为 bool True"""
        d = self.base / "nonempty"
        d.mkdir()
        (d / "a.txt").write_text("x", encoding="utf-8")

        result = fops.call_tool("delete_directory", dir_path=str(d), force="true")
        self.assertTrue(result["success"])

    def test_bool_param_false_via_string(self):
        """force='false' 转为 False"""
        d = self.base / "nonempty"
        d.mkdir()
        (d / "a.txt").write_text("x", encoding="utf-8")

        result = fops.call_tool("delete_directory", dir_path=str(d), force="false")
        self.assertFalse(result["success"])

    def test_missing_required_param(self):
        """缺少必需参数 -> 参数错误"""
        result = fops.call_tool("read_file")  # 缺少 file_path
        self.assertFalse(result["success"])
        self.assertIn("参数错误", result["error"])

    def test_tools_registry_complete(self):
        """TOOLS 注册表应包含全部 10 个工具"""
        self.assertEqual(len(fops.TOOLS), 10)
        expected = {
            "get_current_working_directory",
            "list_directory",
            "get_file_type",
            "read_file",
            "create_file",
            "write_file",
            "create_directory",
            "delete_directory",
            "delete_file",
            "rename_item",
        }
        self.assertEqual(set(fops.TOOLS.keys()), expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
