# -*- coding: utf-8 -*-
"""
xAgent.core.session —— 会话持久化（保存 / 列表 / 恢复 / 事件日志）。

存哪儿
    <项目根>/.agents/sessions/<会话编号>.jsonl

文件长什么样
    第一行 meta（编号、时间、模型、消息数、预览、项目指令标记）
    后面一行一条消息，字段与上下文归档保持一致（role / content / tool_calls / ...）

为什么是 JSONL
    追加便宜、肉眼可读、出问题能一行行看，也不需要任何数据库。

和上下文归档的区别
    .agents/context/ 是「压缩前的快照」，只在 /compact 时产生，用于 recallContext。
    .agents/sessions/ 是「会话本身」，可反复保存、可被 /resume 恢复。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .llm import LLMMessage, ToolCall

SESSION_DIR = Path(".agents") / "sessions"
SESSION_ID_FORMAT = "%Y%m%d-%H%M%S"
HUMAN_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"

#: 消息在事件日志里的类型标记（/resume 靠它判断项目指令是否已注入过）
KIND_MESSAGE = "message"
KIND_AGENTS_MD = "agents_md"


# ============================================================
# 路径与编号
# ============================================================

def session_root(project_root: os.PathLike | str | None = None) -> Path:
    """会话目录：<项目根>/.agents/sessions/"""
    root = Path(project_root) if project_root else Path.cwd()
    return root / SESSION_DIR


def session_root_with(
    project_root: os.PathLike | str | None,
    subdir: str | os.PathLike | None = None,
) -> Path:
    """支持从配置里改目录（例如 session_dir = data/sessions）。"""
    root = Path(project_root) if project_root else Path.cwd()
    return root / Path(subdir) if subdir else session_root(root)


def new_session_id(
    now: Optional[datetime] = None,
    root: os.PathLike | str | None = None,
    subdir: str | os.PathLike | None = None,
) -> str:
    """生成会话编号，如 20261105-112700；同一秒重复时加后缀避免覆盖。"""
    base = (now or datetime.now()).strftime(SESSION_ID_FORMAT)
    target_dir = session_root_with(root, subdir)
    candidate = base
    index = 1
    while (target_dir / f"{candidate}.jsonl").exists():
        index += 1
        candidate = f"{base}-{index}"
    return candidate


# ============================================================
# 消息 <-> 记录
# ============================================================

def message_to_record(index: int, message: LLMMessage, kind: str = KIND_MESSAGE) -> Dict[str, Any]:
    return {
        "type": "message",
        "index": index,
        "kind": kind,
        "role": message.role,
        "content": message.content or "",
        "tool_calls": [
            {"id": call.id, "name": call.name, "arguments": call.arguments}
            for call in (message.tool_calls or [])
        ],
        "tool_call_id": message.tool_call_id,
    }


def record_to_message(record: Dict[str, Any]) -> LLMMessage:
    calls = [
        ToolCall(
            id=str(item.get("id") or ""),
            name=str(item.get("name") or ""),
            arguments=item.get("arguments") or {},
        )
        for item in (record.get("tool_calls") or [])
    ]
    return LLMMessage(
        role=str(record.get("role") or "user"),
        content=record.get("content") or "",
        tool_calls=calls or None,
        tool_call_id=record.get("tool_call_id"),
    )


# ============================================================
# 保存 / 读取 / 列表
# ============================================================

@dataclass
class SessionMeta:
    """会话摘要信息（/resume 列表就画这个）。"""

    id: str
    path: str = ""
    created_at: str = ""
    updated_at: str = ""
    model: str = ""
    title: str = ""
    preview: str = ""
    message_count: int = 0
    estimated_tokens: int = 0
    has_agents_md: bool = False
    messages: List[LLMMessage] = field(default_factory=list)

    @property
    def display_title(self) -> str:
        return self.title or self.preview or "(空会话)"

    @property
    def display_time(self) -> str:
        return self.updated_at or self.created_at or self.id


def _preview_of(messages: Sequence[LLMMessage], limit: int = 60) -> str:
    """取第一条真实用户消息当预览（跳过系统提示与项目指令）。"""
    for message in messages:
        if message.role != "user":
            continue
        text = " ".join((message.content or "").split())
        if not text or text.startswith("以下内容来自项目根目录的"):
            continue
        return text[:limit] + ("…" if len(text) > limit else "")
    return ""


def save_session(
    messages: Sequence[LLMMessage],
    session_id: str,
    project_root: os.PathLike | str | None = None,
    subdir: str | os.PathLike | None = None,
    model: str = "",
    title: str = "",
    kinds: Optional[Sequence[str]] = None,
    estimated_tokens: int = 0,
    source: str = "xagent-tui",
) -> Path:
    """
    把当前会话整体写盘（原子替换，写一半挂掉不会留下半截文件）。

    kinds：与 messages 等长的类型标记，用来记住「项目指令已注入过」。
    """
    target_dir = session_root_with(project_root, subdir)
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{session_id}.jsonl"

    now = datetime.now().strftime(HUMAN_TIME_FORMAT)
    created_at = now
    previous = read_meta(path)
    if previous and previous.get("created_at"):
        created_at = str(previous["created_at"])

    # 文件里本来就有项目指令事件的话，重存时不要丢掉这个标记
    prior_kinds = previous.get("_kinds", []) if previous else []
    resolved_kinds = list(kinds) if kinds is not None else (
        prior_kinds or [KIND_MESSAGE] * len(messages)
    )
    if len(resolved_kinds) != len(messages):
        resolved_kinds = [KIND_MESSAGE] * len(messages)

    meta: Dict[str, Any] = {
        "type": "meta",
        "id": session_id,
        "created_at": created_at,
        "updated_at": now,
        "model": model,
        "title": title,
        "preview": _preview_of(messages),
        "message_count": len(messages),
        "estimated_tokens": estimated_tokens,
        "has_agents_md": KIND_AGENTS_MD in resolved_kinds,
        "source": source,
    }

    tmp = path.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(meta, ensure_ascii=False) + "\n")
        for index, message in enumerate(messages):
            record = message_to_record(index, message, resolved_kinds[index])
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    tmp.replace(path)
    return path


def _read_lines(path: Path) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    if not path.is_file():
        return records
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def read_meta(path: os.PathLike | str) -> Dict[str, Any]:
    """只读第一行 meta。"""
    file_path = Path(path)
    if not file_path.is_file():
        return {}
    try:
        with file_path.open("r", encoding="utf-8") as handle:
            first = handle.readline().strip()
    except OSError:
        return {}
    if not first:
        return {}
    try:
        parsed = json.loads(first)
    except json.JSONDecodeError:
        return {}
    if parsed.get("type") != "meta":
        return {}

    # 让 save_session 知道原文件里的 kinds（避免重存把标记洗掉）
    kinds: List[str] = []
    try:
        with file_path.open("r", encoding="utf-8") as handle:
            handle.readline()
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                kinds.append(record.get("kind") or KIND_MESSAGE)
    except OSError:
        kinds = []
    parsed["_kinds"] = kinds
    return parsed


def load_session(
    session_id: str,
    project_root: os.PathLike | str | None = None,
    subdir: str | os.PathLike | None = None,
) -> Optional[SessionMeta]:
    """读回一个会话；不存在返回 None。"""
    path = session_root_with(project_root, subdir) / f"{session_id}.jsonl"
    if not path.is_file():
        return None

    records = _read_lines(path)
    if not records:
        return None

    meta_raw = records[0] if records[0].get("type") == "meta" else {}
    messages: List[LLMMessage] = []
    has_agents_md = False
    for record in records:
        if record.get("type") != "message":
            continue
        if record.get("kind") == KIND_AGENTS_MD:
            has_agents_md = True
        messages.append(record_to_message(record))

    return SessionMeta(
        id=str(meta_raw.get("id") or session_id),
        path=str(path),
        created_at=str(meta_raw.get("created_at") or ""),
        updated_at=str(meta_raw.get("updated_at") or ""),
        model=str(meta_raw.get("model") or ""),
        title=str(meta_raw.get("title") or ""),
        preview=str(meta_raw.get("preview") or _preview_of(messages)),
        message_count=len(messages),
        estimated_tokens=int(meta_raw.get("estimated_tokens") or 0),
        has_agents_md=bool(meta_raw.get("has_agents_md", has_agents_md)),
        messages=messages,
    )


def list_sessions(
    project_root: os.PathLike | str | None = None,
    subdir: str | os.PathLike | None = None,
    limit: int = 50,
) -> List[SessionMeta]:
    """列出所有会话，最近更新的在前。只读 meta 行，快。"""
    target_dir = session_root_with(project_root, subdir)
    if not target_dir.is_dir():
        return []

    items: List[SessionMeta] = []
    for path in target_dir.glob("*.jsonl"):
        meta = read_meta(path)
        if not meta:
            continue
        items.append(
            SessionMeta(
                id=str(meta.get("id") or path.stem),
                path=str(path),
                created_at=str(meta.get("created_at") or ""),
                updated_at=str(meta.get("updated_at") or ""),
                model=str(meta.get("model") or ""),
                title=str(meta.get("title") or ""),
                preview=str(meta.get("preview") or ""),
                message_count=int(meta.get("message_count") or 0),
                estimated_tokens=int(meta.get("estimated_tokens") or 0),
                has_agents_md=bool(meta.get("has_agents_md")),
            )
        )

    items.sort(key=lambda s: (s.updated_at or s.created_at or s.id), reverse=True)
    return items[:limit]


def delete_session(
    session_id: str,
    project_root: os.PathLike | str | None = None,
    subdir: str | os.PathLike | None = None,
) -> bool:
    """删除一个会话文件（/resume 面板里按 d 用）。"""
    path = session_root_with(project_root, subdir) / f"{session_id}.jsonl"
    if not path.is_file():
        return False
    try:
        path.unlink()
    except OSError:
        return False
    return True


# ============================================================
# AGENTS.md：一次注入，全程复用
# ============================================================

def find_agents_md(
    project_root: os.PathLike | str | None = None,
    filename: str = "AGENTS.md",
) -> Optional[Path]:
    """在项目根找 AGENTS.md（大小写不敏感，兼容 agents.md）。"""
    root = Path(project_root) if project_root else Path.cwd()
    if not root.is_dir():
        return None
    exact = root / filename
    if exact.is_file():
        return exact
    target = filename.lower()
    for child in root.iterdir():
        if child.is_file() and child.name.lower() == target:
            return child
    return None


def read_text(path: Path) -> str:
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def build_agents_md_message(content: str, rel_path: str = "AGENTS.md") -> LLMMessage:
    """
    把 AGENTS.md 变成一条 user 消息。

    为什么用 user 而不是 system：
        system 已被 System Prompt / Skill 清单占用，混进去会打乱「工具定义不动」的约定；
        用 user 消息做「项目指令」也方便归档、恢复和逐条回看。
    """
    body = content.strip()
    return LLMMessage(
        role="user",
        content=(
            f"以下内容来自项目根目录的 {rel_path}，是本项目的长期约定。"
            "请在本会话的后续所有工作中遵守：\n\n"
            "<project_instructions>\n"
            f"{body}\n"
            "</project_instructions>"
        ),
    )


def load_agents_md(
    project_root: os.PathLike | str | None = None,
    filename: str = "AGENTS.md",
) -> Optional[tuple[Path, str]]:
    """找到并读取 AGENTS.md，返回 (路径, 内容)；没有则 None。"""
    path = find_agents_md(project_root, filename)
    if path is None:
        return None
    try:
        content = read_text(path)
    except OSError:
        return None
    if not content.strip():
        return None
    return path, content
