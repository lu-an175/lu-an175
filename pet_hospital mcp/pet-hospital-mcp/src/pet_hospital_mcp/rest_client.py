"""Async HTTP client for the upstream Go Pet Hospital REST API.

This is the only component that talks to the Go service. It owns:

* a single reusable :class:`httpx.AsyncClient` (kept small and bounded),
* per-request timeout,
* bounded retry with exponential back-off for transient network errors,
  but **only** for reads and idempotent writes — a POST that timed out
  may or may not have landed upstream, so retrying it could create a
  duplicate record. Writes fail fast and let the caller decide,
* translation of every upstream failure into a
  :class:`PetHospitalError` so the MCP layer never leaks httpx / Python
  stack traces to the client.

Every Go endpoint answers with the same envelope::

    {"code": 200, "message": "ok", "data": {...}, "time": "..."}

so ``_request_json`` returns ``data`` and validates the envelope once
for all callers.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx

from .config import Settings
from .errors import (
    BACKEND_API_ERROR,
    BACKEND_INVALID_RESPONSE,
    BACKEND_TIMEOUT,
    BACKEND_UNAVAILABLE,
    INTERNAL_ERROR,
    PetHospitalError,
    not_found,
)

logger = logging.getLogger("pet_hospital_mcp.rest")

# Methods that are safe to retry after a transport-level failure.
# POST is deliberately excluded: a timed-out create may already have
# been committed by the backend, and a blind retry would duplicate it.
RETRYABLE_METHODS: frozenset[str] = frozenset({"GET", "DELETE"})


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

    # -- reads ------------------------------------------------------------

    async def list_pets(self, params: dict[str, Any]) -> dict[str, Any]:
        """Call ``GET /api/v1/pets`` and return the parsed ``data`` object.

        ``params`` carries the already-validated query parameters exactly
        as the Go API expects them. The return value is the ``data``
        field of the Go success envelope::

            {"items": [...], "total": N, "page": 1, "pageSize": 20,
             "totalPages": K, "totalCost": X}
        """
        return await self._request_json("GET", "/api/v1/pets", params=params)

    async def get_pet(self, pet_id: str) -> dict[str, Any]:
        """Call ``GET /api/v1/pets/{id}`` and return the full pet record."""
        return await self._request_json("GET", _pet_path(pet_id))

    async def get_pet_summary(self, pet_id: str) -> dict[str, Any]:
        """Call ``GET /api/v1/pets/{id}/summary``.

        Returns the flat cost/visit rollup: total cost, per-category and
        per-doctor breakdown, first/last visit and a text history.
        """
        return await self._request_json("GET", f"{_pet_path(pet_id)}/summary")

    async def get_stats(self, top: int = 5) -> dict[str, Any]:
        """Call ``GET /api/v1/stats`` with an optional top-spender count."""
        return await self._request_json("GET", "/api/v1/stats", params={"top": top})

    # -- writes -----------------------------------------------------------

    async def create_pet(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Call ``POST /api/v1/pets`` and return the created pet record.

        The backend assigns the ``PET-000001``-style id and ignores any
        client-supplied one. Answered with HTTP 201.
        """
        return await self._request_json("POST", "/api/v1/pets", json_body=payload)

    async def patch_pet(self, pet_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        """Call ``PATCH /api/v1/pets/{id}`` with a partial update.

        Only the keys present in ``patch`` are applied upstream; omitted
        fields keep their current value. (``PUT`` is full-replace and
        would wipe ``records``/``charges`` — the MCP surface therefore
        does not expose it.)
        """
        return await self._request_json("PATCH", _pet_path(pet_id), json_body=patch)

    async def delete_pet(self, pet_id: str) -> dict[str, Any]:
        """Call ``DELETE /api/v1/pets/{id}``.

        Returns ``{"id": "<deleted id>"}``. Deleting a missing id raises
        a ``NOT_FOUND`` error rather than succeeding silently.
        """
        return await self._request_json("DELETE", _pet_path(pet_id))

    async def add_medical_record(
        self, pet_id: str, record: dict[str, Any]
    ) -> dict[str, Any]:
        """Call ``POST /api/v1/pets/{id}/records``.

        Appends one visit record and returns the whole updated pet, so
        the caller sees the new ``visitCount`` and the doctor rollover
        without a second request.
        """
        return await self._request_json(
            "POST", f"{_pet_path(pet_id)}/records", json_body=record
        )

    async def add_charge(self, pet_id: str, charge: dict[str, Any]) -> dict[str, Any]:
        """Call ``POST /api/v1/pets/{id}/charges``.

        Appends one charge line and returns the whole updated pet with a
        recalculated ``totalCost``.
        """
        return await self._request_json(
            "POST", f"{_pet_path(pet_id)}/charges", json_body=charge
        )

    # -- internal ---------------------------------------------------------

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Perform one JSON call and return the envelope's ``data`` object.

        Retries transport-level failures (timeout / connect error) only
        for :data:`RETRYABLE_METHODS`. Every other outcome is mapped to a
        :class:`PetHospitalError` exactly once, so callers never have to
        inspect httpx objects.
        """
        method = method.upper()
        attempts = (self._settings.backend_retries + 1) if method in RETRYABLE_METHODS else 1
        last_exc: PetHospitalError | None = None

        for attempt in range(1, attempts + 1):
            try:
                response = await self._client.request(
                    method,
                    path,
                    params=params,
                    json=json_body,
                )
            except httpx.TimeoutException as exc:
                last_exc = PetHospitalError(
                    BACKEND_TIMEOUT,
                    f"Upstream call to {path} timed out after "
                    f"{self._settings.backend_timeout_seconds}s (attempt {attempt}/{attempts}).",
                    {"path": path, "method": method, "attempt": attempt},
                )
                logger.warning(
                    "backend timeout",
                    extra={
                        "path": path, "method": method,
                        "attempt": attempt, "error": str(exc),
                    },
                )
                if method not in RETRYABLE_METHODS:
                    # The write may or may not have landed. Say so,
                    # because the caller must not blindly retry it.
                    last_exc.details["retry_safe"] = False
                    raise last_exc from exc
                await self._backoff(attempt)
                continue
            except httpx.ConnectError as exc:
                last_exc = PetHospitalError(
                    BACKEND_UNAVAILABLE,
                    f"Could not reach the Pet Hospital backend at "
                    f"{self._settings.pet_hospital_base_url} "
                    f"(attempt {attempt}/{attempts}).",
                    {
                        "base_url": self._settings.pet_hospital_base_url,
                        "path": path,
                        "method": method,
                        "attempt": attempt,
                    },
                )
                logger.warning(
                    "backend unreachable",
                    extra={
                        "path": path, "method": method,
                        "attempt": attempt, "error": str(exc),
                    },
                )
                if method not in RETRYABLE_METHODS:
                    # A refused connection definitely did not land, so
                    # the caller can safely retry this one.
                    last_exc.details["retry_safe"] = True
                    raise last_exc from exc
                await self._backoff(attempt)
                continue
            except httpx.HTTPError as exc:
                # Any other httpx transport error. Treat as internal: we
                # don't know what happened, so don't retry blindly.
                raise PetHospitalError(
                    INTERNAL_ERROR,
                    "Unexpected transport error talking to the backend.",
                    {"path": path, "method": method, "error_type": type(exc).__name__},
                ) from exc

            # Transport succeeded; any failure from here is not retried.
            if response.status_code == 404:
                upstream_msg = self._safe_extract_message(response)
                raise not_found(
                    f"No record was found at {path}.",
                    {
                        "path": path,
                        "method": method,
                        "status_code": 404,
                        "upstream_message": upstream_msg,
                    },
                )

            if response.status_code >= 400:
                upstream_msg = self._safe_extract_message(response)
                raise PetHospitalError(
                    BACKEND_API_ERROR,
                    f"Pet Hospital backend returned HTTP {response.status_code}: "
                    f"{upstream_msg}",
                    {
                        "path": path,
                        "method": method,
                        "status_code": response.status_code,
                        "upstream_message": upstream_msg,
                    },
                )

            return self._unwrap_envelope(response, path=path, method=method)

        # All retries exhausted.
        assert last_exc is not None
        raise last_exc

    def _unwrap_envelope(
        self, response: httpx.Response, *, path: str, method: str
    ) -> dict[str, Any]:
        """Validate the Go response envelope and return its ``data`` object."""
        try:
            body = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise PetHospitalError(
                BACKEND_INVALID_RESPONSE,
                "Backend returned a non-JSON body to a JSON request.",
                {"path": path, "method": method, "body_snippet": response.text[:200]},
            ) from exc

        if not isinstance(body, dict):
            raise PetHospitalError(
                BACKEND_INVALID_RESPONSE,
                "Backend returned a JSON value that is not an object.",
                {"path": path, "method": method, "body_type": type(body).__name__},
            )

        if "data" not in body:
            raise PetHospitalError(
                BACKEND_INVALID_RESPONSE,
                "Backend response envelope is missing the 'data' field.",
                {"path": path, "method": method, "body_keys": list(body.keys())},
            )
        data = body["data"]
        if not isinstance(data, dict):
            raise PetHospitalError(
                BACKEND_INVALID_RESPONSE,
                "Backend 'data' field is not an object.",
                {"path": path, "method": method, "data_type": type(data).__name__},
            )
        return data

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


def _pet_path(pet_id: str) -> str:
    """Build ``/api/v1/pets/{id}`` with the id percent-encoded.

    The tool layer already rejects malformed ids, but encoding here means
    a stray ``/`` or ``?`` can never reshape the upstream URL.
    """
    from urllib.parse import quote

    return f"/api/v1/pets/{quote(str(pet_id), safe='')}"


__all__ = ["PetHospitalClient", "RETRYABLE_METHODS"]
