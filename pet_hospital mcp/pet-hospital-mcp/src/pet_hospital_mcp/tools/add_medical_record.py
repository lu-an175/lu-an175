"""``add_medical_record`` MCP tool — append one visit record to a pet."""

from __future__ import annotations

import math
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..models import PetItem
from ..rest_client import PetHospitalClient
from ._common import run_tool, to_json_body, validate_date, validate_pet_id

TOOL_NAME = "add_medical_record"

TOOL_DESCRIPTION = (
    "Append one medical record (历史病历) to an existing pet archive.\n\n"
    "Backend: POST /api/v1/pets/{id}/records.\n\n"
    "Required: diagnosis, doctor.\n"
    "Optional: visitDate (YYYY-MM-DD, defaults to today server-side), "
    "symptoms, treatment, prescription, weightKg, temperature, followUp, "
    "charge.\n\n"
    "Side effects applied by the backend: visitCount increments, and the "
    "pet's primary doctor is rolled over to the doctor of this visit.\n\n"
    "Returns the whole updated pet record (including the new record and the "
    "recalculated visitCount). Fails with NOT_FOUND when the id does not "
    "exist."
)


class MedicalRecordInput(BaseModel):
    """Input for ``add_medical_record`` (Go: ``model.MedicalRecord``).

    ``id`` and ``createdAt`` are assigned by the backend and cannot be set
    from here — ``extra="forbid"`` makes an attempt an explicit error
    rather than a silent no-op.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    diagnosis: str = Field(min_length=1, max_length=300, description="Diagnosis (required).")
    doctor: str = Field(min_length=1, max_length=64, description="Attending doctor (required).")

    visitDate: str | None = Field(default=None, description="Visit date as YYYY-MM-DD; defaults to today.")
    symptoms: str | None = Field(default=None, max_length=500, description="Reported symptoms.")
    treatment: str | None = Field(default=None, max_length=500, description="Treatment given.")
    prescription: list[str] | None = Field(
        default=None, description="Prescribed medicines, one string per item."
    )
    weightKg: float | None = Field(default=None, gt=0, le=300, description="Body weight in kg.")
    temperature: float | None = Field(default=None, gt=0, le=50, description="Body temperature in °C.")
    followUp: str | None = Field(default=None, max_length=300, description="Follow-up advice.")
    charge: float = Field(default=0.0, ge=0, description="Cost of this visit (>= 0).")

    @field_validator("visitDate")
    @classmethod
    def _check_date(cls, value: str | None) -> str | None:
        return validate_date(value, "visitDate")

    @field_validator("charge", "weightKg", "temperature")
    @classmethod
    def _reject_nan_inf(cls, value: float | None) -> float | None:
        if value is None:
            return None
        if math.isnan(value) or math.isinf(value):
            raise ValueError("NaN and Infinity are not allowed.")
        return value


async def execute_add_medical_record(
    client: PetHospitalClient, pet_id: str, record: MedicalRecordInput
) -> PetItem:
    clean_id = validate_pet_id(pet_id)
    body = to_json_body(record)
    return await run_tool(
        tool_name=TOOL_NAME,
        params={"pet_id": clean_id, "record": body},
        op=lambda: client.add_medical_record(clean_id, body),
        parse=PetItem.model_validate,
        shape_label="pet",
    )


def register_add_medical_record(mcp: Any, client: PetHospitalClient) -> None:
    @mcp.tool(name=TOOL_NAME, description=TOOL_DESCRIPTION)
    async def add_medical_record(
        pet_id: Annotated[str, Field(description="Archive id, e.g. 'PET-000001'.")],
        record: Annotated[MedicalRecordInput, Field(description="The visit record to append.")],
    ) -> PetItem:
        return await execute_add_medical_record(client, pet_id, record)


__all__ = [
    "MedicalRecordInput", "TOOL_NAME", "TOOL_DESCRIPTION",
    "execute_add_medical_record", "register_add_medical_record",
]
