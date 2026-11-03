"""Exercise every tool over streamable HTTP against a running server.

    uv run python dev/smoke_http.py http://127.0.0.1:8000/mcp <bearer-token>

Creates throwaway data in Mealie; only point it at a test instance.
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from datetime import date, timedelta
from typing import Any

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport


async def main(url: str, token: str | None) -> None:
    headers = {"Authorization": f"Bearer {token}"} if token else None
    async with Client(StreamableHttpTransport(url, headers=headers)) as client:

        async def call(tool: str, /, **args: Any) -> Any:
            result = await client.call_tool(tool, args, raise_on_error=False)
            text = result.content[0].text if result.content else ""  # type: ignore[union-attr]
            status = "ERROR" if result.is_error else "ok"
            print(f"{status:5} {tool}: {text[:140]}")
            if result.is_error:
                raise SystemExit(f"{tool} failed")
            return json.loads(text)

        tools = await client.list_tools()
        print(f"{len(tools)} tools: {', '.join(t.name for t in tools)}")

        recipe = await call(
            "create_recipe",
            name=f"Smoke Chili {uuid.uuid4().hex[:6]}",
            ingredients=[
                {"text": "1 lb ground beef"},
                {"text": "2 cans kidney beans, drained"},
                {"quantity": 1, "unit": "tablespoon", "food": "chili powder"},
            ],
            instructions=["Brown beef.", {"title": "Simmer", "text": "Add beans, simmer."}],
            tags=["Smoke"],
            servings=4,
        )
        slug = recipe["slug"]
        await call("search_recipes", query=recipe["name"])
        await call("get_recipe", recipe=slug)
        await call("update_recipe", recipe=slug, description="Updated by smoke test")
        await call("list_recipes", per_page=3)
        await call("list_recipe_organizers", kind="tags")
        await call("parse_ingredients", ingredients=["3 cloves garlic, minced"])

        day = (date.today() + timedelta(days=500)).isoformat()
        entry = await call("create_meal_plan_entry", day=day, meal="dinner", recipe=slug)
        random_entry = await call("create_random_meal_plan_entry", day=day, meal="lunch")
        await call("list_meal_plans", start_date=day, end_date=day)
        await call("get_meal_plan_for_date", day=day)
        await call("delete_meal_plan_entry", entry_id=entry["id"])
        await call("delete_meal_plan_entry", entry_id=random_entry["id"])

        sl = await call("create_shopping_list", name=f"Smoke list {uuid.uuid4().hex[:6]}")
        await call("list_shopping_lists")
        added = await call("add_shopping_list_items", list_id=sl["id"], items=[{"text": "Milk"}])
        await call("add_recipe_to_shopping_list", list_id=sl["id"], recipe=slug, scale=2)
        milk = added["added"][0]["id"]
        await call("set_shopping_list_items_checked", list_id=sl["id"], item_ids=[milk])
        await call("get_shopping_list", list_id=sl["id"], include_checked=True)
        await call("remove_shopping_list_items", list_id=sl["id"], all_checked=True)
        print("all tools ok")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None))
