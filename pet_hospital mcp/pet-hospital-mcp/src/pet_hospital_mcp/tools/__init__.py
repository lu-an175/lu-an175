"""MCP tools package.

Each module here registers one tool on the MCPServer via a
``register_<tool>(mcp, client)`` function. New tools are added by
creating a module and calling its register function from
:mod:`pet_hospital_mcp.server`.
"""

from .list_pets import register_list_pets

__all__ = ["register_list_pets"]
