"""``get_pet_summary`` MCP tool — cost/visit rollup for one pet."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

from ..models import PetSummary
from ..rest_client import PetHospitalClient
from ._common import run_tool, validate_pet_id

TOOL_NAME = "get_pet_summary"

TOOL_DESCRIPTION = (
    "Get the money-and-visits rollup for one pet.\n\n"
    "Backend: GET /api/v1/pets/{id}/summary.\n\n"
    "Prefer this over get_pet when the question is about cost or visit "
    "frequency rather than each individual line item. It returns:\n"
    "- totalCost, chargeCount, maxSingleCharge, avgCostPerVisit\n"
    "- costByCategory: spend split by 检查/药品/手术/住院/疫苗/护理/其他\n"
    "- costByDoctor: spend split by attending doctor\n"
    "- firstVisit / lastVisit (YYYY-MM-DD) and historyText (one-line digest)\n\n"
    "Fails with NOT_FOUND when the id does not exist."
)


async def execute_get_pet_summary(
    client: PetHospitalClient, pet_id: str
) -> PetSummary:
    clean_id = validate_pet_id(pet_id)
    return await run_tool(
        tool_name=TOOL_NAME,
        params={"pet_id": clean_id},
        op=lambda: client.get_pet_summary(clean_id),
        parse=PetSummary.model_validate,
        shape_label="pet-summary",
    )


def register_get_pet_summary(mcp: Any, client: PetHospitalClient) -> None:
    @mcp.tool(name=TOOL_NAME, description=TOOL_DESCRIPTION)
    async def get_pet_summary(
        pet_id: Annotated[
            str,
            Field(description="Archive id, e.g. 'PET-000001'."),
        ],
    ) -> PetSummary:
        return await execute_get_pet_summary(client, pet_id)


__all__ = [
    "TOOL_NAME", "TOOL_DESCRIPTION",
    "execute_get_pet_summary", "register_get_pet_summary",
]
