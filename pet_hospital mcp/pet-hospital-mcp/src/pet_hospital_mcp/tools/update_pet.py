"""``update_pet`` MCP tool — partial update of an existing archive record."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..errors import validation_error
from ..models import PetItem
from ..rest_client import PetHospitalClient
from ._common import run_tool, to_json_body, validate_pet_id

TOOL_NAME = "update_pet"

TOOL_DESCRIPTION = (
    "Partially update an existing pet archive record.\n\n"
    "Backend: PATCH /api/v1/pets/{id}.\n\n"
    "Only the fields you pass are changed; everything else keeps its "
    "current value, and records/charges are never touched. This is why the "
    "tool maps to PATCH and not PUT — a PUT would wipe the history.\n\n"
    "Pass at least one field. To clear an optional text field, pass an empty "
    "string (e.g. note: \"\").\n\n"
    "Returns the updated record. Fails with NOT_FOUND when the id does not "
    "exist, or VALIDATION_ERROR when the patch is empty or a field is "
    "invalid (e.g. an unknown species or a blank name)."
)


class UpdatePetInput(BaseModel):
    """Input for ``update_pet`` — every field optional, ``None`` means "leave it"."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=64)
    ownerName: str | None = Field(default=None, min_length=1, max_length=64)
    ownerPhone: str | None = Field(default=None, max_length=32)
    disease: str | None = Field(default=None, min_length=1, max_length=200)
    doctor: str | None = Field(default=None, min_length=1, max_length=64)

    species: Literal["犬", "猫", "兔", "鸟", "仓鼠", "爬宠", "其他"] | None = None
    status: Literal["待就诊", "就诊中", "住院中", "已康复", "慢性病随访"] | None = None

    breed: str | None = Field(default=None, max_length=64)
    gender: str | None = Field(default=None, max_length=16)
    ageMonths: int | None = Field(default=None, ge=0, le=600)
    color: str | None = Field(default=None, max_length=64)
    chipNo: str | None = Field(default=None, max_length=64)
    ownerAddr: str | None = Field(default=None, max_length=200)
    allergy: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=500)

    @field_validator("ownerPhone")
    @classmethod
    def _validate_phone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        from .create_pet import _check_phone

        return _check_phone(value)


async def execute_update_pet(
    client: PetHospitalClient, pet_id: str, patch: UpdatePetInput
) -> PetItem:
    """Send only the supplied fields as a PATCH body."""
    clean_id = validate_pet_id(pet_id)
    body = to_json_body(patch, exclude_unset=True)
    if not body:
        raise validation_error(
            "Nothing to update: pass at least one field to change.",
            {"pet_id": clean_id},
        )
    return await run_tool(
        tool_name=TOOL_NAME,
        params={"pet_id": clean_id, "patch": body},
        op=lambda: client.patch_pet(clean_id, body),
        parse=PetItem.model_validate,
        shape_label="pet",
    )


def register_update_pet(mcp: Any, client: PetHospitalClient) -> None:
    @mcp.tool(name=TOOL_NAME, description=TOOL_DESCRIPTION)
    async def update_pet(
        pet_id: Annotated[str, Field(description="Archive id, e.g. 'PET-000001'.")],
        patch: Annotated[
            UpdatePetInput,
            Field(description="Fields to change; omitted fields are left untouched."),
        ],
    ) -> PetItem:
        return await execute_update_pet(client, pet_id, patch)


__all__ = [
    "UpdatePetInput", "TOOL_NAME", "TOOL_DESCRIPTION",
    "execute_update_pet", "register_update_pet",
]
