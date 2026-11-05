# -*- coding: utf-8 -*-
"""
xAgent.core.tools —— 13 个纯函数式工具（10 个文件操作 + 联网搜索 + 网页正文提取 + CLI 执行）。

设计原则：
  1. 只依赖标准库（os / pathlib / shutil / mimetypes / json / subprocess / shlex / urllib）
     联网能力：curl（系统命令）+ trafilatura（第三方，可选依赖，缺失时给出明确提示）
  2. 不 import 任何 UI 相关模块
  3. 只做一件事：接收参数 -> 执行操作 -> 返回 dict
     （registry 层会把 dict 包成 ToolResult）
  4. 错误处理统一返回 {"success": False, "error": "..."}，不抛异常到上层
"""

import json
import mimetypes
import os
import shlex
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from .config import (
    CONFIG_INI,
    QIANFAN_SEARCH_MODEL,
    QIANFAN_SEARCH_URL,
    read_search_api_key,
)


# ============ 1. get_current_working_directory ============

def get_current_working_directory() -> dict:
    """获取当前工作目录。"""
    try:
        cwd = os.getcwd()
        return {
            "success": True,
            "current_directory": cwd,
            "message": f"当前工作目录: {cwd}",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============ 2. list_directory ============

def list_directory(path: str = ".") -> dict:
    """列出指定目录下所有文件和子目录。"""
    try:
        target = Path(path).resolve()

        if not target.exists():
            return {"success": False, "error": f"路径不存在: {path}"}
        if not target.is_dir():
            return {"success": False, "error": f"不是目录: {path}"}

        files, directories = [], []
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
            "message": f"共 {len(files)} 个文件, {len(directories)} 个子目录",
        }
    except PermissionError:
        return {"success": False, "error": f"权限不足，无法访问: {path}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============ 3. get_file_type ============

def get_file_type(file_path: str) -> dict:
    """获取指定文件的文件类型。"""
    try:
        path = Path(file_path).resolve()

        if not path.exists():
            return {"success": False, "error": f"文件不存在: {file_path}"}
        if not path.is_file():
            return {"success": False, "error": f"不是文件: {file_path}"}

        extension = path.suffix.lower()
        mime_type, _ = mimetypes.guess_type(str(path))

        type_map = {
            '.txt': '纯文本文件', '.py': 'Python 源代码',
            '.json': 'JSON 数据文件', '.xml': 'XML 数据文件',
            '.html': 'HTML 网页文件', '.css': 'CSS 样式文件',
            '.js': 'JavaScript 源代码', '.md': 'Markdown 文档',
            '.csv': 'CSV 数据文件', '.docx': 'Word 文档',
            '.xlsx': 'Excel 表格', '.pptx': 'PowerPoint 演示文稿',
            '.pdf': 'PDF 文档', '.jpg': 'JPEG 图片',
            '.jpeg': 'JPEG 图片', '.png': 'PNG 图片',
            '.gif': 'GIF 图片', '.bmp': 'BMP 图片',
            '.mp3': 'MP3 音频', '.mp4': 'MP4 视频',
            '.zip': 'ZIP 压缩包', '.rar': 'RAR 压缩包',
        }
        file_type = type_map.get(
            extension,
            '未知类型文件' if extension else '无扩展名文件'
        )

        return {
            "success": True,
            "file_path": str(path),
            "file_name": path.name,
            "extension": extension,
            "file_type": file_type,
            "mime_type": mime_type or "未知",
            "size_bytes": path.stat().st_size,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============ 4. read_file ============

def read_file(file_path: str) -> dict:
    """读取文件内容（仅支持纯文本格式文件）。"""
    try:
        path = Path(file_path).resolve()

        if not path.exists():
            return {"success": False, "error": f"文件不存在: {file_path}"}
        if not path.is_file():
            return {"success": False, "error": f"不是文件: {file_path}"}

        with open(path, 'rb') as f:
            chunk = f.read(8192)
            if b'\x00' in chunk:
                return {
                    "success": False,
                    "error": "不支持读取二进制文件，仅支持纯文本格式文件",
                }

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
            "message": f"读取成功，共 {len(lines)} 行",
        }
    except UnicodeDecodeError:
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
                "message": f"读取成功 (GBK编码)，共 {len(lines)} 行",
            }
        except Exception as e:
            return {"success": False, "error": f"文件编码无法识别: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============ 5. create_file ============

def create_file(file_path: str, content: str = "") -> dict:
    """创建新文件（自动创建父目录链）。"""
    try:
        path = Path(file_path)

        if path.parent != Path('.') and not path.parent.exists():
            path.parent.mkdir(parents=True, exist_ok=True)

        if path.exists():
            return {"success": False, "error": f"文件已存在: {file_path}"}

        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)

        return {
            "success": True,
            "file_path": str(path.resolve()),
            "created": True,
            "message": f"文件创建成功: {path}",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============ 6. write_file ============

def write_file(file_path: str, content: str, mode: str = "overwrite") -> dict:
    """编辑文件内容（overwrite / append）。"""
    try:
        path = Path(file_path).resolve()

        if not path.exists():
            return {"success": False, "error": f"文件不存在: {file_path}"}
        if not path.is_file():
            return {"success": False, "error": f"不是文件: {file_path}"}

        if mode == "append":
            with open(path, 'a', encoding='utf-8') as f:
                if content and not content.startswith('\n'):
                    f.write('\n')
                f.write(content)
            action = "追加"
        else:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            action = "覆盖"

        return {
            "success": True,
            "file_path": str(path),
            "mode": mode,
            "action": action,
            "message": f"文件{action}成功",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============ 7. create_directory ============

def create_directory(dir_path: str) -> dict:
    """创建新目录（支持级联创建）。"""
    try:
        path = Path(dir_path).resolve()

        if path.exists():
            if path.is_dir():
                return {
                    "success": True,
                    "directory_path": str(path),
                    "created": False,
                    "message": f"目录已存在: {path}",
                }
            else:
                return {"success": False, "error": f"路径已存在但不是目录: {path}"}

        path.mkdir(parents=True, exist_ok=True)
        return {
            "success": True,
            "directory_path": str(path),
            "created": True,
            "message": f"目录创建成功: {path}",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============ 8. delete_directory ============

def delete_directory(dir_path: str, force: bool = True) -> dict:
    """删除目录（force=True 可删除非空目录）。"""
    try:
        path = Path(dir_path).resolve()

        if not path.exists():
            return {"success": False, "error": f"目录不存在: {dir_path}"}
        if not path.is_dir():
            return {"success": False, "error": f"不是目录: {dir_path}"}

        cwd = Path(os.getcwd()).resolve()
        if path == cwd:
            return {"success": False, "error": "不能删除当前工作目录"}
        if path in cwd.parents:
            return {"success": False, "error": "不能删除当前工作目录的上级目录"}

        has_contents = any(path.iterdir())

        if has_contents and not force:
            return {
                "success": False,
                "error": "目录非空，使用 force=True 强制删除",
                "has_contents": True,
            }

        if force:
            shutil.rmtree(path)
        else:
            path.rmdir()

        return {
            "success": True,
            "deleted_path": str(path),
            "force": force,
            "was_non_empty": has_contents,
            "message": f"目录删除成功: {path}",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============ 9. delete_file ============

def delete_file(file_path: str) -> dict:
    """删除文件。"""
    try:
        path = Path(file_path).resolve()

        if not path.exists():
            return {"success": False, "error": f"文件不存在: {file_path}"}
        if path.is_dir():
            return {"success": False, "error": f"是目录不是文件，请使用 delete_directory: {file_path}"}

        file_name = path.name
        file_size = path.stat().st_size
        path.unlink()

        return {
            "success": True,
            "deleted_file": file_name,
            "deleted_path": str(path),
            "file_size_bytes": file_size,
            "message": f"文件删除成功: {file_name}",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============ 10. rename_item ============

def rename_item(source_path: str, new_name: str) -> dict:
    """重命名文件或目录（保守拒绝覆盖）。"""
    try:
        source = Path(source_path).resolve()

        if not source.exists():
            return {"success": False, "error": f"源路径不存在: {source_path}"}
        if not new_name or not new_name.strip():
            return {"success": False, "error": "新名称不能为空"}
        if os.sep in new_name or (os.altsep and os.altsep in new_name):
            return {"success": False, "error": "新名称不能包含路径分隔符"}

        target = source.parent / new_name

        if target == source:
            return {"success": False, "error": "新名称与原名称相同，无需重命名"}
        if target.exists():
            return {"success": False, "error": f"目标已存在: {target}"}

        old_name = source.name
        is_dir = source.is_dir()

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
            "message": f"{'目录' if is_dir else '文件'}重命名成功: {old_name} -> {new_name}",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============ 11. search_web ============

def _search_error(message: str, **extra) -> dict:
    """搜索失败的统一返回结构。"""
    return {"success": False, "error": message, **extra}


def search_web(query: str, top_k: int = 10) -> dict:
    """
    联网搜索：调用百度千帆「智能搜索生成」API，返回摘要与参考来源。

    返回：
        {
            "success": True,
            "query": "...",
            "summary": "模型根据搜索结果生成的总结",
            "references": [{"id","title","url","site","date","snippet"}],
            "reference_count": 3,
            "message": "搜索完成：..."
        }
    """
    if not query or not query.strip():
        return _search_error("搜索关键词 query 不能为空")

    query = query.strip()

    # ---------- 1. 读取配置 ----------
    if not CONFIG_INI.exists():
        return _search_error(
            f"缺少配置文件：{CONFIG_INI}。"
            f"请在 [llm] 段落下配置 api_key（旧格式 [qianfan] baidu_qianfan_api_key 仍兼容）。"
        )

    try:
        api_key = read_search_api_key()
    except RuntimeError as exc:
        return _search_error(str(exc))

    if not api_key:
        return _search_error(
            f"配置项缺失：{CONFIG_INI} 中 [llm] api_key 为空。"
            f"请填写千帆 API Key 后重试。"
        )

    # ---------- 2. 构造请求 ----------
    payload = {
        "messages": [{"role": "user", "content": query}],
        "model": QIANFAN_SEARCH_MODEL,
        "search_source": "baidu_search_v2",
        "resource_type_filter": [{"type": "web", "top_k": int(top_k)}],
        "search_mode": "required",
        "stream": False,
        "enable_corner_markers": True,
    }
    request = urllib.request.Request(
        QIANFAN_SEARCH_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    # ---------- 3. 发起请求 ----------
    try:
        with urllib.request.urlopen(request, timeout=60) as resp:
            raw = resp.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "ignore")
        code, message = _parse_api_error(detail)
        hint = f"（{code}）{message}" if code or message else detail[:200]
        return _search_error(f"搜索 API 请求失败：HTTP {exc.code} {exc.reason} {hint}")
    except urllib.error.URLError as exc:
        return _search_error(f"网络请求失败：{exc.reason}")
    except TimeoutError:
        return _search_error("网络请求超时：60 秒内未收到搜索 API 响应")
    except OSError as exc:
        return _search_error(f"网络请求失败：{exc}")
    except Exception as exc:
        return _search_error(f"搜索请求异常：{exc}")

    # ---------- 4. 解析响应 ----------
    try:
        body = json.loads(raw)
    except json.JSONDecodeError:
        snippet = raw[:200].replace("\n", " ")
        return _search_error(f"搜索 API 返回内容无法解析为 JSON：{snippet}")

    if not isinstance(body, dict):
        return _search_error("搜索 API 返回结构异常：顶层不是对象")

    # API 业务错误（HTTP 200 但带 code/message）
    if body.get("code") and not body.get("choices"):
        return _search_error(
            f"搜索 API 返回错误（{body.get('code')}）：{body.get('message', '未知错误')}"
        )

    choices = body.get("choices") or []
    if not choices:
        return _search_error("搜索 API 未返回结果（choices 为空）")

    message_obj = choices[0].get("message") or {}
    summary = (message_obj.get("content") or "").strip()
    if not summary:
        return _search_error("搜索 API 未返回摘要内容（choices[0].message.content 为空）")

    references = []
    for ref in body.get("references") or []:
        if not isinstance(ref, dict):
            continue
        url = (ref.get("url") or "").strip()
        title = (ref.get("title") or "").strip()
        if not url and not title:
            continue
        references.append({
            "id": str(ref.get("id", "")),
            "title": title or url,
            "url": url,
            "site": (ref.get("website") or "").strip(),
            "date": (ref.get("date") or "").strip(),
            "snippet": (ref.get("content") or "").strip()[:200],
        })

    return {
        "success": True,
        "query": query,
        "summary": summary,
        "references": references,
        "reference_count": len(references),
        "message": f"搜索完成：找到 {len(references)} 条参考来源",
    }


def _parse_api_error(detail: str) -> tuple[str, str]:
    """从 API 错误响应体中提取 code / message。"""
    try:
        data = json.loads(detail)
    except (json.JSONDecodeError, TypeError):
        return "", ""
    if not isinstance(data, dict):
        return "", ""
    error = data.get("error")
    if isinstance(error, dict):
        return str(error.get("code", "")), str(error.get("message", ""))
    return str(data.get("code", "")), str(data.get("message", ""))


# ============ 12. fetch_web ============

_CURL_TIMEOUT = 30            # 单次网页下载总超时（秒）
_CURL_CONNECT_TIMEOUT = 10    # 连接阶段超时（秒）
_MAX_MARKDOWN_CHARS = 20000   # 正文上限，超出截断以节省上下文 Token
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def _fetch_error(message: str) -> dict:
    """网页抓取失败的统一返回结构。"""
    return {"success": False, "error": message}


def _load_trafilatura():
    """延迟导入 trafilatura，未安装时返回 None（不阻塞其他工具）。"""
    try:
        import trafilatura
    except ImportError:
        return None
    return trafilatura


def _decode_bytes(raw: bytes) -> str:
    """字节流解码：优先 UTF-8，失败后按 GB18030（兼容 GBK/GB2312）兜底。"""
    for encoding in ("utf-8", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "ignore")


def _extract_title(trafilatura, html: str, url: str) -> str:
    """提取网页标题，失败时返回空字符串（不影响正文返回）。"""
    try:
        meta = trafilatura.extract_metadata(html, default_url=url)
    except Exception:
        return ""
    if meta is None:
        return ""
    return (getattr(meta, "title", "") or "").strip()


def fetch_web(url: str) -> dict:
    """
    获取网页正文：curl 下载 HTML → trafilatura 提取正文 → Markdown。

    参数：
        url: 网页地址，必须以 http:// 或 https:// 开头

    返回：
        {
            "success": True,
            "url": "https://...",
            "title": "网页标题",
            "markdown": "正文 Markdown（保留标题/段落/列表/表格/链接）",
            "char_count": 1234,
            "truncated": False,
            "message": "已获取网页正文：..."
        }
    """
    if not url or not url.strip():
        return _fetch_error("网页地址 url 不能为空")

    url = url.strip()
    if not url.lower().startswith(("http://", "https://")):
        return _fetch_error(
            f"不支持的 URL 协议：{url}（仅支持 http:// 或 https://）"
        )

    # ---------- 1. 调用本地 curl 下载 HTML（参数列表，不使用 shell） ----------
    curl_path = shutil.which("curl")
    if not curl_path:
        return _fetch_error("未找到 curl 命令，请确认系统已安装 curl 并加入 PATH")

    command = [
        curl_path,
        "--location",                          # 跟随重定向
        "--compressed",                        # 自动解压
        "--fail",                              # 4xx/5xx 视为失败
        "--silent",
        "--show-error",
        "--max-time", str(_CURL_TIMEOUT),
        "--connect-timeout", str(_CURL_CONNECT_TIMEOUT),
        "--user-agent", _USER_AGENT,
        "--header", "Accept-Language: zh-CN,zh;q=0.9,en;q=0.8",
        url,
    ]

    try:
        # 注意：参数列表 + shell=False（默认），避免命令注入
        proc = subprocess.run(
            command,
            capture_output=True,
            timeout=_CURL_TIMEOUT + 10,
            check=False,
        )
    except FileNotFoundError:
        return _fetch_error(f"未找到 curl 可执行文件：{curl_path}")
    except subprocess.TimeoutExpired:
        return _fetch_error(f"网页访问超时：超过 {_CURL_TIMEOUT} 秒未收到响应")
    except OSError as exc:
        return _fetch_error(f"调用 curl 失败：{exc}")

    stdout = proc.stdout or b""
    stderr = (proc.stderr or b"").decode("utf-8", "ignore").strip()

    if proc.returncode != 0:
        detail = stderr[:300] if stderr else "无错误输出"
        return _fetch_error(
            f"网页访问失败（curl 退出码 {proc.returncode}）：{detail}"
        )
    if not stdout:
        detail = f"；{stderr[:200]}" if stderr else ""
        return _fetch_error(f"网页访问失败：curl 未返回任何内容{detail}")

    html = _decode_bytes(stdout)

    # ---------- 2. trafilatura 提取正文并转 Markdown ----------
    trafilatura = _load_trafilatura()
    if trafilatura is None:
        return _fetch_error(
            "缺少依赖 trafilatura：请执行 py -3.12 -m pip install trafilatura 后重试"
        )

    extract_kwargs = {
        "url": url,
        "output_format": "markdown",
        "include_links": True,        # 保留链接
        "include_tables": True,       # 保留表格
        "include_formatting": True,   # 保留标题/加粗/列表等
        "include_comments": False,    # 去掉评论
        "include_images": False,      # 去掉图片，减少 Token
    }
    try:
        markdown = trafilatura.extract(html, favor_precision=True, **extract_kwargs)
        if not markdown:
            # 精确模式提取不到时，放宽召回再试一次
            markdown = trafilatura.extract(html, favor_recall=True, **extract_kwargs)
    except Exception as exc:
        hint = "" if "<html" in html.lower() else "（返回内容不是 HTML 页面）"
        return _fetch_error(f"HTML 解析失败{hint}：{exc}")

    markdown = (markdown or "").strip()
    if not markdown:
        return _fetch_error(
            "正文提取失败：未能从该页面提取到正文"
            "（可能为动态渲染页面或仅有图片/脚本），建议改用 searchWeb 获取摘要"
        )

    title = _extract_title(trafilatura, html, url)

    truncated = len(markdown) > _MAX_MARKDOWN_CHARS
    if truncated:
        markdown = (
            markdown[:_MAX_MARKDOWN_CHARS]
            + "\n\n…（正文过长已截断，完整内容请查看原网页）"
        )

    return {
        "success": True,
        "url": url,
        "title": title,
        "markdown": markdown,
        "char_count": len(markdown),
        "truncated": truncated,
        "message": (
            f"已获取网页正文：{title or url}"
            f"（{len(markdown)} 字符{', 已截断' if truncated else ''}）"
        ),
    }


# ============ 13. run_cli ============

_CLI_TIMEOUT = 30          # 默认超时（秒）
_CLI_MAX_TIMEOUT = 120     # 允许的最大超时（秒）
_CLI_MAX_STREAM_CHARS = 8000   # stdout / stderr 各自的最大字符数


def _cli_error(message: str, **extra) -> dict:
    """CLI 执行失败的统一返回结构。"""
    return {"success": False, "error": message, **extra}


def _split_args(value: str) -> list:
    """把字符串形式的参数转成列表：优先按 JSON 数组解析，其次按 shell 规则切分。"""
    text = value.strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
        except json.JSONDecodeError:
            pass
    try:
        return shlex.split(text)
    except ValueError:
        return text.split()


def _truncate_stream(text: str, limit: int | None = None) -> tuple[str, bool]:
    """截断过长输出，返回 (文本, 是否截断)。"""
    limit = _CLI_MAX_STREAM_CHARS if limit is None else limit
    if len(text) <= limit:
        return text, False
    return (
        text[:limit] + f"\n…（输出过长已截断，原始共 {len(text)} 字符，仅保留前 {limit} 字符）",
        True,
    )


def run_cli(command: str, args=None, timeout: int = _CLI_TIMEOUT) -> dict:
    """
    执行本地命令行程序（参数列表 + shell=False，不做命令字符串拼接）。

    参数：
        command: 可执行程序名称或路径，如 python、git、curl
        args:    参数列表，如 ["-c", "print(1)"]；也接受 JSON 数组字符串
        timeout: 超时秒数，1-120，默认 30

    返回：
        {
            "success": True/False,
            "command": "git",
            "args": ["status"],
            "exitcode": 0,
            "stdout": "标准输出（过长会截断）",
            "stderr": "标准错误（过长会截断）",
            "stdout_truncated": False,
            "stderr_truncated": False,
            "elapsed_ms": 123,
            "message": "命令执行完成（退出码 0，耗时 123 ms）"
        }
    """
    if not command or not str(command).strip():
        return _cli_error("程序名称 command 不能为空")

    command = str(command).strip()

    # ---------- 1. 参数归一化（一律转成列表，绝不拼成字符串） ----------
    if args is None:
        arg_list: list = []
    elif isinstance(args, str):
        arg_list = _split_args(args)
    elif isinstance(args, (list, tuple)):
        arg_list = [str(item) for item in args]
    else:
        return _cli_error(f"参数 args 必须是列表，实际收到：{type(args).__name__}")

    try:
        limit = int(timeout)
    except (TypeError, ValueError):
        limit = _CLI_TIMEOUT
    limit = max(1, min(limit, _CLI_MAX_TIMEOUT))

    argv = [command, *arg_list]

    # ---------- 2. 执行（shell=False，参数列表） ----------
    started = time.time()
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            timeout=limit,
            shell=False,
            check=False,
        )
    except FileNotFoundError:
        return _cli_error(
            f"未找到可执行程序：{command}（请确认已安装并加入 PATH）",
            command=command, args=arg_list,
        )
    except PermissionError:
        return _cli_error(f"没有执行权限：{command}", command=command, args=arg_list)
    except subprocess.TimeoutExpired as exc:
        stdout, stdout_cut = _truncate_stream(_decode_bytes(exc.stdout or b""))
        stderr, stderr_cut = _truncate_stream(_decode_bytes(exc.stderr or b""))
        return {
            "success": False,
            "error": f"命令执行超时：超过 {limit} 秒被强制终止",
            "command": command,
            "args": arg_list,
            "exitcode": None,
            "stdout": stdout,
            "stderr": stderr,
            "stdout_truncated": stdout_cut,
            "stderr_truncated": stderr_cut,
            "timed_out": True,
            "elapsed_ms": int((time.time() - started) * 1000),
        }
    except OSError as exc:
        return _cli_error(f"命令启动失败：{exc}", command=command, args=arg_list)

    elapsed_ms = int((time.time() - started) * 1000)

    # ---------- 3. 整理输出（解码 + 截断 + 标明截断情况） ----------
    stdout, stdout_cut = _truncate_stream(_decode_bytes(proc.stdout or b""))
    stderr, stderr_cut = _truncate_stream(_decode_bytes(proc.stderr or b""))

    result = {
        "command": command,
        "args": arg_list,
        "exitcode": proc.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "stdout_truncated": stdout_cut,
        "stderr_truncated": stderr_cut,
        "timed_out": False,
        "elapsed_ms": elapsed_ms,
    }

    if proc.returncode == 0:
        result["success"] = True
        result["message"] = f"命令执行完成（退出码 0，耗时 {elapsed_ms} ms）"
    else:
        detail = stderr.strip().splitlines()[0][:200] if stderr.strip() else "无标准错误输出"
        result["success"] = False
        result["error"] = f"命令退出码 {proc.returncode}：{detail}"
        result["message"] = f"命令执行结束（退出码 {proc.returncode}，耗时 {elapsed_ms} ms）"

    return result
