"""Runtime configuration for the Pet Hospital MCP service.

All settings are read from environment variables so the service stays
stateless and 12-factor friendly. Nothing here is persisted to disk.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _get_bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """Resolved service configuration.

    Attributes:
        pet_hospital_base_url: Base URL of the upstream Go REST API.
            Defaults to ``http://127.0.0.1:8080``.
        mcp_host: Network interface to bind the MCP Streamable HTTP
            endpoint to. Defaults to ``127.0.0.1`` (loopback only) because
            the teaching scenario has no auth/CORS.
        mcp_port: TCP port for the MCP endpoint. Defaults to ``8765``.
        backend_timeout_seconds: Per-request timeout for upstream calls.
        backend_retries: How many times to retry a timed-out or
            connection-failed upstream call before giving up. The total
            attempt count is ``backend_retries + 1``.
        backend_backoff_seconds: Base delay (in seconds) for exponential
            back-off between retries.
    """

    pet_hospital_base_url: str
    mcp_host: str
    mcp_port: int
    backend_timeout_seconds: float
    backend_retries: int
    backend_backoff_seconds: float

    @property
    def mcp_url(self) -> str:
        """The public URL of the MCP endpoint (use in Inspector / clients)."""
        return f"http://{self.mcp_host}:{self.mcp_port}/mcp"


def load_settings() -> Settings:
    """Build a :class:`Settings` from the current environment.

    Environment variables:

    * ``PET_HOSPITAL_BASE_URL``  (default ``http://127.0.0.1:8080``)
    * ``MCP_HOST``                (default ``127.0.0.1``)
    * ``MCP_PORT``                (default ``8765``)
    * ``PET_HOSPITAL_TIMEOUT``    (default ``10`` seconds)
    * ``PET_HOSPITAL_RETRIES``    (default ``2`` retries)
    * ``PET_HOSPITAL_BACKOFF``    (default ``0.25`` seconds)
    """
    base = os.environ.get("PET_HOSPITAL_BASE_URL", "http://127.0.0.1:8080").rstrip("/")
    host = os.environ.get("MCP_HOST", "127.0.0.1")
    port = int(os.environ.get("MCP_PORT", "8765"))
    timeout = float(os.environ.get("PET_HOSPITAL_TIMEOUT", "10"))
    retries = int(os.environ.get("PET_HOSPITAL_RETRIES", "2"))
    backoff = float(os.environ.get("PET_HOSPITAL_BACKOFF", "0.25"))
    return Settings(
        pet_hospital_base_url=base,
        mcp_host=host,
        mcp_port=port,
        backend_timeout_seconds=timeout,
        backend_retries=max(0, retries),
        backend_backoff_seconds=max(0.0, backoff),
    )


__all__ = ["Settings", "load_settings"]
