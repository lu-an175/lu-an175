# -*- coding: utf-8 -*-
"""
xAgent.core.config —— 全局配置（LLM / 上下文 / 会话 / UI / MCP）。

配置来源（优先级从高到低）
    1. 环境变量（只覆盖少数几个敏感项，方便 CI / 临时切换）
    2. 当前工作目录下的 config.ini
    3. 代码内置默认值（本文件的 DEFAULTS）

首次运行
    `ensure_config_file()` 会在「当前工作目录」下生成一份完整的 config.ini，
    里面只填 mock 值（不需要联网也能跑），TUI 会弹窗提示用户改完重启。

为什么配置文件放在「当前目录」而不是包里
    Agent 的行为（项目指令、会话历史、归档、MCP 服务器）都跟着项目走，
    所以配置也跟着项目走：换一个项目目录就换一份配置。

兼容旧格式
    早期版本把 key 写在 [qianfan] baidu_qianfan_api_key。
    现在仍能读：若 [llm] api_key 为空，自动回退到旧键。
"""

from __future__ import annotations

import configparser
import os
import shlex
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .mcp import MCPServerConfig

# ============================================================
# 路径
# ============================================================

CONFIG_FILE_NAME = "config.ini"

#: 包内旧版配置（只作为迁移来源 / 兜底，不再作为主配置）
LEGACY_CONFIG_INI: Path = Path(__file__).resolve().parent / "config.ini"


def primary_config_path() -> Path:
    """主配置路径：环境变量 XAGENT_CONFIG > 当前目录 config.ini。"""
    env_value = os.environ.get("XAGENT_CONFIG", "").strip()
    if env_value:
        return Path(env_value).expanduser().resolve()
    return (Path.cwd() / CONFIG_FILE_NAME).resolve()


def resolve_config_path() -> Path:
    """
    实际生效的配置路径。

    当前目录没有 config.ini 时，退回包内的旧配置文件（如果有），
    这样老用户升级后不会突然丢掉 API Key。
    """
    primary = primary_config_path()
    if primary.is_file():
        return primary
    if LEGACY_CONFIG_INI.is_file():
        return LEGACY_CONFIG_INI
    return primary


#: 兼容旧代码 / 测试的模块级常量（少数模块直接 import 它）
CONFIG_INI: Path = resolve_config_path()


# ============================================================
# 默认值
# ============================================================

DEFAULTS: Dict[str, Dict[str, str]] = {
    "llm": {
        # mock = 本地模拟；qianfan = 百度千帆（或任意 OpenAI 兼容端点）
        "provider": "mock",
        "api_key": "",
        "base_url": "https://qianfan.baidubce.com/v2",
        "model": "mock",
        "search_url": "https://qianfan.baidubce.com/v2/ai_search/chat/completions",
        "search_model": "ernie-5.1",
        "timeout": "60",
    },
    "agent": {
        # 单轮对话最多调用多少次模型（防止工具死循环）
        "max_model_calls": "8",
    },
    "context": {
        # 0 = 按模型名自动查表，查不到按 128k 并标记「默认」
        "window": "0",
        # 用量达到窗口的这个比例时警告并锁定输入
        "compact_threshold": "0.7",
        # 压缩摘要的目标 Token
        "target_tokens": "5000",
        "archive_dir": ".agents/context",
        # recallContext 单次最多返回多少条命中 / 总长度上限（字符）
        "recall_matches": "5",
        "recall_max_chars": "1500",
    },
    "session": {
        "dir": ".agents/sessions",
        "auto_save": "true",
        # 会话首次加载时注入项目根的 AGENTS.md（一次注入，全程复用）
        "agents_md": "true",
        "agents_md_file": "AGENTS.md",
    },
    "ui": {
        "sidebar_width": "42",
        # 工具卡片折叠态里结果预览的字符数
        "card_preview_chars": "120",
        "show_command_palette": "true",
    },
    "mcp": {
        "enabled": "true",
        # 逗号分隔的服务器名；留空 = 自动使用所有 [mcp:*] 段
        "servers": "",
        "timeout": "20",
    },
}

#: 首次运行生成的 config.ini 全文（mock 值，能直接跑起来）
CONFIG_TEMPLATE = """; ============================================================
; xAgent 配置文件
; 首次运行自动生成。修改后请【重启 xAgent】才会生效。
; ⚠️ 本文件可能保存 API Key，提交代码前请加入 .gitignore
; ============================================================

[llm]
; mock = 本地模拟（无需联网，功能受限）；qianfan = 百度千帆 / 任意 OpenAI 兼容接口
provider = @@PROVIDER@@
; 千帆的 key 形如 bce-v3/ALTAK-xxxx/yyyy
api_key = @@API_KEY@@
base_url = https://qianfan.baidubce.com/v2
model = @@MODEL@@
; 联网搜索（searchWeb 工具）走的端点与模型
search_url = https://qianfan.baidubce.com/v2/ai_search/chat/completions
search_model = ernie-5.1
; 单次请求超时（秒）
timeout = 60

[agent]
; 单轮对话最多调用多少次模型，防止工具死循环
max_model_calls = 8

[context]
; 上下文窗口（Token）。0 = 按模型名自动判断，判断不出来按 128k 并在界面标「默认」
window = 0
; 用到窗口的百分之多少时警告并锁定输入（0.7 = 70%）
compact_threshold = 0.7
; /compact 生成的摘要目标长度
target_tokens = 5000
; 压缩前的原始上下文归档目录（相对项目根）
archive_dir = .agents/context
; recallContext 单次最多返回几条命中，以及总长度上限（字符）
recall_matches = 5
recall_max_chars = 1500

[session]
; 会话历史保存目录（相对项目根）
dir = .agents/sessions
; 每轮对话结束后自动保存当前会话
auto_save = true
; 是否在会话首次加载时注入 AGENTS.md
agents_md = true
agents_md_file = AGENTS.md

[ui]
; 右侧边栏宽度（列）
sidebar_width = 42
; 工具卡片里结果预览的字符数
card_preview_chars = 120
; 输入 / 时弹出命令补全面板
show_command_palette = true

[mcp]
; 是否启用 MCP 服务器（异步加载，进界面后动态刷新）
enabled = true
; 逗号分隔的服务器名；留空 = 自动使用下面所有 [mcp:名称] 段
servers = demo
; 单次请求超时（秒）
timeout = 20

; ------------------------------------------------------------
; 每台 MCP 服务器一个 [mcp:名称] 段
;   transport = stdio   通过子进程标准输入输出通信
;   command   = python  command 写 python 时使用当前解释器
;   args      = ...     逗号分隔的参数
;   env       = K=V,K2=V2  额外环境变量（可选）
; 不需要的服务器把 enabled 改成 false，或从 servers 里删掉。
; ------------------------------------------------------------
[mcp:demo]
enabled = true
transport = stdio
command = python
args = -m xAgent.mcp_servers.demo_server
"""


# ============================================================
# 首次运行：生成配置文件
# ============================================================

@dataclass
class ConfigBootstrap:
    """配置引导结果 —— TUI 用它在启动时决定是否弹窗。"""

    path: Path
    created: bool = False
    seeded_from: Optional[Path] = None   # 从旧配置文件迁移了哪些值
    error: str = ""

    @property
    def is_mock(self) -> bool:
        return not self.api_key

    api_key: str = ""
    provider: str = "mock"


#: 最近一次 ensure_config_file 的结果（App 启动时读它决定弹不弹窗）
_LAST_BOOTSTRAP: Optional[ConfigBootstrap] = None


def get_bootstrap() -> Optional[ConfigBootstrap]:
    return _LAST_BOOTSTRAP


def _legacy_values(path: Path) -> Dict[str, str]:
    """从旧格式 config.ini 里读出 key / model（能读多少读多少）。"""
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read(path, encoding="utf-8")
    except configparser.Error:
        return {}

    values: Dict[str, str] = {}
    for section, option, target in (
        ("qianfan", "baidu_qianfan_api_key", "api_key"),
        ("llm", "api_key", "api_key"),
        ("qianfan", "model", "model"),
        ("llm", "model", "model"),
        ("qianfan", "base_url", "base_url"),
        ("llm", "base_url", "base_url"),
    ):
        if parser.has_option(section, option):
            raw = (parser.get(section, option, fallback="") or "").strip()
            if raw and target not in values:
                values[target] = raw
    return values


def write_default_config(path: Path, values: Optional[Dict[str, str]] = None) -> Path:
    """把模板写到 path（父目录不存在就建）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    merged = {
        "provider": "mock",
        "api_key": "",
        "model": "mock",
    }
    merged.update({k: v for k, v in (values or {}).items() if v})
    # 有 key 就自动切到真实 provider，省得用户还要改两处
    if merged["api_key"]:
        merged["provider"] = "qianfan"
        if merged["model"] in ("", "mock"):
            merged["model"] = DEFAULTS["llm"]["search_model"]

    text = CONFIG_TEMPLATE
    for key, value in merged.items():
        text = text.replace(f"@@{key.upper()}@@", str(value))
    path.write_text(text, encoding="utf-8")
    return path


def ensure_config_file(path: Optional[Path] = None) -> ConfigBootstrap:
    """
    确保配置文件存在；不存在就生成一份完整的（mock 值）。

    迁移策略：如果包里还留着旧版 config.ini，并且里面有 API Key，
    就把它写进新文件 —— 免得用户升级一次 key 就丢了。
    """
    global _LAST_BOOTSTRAP

    target = Path(path) if path is not None else primary_config_path()
    if target.is_file():
        _LAST_BOOTSTRAP = ConfigBootstrap(path=target, created=False, seeded_from=None)
        return _LAST_BOOTSTRAP

    seeded: Optional[Path] = None
    values: Dict[str, str] = {}
    if LEGACY_CONFIG_INI.is_file() and LEGACY_CONFIG_INI.resolve() != target.resolve():
        values = _legacy_values(LEGACY_CONFIG_INI)
        if values.get("api_key"):
            seeded = LEGACY_CONFIG_INI

    try:
        write_default_config(target, values)
    except OSError as exc:
        _LAST_BOOTSTRAP = ConfigBootstrap(
            path=target, created=False, error=f"无法创建配置文件：{exc}"
        )
        return _LAST_BOOTSTRAP

    _LAST_BOOTSTRAP = ConfigBootstrap(
        path=target,
        created=True,
        seeded_from=seeded,
        api_key=values.get("api_key", ""),
        provider="qianfan" if values.get("api_key") else "mock",
    )
    return _LAST_BOOTSTRAP


# ============================================================
# 配置对象
# ============================================================

@dataclass
class AppConfig:
    """一次解析后的完整配置。字段名 = [section] option 的可读版本。"""

    path: Path = field(default_factory=primary_config_path)

    # [llm]
    provider: str = "mock"
    api_key: str = ""
    base_url: str = "https://qianfan.baidubce.com/v2"
    model: str = "mock"
    search_url: str = "https://qianfan.baidubce.com/v2/ai_search/chat/completions"
    search_model: str = "ernie-5.1"
    timeout: int = 60

    # [agent]
    max_model_calls: int = 8

    # [context]
    context_window: int = 0
    compact_threshold: float = 0.7
    compact_target_tokens: int = 5000
    archive_dir: str = ".agents/context"
    recall_matches: int = 5
    recall_max_chars: int = 1500

    # [session]
    session_dir: str = ".agents/sessions"
    auto_save: bool = True
    agents_md_enabled: bool = True
    agents_md_file: str = "AGENTS.md"

    # [ui]
    sidebar_width: int = 42
    card_preview_chars: int = 120
    show_command_palette: bool = True

    # [mcp]
    mcp_enabled: bool = True
    mcp_timeout: int = 20
    mcp_servers: List[MCPServerConfig] = field(default_factory=list)

    #: 解析过程中遇到的问题（缺文件、脏值等），UI 可以展示
    warnings: List[str] = field(default_factory=list)

    # ---------- 便捷属性 ----------
    @property
    def use_mock(self) -> bool:
        """没有 key 或 provider=mock 时走本地 MockProvider。"""
        return self.provider.lower() == "mock" or not self.api_key

    @property
    def llm_label(self) -> str:
        return "mock" if self.use_mock else self.model


# ---------- 小工具：把脏值吃掉，不因为一个手滑让程序崩 ----------

def _get(parser: configparser.ConfigParser, section: str, option: str, default: str) -> str:
    if not parser.has_section(section):
        return default
    try:
        value = parser.get(section, option, fallback=default)
    except configparser.Error:
        return default
    return (value or "").strip() or default


def _get_keep_blank(parser: configparser.ConfigParser, section: str, option: str, default: str = "") -> str:
    """和后者的区别：允许显式留空（例如 api_key =）。"""
    if not parser.has_section(section):
        return default
    try:
        return (parser.get(section, option, fallback=default) or "").strip()
    except configparser.Error:
        return default


def _to_int(raw: str, default: int, warnings: List[str], label: str) -> int:
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        warnings.append(f"{label} 不是整数（{raw!r}），已用默认值 {default}")
        return default


def _to_float(raw: str, default: float, warnings: List[str], label: str) -> float:
    try:
        return float(str(raw).strip())
    except (TypeError, ValueError):
        warnings.append(f"{label} 不是数字（{raw!r}），已用默认值 {default}")
        return default


def _to_bool(raw: str, default: bool, warnings: List[str], label: str) -> bool:
    text = str(raw).strip().lower()
    if text in ("1", "true", "yes", "on", "y"):
        return True
    if text in ("0", "false", "no", "off", "n"):
        return False
    if not text:
        return default
    warnings.append(f"{label} 不是布尔值（{raw!r}），已用默认值 {default}")
    return default


def _parse_mcp_servers(
    parser: configparser.ConfigParser,
    warnings: List[str],
) -> List[MCPServerConfig]:
    """读 [mcp] servers + 所有 [mcp:名称] 段。"""
    names = [
        item.strip()
        for item in _get(parser, "mcp", "servers", "").split(",")
        if item.strip()
    ]

    sections = [
        section.split(":", 1)[1].strip()
        for section in parser.sections()
        if section.lower().startswith("mcp:") and section.split(":", 1)[1].strip()
    ]

    # servers 留空 = 用全部 [mcp:*] 段
    selected = names or sections
    for name in selected:
        if name not in sections:
            warnings.append(f"MCP 服务器 {name!r} 没有对应的 [mcp:{name}] 配置段，已跳过")

    servers: List[MCPServerConfig] = []
    for name in selected:
        section = f"mcp:{name}"
        if not parser.has_section(section):
            continue
        enabled = _to_bool(
            _get(parser, section, "enabled", "true"), True, warnings, f"[{section}] enabled"
        )
        transport = _get(parser, section, "transport", "stdio").lower()
        args_raw = _get_keep_blank(parser, section, "args", "")
        # 两种写法都支持：`-m x.y`（按空格）或 `-m, x.y`（按逗号）
        if "," in args_raw:
            args = [part.strip() for part in args_raw.split(",") if part.strip()]
        elif args_raw.strip():
            try:
                args = shlex.split(args_raw)
            except ValueError:
                args = args_raw.split()
        else:
            args = []
        env_raw = _get_keep_blank(parser, section, "env", "")
        env: Dict[str, str] = {}
        for pair in env_raw.split(","):
            if "=" in pair:
                key, value = pair.split("=", 1)
                if key.strip():
                    env[key.strip()] = value.strip()

        servers.append(
            MCPServerConfig(
                name=name,
                transport=transport,
                command=_get_keep_blank(parser, section, "command", ""),
                args=args,
                env=env,
                url=_get_keep_blank(parser, section, "url", ""),
                enabled=enabled,
                timeout=_to_int(
                    _get(parser, section, "timeout", str(DEFAULTS["mcp"]["timeout"])),
                    int(DEFAULTS["mcp"]["timeout"]),
                    warnings,
                    f"[{section}] timeout",
                ),
            )
        )
    return servers


def load_config(path: Optional[Path] = None) -> AppConfig:
    """
    读取配置。文件不存在也返回一份「全默认 + mock」的配置（不在这里创建文件，
    创建是 ensure_config_file 的职责，先把两件事分开）。
    """
    target = Path(path) if path is not None else resolve_config_path()
    parser = configparser.ConfigParser(interpolation=None)
    warnings: List[str] = []

    exists = target.is_file()
    if exists:
        try:
            parser.read(target, encoding="utf-8")
        except configparser.Error as exc:
            warnings.append(f"config.ini 解析失败（已全部使用默认值）：{exc}")
            parser = configparser.ConfigParser(interpolation=None)
    else:
        warnings.append(f"未找到配置文件：{target}，本次使用内置默认值")

    # ---- [llm] ----
    api_key = _get_keep_blank(parser, "llm", "api_key")
    if not api_key and parser.has_option("qianfan", "baidu_qianfan_api_key"):
        api_key = (parser.get("qianfan", "baidu_qianfan_api_key", fallback="") or "").strip()

    env_key = os.environ.get("QIANFAN_API_KEY", "").strip()
    if env_key:
        api_key = env_key

    provider = _get(parser, "llm", "provider", DEFAULTS["llm"]["provider"]).lower()
    provider_explicit = parser.has_option("llm", "provider")
    if api_key and provider == "mock":
        # 填了 key 还用 mock，多半是忘了改 provider —— 帮用户一把
        provider = "qianfan"
        if provider_explicit:
            warnings.append("检测到 api_key 但 provider=mock，已自动切换为 qianfan")

    model = _get(parser, "llm", "model", DEFAULTS["llm"]["model"])
    if model == "mock" and api_key:
        model = _get(parser, "llm", "search_model", DEFAULTS["llm"]["search_model"])

    cfg = AppConfig(
        path=target,
        provider=provider,
        api_key=api_key or os.environ.get("XAGENT_API_KEY", "").strip(),
        base_url=os.environ.get("QIANFAN_BASE_URL", "").strip()
        or _get(parser, "llm", "base_url", DEFAULTS["llm"]["base_url"]),
        model=os.environ.get("QIANFAN_MODEL", "").strip() or model,
        search_url=_get(parser, "llm", "search_url", DEFAULTS["llm"]["search_url"]),
        search_model=os.environ.get("QIANFAN_SEARCH_MODEL", "").strip()
        or _get(parser, "llm", "search_model", DEFAULTS["llm"]["search_model"]),
        timeout=_to_int(
            _get(parser, "llm", "timeout", DEFAULTS["llm"]["timeout"]),
            int(DEFAULTS["llm"]["timeout"]), warnings, "[llm] timeout",
        ),
        # ---- [agent] ----
        max_model_calls=_to_int(
            _get(parser, "agent", "max_model_calls", DEFAULTS["agent"]["max_model_calls"]),
            int(DEFAULTS["agent"]["max_model_calls"]), warnings, "[agent] max_model_calls",
        ),
        # ---- [context] ----
        context_window=_to_int(
            os.environ.get("XAGENT_CONTEXT_WINDOW", "").strip()
            or _get(parser, "context", "window", DEFAULTS["context"]["window"]),
            int(DEFAULTS["context"]["window"]), warnings, "[context] window",
        ),
        compact_threshold=_to_float(
            _get(parser, "context", "compact_threshold", DEFAULTS["context"]["compact_threshold"]),
            float(DEFAULTS["context"]["compact_threshold"]), warnings, "[context] compact_threshold",
        ),
        compact_target_tokens=_to_int(
            _get(parser, "context", "target_tokens", DEFAULTS["context"]["target_tokens"]),
            int(DEFAULTS["context"]["target_tokens"]), warnings, "[context] target_tokens",
        ),
        archive_dir=_get(parser, "context", "archive_dir", DEFAULTS["context"]["archive_dir"]),
        recall_matches=_to_int(
            _get(parser, "context", "recall_matches", DEFAULTS["context"]["recall_matches"]),
            int(DEFAULTS["context"]["recall_matches"]), warnings, "[context] recall_matches",
        ),
        recall_max_chars=_to_int(
            _get(parser, "context", "recall_max_chars", DEFAULTS["context"]["recall_max_chars"]),
            int(DEFAULTS["context"]["recall_max_chars"]), warnings, "[context] recall_max_chars",
        ),
        # ---- [session] ----
        session_dir=_get(parser, "session", "dir", DEFAULTS["session"]["dir"]),
        auto_save=_to_bool(
            _get(parser, "session", "auto_save", DEFAULTS["session"]["auto_save"]),
            True, warnings, "[session] auto_save",
        ),
        agents_md_enabled=_to_bool(
            _get(parser, "session", "agents_md", DEFAULTS["session"]["agents_md"]),
            True, warnings, "[session] agents_md",
        ),
        agents_md_file=_get(parser, "session", "agents_md_file", DEFAULTS["session"]["agents_md_file"]),
        # ---- [ui] ----
        sidebar_width=_to_int(
            _get(parser, "ui", "sidebar_width", DEFAULTS["ui"]["sidebar_width"]),
            int(DEFAULTS["ui"]["sidebar_width"]), warnings, "[ui] sidebar_width",
        ),
        card_preview_chars=_to_int(
            _get(parser, "ui", "card_preview_chars", DEFAULTS["ui"]["card_preview_chars"]),
            int(DEFAULTS["ui"]["card_preview_chars"]), warnings, "[ui] card_preview_chars",
        ),
        show_command_palette=_to_bool(
            _get(parser, "ui", "show_command_palette", DEFAULTS["ui"]["show_command_palette"]),
            True, warnings, "[ui] show_command_palette",
        ),
        # ---- [mcp] ----
        mcp_enabled=_to_bool(
            _get(parser, "mcp", "enabled", DEFAULTS["mcp"]["enabled"]),
            True, warnings, "[mcp] enabled",
        ),
        mcp_timeout=_to_int(
            _get(parser, "mcp", "timeout", DEFAULTS["mcp"]["timeout"]),
            int(DEFAULTS["mcp"]["timeout"]), warnings, "[mcp] timeout",
        ),
        mcp_servers=_parse_mcp_servers(parser, warnings),
        warnings=warnings,
    )

    # 夹一下明显不合理的值，避免 UI 被搞崩
    cfg.sidebar_width = max(20, min(cfg.sidebar_width, 120))
    cfg.max_model_calls = max(1, min(cfg.max_model_calls, 50))
    cfg.compact_threshold = min(max(cfg.compact_threshold, 0.1), 0.98)
    cfg.mcp_timeout = max(3, min(cfg.mcp_timeout, 300))
    return cfg


# ---------- 进程内缓存 ----------

_CONFIG: Optional[AppConfig] = None


def get_config(reload: bool = False, path: Optional[Path] = None) -> AppConfig:
    """拿全局配置。第一次调用时解析，之后复用（UI 里四处取配置，别每次读盘）。"""
    global _CONFIG
    if _CONFIG is None or reload or path is not None:
        _CONFIG = load_config(path)
    return _CONFIG


def set_config(cfg: AppConfig) -> AppConfig:
    """测试 / 热重载用：直接替换缓存。"""
    global _CONFIG
    _CONFIG = cfg
    return _CONFIG


def reload_config(path: Optional[Path] = None) -> AppConfig:
    """重新读盘（改了 config.ini 想立刻生效时用）。"""
    global _CONFIG, CONFIG_INI
    _CONFIG = None
    CONFIG_INI = Path(path).resolve() if path is not None else resolve_config_path()
    cfg = get_config(reload=True, path=path)
    sync_module_constants()
    return cfg


def sync_module_constants() -> None:
    """
    把最新配置同步给「按值 import」的模块。

    tools.py 是 `from .config import CONFIG_INI` 这种拿的，重新读盘后
    它手里的还是旧对象；这里回填一次，避免搜索工具读错文件。
    """
    tools = sys.modules.get("xAgent.core.tools")
    if tools is None:
        return
    cfg = get_config()
    for name, value in (
        ("CONFIG_INI", CONFIG_INI),
        ("QIANFAN_SEARCH_URL", cfg.search_url),
        ("QIANFAN_SEARCH_MODEL", cfg.search_model),
    ):
        if hasattr(tools, name):
            setattr(tools, name, value)


# ============================================================
# 兼容旧代码的模块级常量（导入时求值，别在运行期改它们）
# ============================================================

_INITIAL = get_config()

QIANFAN_API_KEY: str = _INITIAL.api_key
QIANFAN_BASE_URL: str = _INITIAL.base_url
QIANFAN_MODEL: str = _INITIAL.model
QIANFAN_SEARCH_URL: str = _INITIAL.search_url
QIANFAN_SEARCH_MODEL: str = _INITIAL.search_model
CONTEXT_WINDOW_OVERRIDE: int = _INITIAL.context_window
CONFIG_ERROR: str = _INITIAL.warnings[0] if _INITIAL.warnings else ""


def read_search_api_key() -> str:
    """每次调用重新读取 API Key，运行中修改 config.ini 无需重启。"""
    env_value = os.environ.get("QIANFAN_API_KEY", "").strip()
    if env_value:
        return env_value

    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read(CONFIG_INI, encoding="utf-8")
    except configparser.Error as exc:
        raise RuntimeError(f"config.ini 解析失败：{exc}") from exc

    key = ""
    if parser.has_option("qianfan", "baidu_qianfan_api_key"):
        key = parser.get("qianfan", "baidu_qianfan_api_key", fallback="")
    if not key and parser.has_option("llm", "api_key"):
        key = parser.get("llm", "api_key", fallback="")
    return (key or "").strip()


def python_command() -> str:
    """MCP 配置里 command=python 时用当前解释器，避免 PATH 里没 python。"""
    return sys.executable or "python"
