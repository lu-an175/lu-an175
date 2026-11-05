"""Behaviour tests for the Phase 2 tools.

One class per tool. Each test drives the public ``execute_*`` coroutine
with a scripted :class:`httpx.MockTransport`, so nothing here touches the
real Go service. Also covered: the retry policy that distinguishes reads
from writes, and the full tool registry built by ``create_app``.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from pet_hospital_mcp.config import Settings
from pet_hospital_mcp.errors import (
    BACKEND_API_ERROR,
    BACKEND_TIMEOUT,
    BACKEND_UNAVAILABLE,
    NOT_FOUND,
    VALIDATION_ERROR,
    PetHospitalError,
)
from pet_hospital_mcp.rest_client import PetHospitalClient
from pet_hospital_mcp.tools.add_charge import ChargeInput, execute_add_charge
from pet_hospital_mcp.tools.add_medical_record import (
    MedicalRecordInput,
    execute_add_medical_record,
)
from pet_hospital_mcp.tools.create_pet import CreatePetInput, execute_create_pet
from pet_hospital_mcp.tools.delete_pet import execute_delete_pet
from pet_hospital_mcp.tools.get_pet import execute_get_pet
from pet_hospital_mcp.tools.get_pet_summary import execute_get_pet_summary
from pet_hospital_mcp.tools.get_stats import execute_get_stats
from pet_hospital_mcp.tools.update_pet import UpdatePetInput, execute_update_pet

from conftest import (
    make_go_data,
    make_go_error,
    make_mock_transport,
    make_pet,
    make_settings,
    make_stats,
    make_summary,
)

ClientFactory = Callable[[httpx.AsyncBaseTransport], PetHospitalClient]


def _client(factory: ClientFactory, handler) -> PetHospitalClient:
    return factory(make_mock_transport(handler))


def _pet_envelope(**overrides: Any) -> dict[str, Any]:
    return make_go_data(make_pet(**overrides), status=201)


# --- get_pet -------------------------------------------------------------

class TestGetPet:
    async def test_happy_path_returns_full_record(self, make_client: ClientFactory) -> None:
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["method"] = request.method
            captured["path"] = request.url.path
            return httpx.Response(200, json=make_go_data(make_pet()))

        client = _client(make_client, handler)
        pet = await execute_get_pet(client, "PET-000001")
        await client.close()

        assert captured["method"] == "GET"
        assert captured["path"] == "/api/v1/pets/PET-000001"
        assert pet.id == "PET-000001"
        assert pet.ownerName == "张三"

    async def test_missing_id_maps_to_not_found(self, make_client: ClientFactory) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json=make_go_error(404, "id=PET-999999"))

        client = _client(make_client, handler)
        with pytest.raises(PetHospitalError) as exc_info:
            await execute_get_pet(client, "PET-999999")
        await client.close()

        assert exc_info.value.code == NOT_FOUND
        assert exc_info.value.details["status_code"] == 404

    async def test_malformed_id_rejected_before_any_request(
        self, make_client: ClientFactory
    ) -> None:
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url.path)
            return httpx.Response(200, json=make_go_data(make_pet()))

        client = _client(make_client, handler)
        with pytest.raises(PetHospitalError) as exc_info:
            await execute_get_pet(client, "../admin/seed")
        await client.close()

        assert exc_info.value.code == VALIDATION_ERROR
        assert calls == [], "no HTTP call may happen for an invalid id"


# --- create_pet ----------------------------------------------------------

class TestCreatePet:
    async def test_body_forwarded_and_created_record_returned(
        self, make_client: ClientFactory
    ) -> None:
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["method"] = request.method
            captured["path"] = request.url.path
            captured["body"] = json.loads(request.content)
            return httpx.Response(201, json=_pet_envelope())

        client = _client(make_client, handler)
        created = await execute_create_pet(client, CreatePetInput(
            name="旺财", ownerName="张三", ownerPhone="13800001111",
            disease="急性肠胃炎", doctor="李医生", species="犬", ageMonths=36,
        ))
        await client.close()

        assert captured["method"] == "POST"
        assert captured["path"] == "/api/v1/pets"
        body = captured["body"]
        assert body["name"] == "旺财"
        assert body["species"] == "犬"
        assert body["ageMonths"] == 36
        # Defaults are materialised, not omitted.
        assert body["status"] == "待就诊"
        # Unset optionals are not sent at all.
        assert "breed" not in body
        assert "note" not in body
        # Backend-assigned id comes back to the caller.
        assert created.id == "PET-000001"

    async def test_phone_with_separators_accepted(self) -> None:
        payload = CreatePetInput(
            name="旺财", ownerName="张三", ownerPhone="+86 (138) 0000-1111",
            disease="肠胃炎", doctor="李医生",
        )
        assert payload.ownerPhone == "+86 (138) 0000-1111"

    async def test_backend_validation_error_surfaces(
        self, make_client: ClientFactory
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, json=make_go_error(400, "ownerPhone 位数不合法"))

        client = _client(make_client, handler)
        with pytest.raises(PetHospitalError) as exc_info:
            await execute_create_pet(client, CreatePetInput(
                name="旺财", ownerName="张三", ownerPhone="1234567",
                disease="肠胃炎", doctor="李医生",
            ))
        await client.close()

        assert exc_info.value.code == BACKEND_API_ERROR
        assert "ownerPhone" in exc_info.value.details["upstream_message"]


# --- update_pet ----------------------------------------------------------

class TestUpdatePet:
    async def test_only_supplied_fields_are_sent(
        self, make_client: ClientFactory
    ) -> None:
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["method"] = request.method
            captured["path"] = request.url.path
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json=make_go_data(make_pet(status="已康复")))

        client = _client(make_client, handler)
        updated = await execute_update_pet(
            client, "PET-000001", UpdatePetInput(status="已康复")
        )
        await client.close()

        assert captured["method"] == "PATCH"
        assert captured["path"] == "/api/v1/pets/PET-000001"
        assert captured["body"] == {"status": "已康复"}
        assert updated.status == "已康复"

    async def test_empty_patch_rejected_without_calling_backend(
        self, make_client: ClientFactory
    ) -> None:
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url.path)
            return httpx.Response(200, json=make_go_data(make_pet()))

        client = _client(make_client, handler)
        with pytest.raises(PetHospitalError) as exc_info:
            await execute_update_pet(client, "PET-000001", UpdatePetInput())
        await client.close()

        assert exc_info.value.code == VALIDATION_ERROR
        assert "at least one field" in exc_info.value.message
        assert calls == []

    async def test_unknown_field_rejected_by_schema(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            UpdatePetInput(totalCost=999.0)  # type: ignore[call-arg]


# --- delete_pet ----------------------------------------------------------

class TestDeletePet:
    async def test_happy_path(self, make_client: ClientFactory) -> None:
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["method"] = request.method
            captured["path"] = request.url.path
            return httpx.Response(200, json=make_go_data({"id": "PET-000001"}))

        client = _client(make_client, handler)
        result = await execute_delete_pet(client, "PET-000001")
        await client.close()

        assert captured["method"] == "DELETE"
        assert captured["path"] == "/api/v1/pets/PET-000001"
        assert result.id == "PET-000001"

    async def test_missing_id_is_an_error_not_a_silent_success(
        self, make_client: ClientFactory
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json=make_go_error(404, "id=PET-404"))

        client = _client(make_client, handler)
        with pytest.raises(PetHospitalError) as exc_info:
            await execute_delete_pet(client, "PET-404")
        await client.close()

        assert exc_info.value.code == NOT_FOUND


# --- add_medical_record --------------------------------------------------

class TestAddMedicalRecord:
    async def test_record_appended_and_visit_count_returned(
        self, make_client: ClientFactory
    ) -> None:
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["method"] = request.method
            captured["path"] = request.url.path
            captured["body"] = json.loads(request.content)
            return httpx.Response(201, json=_pet_envelope(
                records=[{"id": "MR-1", "visitDate": "2025-03-01", "doctor": "李医生",
                          "diagnosis": "肠胃炎", "charge": 380.0, "createdAt": "x"}],
            ))

        client = _client(make_client, handler)
        pet = await execute_add_medical_record(client, "PET-000001", MedicalRecordInput(
            diagnosis="肠胃炎", doctor="李医生", symptoms="呕吐",
            prescription=["阿莫西林"], charge=380.0,
        ))
        await client.close()

        assert captured["method"] == "POST"
        assert captured["path"] == "/api/v1/pets/PET-000001/records"
        assert captured["body"]["diagnosis"] == "肠胃炎"
        assert captured["body"]["prescription"] == ["阿莫西林"]
        assert pet.visitCount == 1
        assert pet.records is not None and pet.records[0].doctor == "李医生"

    async def test_blank_diagnosis_rejected_by_schema(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            MedicalRecordInput(diagnosis="   ", doctor="李医生")

    async def test_bad_visit_date_rejected(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            MedicalRecordInput(diagnosis="肠胃炎", doctor="李医生", visitDate="2025/03/01")


# --- add_charge ----------------------------------------------------------

class TestAddCharge:
    async def test_charge_appended_and_total_recalculated(
        self, make_client: ClientFactory
    ) -> None:
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["method"] = request.method
            captured["path"] = request.url.path
            captured["body"] = json.loads(request.content)
            return httpx.Response(201, json=_pet_envelope(total_cost=300.5))

        client = _client(make_client, handler)
        pet = await execute_add_charge(client, "PET-000001", ChargeInput(
            item="血常规检查", amount=180.0, category="检查", doctor="李医生",
        ))
        await client.close()

        assert captured["method"] == "POST"
        assert captured["path"] == "/api/v1/pets/PET-000001/charges"
        assert captured["body"] == {
            "item": "血常规检查", "amount": 180.0,
            "category": "检查", "doctor": "李医生",
        }
        assert pet.totalCost == pytest.approx(300.5)

    async def test_category_defaults_to_other(self) -> None:
        assert ChargeInput(item="疫苗", amount=120).category == "其他"

    async def test_negative_amount_rejected(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ChargeInput(item="疫苗", amount=-1)

    async def test_nan_amount_rejected(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ChargeInput(item="疫苗", amount=float("nan"))


# --- get_pet_summary -----------------------------------------------------

class TestGetPetSummary:
    async def test_rollup_fields_parsed(self, make_client: ClientFactory) -> None:
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["path"] = request.url.path
            return httpx.Response(200, json=make_go_data(make_summary()))

        client = _client(make_client, handler)
        summary = await execute_get_pet_summary(client, "PET-000001")
        await client.close()

        assert captured["path"] == "/api/v1/pets/PET-000001/summary"
        assert summary.totalCost == pytest.approx(560.0)
        assert summary.visitCount == 2
        assert summary.costByCategory == {"检查": 180.0, "药品": 380.0}
        assert summary.avgCostPerVisit == pytest.approx(280.0)
        assert summary.lastVisit == "2025-02-01"

    async def test_null_breakdowns_accepted(self, make_client: ClientFactory) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=make_go_data(make_summary(
                costByCategory=None, costByDoctor=None, totalCost=0.0,
                visitCount=0, chargeCount=0, historyText="",
            )))

        client = _client(make_client, handler)
        summary = await execute_get_pet_summary(client, "PET-000001")
        await client.close()

        assert summary.costByCategory is None
        assert summary.costByDoctor is None


# --- get_stats -----------------------------------------------------------

class TestGetStats:
    async def test_top_parameter_forwarded(self, make_client: ClientFactory) -> None:
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["path"] = request.url.path
            captured["params"] = dict(request.url.params)
            return httpx.Response(200, json=make_go_data(make_stats()))

        client = _client(make_client, handler)
        stats = await execute_get_stats(client, 10)
        await client.close()

        assert captured["path"] == "/api/v1/stats"
        assert captured["params"]["top"] == "10"
        assert stats.totalPets == 308
        assert stats.bySpecies == {"犬": 120, "猫": 98}
        assert stats.revenueByDoctor is not None

    async def test_null_maps_and_top_spenders_accepted(
        self, make_client: ClientFactory
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=make_go_data({
                "totalPets": 0, "totalRecords": 0, "totalCharges": 0,
                "totalRevenue": 0, "averageCost": 0, "maxCost": 0,
                "bySpecies": None, "byStatus": None, "byDoctor": None,
                "revenueByDoctor": None, "topSpenders": None,
                "logGarbagePct": 0,
            }))

        client = _client(make_client, handler)
        stats = await execute_get_stats(client, 5)
        await client.close()

        assert stats.totalPets == 0
        assert stats.bySpecies is None
        assert stats.topSpenders is None

    async def test_top_spenders_are_parsed_as_pets(
        self, make_client: ClientFactory
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=make_go_data(
                make_stats(top_spenders=[make_pet(pet_id="PET-000009", total_cost=9999.0)])
            ))

        client = _client(make_client, handler)
        stats = await execute_get_stats(client, 1)
        await client.close()

        assert stats.topSpenders is not None
        assert stats.topSpenders[0].id == "PET-000009"


# --- Retry policy: reads retry, writes do not ----------------------------

class _CountingFailTransport(httpx.AsyncBaseTransport):
    """Counts attempts and always fails with the given exception."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc
        self.attempts = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.attempts += 1
        raise self._exc


class _FlakyTransport(httpx.AsyncBaseTransport):
    """Fails the first ``fails`` attempts, then succeeds with ``payload``."""

    def __init__(self, fails: int, payload: dict[str, Any]) -> None:
        self._fails = fails
        self._payload = payload
        self.attempts = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.attempts += 1
        if self.attempts <= self._fails:
            raise httpx.ConnectError("connection refused", request=request)
        return httpx.Response(200, json=self._payload)


class TestRetryPolicy:
    async def test_get_is_retried(self, make_client: ClientFactory) -> None:
        transport = _FlakyTransport(fails=1, payload=make_go_data(make_pet()))
        client = PetHospitalClient(make_settings(backend_retries=1), transport=transport)
        pet = await execute_get_pet(client, "PET-000001")
        await client.close()

        assert pet.id == "PET-000001"
        assert transport.attempts == 2

    async def test_post_is_not_retried_on_timeout(
        self, make_client: ClientFactory
    ) -> None:
        exc = httpx.ReadTimeout("timeout", request=httpx.Request("POST", "http://x"))
        transport = _CountingFailTransport(exc)
        client = PetHospitalClient(make_settings(backend_retries=2), transport=transport)
        with pytest.raises(PetHospitalError) as exc_info:
            await execute_create_pet(client, CreatePetInput(
                name="旺财", ownerName="张三", ownerPhone="13800001111",
                disease="肠胃炎", doctor="李医生",
            ))
        await client.close()

        assert exc_info.value.code == BACKEND_TIMEOUT
        # A timed-out write may already have landed upstream: retrying
        # would risk a duplicate archive, so exactly one attempt is made.
        assert transport.attempts == 1
        assert exc_info.value.details["retry_safe"] is False

    async def test_post_flag_marks_connection_failure_as_retryable(
        self, make_client: ClientFactory
    ) -> None:
        transport = _CountingFailTransport(httpx.ConnectError("refused"))
        client = PetHospitalClient(make_settings(backend_retries=2), transport=transport)
        with pytest.raises(PetHospitalError) as exc_info:
            await execute_create_pet(client, CreatePetInput(
                name="旺财", ownerName="张三", ownerPhone="13800001111",
                disease="肠胃炎", doctor="李医生",
            ))
        await client.close()

        assert exc_info.value.code == BACKEND_UNAVAILABLE
        assert transport.attempts == 1
        assert exc_info.value.details["retry_safe"] is True


# --- Registry ------------------------------------------------------------

class TestToolRegistry:
    async def test_create_app_registers_all_nine_tools(self) -> None:
        from pet_hospital_mcp.server import create_app

        app, client = create_app(make_settings())
        try:
            tools = await app.state.mcp.list_tools()
        finally:
            await client.close()

        names = {t.name for t in tools}
        assert names == {
            "list_pets", "get_pet", "create_pet", "update_pet", "delete_pet",
            "add_medical_record", "add_charge", "get_pet_summary", "get_stats",
        }
