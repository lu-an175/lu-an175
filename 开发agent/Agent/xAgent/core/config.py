# -*- coding: utf-8 -*-
"""
xAgent.core.config —— 全局配置（LLM 接口 / 凭据）。

凭据来源（优先级从高到低）
    1. 环境变量
    2. 同目录 config.ini
    3. 空值（对应功能自动降级）

config.ini 格式
    [qianfan]
    baidu_qianfan_api_key = bce-v3/ALTAK-xxx/yyy

⚠️ 安全提示
    API Key 只放在 config.ini 或环境变量中，不要写进 .py 源码。
    提交代码前请把 config.ini 加入 .gitignore。
"""







from __future__ import annotations

import configparser
import os
from pathlib import Path

CONFIG_INI: Path = Path(__file__).resolve().parent / "config.ini"

_INI_SECTION = "qianfan"
_INI_KEY_OPTION = "baidu_qianfan_api_key"


def _read_ini() -> tuple[configparser.ConfigParser, str]:
    """读取 config.ini，返回 (parser, 错误描述)。"""
    parser = configparser.ConfigParser()
    try:
        found = parser.read(CONFIG_INI, encoding="utf-8")
    except configparser.Error as exc:
        return parser, f"config.ini 解析失败：{exc}"
    if not found:
        return parser, f"未找到配置文件：{CONFIG_INI}"
    return parser, ""


_INI, CONFIG_ERROR = _read_ini()


def _ini_value(option: str, env_name: str) -> str:
    """环境变量优先，其次 config.ini（包导入时读取一次）。"""
    env_value = os.environ.get(env_name, "").strip()
    if env_value:
        return env_value
    return _INI.get(_INI_SECTION, option, fallback="").strip()


def read_search_api_key() -> str:
    """每次调用重新读取 API Key，运行中修改 config.ini 无需重启。"""
    env_value = os.environ.get("QIANFAN_API_KEY", "").strip()
    if env_value:
        return env_value

    parser = configparser.ConfigParser()
    try:
        parser.read(CONFIG_INI, encoding="utf-8")
    except configparser.Error as exc:
        raise RuntimeError(f"config.ini 解析失败：{exc}") from exc
    return parser.get(_INI_SECTION, _INI_KEY_OPTION, fallback="").strip()


# ============================================================
# 百度千帆（OpenAI 兼容 v2 端点）
# ============================================================

QIANFAN_API_KEY: str = _ini_value(_INI_KEY_OPTION, "QIANFAN_API_KEY")

QIANFAN_BASE_URL: str = os.environ.get(
    "QIANFAN_BASE_URL",
    "https://qianfan.baidubce.com/v2",
)

QIANFAN_MODEL: str = os.environ.get(
    "QIANFAN_MODEL",
    "ernie-5.1",
)

# 智能搜索生成接口
QIANFAN_SEARCH_URL: str = os.environ.get(
    "QIANFAN_SEARCH_URL",
    "https://qianfan.baidubce.com/v2/ai_search/chat/completions",
)

QIANFAN_SEARCH_MODEL: str = os.environ.get(
    "QIANFAN_SEARCH_MODEL",
    "ernie-5.1",
)
