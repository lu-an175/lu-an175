"""``create_pet`` MCP tool — open a new pet archive record."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..models import PetItem
from ..rest_client import PetHospitalClient
from ._common import (
    SPECIES_VALUES,
    STATUS_VALUES,
    run_tool,
    to_json_body,
)

TOOL_NAME = "create_pet"

TOOL_DESCRIPTION = (
    "Create a new pet archive record (宠物建档).\n\n"
    "Backend: POST /api/v1/pets.\n\n"
    "Required: name, ownerName, ownerPhone, disease, doctor.\n"
    "Optional: species (default 其他), status (default 待就诊), breed, "
    "gender, ageMonths, color, chipNo, ownerAddr, allergy, note.\n\n"
    "The backend assigns the id (PET-000001 style) and returns the stored "
    "record — read the id from the result before adding records or charges.\n"
    "Do not pass records/charges here; call add_medical_record / add_charge "
    "afterwards instead.\n\n"
    "Fails with VALIDATION_ERROR when a required field is missing/blank or "
    "the phone number does not match the 7-15 digit rule."
)

# Go's model.ValidatePhone: digits only, plus these separators.
_PHONE_SEPARATORS = frozenset("-+ ()")


def _check_phone(value: str) -> str:
    """Mirror ``model.ValidatePhone`` so we reject what Go would reject.

    Doing it here means the model gets a precise message instead of a
    generic HTTP 400 from the backend.
    """
    candidate = value.strip()
    if not candidate:
        raise ValueError("ownerPhone must not be empty.")
    digits = sum(1 for ch in candidate if ch in "0123456789")
    bad = [ch for ch in candidate if ch not in "0123456789" and ch not in _PHONE_SEPARATORS]
    if bad:
        raise ValueError(f"ownerPhone contains illegal character(s): {''.join(bad)!r}.")
    if not 7 <= digits <= 15:
        raise ValueError("ownerPhone must contain 7 to 15 digits.")
    return candidate


class CreatePetInput(BaseModel):
    """Input for ``create_pet``.

    Mirrors the required/optional split enforced by ``model.Pet.Validate``
    on the Go side. ``records`` and ``charges`` are deliberately **not**
    accepted here — use ``add_medical_record`` / ``add_charge`` after
    creating the archive, so every write is a separate auditable call.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=64, description="Pet name (required).")
    ownerName: str = Field(min_length=1, max_length=64, description="Owner name (required).")
    ownerPhone: str = Field(
        description="Owner phone, 7-15 digits; '-', '+', ' ', '(', ')' allowed (required).",
    )
    disease: str = Field(min_length=1, max_length=200, description="Disease / primary diagnosis (required).")
    doctor: str = Field(min_length=1, max_length=64, description="Attending doctor (required).")

    species: Literal["犬", "猫", "兔", "鸟", "仓鼠", "爬宠", "其他"] = Field(
        default="其他", description="Species; defaults to 其他 (other).",
    )
    status: Literal["待就诊", "就诊中", "住院中", "已康复", "慢性病随访"] = Field(
        default="待就诊", description="Visit status; defaults to 待就诊 (waiting).",
    )

    breed: str | None = Field(default=None, max_length=64, description="Breed.")
    gender: str | None = Field(default=None, max_length=16, description="公 / 母 / unset.")
    ageMonths: int | None = Field(default=None, ge=0, le=600, description="Age in months.")
    color: str | None = Field(default=None, max_length=64, description="Coat colour.")
    chipNo: str | None = Field(default=None, max_length=64, description="Microchip number.")
    ownerAddr: str | None = Field(default=None, max_length=200, description="Owner address.")
    allergy: str | None = Field(default=None, max_length=200, description="Known allergies.")
    note: str | None = Field(default=None, max_length=500, description="Free-form note.")

    @field_validator("ownerPhone")
    @classmethod
    def _validate_phone(cls, value: str) -> str:
        return _check_phone(value)


async def execute_create_pet(
    client: PetHospitalClient, payload: CreatePetInput
) -> PetItem:
    """Create the archive and return the record as stored by the backend.

    The returned ``id`` (``PET-000001`` style, assigned server-side) is
    what later calls need, so the tool result is the created object
    rather than a bare acknowledgement.
    """
    body = to_json_body(payload)
    return await run_tool(
        tool_name=TOOL_NAME,
        params={"payload": body},
        op=lambda: client.create_pet(body),
        parse=PetItem.model_validate,
        shape_label="pet",
    )


def register_create_pet(mcp: Any, client: PetHospitalClient) -> None:
    @mcp.tool(name=TOOL_NAME, description=TOOL_DESCRIPTION)
    async def create_pet(
        pet: Annotated[CreatePetInput, Field(description="Fields of the new archive record.")],
    ) -> PetItem:
        return await execute_create_pet(client, pet)


__all__ = [
    "CreatePetInput", "TOOL_NAME", "TOOL_DESCRIPTION",
    "execute_create_pet", "register_create_pet",
]
