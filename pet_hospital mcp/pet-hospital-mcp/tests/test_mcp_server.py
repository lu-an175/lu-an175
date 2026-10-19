"""Integration tests for the MCP server.

These tests use the SDK 2.x in-memory :class:`Client` for tool discovery
and invocation (the SDK's own recommended test pattern), and
:class:`httpx.ASGITransport` for the HTTP-level assertions:

* ``/health`` is reachable and returns 200.
* The ``/mcp`` endpoint does not require or return ``Mcp-Session-Id``
  (the 2026-07-28 protocol is stateless).
* ``list_pets`` is discoverable and callable over the HTTP MCP
  endpoint.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

import httpx
import pytest

from mcp.server.transport_security import TransportSecuritySettings

from pet_hospital_mcp.config import Settings
from pet_hospital_mcp.rest_client import PetHospitalClient
from pet_hospital_mcp.server import create_mcp_server
from pet_hospital_mcp.tools.list_pets import register_list_pets, TOOL_NAME

from conftest import make_go_success, make_mock_transport, make_pet, TEST_BACKEND


# Test-time transport security: disable DNS-rebinding protection so the
# synthetic ``http://test`` base URL used with ``httpx.ASGITransport`` is
# not rejected with HTTP 421 Misdirected Request. Production keeps the
# SDK default (localhost-only).
TEST_TRANSPORT_SECURITY = TransportSecuritySettings(
    enable_dns_rebinding_protection=False,
)


def _stateless_app(mcp) -> object:
    """Return a stateless Streamable HTTP Starlette app for tests."""
    return mcp.streamable_http_app(
        stateless_http=True,
        streamable_http_path="/mcp",
        transport_security=TEST_TRANSPORT_SECURITY,
    )


# --- Fixtures ------------------------------------------------------------

@pytest.fixture
def mcp_with_mock_backend(
    settings: Settings,
) -> tuple[object, PetHospitalClient]:
    """Build an MCPServer with a mock-backed client registered on it."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=make_go_success(
            items=[make_pet()],
            total=1,
            page=1,
            page_size=20,
            total_pages=1,
            total_cost=120.5,
        ))

    mcp = create_mcp_server()
    client = PetHospitalClient(settings, transport=make_mock_transport(handler))
    register_list_pets(mcp, client)
    return mcp, client


# --- Tool registration & schema -----------------------------------------

class TestToolRegistration:
    async def test_tool_is_registered_with_correct_name(
        self,
        mcp_with_mock_backend,
    ) -> None:
        from mcp import Client
        mcp, client = mcp_with_mock_backend
        async with Client(mcp) as mcp_client:
            result = await mcp_client.list_tools()
        names = [t.name for t in result.tools]
        assert TOOL_NAME in names

    async def test_tool_has_input_schema(
        self,
        mcp_with_mock_backend,
    ) -> None:
        from mcp import Client
        mcp, client = mcp_with_mock_backend
        async with Client(mcp) as mcp_client:
            result = await mcp_client.list_tools()
        tool = next(t for t in result.tools if t.name == TOOL_NAME)
        schema = tool.input_schema
        assert schema["type"] == "object"
        assert "filters" in schema["properties"]

    async def test_tool_has_output_schema(
        self,
        mcp_with_mock_backend,
    ) -> None:
        from mcp import Client
        mcp, client = mcp_with_mock_backend
        async with Client(mcp) as mcp_client:
            result = await mcp_client.list_tools()
        tool = next(t for t in result.tools if t.name == TOOL_NAME)
        assert tool.output_schema is not None
        assert "items" in tool.output_schema.get("properties", {})

    async def test_only_one_tool_registered(
        self,
        mcp_with_mock_backend,
    ) -> None:
        from mcp import Client
        mcp, client = mcp_with_mock_backend
        async with Client(mcp) as mcp_client:
            result = await mcp_client.list_tools()
        assert len(result.tools) == 1


# --- Tool invocation via in-memory Client --------------------------------

class TestToolCall:
    async def test_call_list_pets_returns_structured_success(
        self,
        mcp_with_mock_backend,
    ) -> None:
        from mcp import Client
        mcp, client = mcp_with_mock_backend
        async with Client(mcp) as mcp_client:
            result = await mcp_client.call_tool(
                TOOL_NAME, {"filters": {"species": "犬", "page": 1}}
            )
        assert result.is_error is False or result.is_error is None
        assert result.structured_content is not None
        data = result.structured_content
        assert "items" in data
        assert data["total"] == 1

    async def test_call_with_invalid_species_returns_error(
        self,
        mcp_with_mock_backend,
    ) -> None:
        from mcp import Client
        mcp, client = mcp_with_mock_backend
        async with Client(mcp) as mcp_client:
            result = await mcp_client.call_tool(
                TOOL_NAME, {"filters": {"species": "鱼"}}
            )
        assert result.is_error is True


# --- /health endpoint ---------------------------------------------------

class TestHealthEndpoint:
    async def test_health_returns_ok(
        self,
        mcp_with_mock_backend,
    ) -> None:
        mcp, client = mcp_with_mock_backend

        from starlette.responses import JSONResponse

        @mcp.custom_route("/health", methods=["GET"])
        async def health(_request):
            return JSONResponse({"status": "ok"})

        app = _stateless_app(mcp)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http_client:
            response = await http_client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"


# --- Stateless HTTP behaviour -------------------------------------------

class TestStatelessHttp:
    """Verify the 2026-07-28 stateless Streamable HTTP contract.

    The SDK's own :class:`Client` is used with a ``streamable_http_client``
    transport backed by an ``httpx.ASGITransport``. This mirrors how a
    real client connects and automatically stamps the protocol-version
    envelope (``_meta``), ``Accept`` header, and parameter-pinning headers
    that the 2026-07-28 server requires.
    """

    async def test_no_mcp_session_id_in_response(
        self,
        mcp_with_mock_backend,
    ) -> None:
        from mcp import Client
        from mcp.client.streamable_http import streamable_http_client

        mcp, _client = mcp_with_mock_backend
        app = _stateless_app(mcp)

        captured_headers: list[dict[str, str]] = []

        async def _capture(response: httpx.Response) -> None:
            captured_headers.append({k.lower(): v for k, v in response.headers.items()})

        @asynccontextmanager
        async def lifespan() -> AsyncIterator[None]:
            async with mcp.session_manager.run():
                yield

        asgi_transport = httpx.ASGITransport(app=app)
        async with lifespan():
            async with httpx.AsyncClient(
                transport=asgi_transport,
                base_url="http://test",
                event_hooks={"response": [_capture]},
            ) as http_client:
                transport = streamable_http_client(
                    "http://test/mcp", http_client=http_client
                )
                async with Client(transport, mode="2026-07-28") as mcp_client:
                    await mcp_client.list_tools()

        # Every response the server sent must be free of Mcp-Session-Id,
        # proving the 2026-07-28 stateless contract: no initialize, no
        # session handshake, no session-id header.
        assert captured_headers, "expected at least one HTTP response"
        for headers in captured_headers:
            assert "mcp-session-id" not in headers, (
                f"server returned Mcp-Session-Id in stateless mode: {headers}"
            )

    async def test_tool_callable_over_http(
        self,
        mcp_with_mock_backend,
    ) -> None:
        from mcp import Client
        from mcp.client.streamable_http import streamable_http_client

        mcp, _client = mcp_with_mock_backend
        app = _stateless_app(mcp)

        @asynccontextmanager
        async def lifespan() -> AsyncIterator[None]:
            async with mcp.session_manager.run():
                yield

        asgi_transport = httpx.ASGITransport(app=app)
        async with lifespan():
            async with httpx.AsyncClient(
                transport=asgi_transport, base_url="http://test"
            ) as http_client:
                transport = streamable_http_client(
                    "http://test/mcp", http_client=http_client
                )
                async with Client(transport, mode="2026-07-28") as mcp_client:
                    result = await mcp_client.list_tools()
                    assert any(t.name == TOOL_NAME for t in result.tools)

                    call_result = await mcp_client.call_tool(
                        TOOL_NAME, {"filters": {"species": "犬"}}
                    )
                    assert call_result.is_error is False or call_result.is_error is None
                    assert call_result.structured_content is not None
                    assert "items" in call_result.structured_content
