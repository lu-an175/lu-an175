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
| Tools | **9** — full CRUD + medical records + charges + summary + stats |
| Tests | **95 passed** |

## Architecture

```
AI Agent (MCP Client)
        │  Streamable HTTP (stateless, 2026-07-28)
        ▼
┌──────────────────────────────────────────────────┐
│  pet-hospital-mcp (Python)                       │
│  MCPServer + Starlette + uvicorn                 │
│  ┌────────────────────┐  ┌────────────────────┐  │
│  │ /mcp               │  │ /health            │  │
│  │ read:              │  │ health check       │  │
│  │  list_pets         │  │                    │  │
│  │  get_pet           │  └────────────────────┘  │
│  │  get_pet_summary   │                          │
│  │  get_stats         │                          │
│  │ write:             │                          │
│  │  create_pet        │                          │
│  │  update_pet        │                          │
│  │  delete_pet        │                          │
│  │  add_medical_record│                          │
│  │  add_charge        │                          │
│  └─────────┬──────────┘                          │
│            │ httpx (timeout + selective retry)   │
└────────────┼─────────────────────────────────────┘
             ▼
┌──────────────────────────────────────────────────┐
│  Go Pet Hospital REST API                        │
│  127.0.0.1:8080  (29 endpoints)                  │
└──────────────────────────────────────────────────┘
```

## Prerequisites

1. **Go** (for the backend) — install from <https://go.dev/doc/install>
2. **Python 3.11+** — install from <https://www.python.org/downloads/>
3. The Go Pet Hospital REST API source under `../pet-hospital-mcp-teaching-main/`
   (or the prebuilt `../windows/pethospital.exe` with its `data/pet.db`)

## Quick start

### 1. Start the Go backend

```bash
# from source
cd ../pet-hospital-mcp-teaching-main
go run . -seed          # -seed writes demo data on first run
# → listening on 127.0.0.1:8080
```

```bash
# or use the prebuilt Windows binary (ships with 1000+ demo records)
cd ../windows
./pethospital.exe
```

Verify:

```bash
curl http://127.0.0.1:8080/health
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

Discover the tools (raw JSON-RPC, stateless — no `initialize`):

```bash
curl -X POST http://127.0.0.1:8765/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "MCP-Protocol-Version: 2026-07-28" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28","io.modelcontextprotocol/clientCapabilities":{}}}}'
```

Call a tool (SDK Client — recommended). In SDK 2.x the client takes the URL
directly; it opens the Streamable HTTP transport for you:

```python
import asyncio
from mcp import Client

async def main():
    async with Client("http://127.0.0.1:8765/mcp", mode="2026-07-28") as client:
        result = await client.call_tool("list_pets", {
            "filters": {"species": "犬", "page": 1, "pageSize": 5}
        })
        print(result.structured_content)

asyncio.run(main())
```

### 5. End-to-end smoke test (optional)

With both services running, this walks the whole lifecycle — list → get →
create → add record → add charge → summary → update → stats → delete — and
asserts on the results. It deletes the archive it creates.

```bash
python scripts/smoke_e2e.py
# → ALL CHECKS PASSED
```

## Configuration

All settings are environment variables (defaults shown):

| Variable | Default | Description |
|---|---|---|
| `PET_HOSPITAL_BASE_URL` | `http://127.0.0.1:8080` | Go REST API base URL |
| `MCP_HOST` | `127.0.0.1` | Bind interface (loopback only by default) |
| `MCP_PORT` | `8765` | MCP HTTP port |
| `PET_HOSPITAL_TIMEOUT` | `10` | Per-request timeout (seconds) |
| `PET_HOSPITAL_RETRIES` | `2` | Retry count for timeout/connection errors on **reads** |
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

## Tools

Nine tools, mapped one-to-one onto Go endpoints. Every tool takes a single
nested object argument so the JSON schema stays readable.

### Reads

| Tool | Backend | Purpose |
|---|---|---|
| `list_pets` | `GET /api/v1/pets` | Browse / filter / sort / paginate the archive |
| `get_pet` | `GET /api/v1/pets/{id}` | One full record including `records` + `charges` |
| `get_pet_summary` | `GET /api/v1/pets/{id}/summary` | Cost & visit rollup for one pet |
| `get_stats` | `GET /api/v1/stats?top=N` | Clinic-wide totals, breakdowns, top spenders |

### Writes

| Tool | Backend | Purpose |
|---|---|---|
| `create_pet` | `POST /api/v1/pets` | Open a new archive (backend assigns `PET-000001`) |
| `update_pet` | `PATCH /api/v1/pets/{id}` | Partial update; omitted fields are untouched |
| `delete_pet` | `DELETE /api/v1/pets/{id}` | Permanently remove a record |
| `add_medical_record` | `POST /api/v1/pets/{id}/records` | Append one visit to the history |
| `add_charge` | `POST /api/v1/pets/{id}/charges` | Append one charge line; `totalCost` recalculates |

`PUT /api/v1/pets/{id}` is deliberately **not** exposed: it is a full replace
and would silently wipe `records` and `charges`. `update_pet` uses `PATCH`.

### `list_pets` parameters

All optional, nested under `filters`:

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

### `create_pet` parameters

Required: `name`, `ownerName`, `ownerPhone`, `disease`, `doctor`.
Optional: `species` (default `其他`), `status` (default `待就诊`), `breed`,
`gender`, `ageMonths` (0–600), `color`, `chipNo`, `ownerAddr`, `allergy`, `note`.

`ownerPhone` is validated locally with the same rule as the Go backend
(7–15 digits; `-` `+` space `(` `)` allowed), so a bad phone fails fast with
a precise message instead of a generic HTTP 400.

`records` / `charges` are **not** accepted here — use `add_medical_record` /
`add_charge` after creating the archive, so each write is a separate,
auditable call.

### `add_charge` parameters

Required: `item`, `amount` (≥ 0). Optional: `category` (default `其他`),
`doctor`, `date` (`YYYY-MM-DD`), `note`.

`category` is free text because the Go backend never validates it, but the
hospital groups its reports by it — prefer one of
`检查` `药品` `手术` `住院` `疫苗` `护理` `其他`.

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

Error codes: `VALIDATION_ERROR`, `NOT_FOUND`, `BACKEND_TIMEOUT`,
`BACKEND_UNAVAILABLE`, `BACKEND_API_ERROR`, `BACKEND_INVALID_RESPONSE`,
`INTERNAL_ERROR`.

`NOT_FOUND` is worth handling explicitly: it is what a stale or mistyped
`pet_id` produces, and it is reported as an error for `delete_pet` too — a
delete of a missing id never looks like a successful delete.

## Retry policy

Reads and writes are treated differently, on purpose:

| Method | Timeout | Connection refused |
|---|---|---|
| `GET`, `DELETE` | retried with exponential back-off | retried |
| `POST`, `PATCH` | **not retried** (`retry_safe: false`) | **not retried** (`retry_safe: true`) |

A timed-out `POST /pets` may already have been committed by the backend, and
a blind retry would create a duplicate archive. So the write fails fast and
the error `details.retry_safe` tells the caller whether trying again is safe
(`false` = outcome unknown, check before retrying; `true` = definitely did
not land).

## Logging

Single-line JSON to stderr. Each entry includes `timestamp`, `level`,
`logger`, `message`, and tool-specific fields: `tool_name`, `params`,
`status`, `duration_ms` (plus `error_code` on failures).

Sensitive fields (`ownerPhone`, `ownerAddr`, `chipNo` and their snake_case
variants) are recursively redacted before logging — including inside
`params`, so a tool call never writes a raw phone number to disk.

## Testing

Tests use `pytest` + `pytest-asyncio` with `httpx.MockTransport` — the real
Go service is **never** contacted.

Coverage:

- Input validation (species/status/sortBy/order enums, page/pageSize/min/max ranges, NaN/Infinity, unknown fields)
- Pet-id validation (charset, length, path-injection shapes such as `../admin/seed`)
- Date validation (`YYYY-MM-DD` only)
- REST client (parameter forwarding, 4xx/5xx, 404 → `NOT_FOUND`, timeout, connection error, non-JSON, missing `data` key)
- Retry policy (GET retried, POST not retried, `retry_safe` flags)
- Every tool: happy path + backend error + validation rejection
- MCP server (tool registration, input/output schema, tool call, `/health`, stateless HTTP: no `Mcp-Session-Id`, tool callable over HTTP)

```bash
cd pet-hospital-mcp
pytest -q
```

Expected result: **95 passed**.

For a real end-to-end check against a running backend, see
`scripts/smoke_e2e.py` above.

## Verifying the stateless MCP connection

The 2026-07-28 protocol is stateless: no `initialize` handshake, no
`Mcp-Session-Id` header. To verify with MCP Inspector:

```bash
npx @modelcontextprotocol/inspector
```

Set the transport to **Streamable HTTP** and URL to `http://127.0.0.1:8765/mcp`.
Click **Connect** — no `initialize` step is sent or required. All nine tools
should appear in the tools list.

Alternatively, use the SDK 2.x client (Python snippet above) with
`mode="2026-07-28"` to adopt the modern protocol directly.

## Project structure

```
pet-hospital-mcp/
├── pyproject.toml
├── README.md
├── UPGRADE_PROMPT.md
├── scripts/
│   └── smoke_e2e.py            # end-to-end run against a live backend
├── src/
│   └── pet_hospital_mcp/
│       ├── __init__.py
│       ├── __main__.py
│       ├── config.py
│       ├── server.py           # MCPServer assembly + tool registry
│       ├── rest_client.py      # the only component that speaks HTTP
│       ├── models.py           # response shapes mirrored from Go
│       ├── errors.py
│       ├── logging_config.py
│       └── tools/
│           ├── __init__.py     # REGISTERERS — the single tool list
│           ├── _common.py      # enums, id/date validation, run_tool()
│           ├── list_pets.py
│           ├── get_pet.py
│           ├── create_pet.py
│           ├── update_pet.py
│           ├── delete_pet.py
│           ├── add_medical_record.py
│           ├── add_charge.py
│           ├── get_pet_summary.py
│           └── get_stats.py
└── tests/
    ├── conftest.py
    ├── test_input_validation.py
    ├── test_list_pets_tool.py
    ├── test_mcp_server.py
    ├── test_phase2_inputs.py
    ├── test_phase2_tools.py
    └── test_rest_client.py
```

### Adding a tool

1. Create `src/pet_hospital_mcp/tools/<name>.py` with an `Input` model
   (`extra="forbid"`), an `execute_<name>()` coroutine using
   `_common.run_tool()`, and a `register_<name>()` function.
2. Add the client method to `rest_client.py` if the endpoint is new.
3. Append `register_<name>` to `REGISTERERS` in `tools/__init__.py`.
4. Add a test class to `tests/test_phase2_tools.py` (or a new file).

`run_tool()` gives you timing, redacted JSON logging, and the unified error
envelope for free; the REST client already handles timeouts, retries, 404s
and envelope validation.

## Phase status

- **Phase 1 (delivered):** `list_pets`, stateless Streamable HTTP transport,
  REST client, structured logging, unified error model.
- **Phase 2 (delivered):** `get_pet`, `create_pet`, `update_pet`,
  `delete_pet`, `add_medical_record`, `add_charge`, `get_pet_summary`,
  `get_stats`; `NOT_FOUND` error code; read/write-aware retry policy;
  end-to-end smoke script.
- **Not exposed (by design):** `PUT` (destructive full replace), batch
  create/delete, CSV export, `/api/v1/meta`, and the admin endpoints
  (compaction, seeding) — none of them are safe or useful as agent-facing
  tools without extra guardrails.
