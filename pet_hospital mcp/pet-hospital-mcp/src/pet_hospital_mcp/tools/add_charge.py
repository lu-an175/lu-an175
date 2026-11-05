"""``add_charge`` MCP tool — append one charge line to a pet."""

from __future__ import annotations

import math
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..models import PetItem
from ..rest_client import PetHospitalClient
from ._common import (
    CHARGE_CATEGORY_HINTS,
    run_tool,
    to_json_body,
    validate_date,
    validate_pet_id,
)

TOOL_NAME = "add_charge"

TOOL_DESCRIPTION = (
    "Append one charge line (消费明细) to an existing pet archive.\n\n"
    "Backend: POST /api/v1/pets/{id}/charges.\n\n"
    "Required: item, amount (>= 0).\n"
    "Optional: category, doctor, date (YYYY-MM-DD, defaults to today), note.\n\n"
    "category is free text but the hospital reports group by it, so prefer "
    "one of: " + " / ".join(CHARGE_CATEGORY_HINTS) + ".\n\n"
    "Side effect: the pet's totalCost is recalculated as the sum of all "
    "charge lines. Returns the whole updated pet record. Fails with "
    "NOT_FOUND when the id does not exist."
)


class ChargeInput(BaseModel):
    """Input for ``add_charge`` (Go: ``model.Treatment``).

    ``id`` and ``date`` are defaulted server-side when omitted; ``amount``
    is what actually drives ``totalCost``, so it is required.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    item: str = Field(min_length=1, max_length=120, description="Charge item, e.g. '血常规检查' (required).")
    amount: float = Field(ge=0, description="Amount in CNY (>= 0).")

    category: str = Field(
        default="其他",
        max_length=32,
        description="Cost category; " + " / ".join(CHARGE_CATEGORY_HINTS) + ".",
    )
    doctor: str | None = Field(default=None, max_length=64, description="Handling doctor.")
    date: str | None = Field(default=None, description="Charge date as YYYY-MM-DD; defaults to today.")
    note: str | None = Field(default=None, max_length=300, description="Free-form note.")

    @field_validator("date")
    @classmethod
    def _check_date(cls, value: str | None) -> str | None:
        return validate_date(value, "date")

    @field_validator("amount")
    @classmethod
    def _reject_nan_inf(cls, value: float) -> float:
        if math.isnan(value) or math.isinf(value):
            raise ValueError("NaN and Infinity are not allowed for 'amount'.")
        return value


async def execute_add_charge(
    client: PetHospitalClient, pet_id: str, charge: ChargeInput
) -> PetItem:
    clean_id = validate_pet_id(pet_id)
    body = to_json_body(charge)
    return await run_tool(
        tool_name=TOOL_NAME,
        params={"pet_id": clean_id, "charge": body},
        op=lambda: client.add_charge(clean_id, body),
        parse=PetItem.model_validate,
        shape_label="pet",
    )


def register_add_charge(mcp: Any, client: PetHospitalClient) -> None:
    @mcp.tool(name=TOOL_NAME, description=TOOL_DESCRIPTION)
    async def add_charge(
        pet_id: Annotated[str, Field(description="Archive id, e.g. 'PET-000001'.")],
        charge: Annotated[ChargeInput, Field(description="The charge line to append.")],
    ) -> PetItem:
        return await execute_add_charge(client, pet_id, charge)


__all__ = [
    "ChargeInput", "TOOL_NAME", "TOOL_DESCRIPTION",
    "execute_add_charge", "register_add_charge",
]
