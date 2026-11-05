"""``get_pet`` MCP tool — fetch one pet record by its archive id."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

from ..models import PetItem
from ..rest_client import PetHospitalClient
from ._common import run_tool, validate_pet_id

TOOL_NAME = "get_pet"

TOOL_DESCRIPTION = (
    "Fetch a single pet archive record by its id.\n\n"
    "Backend: GET /api/v1/pets/{id}.\n\n"
    "Use this when you already know the archive id (e.g. 'PET-000001') and "
    "need the full record: owner details, doctor, disease, status, the full "
    "medical record history (records) and every charge line (charges).\n"
    "If you only know a name, phone or symptom, call list_pets first and take "
    "the id from there.\n\n"
    "Returns: the pet object. records/charges may be null when the pet has no "
    "history yet. Fails with NOT_FOUND when the id does not exist."
)


async def execute_get_pet(client: PetHospitalClient, pet_id: str) -> PetItem:
    """Look up one pet; ``NOT_FOUND`` surfaces through the error envelope."""
    clean_id = validate_pet_id(pet_id)
    return await run_tool(
        tool_name=TOOL_NAME,
        params={"pet_id": clean_id},
        op=lambda: client.get_pet(clean_id),
        parse=PetItem.model_validate,
        shape_label="pet",
    )


def register_get_pet(mcp: Any, client: PetHospitalClient) -> None:
    @mcp.tool(name=TOOL_NAME, description=TOOL_DESCRIPTION)
    async def get_pet(
        pet_id: Annotated[
            str,
            Field(description="Archive id, e.g. 'PET-000001'. Letters, digits, '-' and '_' only."),
        ],
    ) -> PetItem:
        return await execute_get_pet(client, pet_id)


__all__ = ["TOOL_NAME", "TOOL_DESCRIPTION", "execute_get_pet", "register_get_pet"]
