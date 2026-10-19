"""Shared test fixtures.

Every test uses :class:`httpx.MockTransport` to serve a scripted backend
response, so no test ever touches the real Go service.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest

from pet_hospital_mcp.config import Settings
from pet_hospital_mcp.rest_client import PetHospitalClient


TEST_BACKEND = "http://test-backend.local"


def make_settings(**overrides: Any) -> Settings:
    base = dict(
        pet_hospital_base_url=TEST_BACKEND,
        mcp_host="127.0.0.1",
        mcp_port=8765,
        backend_timeout_seconds=2.0,
        backend_retries=1,
        backend_backoff_seconds=0.0,
    )
    base.update(overrides)
    return Settings(**base)


def make_pet(
    pet_id: str = "PET-000001",
    name: str = "小黄",
    species: str = "犬",
    status: str = "就诊中",
    total_cost: float = 120.5,
    records: list[dict[str, Any]] | None = None,
    charges: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a Go-shaped pet dict for test fixtures."""
    return {
        "id": pet_id,
        "name": name,
        "species": species,
        "breed": "金毛",
        "gender": "公",
        "ageMonths": 24,
        "color": "金黄",
        "chipNo": "CHIP-001",
        "ownerName": "张三",
        "ownerPhone": "13800000000",
        "ownerAddr": "北京市朝阳区",
        "doctor": "李医生",
        "disease": "肠胃炎",
        "status": status,
        "allergy": "",
        "note": "",
        "records": records if records is not None else [],
        "charges": charges if charges is not None else [],
        "totalCost": total_cost,
        "visitCount": len(records) if records is not None else 0,
        "createdAt": "2025-01-01T00:00:00Z",
        "updatedAt": "2025-01-02T00:00:00Z",
    }


def make_go_success(
    items: list[dict[str, Any]] | None = None,
    total: int = 0,
    page: int = 1,
    page_size: int = 20,
    total_pages: int = 0,
    total_cost: float = 0.0,
) -> dict[str, Any]:
    """Build the Go API success envelope body."""
    return {
        "code": 200,
        "message": "ok",
        "data": {
            "items": items if items is not None else [],
            "total": total,
            "page": page,
            "pageSize": page_size,
            "totalPages": total_pages,
            "totalCost": total_cost,
        },
        "time": "2025-01-01T00:00:00Z",
    }


def make_go_error(status_code: int, message: str = "bad request") -> dict[str, Any]:
    """Build a Go API error envelope body."""
    return {"code": status_code, "message": message, "data": None, "time": "2025-01-01T00:00:00Z"}


HandlerFn = Callable[[httpx.Request], httpx.Response]


def make_mock_transport(handler: HandlerFn) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


@pytest.fixture
def settings() -> Settings:
    return make_settings()


@pytest.fixture
def mock_transport_factory() -> Callable[[HandlerFn], httpx.MockTransport]:
    return make_mock_transport


@pytest.fixture
def make_client(settings: Settings) -> Callable[[httpx.AsyncBaseTransport], PetHospitalClient]:
    def _make(transport: httpx.AsyncBaseTransport) -> PetHospitalClient:
        return PetHospitalClient(settings, transport=transport)
    return _make


@pytest.fixture
async def pet_client(make_client: Callable[[httpx.AsyncBaseTransport], PetHospitalClient]) -> AsyncIterator[PetHospitalClient]:
    """A client backed by a transport that returns an empty success page."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=make_go_success(items=[], total=0, page=1, page_size=20, total_pages=0, total_cost=0.0),
        )
    client = make_client(make_mock_transport(handler))
    yield client
    await client.close()
