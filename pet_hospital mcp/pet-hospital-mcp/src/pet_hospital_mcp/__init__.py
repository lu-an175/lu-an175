"""Pet Hospital MCP service.

A stateless MCP server (SDK 2.x, protocol 2026-07-28) that exposes the
Go Pet Hospital REST API as MCP tools. Currently provides one tool:
``list_pets``.
"""

from __future__ import annotations

__version__ = "0.1.0"

from .config import Settings, load_settings
from .errors import (
    ALL_CODES,
    BACKEND_API_ERROR,
    BACKEND_INVALID_RESPONSE,
    BACKEND_TIMEOUT,
    BACKEND_UNAVAILABLE,
    INTERNAL_ERROR,
    VALIDATION_ERROR,
    ErrorPayload,
    ErrorResponse,
    PetHospitalError,
)
from .rest_client import PetHospitalClient
from .server import create_app, create_mcp_server, run

__all__ = [
    "__version__",
    "Settings", "load_settings",
    "PetHospitalClient",
    "create_app", "create_mcp_server", "run",
    "PetHospitalError", "ErrorPayload", "ErrorResponse",
    "VALIDATION_ERROR", "BACKEND_TIMEOUT", "BACKEND_UNAVAILABLE",
    "BACKEND_API_ERROR", "BACKEND_INVALID_RESPONSE", "INTERNAL_ERROR",
    "ALL_CODES",
]
