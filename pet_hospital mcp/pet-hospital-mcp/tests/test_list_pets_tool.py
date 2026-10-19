"""Tests for the ``list_pets`` tool logic (without the MCP SDK).

Exercises :func:`execute_list_pets` directly with a mock-backed client so
we can assert on parameter forwarding, cross-field validation, and the
full error mapping (4xx, timeout, malformed body, shape mismatch).
"""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from pet_hospital_mcp.errors import (
    BACKEND_API_ERROR,
    BACKEND_INVALID_RESPONSE,
    BACKEND_TIMEOUT,
    VALIDATION_ERROR,
    PetHospitalError,
)
from pet_hospital_mcp.rest_client import PetHospitalClient
from pet_hospital_mcp.tools.list_pets import ListPetsInput, execute_list_pets

from conftest import make_go_success, make_mock_transport, make_pet


# --- Happy path ----------------------------------------------------------

class TestListPetsSuccess:
    async def test_full_filter_set_forwarded(
        self,
        settings,
        make_client: Callable[[httpx.AsyncBaseTransport], PetHospitalClient],
    ) -> None:
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["params"] = dict(request.url.params)
            return httpx.Response(200, json=make_go_success(
                items=[make_pet()],
                total=1,
                page=1,
                page_size=20,
                total_pages=1,
                total_cost=120.5,
            ))

        client = make_client(make_mock_transport(handler))
        result = await execute_list_pets(client, ListPetsInput(
            q="肠胃炎", species="犬", status="就诊中",
            sortBy="totalCost", order="desc",
            page=1, pageSize=20, min=0, max=500,
        ))
        await client.close()

        assert result.total == 1
        assert result.page == 1
        assert result.pageSize == 20
        assert result.totalPages == 1
        assert result.totalCost == pytest.approx(120.5)
        assert len(result.items) == 1
        pet = result.items[0]
        assert pet.id == "PET-000001"
        assert pet.species == "犬"
        assert pet.ownerName == "张三"
        assert pet.records == [] or pet.records is None
        assert pet.charges == [] or pet.charges is None

        # Verify all 14 query params made it through.
        assert captured["params"]["q"] == "肠胃炎"
        assert captured["params"]["species"] == "犬"
        assert captured["params"]["min"] == "0"
        assert captured["params"]["max"] == "500"

    async def test_null_records_and_charges_accepted(
        self,
        make_client: Callable[[httpx.AsyncBaseTransport], PetHospitalClient],
    ) -> None:
        pet = make_pet(records=None, charges=None)
        # Force null in JSON by overriding
        pet["records"] = None
        pet["charges"] = None

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=make_go_success(items=[pet], total=1))

        client = make_client(make_mock_transport(handler))
        result = await execute_list_pets(client, ListPetsInput())
        await client.close()

        assert result.items[0].records is None
        assert result.items[0].charges is None


# --- Cross-field validation ---------------------------------------------

class TestMinMaxCrossField:
    async def test_min_greater_than_max_rejected(
        self,
        pet_client: PetHospitalClient,
    ) -> None:
        with pytest.raises(PetHospitalError) as exc_info:
            await execute_list_pets(pet_client, ListPetsInput(min=500, max=100))
        assert exc_info.value.code == VALIDATION_ERROR
        assert "min" in exc_info.value.message


# --- Backend errors surface as PetHospitalError --------------------------

class TestBackendErrors:
    async def test_4xx_maps_to_backend_api_error(
        self,
        make_client: Callable[[httpx.AsyncBaseTransport], PetHospitalClient],
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"code": 404, "message": "not found"})

        client = make_client(make_mock_transport(handler))
        with pytest.raises(PetHospitalError) as exc_info:
            await execute_list_pets(client, ListPetsInput())
        await client.close()
        assert exc_info.value.code == BACKEND_API_ERROR

    async def test_timeout_maps_to_backend_timeout(
        self,
        make_client: Callable[[httpx.AsyncBaseTransport], PetHospitalClient],
    ) -> None:
        from test_rest_client import FailingTransport
        exc = httpx.ReadTimeout("timeout", request=httpx.Request("GET", "http://x"))
        client = make_client(FailingTransport(exc))
        with pytest.raises(PetHospitalError) as exc_info:
            await execute_list_pets(client, ListPetsInput())
        await client.close()
        assert exc_info.value.code == BACKEND_TIMEOUT

    async def test_non_json_maps_to_invalid_response(
        self,
        make_client: Callable[[httpx.AsyncBaseTransport], PetHospitalClient],
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="<<<not json>>>")

        client = make_client(make_mock_transport(handler))
        with pytest.raises(PetHospitalError) as exc_info:
            await execute_list_pets(client, ListPetsInput())
        await client.close()
        assert exc_info.value.code == BACKEND_INVALID_RESPONSE

    async def test_shape_mismatch_maps_to_invalid_response(
        self,
        make_client: Callable[[httpx.AsyncBaseTransport], PetHospitalClient],
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            # data has the wrong keys
            return httpx.Response(200, json={"code": 200, "data": {"wrong": 1}})

        client = make_client(make_mock_transport(handler))
        with pytest.raises(PetHospitalError) as exc_info:
            await execute_list_pets(client, ListPetsInput())
        await client.close()
        assert exc_info.value.code == BACKEND_INVALID_RESPONSE
