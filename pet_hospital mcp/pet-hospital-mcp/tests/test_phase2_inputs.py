"""Validation tests for the shared Phase 2 helpers.

``_common`` is the single gate every new tool goes through, so its two
validators get their own focused tests: a pet id that reaches httpx
unchanged could reshape the upstream URL, and a bad date would be
silently stored by the Go backend.
"""

from __future__ import annotations

import pytest

from pet_hospital_mcp.errors import VALIDATION_ERROR, PetHospitalError
from pet_hospital_mcp.tools._common import (
    PET_ID_PATTERN,
    to_json_body,
    validate_date,
    validate_pet_id,
)


class TestPetIdValidation:
    def test_realistic_ids_accepted(self) -> None:
        for pet_id in ("PET-000001", "PET-999999", "abc_123", "A"):
            assert validate_pet_id(pet_id) == pet_id

    def test_surrounding_whitespace_stripped(self) -> None:
        assert validate_pet_id("  PET-000001  ") == "PET-000001"

    def test_empty_rejected(self) -> None:
        with pytest.raises(PetHospitalError) as exc_info:
            validate_pet_id("   ")
        assert exc_info.value.code == VALIDATION_ERROR

    def test_empty_string_rejected(self) -> None:
        with pytest.raises(PetHospitalError):
            validate_pet_id("")

    def test_non_string_rejected(self) -> None:
        with pytest.raises(PetHospitalError) as exc_info:
            validate_pet_id(123)  # type: ignore[arg-type]
        assert exc_info.value.code == VALIDATION_ERROR

    @pytest.mark.parametrize("bad", [
        "../admin/seed",
        "x?force=true",
        "PET-000001/records",
        "PET 000001",
        "PET#1",
        "宠物",
        "a" * 65,
    ])
    def test_injection_shaped_ids_rejected(self, bad: str) -> None:
        with pytest.raises(PetHospitalError) as exc_info:
            validate_pet_id(bad)
        assert exc_info.value.code == VALIDATION_ERROR

    def test_pattern_is_anchored(self) -> None:
        # ``fullmatch`` is what the validator uses, so an id carrying a
        # slash cannot slip through as a prefix match.
        assert PET_ID_PATTERN.fullmatch("PET-1") is not None
        assert PET_ID_PATTERN.fullmatch("PET-1/../x") is None
        assert PET_ID_PATTERN.fullmatch("PET-1?force=true") is None


class TestDateValidation:
    def test_iso_date_accepted(self) -> None:
        assert validate_date("2025-03-01", "visitDate") == "2025-03-01"

    def test_none_passes_through(self) -> None:
        assert validate_date(None, "visitDate") is None

    @pytest.mark.parametrize("bad", ["2025/03/01", "01-03-2025", "2025-3-1", "20250301", ""])
    def test_other_formats_rejected(self, bad: str) -> None:
        # ValueError (not PetHospitalError) so Pydantic wraps it into a
        # ValidationError carrying the field location.
        with pytest.raises(ValueError) as exc_info:
            validate_date(bad, "visitDate")
        assert "visitDate" in str(exc_info.value)
        assert "YYYY-MM-DD" in str(exc_info.value)


class TestToJsonBody:
    def test_default_drops_none_values(self) -> None:
        from pet_hospital_mcp.tools.update_pet import UpdatePetInput

        body = to_json_body(UpdatePetInput(status="已康复", note=None))
        assert body == {"status": "已康复"}

    def test_exclude_unset_keeps_only_explicit_fields(self) -> None:
        from pet_hospital_mcp.tools.update_pet import UpdatePetInput

        body = to_json_body(UpdatePetInput(status="已康复"), exclude_unset=True)
        assert body == {"status": "已康复"}

    def test_create_defaults_are_materialised(self) -> None:
        from pet_hospital_mcp.tools.create_pet import CreatePetInput

        body = to_json_body(CreatePetInput(
            name="旺财", ownerName="张三", ownerPhone="13800001111",
            disease="肠胃炎", doctor="李医生",
        ))
        assert body["species"] == "其他"
        assert body["status"] == "待就诊"
        assert "breed" not in body
