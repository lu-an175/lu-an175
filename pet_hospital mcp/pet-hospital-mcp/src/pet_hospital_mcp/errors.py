"""Unified error model for the Pet Hospital MCP service.

Every failure path -- invalid tool input, upstream timeout, bad JSON
from the backend, an unexpected Python exception -- is normalised into
the same wire shape::

    {
        "error": {
            "code": "ERROR_CODE",
            "message": "Human-readable explanation",
            "details": { ...optional context... }
        }
    }

The :class:`PetHospitalError` exception carries that shape and its
``__str__`` returns the JSON envelope, so when the MCP SDK 2.x wraps a
raised exception into an ``is_error=True`` tool result the structured
envelope survives intact inside the text content the model reads.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field


# --- Error codes ---------------------------------------------------------

VALIDATION_ERROR = "VALIDATION_ERROR"
BACKEND_TIMEOUT = "BACKEND_TIMEOUT"
BACKEND_UNAVAILABLE = "BACKEND_UNAVAILABLE"
BACKEND_API_ERROR = "BACKEND_API_ERROR"
BACKEND_INVALID_RESPONSE = "BACKEND_INVALID_RESPONSE"
INTERNAL_ERROR = "INTERNAL_ERROR"

ALL_CODES: frozenset[str] = frozenset({
    VALIDATION_ERROR,
    BACKEND_TIMEOUT,
    BACKEND_UNAVAILABLE,
    BACKEND_API_ERROR,
    BACKEND_INVALID_RESPONSE,
    INTERNAL_ERROR,
})


# --- Pydantic models -----------------------------------------------------

class ErrorPayload(BaseModel):
    """The ``error`` object inside the unified envelope."""

    code: str = Field(description="Stable machine-readable error code.")
    message: str = Field(description="Human-readable explanation.")
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional structured context about the failure.",
    )


class ErrorResponse(BaseModel):
    """The full unified error envelope::

        {"error": {"code": ..., "message": ..., "details": {...}}}
    """

    error: ErrorPayload


# --- Exception -----------------------------------------------------------

class PetHospitalError(Exception):
    """Raised by tool code to signal a failure the model should see.

    The MCP SDK 2.x catches any exception raised inside a tool and
    returns it as an ``is_error=True`` :class:`CallToolResult` whose
    text content is the exception's string form, so the JSON envelope
    produced by :meth:`to_json` reaches the model verbatim.
    """

    def __init__(
        self,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        if code not in ALL_CODES:
            raise ValueError(f"Unknown error code: {code!r}")
        self.code = code
        self.message = message
        self.details = dict(details or {})
        super().__init__(self.to_json())

    def to_envelope(self) -> ErrorResponse:
        return ErrorResponse(error=ErrorPayload(
            code=self.code,
            message=self.message,
            details=self.details,
        ))

    def to_json(self) -> str:
        return self.to_envelope().model_dump_json()


# --- Factory helpers -----------------------------------------------------

def validation_error(message: str, details: dict[str, Any] | None = None) -> PetHospitalError:
    return PetHospitalError(VALIDATION_ERROR, message, details)


def backend_timeout(message: str, details: dict[str, Any] | None = None) -> PetHospitalError:
    return PetHospitalError(BACKEND_TIMEOUT, message, details)


def backend_unavailable(message: str, details: dict[str, Any] | None = None) -> PetHospitalError:
    return PetHospitalError(BACKEND_UNAVAILABLE, message, details)


def backend_api_error(message: str, details: dict[str, Any] | None = None) -> PetHospitalError:
    return PetHospitalError(BACKEND_API_ERROR, message, details)


def backend_invalid_response(message: str, details: dict[str, Any] | None = None) -> PetHospitalError:
    return PetHospitalError(BACKEND_INVALID_RESPONSE, message, details)


def internal_error(message: str, details: dict[str, Any] | None = None) -> PetHospitalError:
    return PetHospitalError(INTERNAL_ERROR, message, details)


__all__ = [
    "VALIDATION_ERROR", "BACKEND_TIMEOUT", "BACKEND_UNAVAILABLE",
    "BACKEND_API_ERROR", "BACKEND_INVALID_RESPONSE", "INTERNAL_ERROR",
    "ALL_CODES",
    "ErrorPayload", "ErrorResponse", "PetHospitalError",
    "validation_error", "backend_timeout", "backend_unavailable",
    "backend_api_error", "backend_invalid_response", "internal_error",
]
