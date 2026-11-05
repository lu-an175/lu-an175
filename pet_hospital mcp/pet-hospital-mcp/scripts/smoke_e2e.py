"""End-to-end smoke test against the real Go backend.

Drives the running MCP service (http://127.0.0.1:8765/mcp) with the SDK
2.x client and walks the full lifecycle:

    list_pets -> get_pet -> create_pet -> add_medical_record
    -> add_charge -> get_pet_summary -> update_pet -> get_stats
    -> error paths -> delete_pet -> get_pet (expect NOT_FOUND)

Run it with both services up; it cleans up the archive it creates.
Exit code 0 means every check passed.
"""

from __future__ import annotations

import asyncio
import json
import sys

from mcp import Client

MCP_URL = "http://127.0.0.1:8765/mcp"


def show(label: str, payload: object, *, limit: int = 260) -> None:
    text = json.dumps(payload, ensure_ascii=False, default=str)
    print(f"\n--- {label} ---")
    print(text[:limit] + ("..." if len(text) > limit else ""))


def _text(result: object) -> str:
    content = getattr(result, "content", None) or []
    return content[0].text if content else ""


async def main() -> int:
    failures: list[str] = []

    def check(cond: bool, msg: str) -> None:
        print(("  OK   " if cond else "  FAIL ") + msg)
        if not cond:
            failures.append(msg)

    async with Client(MCP_URL, mode="2026-07-28") as client:
        tools = await client.list_tools()
        names = sorted(t.name for t in tools.tools)
        print(f"discovered {len(names)} tools: {names}")
        check(len(names) == 9, "9 tools exposed")

        # 1. list_pets — pick a real id to work with.
        listed = await client.call_tool(
            "list_pets",
            {"filters": {"pageSize": 2, "sortBy": "totalCost", "order": "desc"}},
        )
        check(not listed.is_error, "list_pets succeeded")
        data = listed.structured_content or {}
        check(data.get("total", 0) > 0, f"list_pets total={data.get('total')}")
        seed_id = data["items"][0]["id"]
        print(f"  (top spender in the archive: {seed_id})")

        # 2. get_pet
        got = await client.call_tool("get_pet", {"pet_id": seed_id})
        check(not got.is_error, f"get_pet {seed_id} succeeded")
        show("get_pet", {"name": (got.structured_content or {}).get("name")})

        # 3. create_pet
        created = await client.call_tool("create_pet", {
            "pet": {
                "name": "冒烟测试犬",
                "ownerName": "阿零",
                "ownerPhone": "13800001234",
                "disease": "急性肠胃炎",
                "doctor": "李医生",
                "species": "犬",
                "ageMonths": 30,
                "note": "phase2 smoke test",
            }
        })
        check(not created.is_error, "create_pet succeeded")
        new_id = (created.structured_content or {}).get("id", "")
        check(new_id.startswith("PET-"), f"backend assigned id={new_id}")
        show("create_pet", created.structured_content)

        # 4. add_medical_record
        recorded = await client.call_tool("add_medical_record", {
            "pet_id": new_id,
            "record": {
                "diagnosis": "急性肠胃炎",
                "doctor": "李医生",
                "symptoms": "呕吐、腹泻",
                "treatment": "补液消炎",
                "prescription": ["阿莫西林"],
                "weightKg": 12.5,
                "temperature": 39.1,
                "charge": 380,
            },
        })
        check(not recorded.is_error, "add_medical_record succeeded")
        rec = recorded.structured_content or {}
        check(rec.get("visitCount") == 1, f"visitCount={rec.get('visitCount')}")

        # 5. add_charge
        charged = await client.call_tool("add_charge", {
            "pet_id": new_id,
            "charge": {
                "item": "血常规检查",
                "amount": 180,
                "category": "检查",
                "doctor": "李医生",
            },
        })
        check(not charged.is_error, "add_charge succeeded")
        ch = charged.structured_content or {}
        check(abs(float(ch.get("totalCost", 0)) - 180.0) < 0.01, f"totalCost={ch.get('totalCost')}")

        # 6. get_pet_summary
        summary = await client.call_tool("get_pet_summary", {"pet_id": new_id})
        check(not summary.is_error, "get_pet_summary succeeded")
        sm = summary.structured_content or {}
        check(sm.get("visitCount") == 1, f"summary visitCount={sm.get('visitCount')}")
        check((sm.get("costByCategory") or {}).get("检查") == 180.0, "costByCategory 检查=180")
        show("get_pet_summary", sm)

        # 7. update_pet (PATCH must not wipe history)
        updated = await client.call_tool("update_pet", {
            "pet_id": new_id,
            "patch": {"status": "已康复", "note": "已出院"},
        })
        check(not updated.is_error, "update_pet succeeded")
        up = updated.structured_content or {}
        check(up.get("status") == "已康复", f"status={up.get('status')}")
        check(up.get("visitCount") == 1, "PATCH kept the medical history")
        check(abs(float(up.get("totalCost", 0)) - 180.0) < 0.01, "PATCH kept the charge total")

        # 8. get_stats
        stats = await client.call_tool("get_stats", {"top": 3})
        check(not stats.is_error, "get_stats succeeded")
        st = stats.structured_content or {}
        check(st.get("totalPets", 0) > 0, f"stats totalPets={st.get('totalPets')}")
        check(len(st.get("topSpenders") or []) == 3, "topSpenders honours top=3")

        # 9. error paths
        missing = await client.call_tool("get_pet", {"pet_id": "PET-999999"})
        check(missing.is_error is True, "get_pet on a missing id is an error")
        check("NOT_FOUND" in _text(missing), "error envelope carries NOT_FOUND")
        show("error envelope (NOT_FOUND)", _text(missing))

        bad_id = await client.call_tool("get_pet", {"pet_id": "../admin/seed"})
        check(bad_id.is_error is True, "path-shaped id rejected")
        check("VALIDATION_ERROR" in _text(bad_id), "error envelope carries VALIDATION_ERROR")

        bad_patch = await client.call_tool("update_pet", {"pet_id": new_id, "patch": {}})
        check(bad_patch.is_error is True, "empty patch rejected")

        bad_species = await client.call_tool("create_pet", {
            "pet": {
                "name": "鱼", "ownerName": "阿零", "ownerPhone": "13800001234",
                "disease": "白点病", "doctor": "李医生", "species": "鱼",
            }
        })
        check(bad_species.is_error is True, "unknown species rejected")

        bad_phone = await client.call_tool("create_pet", {
            "pet": {
                "name": "旺财", "ownerName": "阿零", "ownerPhone": "abc",
                "disease": "肠胃炎", "doctor": "李医生",
            }
        })
        check(bad_phone.is_error is True, "invalid phone rejected")

        # 10. delete_pet — clean up.
        deleted = await client.call_tool("delete_pet", {"pet_id": new_id})
        check(not deleted.is_error, "delete_pet succeeded")
        check((deleted.structured_content or {}).get("id") == new_id, "delete returned the id")

        gone = await client.call_tool("get_pet", {"pet_id": new_id})
        check(gone.is_error is True, "record is really gone")

    print("\n" + ("ALL CHECKS PASSED" if not failures else f"FAILURES ({len(failures)}): {failures}"))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
