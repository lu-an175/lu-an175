"""``delete_pet`` MCP tool — permanently remove one archive record."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, Field

from ..rest_client import PetHospitalClient
from ._common import run_tool, validate_pet_id

TOOL_NAME = "delete_pet"

TOOL_DESCRIPTION = (
    "Permanently delete one pet archive record.\n\n"
    "Backend: DELETE /api/v1/pets/{id}.\n\n"
    "This is irreversible — the record, its medical history and its charge "
    "lines all go with it. Confirm the id with get_pet first when there is "
    "any doubt. There is no undo and no trash.\n\n"
    "Returns: {'id': '<deleted id>'}. Fails with NOT_FOUND when the id does "
    "not exist (a delete of a missing id is reported as an error rather than "
    "silently succeeding, so a stale id never looks like a successful delete)."
)


class DeletePetSuccess(BaseModel):
    """Result of ``delete_pet`` — mirrors the Go ``{"id": ...}`` payload."""

    id: str = Field(description="The archive id that was deleted.")


async def execute_delete_pet(
    client: PetHospitalClient, pet_id: str
) -> DeletePetSuccess:
    clean_id = validate_pet_id(pet_id)
    return await run_tool(
        tool_name=TOOL_NAME,
        params={"pet_id": clean_id},
        op=lambda: client.delete_pet(clean_id),
        parse=DeletePetSuccess.model_validate,
        shape_label="delete-acknowledgement",
    )


def register_delete_pet(mcp: Any, client: PetHospitalClient) -> None:
    @mcp.tool(name=TOOL_NAME, description=TOOL_DESCRIPTION)
    async def delete_pet(
        pet_id: Annotated[str, Field(description="Archive id to delete, e.g. 'PET-000001'.")],
    ) -> DeletePetSuccess:
        return await execute_delete_pet(client, pet_id)


__all__ = [
    "DeletePetSuccess", "TOOL_NAME", "TOOL_DESCRIPTION",
    "execute_delete_pet", "register_delete_pet",
]
