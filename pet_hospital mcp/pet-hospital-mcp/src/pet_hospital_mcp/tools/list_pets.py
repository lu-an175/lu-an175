"""``list_pets`` MCP tool.

Exposes ``GET /api/v1/pets`` from the Go Pet Hospital REST API as a
single MCP tool. The input model mirrors the Go API's query parameters
exactly (no adapter-private business fields), the success model mirrors
the Go ``Result.data`` shape, and every failure is normalised into the
unified :class:`ErrorResponse` envelope defined in
:mod:`pet_hospital_mcp.errors`.
"""

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..errors import validation_error
from ..models import MedicalRecord, PetItem, Treatment
from ..rest_client import PetHospitalClient
from ._common import (
    ORDER_VALUES,
    SORTBY_VALUES,
    SPECIES_VALUES,
    STATUS_VALUES,
    run_tool,
)


# --- Input model ----------------------------------------------------------

class ListPetsInput(BaseModel):
    """Input for the ``list_pets`` tool.

    Every field is optional and mirrors a query parameter accepted by
    ``GET /api/v1/pets`` on the Go backend. Unknown fields are rejected
    (``extra="forbid"``) so the model cannot smuggle in parameters the
    backend does not understand.
    """

    model_config = ConfigDict(extra="forbid")

    q: str | None = Field(default=None, description="Full-text search across all fields.")
    name: str | None = Field(default=None, description="Filter by pet name.")
    ownerName: str | None = Field(default=None, description="Filter by owner name.")
    ownerPhone: str | None = Field(default=None, description="Filter by owner phone number.")
    species: Literal["犬", "猫", "兔", "鸟", "仓鼠", "爬宠", "其他"] | None = Field(
        default=None, description="Filter by species."
    )
    doctor: str | None = Field(default=None, description="Filter by attending doctor.")
    disease: str | None = Field(default=None, description="Filter by disease / diagnosis.")
    status: Literal["待就诊", "就诊中", "住院中", "已康复", "慢性病随访"] | None = Field(
        default=None, description="Filter by visit status."
    )
    min: float | None = Field(default=None, ge=0, description="Minimum total cost.")
    max: float | None = Field(default=None, ge=0, description="Maximum total cost.")
    sortBy: Literal[
        "id", "name", "ownerName", "species", "doctor", "disease", "status",
        "totalCost", "visitCount", "createdAt", "updatedAt"
    ] | None = Field(default=None, description="Sort field.")
    order: Literal["asc", "desc"] | None = Field(
        default=None, description="Sort direction."
    )
    page: int = Field(default=1, ge=1, description="Page number (1-based).")
    pageSize: int = Field(default=20, ge=1, le=500, description="Page size (1-500).")

    @field_validator("min", "max")
    @classmethod
    def _reject_nan_inf(cls, value: float | None) -> float | None:
        if value is None:
            return None
        if math.isnan(value) or math.isinf(value):
            raise ValueError("NaN and Infinity are not allowed for numeric parameters.")
        return value


# --- Output models --------------------------------------------------------

class ListPetsSuccess(BaseModel):
    """Successful result of ``list_pets``.

    Mirrors the ``data`` field of the Go API success envelope.
    """

    items: list[PetItem] = Field(default_factory=list, description="Pet records on the current page.")
    total: int = Field(ge=0, description="Total number of records matching the filters.")
    page: int = Field(ge=1, description="Current page number.")
    pageSize: int = Field(ge=1, description="Page size.")
    totalPages: int = Field(ge=0, description="Total number of pages.")
    totalCost: float = Field(ge=0, description="Sum of totalCost across all matching records.")


# --- Core logic ----------------------------------------------------------

async def execute_list_pets(
    client: PetHospitalClient,
    filters: ListPetsInput,
) -> ListPetsSuccess:
    """Call the backend and return a validated :class:`ListPetsSuccess`.

    All failures raise :class:`PetHospitalError`, which the MCP SDK 2.x
    turns into an ``is_error=True`` tool result carrying the unified
    error envelope as text content.
    """
    # Cross-field validation that Pydantic cannot express declaratively.
    if filters.min is not None and filters.max is not None and filters.min > filters.max:
        raise validation_error(
            "'min' must be less than or equal to 'max'.",
            {"min": filters.min, "max": filters.max},
        )

    params = _to_query_params(filters)
    return await run_tool(
        tool_name=TOOL_NAME,
        params=filters.model_dump(exclude_none=True),
        op=lambda: client.list_pets(params),
        parse=ListPetsSuccess.model_validate,
        shape_label="list-pets",
    )


# --- Helpers -------------------------------------------------------------

def _to_query_params(filters: ListPetsInput) -> dict[str, Any]:
    """Translate the validated input into the Go API's query dict.

    ``None`` values are dropped so the backend applies its own defaults;
    everything else is serialised as-is (httpx handles str/int/float).
    """
    raw = filters.model_dump(exclude_none=True)
    out: dict[str, Any] = {}
    for key, value in raw.items():
        if isinstance(value, float) and value.is_integer():
            # Keep integer-looking floats as ints so the backend parses
            # them as ints when the parameter is integer-typed.
            out[key] = int(value)
        else:
            out[key] = value
    return out


# --- Registration --------------------------------------------------------

TOOL_NAME = "list_pets"

TOOL_DESCRIPTION = (
    "List pet records from the Pet Hospital backend.\n\n"
    "Use this tool to browse, filter, sort and paginate the hospital's pet "
    "archive via the Go REST API (GET /api/v1/pets). All parameters are "
    "optional; omit them to get the first page of the default sorted list.\n\n"
    "Parameters (all optional):\n"
    "- q: full-text search across all fields (name, breed, disease, doctor, "
    "owner, notes, history, charges).\n"
    "- name / ownerName / ownerPhone / doctor / disease: exact or "
    "contains-style filters on the matching field.\n"
    "- species: one of " + ", ".join(SPECIES_VALUES) + ".\n"
    "- status: one of " + ", ".join(STATUS_VALUES) + ".\n"
    "- min / max: total-cost range (non-negative, min <= max).\n"
    "- sortBy: one of " + ", ".join(SORTBY_VALUES) + ".\n"
    "- order: one of " + ", ".join(ORDER_VALUES) + ".\n"
    "- page: 1-based page number (>= 1).\n"
    "- pageSize: items per page (1-500).\n\n"
    "Returns: an object with items (list of pet records, each including "
    "records and charges which may be null), total, page, pageSize, "
    "totalPages and totalCost. On failure returns an error envelope "
    "{'error': {'code', 'message', 'details'}} with is_error=True."
)


def register_list_pets(mcp: Any, client: PetHospitalClient) -> None:
    """Register the ``list_pets`` tool on an :class:`MCPServer`."""
    @mcp.tool(name=TOOL_NAME, description=TOOL_DESCRIPTION)
    async def list_pets(filters: ListPetsInput) -> ListPetsSuccess:
        return await execute_list_pets(client, filters)


__all__ = [
    "ListPetsInput", "ListPetsSuccess", "PetItem",
    "MedicalRecord", "Treatment",
    "SPECIES_VALUES", "STATUS_VALUES", "SORTBY_VALUES", "ORDER_VALUES",
    "execute_list_pets", "register_list_pets",
    "TOOL_NAME", "TOOL_DESCRIPTION",
]
