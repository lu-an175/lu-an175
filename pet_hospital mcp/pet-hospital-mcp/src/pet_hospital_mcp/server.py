"""MCP server assembly.

Builds an :class:`MCPServer` (SDK 2.x high-level server), registers the
``list_pets`` tool against an injectable :class:`PetHospitalClient`, and
mounts it under a stateless Streamable HTTP transport with a ``/health``
endpoint next to ``/mcp``.

No ``initialize`` handshake, no ``Mcp-Session-Id``, no session store, no
``max_sessions``: the 2026-07-28 protocol revision is stateless by
default and we pass ``stateless_http=True`` to make that explicit even
for legacy clients that try to open a session.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp.server import MCPServer

from .config import Settings, load_settings
from .logging_config import setup_logging
from .rest_client import PetHospitalClient
from .tools.list_pets import register_list_pets

logger = logging.getLogger("pet_hospital_mcp.server")

SERVER_NAME = "pet-hospital-mcp"
SERVER_INSTRUCTIONS = (
    "Pet Hospital MCP service. Exposes the Go Pet Hospital REST API "
    "as MCP tools. Currently provides one tool: list_pets, which lists "
    "and filters pet records via GET /api/v1/pets."
)


def create_mcp_server() -> MCPServer:
    """Build the bare :class:`MCPServer` (no transport wiring)."""
    return MCPServer(
        SERVER_NAME,
        instructions=SERVER_INSTRUCTIONS,
        log_level="INFO",
    )


def build_client(settings: Settings) -> PetHospitalClient:
    return PetHospitalClient(settings)


def create_app(settings: Settings | None = None) -> tuple[object, PetHospitalClient]:
    """Build the Starlette ASGI app and its owning client.

    Returns ``(app, client)`` so callers (tests, __main__) can manage
    the client lifecycle and feed a mock transport when needed.
    """
    if settings is None:
        settings = load_settings()
    setup_logging()

    mcp = create_mcp_server()
    client = build_client(settings)
    register_list_pets(mcp, client)

    @mcp.custom_route("/health", methods=["GET"])
    async def health(_request) -> object:  # type: ignore[no-untyped-def]
        from starlette.responses import JSONResponse
        return JSONResponse({
            "status": "ok",
            "service": SERVER_NAME,
            "backend": settings.pet_hospital_base_url,
        })

    inner_app = mcp.streamable_http_app(
        stateless_http=True,
        streamable_http_path="/mcp",
    )

    @asynccontextmanager
    async def lifespan(_app) -> AsyncIterator[None]:
        async with client:
            async with mcp.session_manager.run():
                yield

    from starlette.applications import Starlette
    from starlette.routing import Mount

    app = Starlette(
        routes=[Mount("/", app=inner_app)],
        lifespan=lifespan,
    )
    # Expose the MCP server on the app for tests/inspector.
    app.state.mcp = mcp  # type: ignore[attr-defined]
    app.state.settings = settings  # type: ignore[attr-defined]
    return app, client


def run() -> None:
    """Entry point used by ``python -m pet_hospital_mcp`` and the script."""
    import uvicorn

    settings = load_settings()
    app, _client = create_app(settings)
    logger.info(
        "starting pet-hospital-mcp",
        extra={
            "mcp_url": settings.mcp_url,
            "backend": settings.pet_hospital_base_url,
        },
    )
    uvicorn.run(
        app,
        host=settings.mcp_host,
        port=settings.mcp_port,
        log_level="info",
    )


__all__ = ["create_app", "create_mcp_server", "run", "SERVER_NAME"]
