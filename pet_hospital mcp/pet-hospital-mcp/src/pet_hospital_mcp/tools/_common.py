"""Shared plumbing for every MCP tool module.

Three things are identical across all tools and live here so the tool
modules stay readable:

1. **Allowed enum values** mirrored from the Go backend
   (:data:`SPECIES_VALUES`, :data:`STATUS_VALUES`, ...). Only values the
   Go side actually validates are turned into a ``Literal``; fields the
   backend accepts freely (e.g. ``category``) stay plain strings so the
   MCP layer never rejects data the API would have stored.
2. **Pet-id validation.** Ids travel inside the URL path, so they are
   constrained to a safe charset before ever reaching httpx.
3. **:func:`run_tool`** — the single place that times a call, writes the
   structured JSON log line (params redacted), normalises every failure
   into the unified error envelope, and converts a shape mismatch from
   the backend into ``BACKEND_INVALID_RESPONSE``.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from ..errors import (
    BACKEND_INVALID_RESPONSE,
    PetHospitalError,
    internal_error,
    validation_error,
)
from ..logging_config import redact

logger = logging.getLogger("pet_hospital_mcp.tools")

# --- Enums mirrored from internal/model/model.go -------------------------

SPECIES_VALUES: tuple[str, ...] = (
    "犬", "猫", "兔", "鸟", "仓鼠", "爬宠", "其他",
)
STATUS_VALUES: tuple[str, ...] = (
    "待就诊", "就诊中", "住院中", "已康复", "慢性病随访",
)
SORTBY_VALUES: tuple[str, ...] = (
    "id", "name", "ownerName", "species", "doctor", "disease", "status",
    "totalCost", "visitCount", "createdAt", "updatedAt",
)
ORDER_VALUES: tuple[str, ...] = ("asc", "desc")

# Charge categories suggested by the backend's seed generator. Not an
# enum: ``c.Category`` is never validated in Go, so anything is stored.
CHARGE_CATEGORY_HINTS: tuple[str, ...] = (
    "检查", "药品", "手术", "住院", "疫苗", "护理", "其他",
)

# --- Pet id --------------------------------------------------------------

# PET-000001 style ids, plus a little headroom for hand-made ones.
PET_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def validate_pet_id(pet_id: str) -> str:
    """Return ``pet_id`` unchanged, or raise a ``VALIDATION_ERROR``.

    Rejecting anything that is not ``[A-Za-z0-9_-]`` keeps ids from
    reshaping the upstream URL (``../admin/seed``, ``x?force=true``) and
    keeps error messages predictable for the model.
    """
    if not isinstance(pet_id, str):
        raise validation_error(
            "'pet_id' must be a string.",
            {"pet_id_type": type(pet_id).__name__},
        )
    candidate = pet_id.strip()
    if not candidate:
        raise validation_error("'pet_id' must not be empty.")
    if not PET_ID_PATTERN.fullmatch(candidate):
        raise validation_error(
            "'pet_id' may only contain letters, digits, hyphens and "
            "underscores (e.g. 'PET-000001').",
            {"pet_id": candidate},
        )
    return candidate


# --- Response date fields ------------------------------------------------

_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def validate_date(value: str | None, field: str) -> str | None:
    """Check a ``YYYY-MM-DD`` date string; ``None`` passes through.

    Raises :class:`ValueError` on purpose: this helper is only ever
    called from a Pydantic ``field_validator``, and Pydantic turns a
    ``ValueError`` into a proper :class:`ValidationError` with the field
    location attached — which is what the SDK needs in order to report
    the bad argument precisely. (``validate_pet_id`` raises
    :class:`PetHospitalError` instead, because it is called from tool
    body code rather than a validator.)
    """
    if value is None:
        return None
    candidate = value.strip()
    if not _DATE_ONLY.fullmatch(candidate):
        raise ValueError(f"'{field}' must be an ISO date (YYYY-MM-DD).")
    return candidate


# --- The shared tool wrapper --------------------------------------------

M = TypeVar("M", bound=BaseModel)


async def run_tool(
    *,
    tool_name: str,
    params: dict[str, Any],
    op: Callable[[], Awaitable[dict[str, Any]]],
    parse: Callable[[dict[str, Any]], M],
    shape_label: str,
) -> M:
    """Run one backend call under consistent logging and error handling.

    Args:
        tool_name: Stable tool name, used as ``tool_name`` in the log line.
        params: Raw call arguments; redacted before logging.
        op: Zero-arg coroutine performing the HTTP call, returning the
            envelope's ``data`` object.
        parse: Maps ``data`` to the tool's success model.
        shape_label: Human-readable name of the expected shape, used in
            the ``BACKEND_INVALID_RESPONSE`` message.

    Raises:
        PetHospitalError: on any failure, already carrying the unified
            ``{"error": {...}}`` envelope in its string form.
    """
    start = time.perf_counter()
    safe_params = redact(params)

    def _log(message: str, status: str, **extra: Any) -> None:
        logger.info(
            message,
            extra={
                "tool_name": tool_name,
                "params": safe_params,
                "status": status,
                "duration_ms": int((time.perf_counter() - start) * 1000),
                **extra,
            },
        )

    _log(f"{tool_name} called", "started")
    data: dict[str, Any] = {}
    try:
        data = await op()
        result = parse(data)
    except PetHospitalError as exc:
        logger.warning(
            f"{tool_name} failed",
            extra={
                "tool_name": tool_name,
                "params": safe_params,
                "status": "error",
                "duration_ms": int((time.perf_counter() - start) * 1000),
                "error_code": exc.code,
            },
        )
        raise
    except ValidationError as exc:
        # The backend answered, but not in the shape this tool promised.
        logger.warning(
            f"{tool_name} shape mismatch",
            extra={
                "tool_name": tool_name,
                "params": safe_params,
                "status": "invalid_response",
                "duration_ms": int((time.perf_counter() - start) * 1000),
            },
        )
        raise PetHospitalError(
            BACKEND_INVALID_RESPONSE,
            f"Backend response did not match the expected {shape_label} shape.",
            {
                "data_keys": list(data.keys()) if isinstance(data, dict) else [],
                "errors": [
                    {"loc": list(err.get("loc", ())), "type": err.get("type", "")}
                    for err in exc.errors(include_url=False)
                ],
            },
        ) from exc
    except Exception as exc:  # noqa: BLE001 - last-resort normalisation
        logger.exception(
            f"{tool_name} internal error",
            extra={
                "tool_name": tool_name,
                "params": safe_params,
                "status": "internal_error",
                "duration_ms": int((time.perf_counter() - start) * 1000),
            },
        )
        raise internal_error(
            f"An unexpected error occurred while running {tool_name}.",
            {"error_type": type(exc).__name__},
        ) from exc

    _log(f"{tool_name} succeeded", "ok")
    return result


def to_json_body(model: BaseModel, *, exclude_unset: bool = False) -> dict[str, Any]:
    """Serialise a validated input model into the Go request body.

    ``exclude_unset=True`` is what makes PATCH a real partial update:
    only the fields the caller actually supplied are sent, so an omitted
    ``doctor`` keeps its current value instead of being cleared.
    """
    return model.model_dump(mode="json", exclude_unset=exclude_unset, exclude_none=True)


__all__ = [
    "SPECIES_VALUES", "STATUS_VALUES", "SORTBY_VALUES", "ORDER_VALUES",
    "CHARGE_CATEGORY_HINTS",
    "PET_ID_PATTERN", "validate_pet_id", "validate_date",
    "run_tool", "to_json_body",
]
