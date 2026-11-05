# -*- coding: utf-8 -*-
"""
xAgent.core.context —— 上下文窗口管理（压缩 / 归档 / 检索）。

这一层解决一个很朴素的问题：
    对话越聊越长，早晚会撑爆模型的上下文窗口。
    打不过就归档 —— 把老对话存成文件，把摘要放回对话里。

三件事，各一个函数族：
    1. 计量   estimate_tokens / estimate_messages_tokens / resolve_context_window
    2. 归档   save_archive / load_archive / list_archives
    3. 压缩   compact_messages（含失败回滚）+ recall_context（归档里做全文检索）

设计取舍（故意保持简单，方便学生阅读）：
    - 不引入向量库 / Embedding，检索就是「大小写不敏感的关键词包含 + 出现次数打分」
    - 归档用 JSONL，一行一条消息，肉眼可读、可 grep、可逐行追
    - Token 用估算，只有拿到模型 API 的 usage 时才用真实值
    - 压缩是「一次性」的：不搞流式、不搞增量摘要，先把事做对
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .llm import LLMMessage, ToolCall


# ============================================================
# 0. 常量
# ============================================================

#: 归档根目录（相对项目根）
ARCHIVE_ROOT = Path(".agents") / "context"

#: 归档编号格式：20261022-153000
ARCHIVE_ID_FORMAT = "%Y%m%d-%H%M%S"

#: 人读的归档时间格式：2026-10-22 15:30:00
HUMAN_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"

#: 触发压缩警告的阈值（占窗口比例）
COMPACT_THRESHOLD = 0.70

#: 压缩后希望落在多少 Token 左右
COMPACT_TARGET_TOKENS = 5000


# ============================================================
# 1. 计量：Token 估算 & 上下文窗口
# ============================================================

#: 已知模型的上下文窗口（单位：Token）。
#: 查不到就统一按 128k 兜底，并在 UI 上标「默认」。
MODEL_CONTEXT_WINDOWS: Dict[str, int] = {
    "ernie-5.1": 128_000,
    "ernie-4.5-turbo-128k": 128_000,
    "ernie-4.5-turbo-32k": 32_000,
    "deepseek-v4-pro": 128_000,
    "deepseek-v4.1-flash": 128_000,
    "deepseek-v4-flash": 128_000,
    "glm-5.3": 128_000,
    "glm-5.2": 128_000,
    "qwen3.5-397b-a17b": 128_000,
    "qwen3.5-122b-a10b": 128_000,
    "qwen3.5-35b-a3b": 128_000,
}

#: 兜底窗口：查不到模型就用它（UI 上会标「默认」）
DEFAULT_CONTEXT_WINDOW = 128_000


def _is_wide_char(ch: str) -> bool:
    """中日韩文字/全角符号 —— 这些字符基本是「一字一 Token」。"""
    code = ord(ch)
    return (
        0x4E00 <= code <= 0x9FFF      # CJK 统一表意文字
        or 0x3400 <= code <= 0x4DBF   # CJK 扩展 A
        or 0x3000 <= code <= 0x303F   # CJK 标点
        or 0xFF00 <= code <= 0xFFEF   # 全角字符
        or 0xAC00 <= code <= 0xD7AF   # 韩文
        or 0x3040 <= code <= 0x30FF   # 日文假名
    )


def estimate_tokens(text: str) -> int:
    """
    粗略估算一段文本的 Token 数。

    经验值：
        中文 ≈ 1 字 1 Token（宁可高估，触发警告早一点总比爆窗好）
        英文/代码 ≈ 4 字符 1 Token

    这里刻意偏高估 —— 上下文超限是硬失败，提前一点提醒没坏处。
    """
    if not text:
        return 0
    wide = sum(1 for ch in text if _is_wide_char(ch))
    narrow = len(text) - wide
    return int(wide + narrow / 4) + 1


def estimate_message_tokens(message: LLMMessage) -> int:
    """单条消息的 Token（含角色标记和工具调用的 JSON 开销）。"""
    total = estimate_tokens(message.content or "")
    total += 4  # role / 分隔符等固定开销
    if message.tool_calls:
        for call in message.tool_calls:
            total += estimate_tokens(call.name)
            total += estimate_tokens(json.dumps(call.arguments, ensure_ascii=False))
            total += 8
    return total


def estimate_messages_tokens(
    messages: Sequence[LLMMessage],
    tools_schema: Optional[Sequence[Dict[str, Any]]] = None,
) -> int:
    """
    估算整段上下文的 Token 数。

    包含：System Prompt、用户消息、助手回复、工具调用参数、工具返回结果，
    以及（可选）传给模型的工具定义 —— 工具定义也是要占窗口的。
    """
    total = sum(estimate_message_tokens(m) for m in messages)
    if tools_schema:
        total += estimate_tokens(json.dumps(list(tools_schema), ensure_ascii=False))
    return total


def resolve_context_window(
    model: str,
    override: Optional[int] = None,
) -> Tuple[int, bool]:
    """
    查模型上下文窗口，返回 (窗口大小, 是否是默认兜底值)。

    优先级：显式 override > 模型名精确匹配 > 名称前缀匹配 > 128k 兜底
    """
    if override and override > 0:
        return int(override), False

    name = (model or "").strip().lower()
    if name in MODEL_CONTEXT_WINDOWS:
        return MODEL_CONTEXT_WINDOWS[name], False

    # 允许 "ernie-5.1-xxx" 这类带尾巴的名字命中前缀
    for key, window in MODEL_CONTEXT_WINDOWS.items():
        if name.startswith(key):
            return window, False

    return DEFAULT_CONTEXT_WINDOW, True


def format_tokens(tokens: int) -> str:
    """1234 -> '1.2k'，128000 -> '128k'。"""
    if tokens < 1000:
        return str(tokens)
    value = tokens / 1000
    text = f"{value:.1f}".rstrip("0").rstrip(".")
    return f"{text}k"


@dataclass
class ContextUsage:
    """一次上下文用量快照 —— TUI 拿它渲染「上下文 x/yk (p%)」。"""

    tokens: int
    window: int
    is_default_window: bool = False
    source: str = "estimate"   # "api" = 模型返回的 usage；"estimate" = 本地估算
    #: 触发告警的比例（默认值可被 config.ini [context] compact_threshold 覆盖）
    threshold: float = COMPACT_THRESHOLD

    @property
    def ratio(self) -> float:
        if self.window <= 0:
            return 0.0
        return self.tokens / self.window

    @property
    def percent(self) -> float:
        return self.ratio * 100

    @property
    def over_threshold(self) -> bool:
        return self.ratio >= self.threshold

    @property
    def source_label(self) -> str:
        return "实测" if self.source == "api" else "估算"

    def format_meter(self) -> str:
        """例：3.2k/128k(默认) 2.5%"""
        window_tag = "(默认)" if self.is_default_window else ""
        return (
            f"{format_tokens(self.tokens)}/{format_tokens(self.window)}"
            f"{window_tag} {self.percent:.1f}%"
        )

    def format_detail(self) -> str:
        """给状态栏用的一整段：上下文 3.2k/128k(默认) 2.5% · 估算"""
        return f"上下文 {self.format_meter()} · {self.source_label}"


def measure_usage(
    messages: Sequence[LLMMessage],
    model: str,
    tools_schema: Optional[Sequence[Dict[str, Any]]] = None,
    api_prompt_tokens: Optional[int] = None,
    window_override: Optional[int] = None,
    threshold: float = COMPACT_THRESHOLD,
) -> ContextUsage:
    """
    算当前上下文用量。

    优先用模型 API 返回的 prompt_tokens（最准，含 System Prompt 和工具定义），
    拿不到才退回本地估算。
    """
    window, is_default = resolve_context_window(model, window_override)
    if api_prompt_tokens and api_prompt_tokens > 0:
        return ContextUsage(
            tokens=int(api_prompt_tokens),
            window=window,
            is_default_window=is_default,
            source="api",
            threshold=threshold,
        )
    return ContextUsage(
        tokens=estimate_messages_tokens(messages, tools_schema),
        window=window,
        is_default_window=is_default,
        source="estimate",
        threshold=threshold,
    )


# ============================================================
# 2. 归档：把原始上下文落盘成 JSONL
# ============================================================

def _configured_archive_subdir() -> str:
    """归档子目录默认值来自 config.ini [context] archive_dir。"""
    try:
        from .config import get_config

        return get_config().archive_dir or str(ARCHIVE_ROOT)
    except Exception:  # 配置层出问题时不要连归档一起挂掉
        return str(ARCHIVE_ROOT)


def archive_dir(
    project_root: os.PathLike | str | None = None,
    subdir: str | os.PathLike | None = None,
) -> Path:
    """归档目录：<project_root>/<archive_dir>/，默认 .agents/context/"""
    root = Path(project_root) if project_root else Path.cwd()
    return root / Path(subdir if subdir else _configured_archive_subdir())


def new_archive_id(now: Optional[datetime] = None) -> str:
    """生成归档编号，如 20261022-153000。"""
    return (now or datetime.now()).strftime(ARCHIVE_ID_FORMAT)


def _message_to_record(index: int, message: LLMMessage) -> Dict[str, Any]:
    """LLMMessage -> 可落盘的一行 JSON。"""
    return {
        "type": "message",
        "index": index,
        "role": message.role,
        "content": message.content or "",
        "tool_calls": [
            {
                "id": call.id,
                "name": call.name,
                "arguments": call.arguments,
            }
            for call in (message.tool_calls or [])
        ],
        "tool_call_id": message.tool_call_id,
    }


def save_archive(
    messages: Sequence[LLMMessage],
    project_root: os.PathLike | str | None = None,
    archive_id: Optional[str] = None,
    model: str = "",
    note: str = "",
    subdir: str | os.PathLike | None = None,
) -> Path:
    """
    把当前上下文完整写进 <project>/.agents/context/<archive_id>.jsonl。

    返回归档文件路径；写失败直接抛异常（调用方必须保证「存不进去就不压缩」）。

    文件结构：第一行 meta，后面每条消息一行，顺序与对话顺序一致。
    """
    target_dir = archive_dir(project_root, subdir)
    target_dir.mkdir(parents=True, exist_ok=True)

    aid = archive_id or new_archive_id()
    path = target_dir / f"{aid}.jsonl"

    # 极短时间内重复压缩会撞编号，加后缀避免覆盖
    suffix = 1
    while path.exists():
        suffix += 1
        path = target_dir / f"{aid}-{suffix}.jsonl"

    meta = {
        "type": "meta",
        "id": path.stem,
        "created_at": datetime.now().strftime(HUMAN_TIME_FORMAT),
        "model": model,
        "message_count": len(messages),
        "estimated_tokens": estimate_messages_tokens(messages),
        "note": note,
    }

    tmp = path.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        f.write(json.dumps(meta, ensure_ascii=False) + "\n")
        for index, message in enumerate(messages):
            f.write(
                json.dumps(_message_to_record(index, message), ensure_ascii=False) + "\n"
            )
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(path)  # 原子落盘：要么完整文件，要么没有
    return path


def load_archive(path: os.PathLike | str) -> List[Dict[str, Any]]:
    """读一个归档文件，返回 [{type, index, role, content, tool_calls, ...}]。"""
    records: List[Dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # 半截行（比如进程被杀）直接跳过，不影响其余数据
    return records


def list_archives(
    project_root: os.PathLike | str | None = None,
    subdir: str | os.PathLike | None = None,
) -> List[Dict[str, Any]]:
    """列出所有归档（新的在前），返回 meta 列表。"""
    target_dir = archive_dir(project_root, subdir)
    if not target_dir.is_dir():
        return []

    items: List[Dict[str, Any]] = []
    for path in target_dir.glob("*.jsonl"):
        meta: Dict[str, Any] = {"id": path.stem, "path": str(path)}
        try:
            with path.open("r", encoding="utf-8") as f:
                first = f.readline().strip()
            if first:
                parsed = json.loads(first)
                if parsed.get("type") == "meta":
                    meta.update(parsed)
        except (OSError, json.JSONDecodeError):
            pass
        meta.setdefault("created_at", "")
        items.append(meta)

    items.sort(key=lambda m: str(m.get("created_at", "")), reverse=True)
    return items


# ============================================================
# 3. 检索：recallContext 的底层实现（纯本地全文匹配）
# ============================================================

def _split_terms(text: str) -> List[str]:
    """关键词切分：空白 + 常见分隔符，去重保序。"""
    raw = re.split(r"[\s,，、;；|]+", (text or "").strip())
    terms: List[str] = []
    for item in raw:
        item = item.strip()
        if item and item not in terms:
            terms.append(item)
    return terms


def _snippet(content: str, terms: Sequence[str], width: int = 90) -> str:
    """截取命中位置前后的一小段原文，命不中就取开头。"""
    lower = content.lower()
    pos = -1
    for term in terms:
        pos = lower.find(term.lower())
        if pos >= 0:
            break
    if pos < 0:
        pos = 0
    start = max(0, pos - width // 3)
    end = min(len(content), start + width)
    piece = content[start:end].replace("\n", " ⏎ ")
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(content) else ""
    return f"{prefix}{piece}{suffix}"


def recall_context(
    text: str,
    id: Optional[str] = None,  # noqa: A002 - 工具参数名就叫 id，保持与设计文档一致
    project_root: os.PathLike | str | None = None,
    max_matches: Optional[int] = None,
    max_chars: Optional[int] = None,
    subdir: str | os.PathLike | None = None,
) -> dict:
    """
    在历史归档里做关键词检索（recallContext 工具的实现）。

    参数
        text          要查的关键词，多个词用空格分隔
        id            可选，只查指定的归档编号；不传就查全部归档
        project_root  项目根目录（默认当前工作目录）
        max_matches   最多返回几条命中（默认取 config.ini [context] recall_matches）
        max_chars     返回内容总长度上限，防止检索结果又撑爆上下文

    返回（registry 会包成 ToolResult）
        {"success": True, "matches": [...], "archives_scanned": n, ...}
    """
    if max_matches is None or max_chars is None:
        default_matches, default_chars = 5, 1500
        try:
            from .config import get_config

            cfg = get_config()
            default_matches = cfg.recall_matches
            default_chars = cfg.recall_max_chars
        except Exception:  # 配置层异常不该让检索挂掉
            pass
        max_matches = max_matches or default_matches
        max_chars = max_chars or default_chars

    terms = _split_terms(text)
    if not terms:
        return {"success": False, "error": "text 参数不能为空，请给出要检索的关键词"}

    target_dir = archive_dir(project_root, subdir)

    if id:
        candidate = target_dir / f"{id}.jsonl"
        if not candidate.is_file():
            # 也允许直接传带后缀的文件名
            candidate = target_dir / f"{id}"
        if not candidate.is_file():
            return {
                "success": False,
                "error": f"归档不存在：{id}（目录 {target_dir}）",
                "available": [m["id"] for m in list_archives(project_root, subdir)[:10]],
            }
        files = [candidate]
    else:
        files = sorted(target_dir.glob("*.jsonl")) if target_dir.is_dir() else []

    if not files:
        return {
            "success": True,
            "matches": [],
            "archives_scanned": 0,
            "message": f"还没有任何归档（目录 {target_dir}），当前会话从未压缩过。",
        }

    matches: List[Dict[str, Any]] = []
    for path in files:
        for record in load_archive(path):
            if record.get("type") != "message":
                continue
            content = record.get("content") or ""
            # 工具调用参数也参与检索 —— 函数名/路径常藏在参数里
            haystack = content
            calls = record.get("tool_calls") or []
            if calls:
                haystack += " " + json.dumps(calls, ensure_ascii=False)

            lower = haystack.lower()
            hits = sum(lower.count(term.lower()) for term in terms)
            if hits == 0:
                continue
            matches.append({
                "archive_id": path.stem,
                "index": record.get("index"),
                "role": record.get("role"),
                "hits": hits,
                "snippet": _snippet(haystack, terms),
            })

    matches.sort(key=lambda m: (-m["hits"], str(m["archive_id"]), -(m.get("index") or 0)))

    kept: List[Dict[str, Any]] = []
    used = 0
    for item in matches:
        cost = len(item["snippet"]) + 80
        if kept and used + cost > max_chars:
            break
        kept.append(item)
        used += cost
        if len(kept) >= max_matches:
            break

    result: Dict[str, Any] = {
        "success": True,
        "query": " ".join(terms),
        "archives_scanned": len(files),
        "total_matches": len(matches),
        "matches": kept,
        "message": (
            f"命中 {len(matches)} 条，返回前 {len(kept)} 条"
            if matches
            else f"在 {len(files)} 个归档里没有找到「{text}」相关内容"
        ),
    }
    if len(matches) > len(kept):
        result["truncated"] = True
        result["hint"] = "结果已截断，可换个更具体的关键词，或用 id 参数只查某个归档"
    return result


# ============================================================
# 4. 压缩：调 LLM 生成摘要，再用摘要替换历史
# ============================================================

#: 上下文压缩专用 Prompt（系统提示词）
COMPACTION_SYSTEM_PROMPT = """你是一名 AI Agent 的上下文管理助手。当前会话即将达到上下文窗口限制，需要将历史对话压缩为一份高质量的工作摘要，以便 Agent 在新的上下文中继续执行任务。

请认真阅读提供的历史上下文，提取对后续工作仍然有价值的信息，并生成一份约 5,000 Tokens 的 Markdown 摘要。

摘要应重点保留以下内容：

1. **用户目标与要求**：用户希望完成什么任务？有哪些必须遵守的约束、偏好和验收条件？
2. **已经完成的工作**：哪些任务已经完成？实现了哪些功能？获得了哪些已经验证的结果？
3. **当前工作状态**：Agent 正在处理什么任务？当前进展到哪一步？是否存在尚未解决的问题？
4. **关键技术信息**：保留重要的文件路径、函数名称、接口定义、配置项、执行命令、错误信息和必要的代码片段。
5. **关键决策与原因**：记录用户和 Agent 已经确定的技术方案，以及重要的设计取舍。
6. **下一步任务**：明确接下来应该执行的操作，以及需要继续验证的事项。

请遵守以下要求：

- 优先保留对后续任务有直接影响的信息，删除寒暄、重复讨论、过时的尝试和无关内容。
- 对已经验证的事实与尚未验证的推测作出明确区分。
- 不要将计划完成的任务描述为已经完成。
- 重要的文件路径、函数名称、配置名称和命令应保留准确原文。
- 对失败的尝试，只保留有助于避免重复错误的信息。
- 如果信息存在冲突，应优先保留用户最新确认的要求，并简要说明仍然存在的冲突。
- 如果某些历史细节无法在摘要中完整保留，可简要说明它们已保存到原始上下文归档中，后续可以通过 `recallContext` 工具重新检索。
- 使用清晰的 Markdown 结构输出摘要，不要附加解释或无关内容。

**最终目标：使一个从未阅读过原始对话的 Agent，仅凭这份摘要，就能够理解当前任务、继承关键决策，并继续开展工作。**"""

#: 单条消息在 transcript 里的截断长度（避免压缩请求自己又爆窗）
_TRANSCRIPT_ITEM_LIMIT = 4000


def build_transcript(messages: Sequence[LLMMessage]) -> str:
    """把消息列表摊平成一份可读文本，喂给压缩用的 LLM。"""
    blocks: List[str] = []
    for index, message in enumerate(messages):
        role = message.role
        body = (message.content or "").strip()
        if len(body) > _TRANSCRIPT_ITEM_LIMIT:
            body = body[:_TRANSCRIPT_ITEM_LIMIT] + "\n…（内容过长，已截断）"

        head = f"### [{index}] {role}"
        lines = [head]
        if message.tool_calls:
            for call in message.tool_calls:
                args = json.dumps(call.arguments, ensure_ascii=False)
                lines.append(f"- 调用工具 `{call.name}` 参数 {args}（call_id={call.id}）")
        if message.tool_call_id:
            lines.append(f"- 对应 call_id：{message.tool_call_id}")
        if body:
            lines.append(body)
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def build_compaction_messages(messages: Sequence[LLMMessage]) -> List[LLMMessage]:
    """构造发给 LLM 的压缩请求：系统提示词 + 整段历史 transcript。"""
    transcript = build_transcript(messages)
    return [
        LLMMessage(role="system", content=COMPACTION_SYSTEM_PROMPT),
        LLMMessage(
            role="user",
            content=(
                f"以下是需要压缩的历史上下文（共 {len(messages)} 条消息）：\n\n"
                f"{transcript}"
            ),
        ),
    ]


def build_summary_message(
    summary: str,
    archive_id: str,
    created_at: str,
) -> LLMMessage:
    """
    把摘要包装成一条消息，塞回对话开头。

    末尾的归档说明是硬要求：模型日后发现摘要缺东西时，
    得知道该用 recallContext 去哪个编号里翻。
    """
    content = (
        "以下是你（Agent）在此前对话中的工作摘要。这是一份压缩后的上下文，"
        "用于在新会话中继续原来的任务：\n\n"
        f"{summary.strip()}\n\n"
        "---\n\n"
        f"> 此前上下文已于 {created_at} 完成压缩，原始上下文保存在编号为 "
        f"{archive_id} 的归档文件中。如需查找历史信息，请使用 recallContext 工具。"
    )
    return LLMMessage(role="user", content=content)


@dataclass
class CompactionResult:
    """压缩结果 —— TUI 只负责把里面的字段画出来。"""

    success: bool
    archive_id: str = ""
    archive_path: str = ""
    summary: str = ""
    messages: List[LLMMessage] = field(default_factory=list)
    error: str = ""
    tokens_before: int = 0
    tokens_after: int = 0
    summary_tokens: int = 0
    created_at: str = ""


def compact_messages(
    messages: Sequence[LLMMessage],
    provider: Any,
    project_root: os.PathLike | str | None = None,
    model: str = "",
    keep_system: bool = True,
    archive_subdir: str | os.PathLike | None = None,
) -> CompactionResult:
    """
    执行一次完整压缩：归档 → 调 LLM 出摘要 → 用摘要替换上下文。

    顺序是硬性的：**先归档成功，才允许压缩**。
    任何一步失败都返回 success=False，且不改动传入的 messages。

    返回的 CompactionResult.messages 是压缩后的新列表，调用方自行替换。
    """
    before = estimate_messages_tokens(messages)

    # ---- 第 1 步：归档原始上下文 ----
    try:
        path = save_archive(
            messages,
            project_root=project_root,
            model=model,
            note="上下文压缩前自动归档",
            subdir=archive_subdir,
        )
    except Exception as exc:  # 磁盘满/没权限/路径非法
        return CompactionResult(
            success=False,
            error=f"归档保存失败，已取消压缩：{exc}",
            messages=list(messages),
            tokens_before=before,
        )

    archive_id = path.stem
    created_at = datetime.now().strftime(HUMAN_TIME_FORMAT)

    # ---- 第 2 步：让 LLM 生成摘要 ----
    try:
        request = build_compaction_messages(messages)
        response = provider.chat(request, [])  # 不带 tools：压缩期间不执行任何工具
    except Exception as exc:
        return CompactionResult(
            success=False,
            error=f"摘要生成失败（原始上下文已归档为 {archive_id}）：{exc}",
            archive_id=archive_id,
            archive_path=str(path),
            messages=list(messages),
            tokens_before=before,
        )

    summary = (response.content or "").strip()
    if response.tool_calls and not summary:
        return CompactionResult(
            success=False,
            error=(
                "模型在压缩阶段请求了工具调用，但压缩期间不允许执行任何工具；"
                f"未生成摘要（原始上下文已归档为 {archive_id}），请重试 /compact"
            ),
            archive_id=archive_id,
            archive_path=str(path),
            messages=list(messages),
            tokens_before=before,
        )
    if not summary:
        return CompactionResult(
            success=False,
            error=f"模型返回了空摘要（原始上下文已归档为 {archive_id}），请重试 /compact",
            archive_id=archive_id,
            archive_path=str(path),
            messages=list(messages),
            tokens_before=before,
        )

    # ---- 第 3 步：用摘要替换历史（System Prompt 原样保留） ----
    new_messages = replace_messages(
        messages,
        build_summary_message(summary, archive_id, created_at),
        keep_system=keep_system,
    )

    return CompactionResult(
        success=True,
        archive_id=archive_id,
        archive_path=str(path),
        summary=summary,
        messages=new_messages,
        tokens_before=before,
        tokens_after=estimate_messages_tokens(new_messages),
        summary_tokens=estimate_tokens(summary),
        created_at=created_at,
    )


def replace_messages(
    messages: Sequence[LLMMessage],
    summary_message: LLMMessage,
    keep_system: bool = True,
) -> List[LLMMessage]:
    """
    生成压缩后的消息列表：System Prompt 保留 + 摘要 + 一句确认。

    为什么补一句 assistant 确认：
        摘要那条是 user 角色，紧跟真实用户提问会出现连续两条 user，
        有些兼容接口会因此报格式错误，加一句确认既自然又稳。
    """
    new_messages: List[LLMMessage] = []
    if keep_system and messages and messages[0].role == "system":
        new_messages.append(messages[0])
    new_messages.append(summary_message)
    new_messages.append(
        LLMMessage(
            role="assistant",
            content="已理解此前的工作摘要，我会在此基础上继续完成任务。",
        )
    )
    return new_messages


def build_archive_hint(archive_id: str, created_at: str) -> str:
    """归档说明（独立函数，便于 TUI 单独展示或在别处复用）。"""
    return (
        f"此前上下文已于 {created_at} 完成压缩，原始上下文保存在编号为 "
        f"{archive_id} 的归档文件中。如需查找历史信息，请使用 recallContext 工具。"
    )
