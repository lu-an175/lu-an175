"""Async HTTP client for the upstream Go Pet Hospital REST API.

This is the only component that talks to the Go service. It owns:

* a single reusable :class:`httpx.AsyncClient` (kept small and bounded),
* per-request timeout,
* bounded retry with exponential back-off for transient network errors,
* translation of every upstream failure into a
  :class:`PetHospitalError` so the MCP layer never leaks httpx / Python
  stack traces to the client.

The client is intentionally tiny: it only knows how to call
``GET /api/v1/pets``. Future tools add more methods on the same client.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator

import httpx

from .config import Settings
from .errors import (
    BACKEND_API_ERROR,
    BACKEND_INVALID_RESPONSE,
    BACKEND_TIMEOUT,
    BACKEND_UNAVAILABLE,
    INTERNAL_ERROR,
    PetHospitalError,
)

logger = logging.getLogger("pet_hospital_mcp.rest")


class PetHospitalClient:
    """Thin async wrapper over the Go Pet Hospital REST API.

    The instance owns one :class:`httpx.AsyncClient` and should be closed
    via :meth:`close` when the MCP server shuts down. Tests may pass a
    custom ``transport`` (e.g. :class:`httpx.MockTransport`) to avoid
    touching the real network.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._client = httpx.AsyncClient(
            base_url=settings.pet_hospital_base_url,
            timeout=httpx.Timeout(settings.backend_timeout_seconds),
            transport=transport,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "PetHospitalClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    # -- public surface ---------------------------------------------------

    async def list_pets(self, params: dict[str, Any]) -> dict[str, Any]:
        """Call ``GET /api/v1/pets`` and return the parsed ``data`` object.

        ``params`` carries the already-validated query parameters exactly
        as the Go API expects them. The return value is the ``data``
        field of the Go success envelope::

            {"items": [...], "total": N, "page": 1, "pageSize": 20,
             "totalPages": K, "totalCost": X}
        """
        return await self._get_json("/api/v1/pets", params=params)

    # -- internal ---------------------------------------------------------

    async def _get_json(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        attempts = self._settings.backend_retries + 1
        last_exc: PetHospitalError | None = None
        for attempt in range(1, attempts + 1):
            try:
                response = await self._client.get(path, params=params)
            except httpx.TimeoutException as exc:
                last_exc = PetHospitalError(
                    BACKEND_TIMEOUT,
                    f"Upstream call to {path} timed out after "
                    f"{self._settings.backend_timeout_seconds}s (attempt {attempt}/{attempts}).",
                    {"path": path, "attempt": attempt},
                )
                logger.warning(
                    "backend timeout",
                    extra={"path": path, "attempt": attempt, "error": str(exc)},
                )
                await self._backoff(attempt)
                continue
            except httpx.ConnectError as exc:
                last_exc = PetHospitalError(
                    BACKEND_UNAVAILABLE,
                    f"Could not reach the Pet Hospital backend at "
                    f"{self._settings.pet_hospital_base_url} "
                    f"(attempt {attempt}/{attempts}).",
                    {"base_url": self._settings.pet_hospital_base_url, "attempt": attempt},
                )
                logger.warning(
                    "backend unreachable",
                    extra={"path": path, "attempt": attempt, "error": str(exc)},
                )
                await self._backoff(attempt)
                continue
            except httpx.HTTPError as exc:
                # Any other httpx transport error. Treat as internal: we
                # don't know what happened, so don't retry blindly.
                raise PetHospitalError(
                    INTERNAL_ERROR,
                    "Unexpected transport error talking to the backend.",
                    {"path": path, "error_type": type(exc).__name__},
                ) from exc

            # Transport succeeded; any failure from here is not retried.
            if response.status_code >= 400:
                upstream_msg = self._safe_extract_message(response)
                raise PetHospitalError(
                    BACKEND_API_ERROR,
                    f"Pet Hospital backend returned HTTP {response.status_code}: "
                    f"{upstream_msg}",
                    {
                        "path": path,
                        "status_code": response.status_code,
                        "upstream_message": upstream_msg,
                    },
                )

            try:
                body = response.json()
            except (json.JSONDecodeError, ValueError) as exc:
                raise PetHospitalError(
                    BACKEND_INVALID_RESPONSE,
                    "Backend returned a non-JSON body to a JSON request.",
                    {"path": path, "body_snippet": response.text[:200]},
                ) from exc

            if not isinstance(body, dict):
                raise PetHospitalError(
                    BACKEND_INVALID_RESPONSE,
                    "Backend returned a JSON value that is not an object.",
                    {"path": path, "body_type": type(body).__name__},
                )

            if "data" not in body:
                raise PetHospitalError(
                    BACKEND_INVALID_RESPONSE,
                    "Backend response envelope is missing the 'data' field.",
                    {"path": path, "body_keys": list(body.keys())},
                )
            data = body["data"]
            if not isinstance(data, dict):
                raise PetHospitalError(
                    BACKEND_INVALID_RESPONSE,
                    "Backend 'data' field is not an object.",
                    {"path": path, "data_type": type(data).__name__},
                )
            return data

        # All retries exhausted.
        assert last_exc is not None
        raise last_exc

    async def _backoff(self, attempt: int) -> None:
        if attempt <= 0:
            return
        delay = self._settings.backend_backoff_seconds * (2 ** (attempt - 1))
        if delay > 0:
            await asyncio.sleep(delay)

    @staticmethod
    def _safe_extract_message(response: httpx.Response) -> str:
        try:
            body = response.json()
        except Exception:
            return response.text[:200]
        if isinstance(body, dict):
            for key in ("message", "error", "detail"):
                value = body.get(key)
                if isinstance(value, str):
                    return value
        return str(body)[:200]


__all__ = ["PetHospitalClient"]
