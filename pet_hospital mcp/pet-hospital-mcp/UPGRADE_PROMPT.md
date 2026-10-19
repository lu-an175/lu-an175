# UPGRADE_PROMPT — Phase 2

> **This file is a planning artifact for the next development phase.**
> Phase 1 is complete: only `list_pets` is implemented. The prompt below
> describes how to extend the service with additional tools without
> refactoring the existing structure.

---

You are an expert MCP + Python developer. The `pet-hospital-mcp/` service
already implements one tool (`list_pets`) using MCP SDK 2.x (`mcp==2.0.0`),
protocol version 2026-07-28, stateless Streamable HTTP, and `MCPServer`.

## Goal

Add the following tools, each adapting the corresponding Go REST API
endpoint. Do **not** modify the Go backend. Each new tool lives in its own
module under `src/pet_hospital_mcp/tools/` and is registered in
`server.py` alongside `list_pets`.

## Tools to implement

| Tool name | Go endpoint | Notes |
|---|---|---|
| `get_pet` | `GET /api/v1/pets/{id}` | Return a single pet or `BACKEND_API_ERROR` on 404. |
| `create_pet` | `POST /api/v1/pets` | Input model mirrors the Go `Pet` create payload. |
| `update_pet` | `PUT /api/v1/pets/{id}` | Partial update; reject unknown fields. |
| `delete_pet` | `DELETE /api/v1/pets/{id}` | Return success envelope on 200. |
| `list_medical_records` | `GET /api/v1/pets/{id}/records` | Paginated. |
| `add_medical_record` | `POST /api/v1/pets/{id}/records` | Input mirrors `MedicalRecord`. |
| `list_charges` | `GET /api/v1/pets/{id}/charges` | Paginated. |
| `add_charge` | `POST /api/v1/pets/{id}/charges` | Input mirrors `Treatment`. |
| `get_statistics` | `GET /api/v1/statistics` | Return aggregate stats. |
| `batch_import` | `POST /api/v1/pets/batch` | Accept a list of pets; return per-item results. |
| `export_pets` | `GET /api/v1/pets/export` | Return a downloadable format. |

## Rules

1. **Reuse** `rest_client.py`, `errors.py`, `logging_config.py`, `config.py`.
   Do not duplicate their logic. Extend `PetHospitalClient` with new
   methods only if the existing generic `get()` / `post()` / `put()` /
   `delete()` helpers are insufficient.

2. **Input/output models**: use Pydantic with `extra="forbid"` on inputs.
   Enum values must match the Go backend exactly (see
   `tools/list_pets.py` for the pattern). Output models mirror the Go
   response `data` field.

3. **Error handling**: raise `PetHospitalError` with the appropriate code
   from `errors.py`. Never expose HTTPX, Pydantic, or Python stack traces
   to the MCP client.

4. **Logging**: every tool logs `tool_name`, `params` (redacted), `status`,
   `duration_ms` via the existing `logging_config.py` infrastructure.

5. **Tests**: add a test module per tool under `tests/`. Use
   `httpx.MockTransport` (via `conftest.make_mock_transport`). Never
   contact the real Go service. Cover: success, validation failure,
   4xx/5xx, timeout, non-JSON, shape mismatch.

6. **Registration**: call `register_<tool_name>(mcp, client)` in
   `server.py` inside `create_app()`, right after `register_list_pets`.

7. **No stateful sessions**: do not add `initialize`, `Mcp-Session-Id`,
   session stores, or `max_sessions`. The 2026-07-28 protocol remains
   stateless.

8. **No FastMCP**: do not import `mcp.server.fastmcp.FastMCP`.

## Verification

```bash
cd pet-hospital-mcp
pytest -q
```

All tests (phase 1 + phase 2) must pass. Then manually verify each new
tool with the MCP Inspector or SDK client.
