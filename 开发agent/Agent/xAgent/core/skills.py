# -*- coding: utf-8 -*-
"""
xAgent.core.skills —— 符合 Agent Skills 规范的 Skill 动态加载。

设计要点：
  1. 初始化只扫描 <项目根>/.agents/skills 下各 Skill 子目录的 SKILL.md
     frontmatter（name / description），不读取正文
  2. Skill 正文与附加文件只在 LLM 调用 loadSkill 时进入对话上下文
  3. 文件读取严格限制在对应 Skill 目录内部，拒绝目录外的路径
  4. 仅依赖标准库（内置轻量 frontmatter 解析，不依赖 PyYAML）
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

SKILL_FILE_NAME = "SKILL.md"
SKILLS_REL_DIR = (".agents", "skills")

_KV_RE = re.compile(r"^([A-Za-z0-9_.\-]+)\s*:\s*(.*)$")


# ============================================================
# frontmatter 解析（只处理 name / description 等简单标量）
# ============================================================

def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def _parse_frontmatter_lines(lines: List[str]) -> Dict[str, str]:
    """解析 YAML frontmatter 主体，支持单行值、引号值与 | / > 块标量。"""
    meta: Dict[str, str] = {}
    key: Optional[str] = None
    block_mode: Optional[str] = None
    block_lines: List[str] = []

    def flush() -> None:
        nonlocal key, block_mode, block_lines
        if key is not None and block_mode is not None:
            if block_mode == "|":
                meta[key] = "\n".join(block_lines).strip("\n")
            else:
                meta[key] = " ".join(
                    part for part in (line.strip() for line in block_lines) if part
                )
        key = None
        block_mode = None
        block_lines = []

    for raw in lines:
        line = raw.rstrip("\r")
        if not line.strip():
            if key is not None and block_mode is not None:
                block_lines.append("")
            continue

        # 缩进行：属于上一个键的块标量或续行
        if line[0] in (" ", "\t"):
            if key is None:
                continue
            value = line.strip()
            if block_mode is not None:
                block_lines.append(value)
            else:
                meta[key] = f"{meta.get(key, '')} {value}".strip()
            continue

        match = _KV_RE.match(line)
        if not match:
            continue

        flush()
        key = match.group(1).strip()
        value = match.group(2).strip()
        if value[:1] in (">", "|"):
            block_mode = value[0]
            block_lines = []
        else:
            block_mode = None
            meta[key] = _unquote(value)

    flush()
    return meta


def _split_frontmatter(text: str) -> Tuple[Dict[str, str], str]:
    """拆出 frontmatter 与正文；没有合法 frontmatter 时返回 ({}, 原文)。"""
    text = text.lstrip("\ufeff")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text

    end = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end = index
            break
    if end is None:
        return {}, text

    return _parse_frontmatter_lines(lines[1:end]), "\n".join(lines[end + 1:])


def _get_ci(meta: Dict[str, str], key: str) -> str:
    """按 key 取值（大小写不敏感）。"""
    for meta_key, value in meta.items():
        if meta_key.lower() == key:
            return (value or "").strip()
    return ""


def _read_text(path: Path) -> str:
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


# ============================================================
# Skill 元数据与注册表
# ============================================================

@dataclass
class SkillInfo:
    """初始化阶段只保存 name / description 与路径，不保存正文。"""

    name: str
    description: str
    directory: Path
    skill_file: Path


@dataclass
class SkillRegistry:
    """扫描并持有当前项目的所有 Skill 元数据。"""

    project_root: Path
    skills_dir: Path
    skills: Dict[str, SkillInfo] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    @classmethod
    def for_project(cls, project_root: Optional[Path | str] = None) -> "SkillRegistry":
        root = Path(project_root) if project_root is not None else Path(os.getcwd())
        root = root.resolve()
        return cls(
            project_root=root,
            skills_dir=root.joinpath(*SKILLS_REL_DIR).resolve(),
        )

    def discover(self) -> "SkillRegistry":
        self.skills.clear()
        self.warnings.clear()

        if not self.skills_dir.is_dir():
            return self

        for child in sorted(self.skills_dir.iterdir(), key=lambda p: p.name.lower()):
            if not child.is_dir():
                continue
            info = _load_skill_info(child)
            if info is None:
                self.warnings.append(
                    f"{child.name}: 缺少 SKILL.md，或 frontmatter 中 name / description 不完整"
                )
                continue
            if info.name in self.skills:
                self.warnings.append(
                    f"{child.name}: Skill 名称重复（{info.name}），已忽略"
                )
                continue
            self.skills[info.name] = info

        return self

    def get(self, name: str) -> Optional[SkillInfo]:
        if name in self.skills:
            return self.skills[name]
        lower = name.lower()
        for skill_name, info in self.skills.items():
            if skill_name.lower() == lower:
                return info
        return None

    def names(self) -> List[str]:
        return list(self.skills.keys())

    def __len__(self) -> int:
        return len(self.skills)


def _find_skill_file(directory: Path) -> Optional[Path]:
    target = SKILL_FILE_NAME.lower()
    for item in directory.iterdir():
        if item.is_file() and item.name.lower() == target:
            return item
    return None


def _load_skill_info(directory: Path) -> Optional[SkillInfo]:
    skill_file = _find_skill_file(directory)
    if skill_file is None:
        return None

    text = _read_text(skill_file)
    meta, _body = _split_frontmatter(text)
    name = _get_ci(meta, "name")
    description = _get_ci(meta, "description")

    if not name or not description:
        return None

    return SkillInfo(
        name=name,
        description=" ".join(description.split()),
        directory=directory.resolve(),
        skill_file=skill_file.resolve(),
    )


# ---------- 模块级注册表（进程内单例，启动时初始化一次） ----------

_REGISTRY: Optional[SkillRegistry] = None


def discover_skills(project_root: Optional[Path | str] = None) -> SkillRegistry:
    """以 project_root（默认当前工作目录）为项目根目录，重新扫描并缓存 Skill。"""
    global _REGISTRY
    _REGISTRY = SkillRegistry.for_project(project_root).discover()
    return _REGISTRY


def get_skill_registry() -> SkillRegistry:
    """获取注册表；尚未初始化时按当前工作目录做一次发现。"""
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = SkillRegistry.for_project().discover()
    return _REGISTRY


def reset_skill_registry() -> None:
    global _REGISTRY
    _REGISTRY = None


def build_skill_prompt(registry: Optional[SkillRegistry] = None) -> str:
    """生成注入 System Prompt 的 Skill 清单；没有 Skill 时返回空字符串。"""
    registry = registry if registry is not None else get_skill_registry()
    if not registry.skills:
        return ""

    lines = ["You have access to the following skills:"]
    for info in registry.skills.values():
        lines.append(f"- '{info.name}': {info.description}")
    lines.append(
        "Use the loadSkill tool to load the full instructions of a skill when needed. "
        "You can also load additional files referenced by a skill."
    )
    lines.append(
        "If the user's request matches one of the skills above, you MUST call loadSkill "
        "with that skill's name first and follow its loaded instructions, instead of "
        "answering from general knowledge or substituting other tools."
    )
    return "\n".join(lines)


# ============================================================
# 文件路径解析（严格限制在 Skill 目录内）
# ============================================================

def _is_within(path: Path, root: Path) -> bool:
    try:
        return os.path.commonpath([
            os.path.normcase(str(path)), os.path.normcase(str(root)),
        ]) == os.path.normcase(str(root))
    except ValueError:  # 不同盘符
        return False


def _relative_display(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _search_by_name(directory: Path, filename: str) -> List[Path]:
    """在 Skill 目录内递归搜索同名文件（大小写不敏感，去重）。"""
    target = filename.lower()
    matches: List[Path] = []
    seen = set()
    for item in directory.rglob("*"):
        if not item.is_file():
            continue
        if item.name != filename and item.name.lower() != target:
            continue
        resolved = item.resolve()
        if not _is_within(resolved, directory):
            continue
        key = os.path.normcase(str(resolved))
        if key in seen:
            continue
        seen.add(key)
        matches.append(resolved)
    return sorted(matches, key=lambda p: str(p).lower())


def _resolve_skill_file(
    skill: SkillInfo,
    project_root: Path,
    filename: str,
) -> Tuple[Optional[Path], List[str], str]:
    """
    解析 filename，返回 (目标文件, 候选列表, 错误描述)。

    匹配顺序：绝对路径 → Skill 相对路径 → 项目相对路径 → 仅文件名时递归搜索。
    """
    raw = filename.strip().strip("\"'")
    if not raw:
        return None, [], "filename 不能为空"
    if raw.startswith("~"):
        return None, [], f"不支持 ~ 展开的路径：{filename}"

    raw_path = Path(raw)

    # 1. 绝对路径：必须位于 Skill 目录内
    if raw_path.is_absolute():
        resolved = raw_path.resolve()
        if not resolved.is_file():
            return None, [], f"未找到文件：{filename}"
        if not _is_within(resolved, skill.directory):
            return None, [], (
                f"文件路径不在 Skill '{skill.name}' 的目录内，已拒绝读取：{filename}"
            )
        return resolved, [], ""

    # 2. 带路径分隔符：先按 Skill 相对，再按项目相对
    if "/" in raw or "\\" in raw:
        tried: List[str] = []
        for candidate in (skill.directory / raw_path, project_root / raw_path):
            resolved = candidate.resolve()
            tried.append(str(candidate))
            if not resolved.is_file():
                continue
            if not _is_within(resolved, skill.directory):
                return None, [], (
                    f"文件路径不在 Skill '{skill.name}' 的目录内，已拒绝读取：{filename}"
                )
            return resolved, [], ""
        return None, [], f"未找到文件：{filename}（已尝试：{'; '.join(tried)}）"

    # 3. 仅文件名：先精确匹配，再递归搜索
    exact = (skill.directory / raw_path).resolve()
    if exact.is_file() and _is_within(exact, skill.directory):
        return exact, [], ""

    matches = _search_by_name(skill.directory, raw)
    if len(matches) == 1:
        return matches[0], [], ""
    if not matches:
        return None, [], f"Skill '{skill.name}' 中未找到文件：{filename}"

    candidates = [_relative_display(item, skill.directory) for item in matches]
    message = (
        f"Skill '{skill.name}' 中存在 {len(candidates)} 个同名文件，"
        f"请提供完整路径后重试：{'; '.join(candidates)}"
    )
    return None, candidates, message


# ============================================================
# loadSkill 工具实现
# ============================================================

def _read_skill_file(path: Path) -> str:
    data = path.read_bytes()
    if b"\x00" in data[:8192]:
        raise ValueError(f"不支持读取二进制文件：{path.name}")
    return _read_text(path)


def load_skill(name: str, filename: Optional[str] = None) -> dict:
    """
    加载 Skill 的完整说明或附加文件。

    - 仅提供 name：返回该 Skill 的 SKILL.md 全文
    - 同时提供 filename：只读取指定附加文件，不重复加载 SKILL.md
    """
    skill_name = (name or "").strip() if isinstance(name, str) else ""
    if not skill_name:
        return {"success": False, "error": "参数 name 不能为空"}

    registry = get_skill_registry()
    skill = registry.get(skill_name)
    if skill is None:
        return {
            "success": False,
            "error": f"未找到 Skill：{skill_name}",
            "available_skills": registry.names(),
        }

    file_arg = (filename or "").strip() if isinstance(filename, str) else ""

    if file_arg:
        target, candidates, error = _resolve_skill_file(
            skill, registry.project_root, file_arg
        )
        if target is None:
            result = {"success": False, "error": error, "name": skill.name}
            if candidates:
                result["candidates"] = candidates
                result["message"] = error
            return result
    else:
        target = skill.skill_file
        candidates = []

    try:
        content = _read_skill_file(target)
    except ValueError as exc:
        return {
            "success": False,
            "error": str(exc),
            "name": skill.name,
            "file_path": str(target),
        }
    except OSError as exc:
        return {
            "success": False,
            "error": f"读取文件失败：{exc}",
            "name": skill.name,
            "file_path": str(target),
        }

    return {
        "success": True,
        "name": skill.name,
        "file_path": str(target),
        "relative_path": _relative_display(target, skill.directory),
        "content": content,
        "char_count": len(content),
        "message": (
            f"已加载 Skill '{skill.name}' 的文件："
            f"{_relative_display(target, skill.directory)}"
        ),
    }
