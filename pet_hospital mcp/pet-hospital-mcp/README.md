# Pet Hospital MCP

An independent Python MCP service that exposes the [Go Pet Hospital REST API](../pet-hospital-mcp-teaching-main/) to AI agents via the **Model Context Protocol (MCP) 2026-07-28** specification.

## Key facts

| Item | Value |
|---|---|
| Python | 3.11+ |
| MCP Python SDK | `mcp==2.0.0` |
| MCP protocol version | `2026-07-28` |
| Server class | `mcp.server.MCPServer` (SDK 2.x high-level server) |
| Transport | Stateless Streamable HTTP |
| `initialize` handshake | **Not implemented** (removed in 2026-07-28) |
| `Mcp-Session-Id` | **Not produced or consumed** (stateless) |
| `FastMCP` | **Not used** (`mcp.server.fastmcp` is never imported) |
| Tools | `list_pets` only (phase one) |

## Architecture

```
AI Agent (MCP Client)
        │  Streamable HTTP (stateless, 2026-07-28)
        ▼
┌──────────────────────────────────────┐
│  pet-hospital-mcp (Python)           │
│  MCPServer + Starlette + uvicorn    │
│  ┌────────────┐  ┌────────────────┐ │
│  │ /mcp       │  │ /health        │ │
│  │ tool:      │  │ health check   │ │
│  │ list_pets  │  │                │ │
│  └─────┬──────┘  └────────────────┘ │
│        │ httpx (timeout + retry)     │
└────────┼─────────────────────────────┘
         ▼
┌──────────────────────────────────────┐
│  Go Pet Hospital REST API            │
│  127.0.0.1:8080  (GET /api/v1/pets)  │
└──────────────────────────────────────┘
```

## Prerequisites

1. **Go** (for the backend) — install from <https://go.dev/doc/install>
2. **Python 3.11+** — install from <https://www.python.org/downloads/>
3. The Go Pet Hospital REST API source under `../pet-hospital-mcp-teaching-main/`

## Quick start

### 1. Start the Go backend

```bash
cd ../pet-hospital-mcp-teaching-main
go run . -seed          # -seed writes demo data on first run
# → listening on 127.0.0.1:8080
```

Verify:

```bash
curl http://127.0.0.1:8080/api/v1/pets?pageSize=1
```

### 2. Install the MCP service

```bash
cd pet-hospital-mcp
python -m venv .venv

# Windows (PowerShell)
.\.venv\Scripts\Activate.ps1
# Linux / macOS
source .venv/bin/activate

pip install -e ".[dev]"
```

### 3. Start the MCP service

```bash
python -m pet_hospital_mcp
# → Uvicorn running on http://127.0.0.1:8765
```

### 4. Verify

Health check:

```bash
curl http://127.0.0.1:8765/health
# {"status":"ok","service":"pet-hospital-mcp","backend":"http://127.0.0.1:8080"}
```

Discover the tool (raw JSON-RPC, stateless — no `initialize`):

```bash
curl -X POST http://127.0.0.1:8765/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "MCP-Protocol-Version: 2026-07-28" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28","io.modelcontextprotocol/clientCapabilities":{}}}}'
```

Call `list_pets` (SDK Client — recommended):

```python
import asyncio
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

async def main():
    async with streamable_http_client("http://127.0.0.1:8765/mcp") as (read, write):
        async with Client(read, write, mode="2026-07-28") as client:
            result = await client.call_tool("list_pets", {
                "filters": {"species": "犬", "page": 1, "pageSize": 5}
            })
            print(result.structured_content)

asyncio.run(main())
```

## Configuration

All settings are environment variables (defaults shown):

| Variable | Default | Description |
|---|---|---|
| `PET_HOSPITAL_BASE_URL` | `http://127.0.0.1:8080` | Go REST API base URL |
| `MCP_HOST` | `127.0.0.1` | Bind interface (loopback only by default) |
| `MCP_PORT` | `8765` | MCP HTTP port |
| `PET_HOSPITAL_TIMEOUT` | `10` | Per-request timeout (seconds) |
| `PET_HOSPITAL_RETRIES` | `2` | Retry count for timeout/connection errors |
| `PET_HOSPITAL_BACKOFF` | `0.25` | Base back-off between retries (seconds) |

Example:

```bash
MCP_PORT=9000 PET_HOSPITAL_BASE_URL=http://localhost:8080 python -m pet_hospital_mcp
```

## MCP endpoints

| Path | Method | Purpose |
|---|---|---|
| `/mcp` | POST | MCP JSON-RPC endpoint (stateless Streamable HTTP) |
| `/health` | GET | Health check (returns service + backend status) |

## The `list_pets` tool

**Purpose:** Browse, filter, sort and paginate the hospital's pet archive.

**Backend:** `GET /api/v1/pets`

**Input** (all fields optional, nested under `filters`):

| Field | Type | Constraints |
|---|---|---|
| `q` | string | Full-text search |
| `name` | string | Filter by pet name |
| `ownerName` | string | Filter by owner name |
| `ownerPhone` | string | Filter by owner phone |
| `species` | enum | `犬` `猫` `兔` `鸟` `仓鼠` `爬宠` `其他` |
| `doctor` | string | Filter by doctor |
| `disease` | string | Filter by disease |
| `status` | enum | `待就诊` `就诊中` `住院中` `已康复` `慢性病随访` |
| `min` | float | Min total cost (≥ 0, ≤ `max`) |
| `max` | float | Max total cost (≥ 0) |
| `sortBy` | enum | `id` `name` `ownerName` `species` `doctor` `disease` `status` `totalCost` `visitCount` `createdAt` `updatedAt` |
| `order` | enum | `asc` `desc` |
| `page` | int | Page number (≥ 1) |
| `pageSize` | int | Page size (1–500) |

Unknown fields, NaN, Infinity, and `min > max` are rejected.

**Success output:**

```json
{
  "items": [ { "id": "...", "name": "...", "species": "犬", ... } ],
  "total": 1008,
  "page": 1,
  "pageSize": 20,
  "totalPages": 51,
  "totalCost": 123456.78
}
```

`records` and `charges` inside each pet item may be `null` (no history yet) or a list.

**Error output** (returned with `is_error=True`):

```json
{
  "error": {
    "code": "BACKEND_TIMEOUT",
    "message": "Backend did not respond within the timeout.",
    "details": {}
  }
}
```

Error codes: `VALIDATION_ERROR`, `BACKEND_TIMEOUT`, `BACKEND_UNAVAILABLE`, `BACKEND_API_ERROR`, `BACKEND_INVALID_RESPONSE`, `INTERNAL_ERROR`.

## Logging

Single-line JSON to stderr. Each entry includes `timestamp`, `level`, `logger`, `message`, and tool-specific fields: `tool_name`, `params`, `status`, `duration_ms`.

Sensitive fields (`ownerPhone`, `ownerAddr`, `chipNo` and their snake_case variants) are recursively redacted before logging.

## Testing

Tests use `pytest` + `pytest-asyncio` with `httpx.MockTransport` — the real Go service is **never** contacted.

Coverage:

- Input validation (species/status/sortBy/order enums, page/pageSize/min/max ranges, NaN/Infinity, unknown fields)
- REST client (parameter forwarding, 4xx/5xx, timeout, connection error, non-JSON, missing `data` key)
- `list_pets` tool (success, null records/charges, min>max, 4xx, timeout, non-JSON, shape mismatch)
- MCP server (tool registration, input/output schema, tool call, `/health`, stateless HTTP: no `Mcp-Session-Id`, tool callable over HTTP)

```bash
cd pet-hospital-mcp
pytest -q
```

Expected result: **44 passed**.

## Verifying the stateless MCP connection

The 2026-07-28 protocol is stateless: no `initialize` handshake, no `Mcp-Session-Id` header. To verify with MCP Inspector:

```bash
npx @modelcontextprotocol/inspector
```

Set the transport to **Streamable HTTP** and URL to `http://127.0.0.1:8765/mcp`. Click **Connect** — no `initialize` step is sent or required. The `list_pets` tool should appear in the tools list.

Alternatively, use the SDK 2.x client (Python snippet above) with `mode="2026-07-28"` to adopt the modern protocol directly.

## Project structure

```
pet-hospital-mcp/
├── pyproject.toml
├── README.md
├── UPGRADE_PROMPT.md
├── src/
│   └── pet_hospital_mcp/
│       ├── __init__.py
│       ├── __main__.py
│       ├── config.py
│       ├── server.py
│       ├── rest_client.py
│       ├── errors.py
│       ├── logging_config.py
│       └── tools/
│           ├── __init__.py
│           └── list_pets.py
└── tests/
    ├── conftest.py
    ├── test_input_validation.py
    ├── test_list_pets_tool.py
    ├── test_mcp_server.py
    └── test_rest_client.py
```

To add a new tool in a future phase, create a module under `src/pet_hospital_mcp/tools/` and register it in `server.py` — the REST client, logging, and error conventions are reusable.

## Phase status

- **Phase 1 (this delivery):** `list_pets` only.
- **Phase 2 (not implemented):** additional tools (get-pet-by-id, create, update, delete, medical records, batch operations, statistics). The module structure is designed to accept them without refactoring.
