"""Unit tests for :class:`PetHospitalClient`.

Each test wires a scripted :class:`httpx.MockTransport` (or a tiny
failing transport) so no real network call is ever made. The tests
cover: happy path parameter forwarding, 4xx/5xx handling, timeout,
connection failure, non-JSON body, and malformed envelope.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

from pet_hospital_mcp.errors import (
    BACKEND_API_ERROR,
    BACKEND_INVALID_RESPONSE,
    BACKEND_TIMEOUT,
    BACKEND_UNAVAILABLE,
    INTERNAL_ERROR,
    PetHospitalError,
)
from pet_hospital_mcp.rest_client import PetHospitalClient

from conftest import make_go_error, make_go_success, make_mock_transport


# --- Happy path: parameter forwarding ------------------------------------

class TestListPetsForwarding:
    async def test_path_and_all_params_forwarded(
        self,
        settings,
        make_client: Callable[[httpx.AsyncBaseTransport], PetHospitalClient],
    ) -> None:
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["params"] = dict(request.url.params)
            return httpx.Response(200, json=make_go_success())

        client = make_client(make_mock_transport(handler))
        await client.list_pets({
            "q": "肠胃炎",
            "name": "小黄",
            "ownerName": "张三",
            "ownerPhone": "13800000000",
            "species": "犬",
            "doctor": "李医生",
            "disease": "肠胃炎",
            "status": "就诊中",
            "min": 100,
            "max": 500,
            "sortBy": "totalCost",
            "order": "desc",
            "page": 2,
            "pageSize": 15,
        })
        await client.close()

        assert "/api/v1/pets" in captured["url"]
        params = captured["params"]
        assert params["q"] == "肠胃炎"
        assert params["name"] == "小黄"
        assert params["ownerName"] == "张三"
        assert params["ownerPhone"] == "13800000000"
        assert params["species"] == "犬"
        assert params["doctor"] == "李医生"
        assert params["disease"] == "肠胃炎"
        assert params["status"] == "就诊中"
        assert params["min"] == "100"
        assert params["max"] == "500"
        assert params["sortBy"] == "totalCost"
        assert params["order"] == "desc"
        assert params["page"] == "2"
        assert params["pageSize"] == "15"

    async def test_returns_data_field(
        self,
        pet_client: PetHospitalClient,
    ) -> None:
        data = await pet_client.list_pets({})
        assert isinstance(data, dict)
        assert "items" in data
        assert "total" in data


# --- 4xx / 5xx -----------------------------------------------------------

class TestBackendApiError:
    async def test_4xx_raises_backend_api_error(
        self,
        settings,
        make_client: Callable[[httpx.AsyncBaseTransport], PetHospitalClient],
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, json=make_go_error(400, "参数错误"))

        client = make_client(make_mock_transport(handler))
        with pytest.raises(PetHospitalError) as exc_info:
            await client.list_pets({"species": "鱼"})
        await client.close()

        assert exc_info.value.code == BACKEND_API_ERROR
        assert "400" in exc_info.value.message
        assert exc_info.value.details["status_code"] == 400

    async def test_500_raises_backend_api_error(
        self,
        make_client: Callable[[httpx.AsyncBaseTransport], PetHospitalClient],
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="internal server error")

        client = make_client(make_mock_transport(handler))
        with pytest.raises(PetHospitalError) as exc_info:
            await client.list_pets({})
        await client.close()

        assert exc_info.value.code == BACKEND_API_ERROR
        assert exc_info.value.details["status_code"] == 500


# --- Timeout and connection failures -------------------------------------

class FailingTransport(httpx.AsyncBaseTransport):
    """A transport that always raises a prescribed exception."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        raise self._exc


class TestTimeoutAndUnavailable:
    async def test_timeout_raises_backend_timeout(
        self,
        settings,
        make_client: Callable[[httpx.AsyncBaseTransport], PetHospitalClient],
    ) -> None:
        exc = httpx.ReadTimeout("read timed out", request=httpx.Request("GET", "http://x"))
        client = make_client(FailingTransport(exc))
        with pytest.raises(PetHospitalError) as exc_info:
            await client.list_pets({})
        await client.close()

        assert exc_info.value.code == BACKEND_TIMEOUT

    async def test_connect_error_raises_backend_unavailable(
        self,
        make_client: Callable[[httpx.AsyncBaseTransport], PetHospitalClient],
    ) -> None:
        exc = httpx.ConnectError("connection refused")
        client = make_client(FailingTransport(exc))
        with pytest.raises(PetHospitalError) as exc_info:
            await client.list_pets({})
        await client.close()

        assert exc_info.value.code == BACKEND_UNAVAILABLE


# --- Malformed responses --------------------------------------------------

class TestInvalidResponse:
    async def test_non_json_body(
        self,
        make_client: Callable[[httpx.AsyncBaseTransport], PetHospitalClient],
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="<html>not json</html>")

        client = make_client(make_mock_transport(handler))
        with pytest.raises(PetHospitalError) as exc_info:
            await client.list_pets({})
        await client.close()

        assert exc_info.value.code == BACKEND_INVALID_RESPONSE

    async def test_data_not_object(
        self,
        make_client: Callable[[httpx.AsyncBaseTransport], PetHospitalClient],
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"code": 200, "message": "ok", "data": [1, 2, 3]})

        client = make_client(make_mock_transport(handler))
        with pytest.raises(PetHospitalError) as exc_info:
            await client.list_pets({})
        await client.close()

        assert exc_info.value.code == BACKEND_INVALID_RESPONSE

    async def test_missing_data_key(
        self,
        make_client: Callable[[httpx.AsyncBaseTransport], PetHospitalClient],
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"code": 200, "message": "ok"})

        client = make_client(make_mock_transport(handler))
        with pytest.raises(PetHospitalError) as exc_info:
            await client.list_pets({})
        await client.close()

        assert exc_info.value.code == BACKEND_INVALID_RESPONSE
