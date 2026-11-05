"""MCP tools package.

Each module here registers one tool on the MCPServer via a
``register_<tool>(mcp, client)`` function, called from
:mod:`pet_hospital_mcp.server`.

Shared conventions (enums mirrored from the Go model, pet-id validation,
the logging/error wrapper) live in :mod:`._common`; response shapes live
in :mod:`pet_hospital_mcp.models`.
"""

from .add_charge import register_add_charge
from .add_medical_record import register_add_medical_record
from .create_pet import register_create_pet
from .delete_pet import register_delete_pet
from .get_pet import register_get_pet
from .get_pet_summary import register_get_pet_summary
from .get_stats import register_get_stats
from .list_pets import register_list_pets
from .update_pet import register_update_pet

#: Every ``register_*`` function, in the order they are advertised.
REGISTERERS = (
    register_list_pets,
    register_get_pet,
    register_create_pet,
    register_update_pet,
    register_delete_pet,
    register_add_medical_record,
    register_add_charge,
    register_get_pet_summary,
    register_get_stats,
)

__all__ = [
    "REGISTERERS",
    "register_list_pets",
    "register_get_pet",
    "register_create_pet",
    "register_update_pet",
    "register_delete_pet",
    "register_add_medical_record",
    "register_add_charge",
    "register_get_pet_summary",
    "register_get_stats",
]
