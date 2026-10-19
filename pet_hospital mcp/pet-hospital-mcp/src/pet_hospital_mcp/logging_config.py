"""Structured JSON logging with recursive PII redaction.

The MCP service logs one JSON object per record with at least these
fields: ``timestamp``, ``tool_name``, ``params``, ``status``,
``duration_ms``. Any sensitive value nested inside the record (including
inside ``params``) is redacted before it reaches the handler, so raw
owner phone numbers, addresses and chip numbers never leave the process.

Redaction is recursive: it walks dicts and lists and masks the values of
any key whose lowercased name is in :data:`SENSITIVE_KEYS`. Both the
camelCase (``ownerPhone``) and snake_case (``owner_phone``) spellings are
covered, and so are the substrings ``phone``, ``addr`` and ``chip`` for
robustness against future field names.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import time
from typing import Any

# Exact key names (after lowercasing and stripping) that must be masked.
SENSITIVE_KEYS: frozenset[str] = frozenset({
    "ownerphone", "owner_phone",
    "owneraddr", "owner_addr",
    "chipno", "chip_no",
})

# Substrings that flag an arbitrary key as sensitive even if it is not
# in the exact set above (e.g. ``ownerPhone2``, ``shipping_addr``).
SENSITIVE_SUBSTRINGS: tuple[str, ...] = ("phone", "addr", "chip")

_MASK = "***REDACTED***"


def _is_sensitive_key(key: str) -> bool:
    if not isinstance(key, str):
        return False
    lowered = key.lower()
    if lowered in SENSITIVE_KEYS:
        return True
    return any(sub in lowered for sub in SENSITIVE_SUBSTRINGS)


def redact(value: Any) -> Any:
    """Recursively mask sensitive values inside ``value``.

    Returns a shallow-ish copy: dicts and lists are rebuilt, primitives
    are returned as-is. The original is never mutated.
    """
    if isinstance(value, dict):
        return {k: (_MASK if _is_sensitive_key(k) else redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value)
    return value


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per log record on a single line.

    The base fields are ``timestamp``, ``level``, ``logger``,
    ``message``. Any ``extra`` keys passed to the log call are merged in
    and redacted before serialisation.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": time.strftime(
                "%Y-%m-%dT%H:%M:%S%z", time.localtime(record.created)
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in {
                "name", "msg", "args", "levelname", "levelno", "pathname",
                "filename", "module", "exc_info", "exc_text", "stack_info",
                "lineno", "funcName", "created", "msecs", "relativeCreated",
                "thread", "threadName", "processName", "process",
                "taskName",
            }:
                continue
            payload[key] = value
        payload = redact(payload)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_logging(level: str = "INFO") -> logging.Logger:
    """Configure stderr JSON logging and return the package logger."""
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    logger = logging.getLogger("pet_hospital_mcp")
    logger.setLevel(root.level)
    return logger


__all__ = ["JsonFormatter", "redact", "setup_logging", "SENSITIVE_KEYS"]
