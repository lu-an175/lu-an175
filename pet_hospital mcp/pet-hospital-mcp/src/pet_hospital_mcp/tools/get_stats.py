"""``get_stats`` MCP tool — clinic-wide business statistics."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

from ..models import HospitalStats
from ..rest_client import PetHospitalClient
from ._common import run_tool

TOOL_NAME = "get_stats"

TOOL_DESCRIPTION = (
    "Get clinic-wide business statistics.\n\n"
    "Backend: GET /api/v1/stats?top=N.\n\n"
    "Returns: totalPets, totalRecords, totalCharges, totalRevenue, "
    "averageCost, maxCost, plus breakdowns bySpecies / byStatus / byDoctor "
    "(record counts) and revenueByDoctor (money), and topSpenders (the N "
    "highest-spending pets; N is the 'top' parameter, default 5).\n\n"
    "Use this for questions like \"how many dogs are hospitalised\", \"who is "
    "the top doctor by revenue\" or \"what is the average ticket size\". "
    "For a single pet's cost breakdown use get_pet_summary instead.\n\n"
    "Note: breakdown maps are null when there is no data yet, and "
    "logGarbagePct reports how much dead space the single-file DB holds "
    "(high values mean it is due for compaction)."
)


async def execute_get_stats(client: PetHospitalClient, top: int = 5) -> HospitalStats:
    return await run_tool(
        tool_name=TOOL_NAME,
        params={"top": top},
        op=lambda: client.get_stats(top),
        parse=HospitalStats.model_validate,
        shape_label="stats",
    )


def register_get_stats(mcp: Any, client: PetHospitalClient) -> None:
    @mcp.tool(name=TOOL_NAME, description=TOOL_DESCRIPTION)
    async def get_stats(
        top: Annotated[
            int,
            Field(ge=1, le=50, description="How many top spenders to include (1-50)."),
        ] = 5,
    ) -> HospitalStats:
        return await execute_get_stats(client, top)


__all__ = [
    "TOOL_NAME", "TOOL_DESCRIPTION", "execute_get_stats", "register_get_stats",
]
