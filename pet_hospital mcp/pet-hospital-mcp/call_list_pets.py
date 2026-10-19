"""Quick client to call list_pets via MCP Streamable HTTP and show summary."""

import asyncio
import json

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def main() -> None:
    url = "http://127.0.0.1:8765/mcp"
    async with streamable_http_client(url) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "list_pets",
                {"filters": {"pageSize": 5}},
            )
            data = None
            for item in result.content:
                if hasattr(item, "text") and item.text:
                    try:
                        data = json.loads(item.text)
                    except json.JSONDecodeError:
                        pass
            if data is None and getattr(result, "structured_content", None):
                data = result.structured_content

            if data is None:
                print("No data returned")
                return

            print("=" * 60)
            print(f"  宠物医院动物总数: {data['total']} 只")
            print(f"  当前页: {data['page']} / 总页数: {data['totalPages']}")
            print(f"  总费用合计: {data['totalCost']}")
            print("=" * 60)
            print()
            print(f"{'编号':<15} {'名字':<8} {'物种':<6} {'品种':<12} {'状态':<10} {'主人':<8}")
            print("-" * 60)
            for pet in data.get("items", []):
                print(
                    f"{pet.get('id',''):<15} "
                    f"{pet.get('name',''):<8} "
                    f"{pet.get('species',''):<6} "
                    f"{pet.get('breed','') or '-':<12} "
                    f"{pet.get('status',''):<10} "
                    f"{pet.get('ownerName',''):<8}"
                )


if __name__ == "__main__":
    asyncio.run(main())
