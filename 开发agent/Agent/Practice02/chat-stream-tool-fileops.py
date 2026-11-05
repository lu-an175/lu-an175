

# -*- coding: utf-8 -*-
"""
文件操作工具集合: chat-stream-tool-fileops.py
基于 chat-stream-tool-isLeapYear.py 模板开发，
新增9个本地文件操作的 function。
"""

import json
import os
import shutil
import mimetypes
from pathlib import Path


# ============ 工具函数定义 ============

def get_current_working_directory() -> dict:
    """
    1. 获取当前工作目录。
    
    Returns:
        dict: 包含当前工作目录路径的字典
    """
    try:
        cwd = os.getcwd()
        return {
            "success": True,
            "current_directory": cwd,
            "message": f"当前工作目录: {cwd}"
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def list_directory(path: str = ".") -> dict:
    """
    2. 列出指定目录下所有文件和子目录。
    
    Args:
        path: 要列出的目录路径，默认为当前目录
    
    Returns:
        dict: 包含目录内容的字典（文件列表 + 子目录列表）
    """
    try:
        target = Path(path).resolve()
        
        if not target.exists():
            return {"success": False, "error": f"路径不存在: {path}"}
        
        if not target.is_dir():
            return {"success": False, "error": f"不是目录: {path}"}
        
        files = []
        directories = []
        
        for item in target.iterdir():
            if item.is_file():
                files.append(item.name)
            elif item.is_dir():
                directories.append(item.name)
        
        return {
            "success": True,
            "path": str(target),
            "files": sorted(files),
            "directories": sorted(directories),
            "file_count": len(files),
            "directory_count": len(directories),
            "message": f"共 {len(files)} 个文件, {len(directories)} 个子目录"
        }
    except PermissionError:
        return {"success": False, "error": f"权限不足，无法访问: {path}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_file_type(file_path: str) -> dict:
    """
    3. 获取指定文件的文件类型。
    
    Args:
        file_path: 文件路径
    
    Returns:
        dict: 包含文件类型信息的字典
    """
    try:
        path = Path(file_path).resolve()
        
        if not path.exists():
            return {"success": False, "error": f"文件不存在: {file_path}"}
        
        if not path.is_file():
            return {"success": False, "error": f"不是文件: {file_path}"}
        
        # 获取文件扩展名
        extension = path.suffix.lower()
        
        # 获取 MIME 类型
        mime_type, _ = mimetypes.guess_type(str(path))
        
        # 常见文件类型映射
        type_map = {
            '.txt': '纯文本文件',
            '.py': 'Python 源代码',
            '.json': 'JSON 数据文件',
            '.xml': 'XML 数据文件',
            '.html': 'HTML 网页文件',
            '.css': 'CSS 样式文件',
            '.js': 'JavaScript 源代码',
            '.md': 'Markdown 文档',
            '.csv': 'CSV 数据文件',
            '.docx': 'Word 文档',
            '.xlsx': 'Excel 表格',
            '.pptx': 'PowerPoint 演示文稿',
            '.pdf': 'PDF 文档',
            '.jpg': 'JPEG 图片',
            '.jpeg': 'JPEG 图片',
            '.png': 'PNG 图片',
            '.gif': 'GIF 图片',
            '.bmp': 'BMP 图片',
            '.mp3': 'MP3 音频',
            '.mp4': 'MP4 视频',
            '.zip': 'ZIP 压缩包',
            '.rar': 'RAR 压缩包',
        }
        
        file_type = type_map.get(extension, '未知类型文件' if extension else '无扩展名文件')
        
        return {
            "success": True,
            "file_path": str(path),
            "file_name": path.name,
            "extension": extension,
            "file_type": file_type,
            "mime_type": mime_type or "未知",
            "size_bytes": path.stat().st_size
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def read_file(file_path: str) -> dict:
    """
    4. 获取指定文件的内容（仅支持纯文本格式文件）。
    
    Args:
        file_path: 文件路径
    
    Returns:
        dict: 包含文件内容的字典
    """
    try:
        path = Path(file_path).resolve()
        
        if not path.exists():
            return {"success": False, "error": f"文件不存在: {file_path}"}
        
        if not path.is_file():
            return {"success": False, "error": f"不是文件: {file_path}"}
        
        # 检查是否为二进制文件（尝试读取前几个字节）
        with open(path, 'rb') as f:
            chunk = f.read(8192)
            if b'\x00' in chunk:
                return {
                    "success": False,
                    "error": "不支持读取二进制文件，仅支持纯文本格式文件"
                }
        
        # 读取文本内容
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        lines = content.split('\n')
        
        return {
            "success": True,
            "file_path": str(path),
            "file_name": path.name,
            "size_bytes": path.stat().st_size,
            "line_count": len(lines),
            "char_count": len(content),
            "content": content,
            "message": f"读取成功，共 {len(lines)} 行"
        }
    except UnicodeDecodeError:
        # 尝试用其他编码
        try:
            with open(path, 'r', encoding='gbk') as f:
                content = f.read()
            lines = content.split('\n')
            return {
                "success": True,
                "file_path": str(path),
                "file_name": path.name,
                "size_bytes": path.stat().st_size,
                "line_count": len(lines),
                "char_count": len(content),
                "content": content,
                "encoding": "gbk",
                "message": f"读取成功 (GBK编码)，共 {len(lines)} 行"
            }
        except Exception as e:
            return {"success": False, "error": f"文件编码无法识别: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def create_file(file_path: str, content: str = "") -> dict:
    """
    5. 创建指定的目录和文件名创建新文件。
    
    Args:
        file_path: 文件路径（可包含目录）
        content: 文件初始内容，默认为空
    
    Returns:
        dict: 包含创建结果的字典
    """
    try:
        path = Path(file_path)
        
        # 如果路径中有目录，先创建目录
        if path.parent != Path('.') and not path.parent.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
        
        # 检查文件是否已存在
        if path.exists():
            return {"success": False, "error": f"文件已存在: {file_path}"}
        
        # 创建文件并写入内容
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        return {
            "success": True,
            "file_path": str(path.resolve()),
            "created": True,
            "message": f"文件创建成功: {path}"
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def write_file(file_path: str, content: str, mode: str = "overwrite") -> dict:
    """
    6. 编辑指定文件的内容（仅支持纯文本格式文件）。
    
    Args:
        file_path: 文件路径
        content: 要写入的新内容
        mode: 写入模式，"overwrite"(覆盖) 或 "append"(追加)，默认为 overwrite
    
    Returns:
        dict: 包含编辑结果的字典
    """
    try:
        path = Path(file_path).resolve()
        
        if not path.exists():
            return {"success": False, "error": f"文件不存在: {file_path}"}
        
        if not path.is_file():
            return {"success": False, "error": f"不是文件: {file_path}"}
        
        if mode == "append":
            # 检查是否有换行符（追加模式下自动补换行）
            with open(path, 'a', encoding='utf-8') as f:
                if content and not content.startswith('\n'):
                    f.write('\n')
                f.write(content)
            action = "追加"
        else:
            # 覆盖模式
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            action = "覆盖"
        
        return {
            "success": True,
            "file_path": str(path),
            "mode": mode,
            "action": action,
            "message": f"文件{action}成功"
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def create_directory(dir_path: str) -> dict:
    """
    7. 创建新目录。
    
    Args:
        dir_path: 要创建的目录路径
    
    Returns:
        dict: 包含创建结果的字典
    """
    try:
        path = Path(dir_path).resolve()
        
        if path.exists():
            if path.is_dir():
                return {
                    "success": True,
                    "directory_path": str(path),
                    "created": False,
                    "message": f"目录已存在: {path}"
                }
            else:
                return {"success": False, "error": f"路径已存在但不是目录: {path}"}
        
        # 创建目录（包括父目录）
        path.mkdir(parents=True, exist_ok=True)
        
        return {
            "success": True,
            "directory_path": str(path),
            "created": True,
            "message": f"目录创建成功: {path}"
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def delete_directory(dir_path: str, force: bool = True) -> dict:
    """
    8. 删除目录（非空）。
    
    Args:
        dir_path: 要删除的目录路径
        force: 是否强制删除非空目录，默认为 True
    
    Returns:
        dict: 包含删除结果的字典
    """
    try:
        path = Path(dir_path).resolve()
        
        if not path.exists():
            return {"success": False, "error": f"目录不存在: {dir_path}"}
        
        if not path.is_dir():
            return {"success": False, "error": f"不是目录: {dir_path}"}
        
        # 不能删除当前工作目录本身
        cwd = Path(os.getcwd()).resolve()
        if path == cwd:
            return {"success": False, "error": "不能删除当前工作目录"}
        # 也不能删除 cwd 的父目录或祖先目录（防止目录被删导致当前路径失效）
        if path in cwd.parents:
            return {"success": False, "error": "不能删除当前工作目录的上级目录"}
        
        # 检查目录是否为空
        has_contents = any(path.iterdir())
        
        if has_contents and not force:
            return {
                "success": False,
                "error": f"目录非空，使用 force=True 强制删除",
                "has_contents": True
            }
        
        # 删除目录
        if force:
            shutil.rmtree(path)
        else:
            path.rmdir()
        
        return {
            "success": True,
            "deleted_path": str(path),
            "force": force,
            "was_non_empty": has_contents,
            "message": f"目录删除成功: {path}"
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def delete_file(file_path: str) -> dict:
    """
    9. 删除文件。
    
    Args:
        file_path: 要删除的文件路径
    
    Returns:
        dict: 包含删除结果的字典
    """
    try:
        path = Path(file_path).resolve()
        
        if not path.exists():
            return {"success": False, "error": f"文件不存在: {file_path}"}
        
        if path.is_dir():
            return {"success": False, "error": f"是目录不是文件，请使用 delete_directory: {file_path}"}
        
        # 记录文件信息
        file_name = path.name
        file_size = path.stat().st_size
        
        # 删除文件
        path.unlink()
        
        return {
            "success": True,
            "deleted_file": file_name,
            "deleted_path": str(path),
            "file_size_bytes": file_size,
            "message": f"文件删除成功: {file_name}"
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def rename_item(source_path: str, new_name: str) -> dict:
    """
    10. 重命名文件或目录。
    
    Args:
        source_path: 源文件或目录路径
        new_name: 新名称（只提供文件名/目录名，不包含路径）
    
    Returns:
        dict: 包含重命名结果的字典
    """
    try:
        source = Path(source_path).resolve()
        
        if not source.exists():
            return {"success": False, "error": f"源路径不存在: {source_path}"}
        
        if not new_name or not new_name.strip():
            return {"success": False, "error": "新名称不能为空"}
        
        # 禁止路径分隔符，防止越权
        if os.sep in new_name or (os.altsep and os.altsep in new_name):
            return {"success": False, "error": "新名称不能包含路径分隔符"}
        
        target = source.parent / new_name
        
        # 同名
        if target == source:
            return {"success": False, "error": "新名称与原名称相同，无需重命名"}
        
        # 目标已存在 -> 拒绝覆盖，保持保守安全策略
        if target.exists():
            return {"success": False, "error": f"目标已存在: {target}"}
        
        old_name = source.name
        is_dir = source.is_dir()
        
        # 使用 resolve() 拿到目标绝对路径；跨盘符/文件系统时 Path.rename 可能失败，用 shutil.move 兜底
        try:
            source.rename(target)
        except OSError:
            shutil.move(str(source), str(target))
        
        return {
            "success": True,
            "old_path": str(source),
            "new_path": str(target.resolve()),
            "old_name": old_name,
            "new_name": new_name,
            "item_type": "目录" if is_dir else "文件",
            "message": f"{'目录' if is_dir else '文件'}重命名成功: {old_name} -> {new_name}"
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============ 工具注册表 ============

TOOLS = {
    "get_current_working_directory": {
        "func": get_current_working_directory,
        "description": "获取当前工作目录",
        "parameters": {}
    },
    "list_directory": {
        "func": list_directory,
        "description": "列出指定目录下所有文件和子目录",
        "parameters": {
            "path": "str: 目录路径（可选，默认为当前目录）"
        }
    },
    "get_file_type": {
        "func": get_file_type,
        "description": "获取指定文件的文件类型",
        "parameters": {
            "file_path": "str: 文件路径（必需）"
        }
    },
    "read_file": {
        "func": read_file,
        "description": "获取指定文件的内容（仅支持纯文本格式文件）",
        "parameters": {
            "file_path": "str: 文件路径（必需）"
        }
    },
    "create_file": {
        "func": create_file,
        "description": "创建指定的目录和文件名创建新文件",
        "parameters": {
            "file_path": "str: 文件路径（必需）",
            "content": "str: 文件初始内容（可选，默认为空）"
        }
    },
    "write_file": {
        "func": write_file,
        "description": "编辑指定文件的内容（仅支持纯文本格式文件）",
        "parameters": {
            "file_path": "str: 文件路径（必需）",
            "content": "str: 要写入的新内容（必需）",
            "mode": "str: 写入模式 'overwrite' 或 'append'（可选，默认 overwrite）"
        }
    },
    "create_directory": {
        "func": create_directory,
        "description": "创建新目录",
        "parameters": {
            "dir_path": "str: 目录路径（必需）"
        }
    },
    "delete_directory": {
        "func": delete_directory,
        "description": "删除目录（非空）",
        "parameters": {
            "dir_path": "str: 目录路径（必需）",
            "force": "bool: 是否强制删除非空目录（可选，默认 True）"
        }
    },
    "delete_file": {
        "func": delete_file,
        "description": "删除文件",
        "parameters": {
            "file_path": "str: 文件路径（必需）"
        }
    },
    "rename_item": {
        "func": rename_item,
        "description": "重命名文件或目录",
        "parameters": {
            "source_path": "str: 源文件或目录路径（必需）",
            "new_name": "str: 新名称，只提供名称不含路径（必需）"
        }
    }
}


# ============ 工具调用入口 ============

def call_tool(tool_name: str, **kwargs) -> dict:
    """
    调用指定的工具函数。
    
    Args:
        tool_name: 工具名称
        **kwargs: 传递给工具的参数
    
    Returns:
        dict: 工具执行结果
    """
    if tool_name not in TOOLS:
        return {"success": False, "error": f"未知工具: {tool_name}"}
    
    tool_info = TOOLS[tool_name]
    
    # 类型转换辅助
    converted_kwargs = {}
    for key, value in kwargs.items():
        param_type = tool_info["parameters"].get(key, "")
        if "bool" in param_type.lower():
            converted_kwargs[key] = value.lower() in ('true', '1', 'yes') if isinstance(value, str) else bool(value)
        elif "int" in param_type.lower():
            try:
                converted_kwargs[key] = int(value)
            except (ValueError, TypeError):
                converted_kwargs[key] = value
        else:
            converted_kwargs[key] = value
    
    try:
        result = tool_info["func"](**converted_kwargs)
        return result
    except TypeError as e:
        return {"success": False, "error": f"参数错误: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============ 交互式主程序 ============

def show_tool_list():
    """显示所有可用工具"""
    print("=" * 60)
    print("📋 可用文件操作工具列表:")
    print("-" * 60)
    for i, (name, info) in enumerate(TOOLS.items(), 1):
        print(f"  {i}. {name}")
        print(f"     📝 {info['description']}")
        if info['parameters']:
            print(f"     🔧 参数:")
            for param, desc in info['parameters'].items():
                print(f"        {param}: {desc}")
        print()
    print("=" * 60)


def main():
    """交互式主程序入口"""
    print("=" * 60)
    print("🚀 文件操作工具 (File Operations Tool)")
    print("=" * 60)
    print()
    
    show_tool_list()
    
    print("\n💡 使用说明:")
    print("  - 输入工具名称和参数来调用工具")
    print("  - 格式: 工具名 参数1=值1 参数2=值2")
    print("  - 输入 'help' 查看工具列表")
    print("  - 输入 'q' 退出程序")
    print()
    
    while True:
        try:
            print("\n请输入工具调用:")
            user_input = input("> ").strip()
            
            if user_input.lower() == 'q':
                print("👋 退出程序")
                break
            
            if user_input.lower() == 'help':
                show_tool_list()
                continue
            
            if not user_input:
                continue
            
            # 解析输入
            parts = user_input.split()
            if len(parts) < 1:
                print("❌ 输入格式错误")
                continue
            
            tool_name = parts[0]
            params = {}
            
            for part in parts[1:]:
                if '=' in part:
                    key, val = part.split('=', 1)
                    params[key] = val
                else:
                    # 如果没有 =，可能是位置参数（用于简单命令）
                    pass
            
            # 调用工具
            print(f"\n🔨 调用工具: {tool_name}")
            if params:
                print(f"   参数: {params}")
            
            result = call_tool(tool_name, **params)
            
            print(f"\n{'✅ 结果:' if result.get('success') else '❌ 结果:'}")
            print(json.dumps(result, ensure_ascii=False, indent=2))
            
        except KeyboardInterrupt:
            print("\n👋 退出程序")
            break
        except Exception as e:
            print(f"❌ 错误: {e}")


# ============ 快速测试 ============

def run_demo():
    """运行演示，测试所有9个功能"""
    print("=" * 60)
    print("🧪 文件操作工具 - 功能演示测试")
    print("=" * 60)
    
    test_dir = "./demo_test"
    test_file = f"{test_dir}/test.txt"
    
    # 1. 获取当前工作目录
    print("\n【1/9】获取当前工作目录")
    r = call_tool("get_current_working_directory")
    print(json.dumps(r, ensure_ascii=False, indent=2))
    
    # 2. 创建测试目录
    print("\n【7/9】创建新目录")
    r = call_tool("create_directory", dir_path=test_dir)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    
    # 5. 创建测试文件
    print("\n【5/9】创建新文件")
    r = call_tool("create_file", file_path=test_file, content="Hello World!\n这是一个测试文件。\n")
    print(json.dumps(r, ensure_ascii=False, indent=2))
    
    # 3. 获取文件类型
    print("\n【3/9】获取文件类型")
    r = call_tool("get_file_type", file_path=test_file)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    
    # 4. 读取文件内容
    print("\n【4/9】读取文件内容")
    r = call_tool("read_file", file_path=test_file)
    if r.get('success'):
        # 简化显示，不打印完整内容
        r_display = {k: v for k, v in r.items() if k != 'content'}
        r_display['content_preview'] = r['content'][:50] + '...' if len(r['content']) > 50 else r['content']
        print(json.dumps(r_display, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    
    # 6. 编辑文件内容（追加模式）
    print("\n【6/9】编辑文件内容（追加）")
    r = call_tool("write_file", file_path=test_file, content="追加的新内容！", mode="append")
    print(json.dumps(r, ensure_ascii=False, indent=2))
    
    # 2. 列出目录
    print("\n【2/9】列出目录内容")
    r = call_tool("list_directory", path=test_dir)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    
    # 9. 删除文件
    print("\n【9/9】删除文件")
    r = call_tool("delete_file", file_path=test_file)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    
    # 8. 删除目录
    print("\n【8/9】删除目录")
    r = call_tool("delete_directory", dir_path=test_dir)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    
    print("\n" + "=" * 60)
    print("✅ 所有9个功能演示完毕！")
    print("=" * 60)


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "--demo":
        run_demo()
    else:
        main()
