"""End-to-end tests against a real Mealie.

Run with a throwaway instance only (they create and delete data):
    docker compose -f dev/compose.yaml up -d --wait mealie
    eval "$(uv run python dev/bootstrap_mealie.py)" && export MEALIE_URL MEALIE_API_TOKEN
    uv run pytest -m integration
Set MEALIE_IT_SCRAPE_URL to also test recipe import from a live web page.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import AsyncIterator
from datetime import date, timedelta
from typing import Any

import pytest
from fastmcp import Client

from mealie_agent_mcp.config import Settings
from mealie_agent_mcp.server import create_server

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (os.environ.get("MEALIE_URL") and os.environ.get("MEALIE_API_TOKEN")),
        reason="MEALIE_URL / MEALIE_API_TOKEN not set",
    ),
]


@pytest.fixture
async def mcp_client() -> AsyncIterator[Client[Any]]:
    async with Client(create_server(Settings.load())) as c:
        yield c


async def call(client: Client[Any], tool: str, /, **args: Any) -> Any:
    result = await client.call_tool(tool, args, raise_on_error=False)
    text = result.content[0].text  # type: ignore[union-attr]
    assert not result.is_error, f"{tool}: {text}"
    return json.loads(text)


async def test_recipe_lifecycle(mcp_client: Client[Any]) -> None:
    name = f"IT Chili {uuid.uuid4().hex[:6]}"
    created = await call(
        mcp_client,
        "create_recipe",
        name=name,
        description="integration test",
        ingredients=[
            {"text": "1 lb ground beef"},
            {"text": "2 cans kidney beans, drained"},
            {"quantity": 1, "unit": "tablespoon", "food": "chili powder"},
            {"text": "salt to taste", "title": "Seasoning"},
        ],
        instructions=["Brown the beef.", {"title": "Simmer", "text": "Simmer 30 minutes."}],
        tags=["Integration"],
        servings=4,
    )
    slug = created["slug"]
    assert created["servings"] == 4
    assert created["tags"] == ["Integration"]
    beans = created["ingredients"][1]
    assert (beans["quantity"], beans["food"], beans["note"]) == (2, "kidney beans", "drained")
    assert created["ingredients"][2]["food"] == "chili powder"
    assert created["ingredients"][3]["title"] == "Seasoning"
    assert created["instructions"][1] == {"title": "Simmer", "text": "Simmer 30 minutes."}
    assert created["url"].endswith(f"/r/{slug}")

    found = await call(mcp_client, "search_recipes", query=name)
    assert slug in [r["slug"] for r in found["recipes"]]
    tagged = await call(mcp_client, "search_recipes", tags=["integration"])
    assert slug in [r["slug"] for r in tagged["recipes"]]

    by_id = await call(mcp_client, "get_recipe", recipe=created["id"])
    assert by_id["slug"] == slug

    updated = await call(
        mcp_client,
        "update_recipe",
        recipe=slug,
        description="changed",
        ingredients=[{"quantity": 500, "unit": "g", "food": "ground beef"}],
    )
    assert updated["description"] == "changed"
    assert updated["instructions"] == created["instructions"]
    assert [i["food"] for i in updated["ingredients"]] == ["ground beef"]

    listed = await call(mcp_client, "list_recipes", order_by="date_added", per_page=50)
    assert slug in [r["slug"] for r in listed["recipes"]]
    organizers = await call(mcp_client, "list_recipe_organizers", kind="tags")
    assert "integration" in [t["slug"] for t in organizers["tags"]]
    parsed = await call(mcp_client, "parse_ingredients", ingredients=["3 cloves garlic, minced"])
    assert parsed["ingredients"][0]["food"] == "garlic"


async def test_meal_plan_and_shopping(mcp_client: Client[Any]) -> None:
    recipe = await call(
        mcp_client,
        "create_recipe",
        name=f"IT Soup {uuid.uuid4().hex[:6]}",
        ingredients=[{"text": "2 carrots"}, {"text": "1 onion"}],
    )
    day = (date.today() + timedelta(days=400)).isoformat()

    entry = await call(
        mcp_client, "create_meal_plan_entry", day=day, meal="lunch", recipe=recipe["slug"]
    )
    note = await call(mcp_client, "create_meal_plan_entry", day=day, title="Leftovers")
    rnd = await call(mcp_client, "create_random_meal_plan_entry", day=day, meal="dinner")
    on_day = (await call(mcp_client, "get_meal_plan_for_date", day=day))["entries"]
    assert [e["meal"] for e in on_day] == ["lunch", "dinner", "dinner"]
    in_range = await call(mcp_client, "list_meal_plans", start_date=day, end_date=day)
    assert {e["id"] for e in in_range["entries"]} == {entry["id"], note["id"], rnd["id"]}
    for e in (entry, note, rnd):
        await call(mcp_client, "delete_meal_plan_entry", entry_id=e["id"])
    assert (await call(mcp_client, "get_meal_plan_for_date", day=day))["entries"] == []

    sl = await call(mcp_client, "create_shopping_list", name=f"IT list {uuid.uuid4().hex[:6]}")
    assert sl["id"] in [
        s["id"] for s in (await call(mcp_client, "list_shopping_lists"))["shopping_lists"]
    ]
    added = await call(
        mcp_client,
        "add_shopping_list_items",
        list_id=sl["id"],
        items=[{"text": "Milk", "quantity": 2}],
    )
    milk = added["added"][0]["id"]
    with_recipe = await call(
        mcp_client, "add_recipe_to_shopping_list", list_id=sl["id"], recipe=recipe["slug"], scale=2
    )
    assert with_recipe["unchecked_count"] == 3

    checked = await call(
        mcp_client, "set_shopping_list_items_checked", list_id=sl["id"], item_ids=[milk]
    )
    assert checked["updated"][0]["checked"] is True
    detail = await call(mcp_client, "get_shopping_list", list_id=sl["id"])
    assert (detail["unchecked_count"], detail["checked_count"]) == (2, 1)
    assert milk not in [i["id"] for i in detail["items"]]
    # The full item survived the round trip (quantity not reset by the bulk update).
    full = await call(mcp_client, "get_shopping_list", list_id=sl["id"], include_checked=True)
    assert any(i["id"] == milk and i["text"].startswith("2") for i in full["items"])

    await call(
        mcp_client,
        "set_shopping_list_items_checked",
        list_id=sl["id"],
        item_ids=[milk],
        checked=False,
    )
    await call(mcp_client, "set_shopping_list_items_checked", list_id=sl["id"], item_ids=[milk])
    removed = await call(
        mcp_client, "remove_shopping_list_items", list_id=sl["id"], all_checked=True
    )
    assert removed["deleted"] == 1


@pytest.mark.skipif(not os.environ.get("MEALIE_IT_SCRAPE_URL"), reason="needs network")
async def test_create_recipe_from_url(mcp_client: Client[Any]) -> None:
    out = await call(mcp_client, "create_recipe_from_url", url=os.environ["MEALIE_IT_SCRAPE_URL"])
    assert out["slug"] and out["ingredient_count"] > 0


async def test_read_only_mode() -> None:
    settings = Settings.load(read_only=True)
    async with Client(create_server(settings)) as c:
        names = {t.name for t in await c.list_tools()}
    assert "create_recipe" not in names and "get_recipe" in names
