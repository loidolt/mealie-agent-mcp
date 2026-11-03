from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from typing import Any

import httpx
import pytest
import respx
from fastmcp import Client, FastMCP

READ_TOOLS = {
    "search_recipes",
    "list_recipes",
    "get_recipe",
    "list_recipe_organizers",
    "parse_ingredients",
    "list_meal_plans",
    "get_meal_plan_for_date",
    "list_shopping_lists",
    "get_shopping_list",
}
WRITE_TOOLS = {
    "create_recipe_from_url",
    "create_recipe",
    "update_recipe",
    "create_meal_plan_entry",
    "create_random_meal_plan_entry",
    "delete_meal_plan_entry",
    "create_shopping_list",
    "add_shopping_list_items",
    "add_recipe_to_shopping_list",
    "set_shopping_list_items_checked",
    "remove_shopping_list_items",
}

RECIPE = {
    "id": "11111111-1111-1111-1111-111111111111",
    "slug": "chili",
    "name": "Chili",
    "groupId": "g",
    "recipeIngredient": [],
    "recipeInstructions": [],
    "tags": [],
}


async def call(client: Client[Any], tool: str, /, **args: Any) -> Any:
    result = await client.call_tool(tool, args, raise_on_error=False)
    text = result.content[0].text if result.content else ""  # type: ignore[union-attr]
    if result.is_error:
        return {"error": text}
    return json.loads(text)


def body(route: respx.Route, index: int = -1) -> Any:
    return json.loads(route.calls[index].request.content)


async def test_tool_sets(server_factory: Callable[..., FastMCP]) -> None:
    async with Client(server_factory()) as c:
        tools = {t.name: t for t in await c.list_tools()}
    assert set(tools) == READ_TOOLS | WRITE_TOOLS
    for name in READ_TOOLS:
        assert tools[name].annotations and tools[name].annotations.read_only_hint is True
    for name in WRITE_TOOLS:
        assert tools[name].annotations and tools[name].annotations.read_only_hint is False
        assert tools[name].description

    async with Client(server_factory(read_only=True)) as c:
        assert {t.name for t in await c.list_tools()} == READ_TOOLS


def test_no_dangerous_surface() -> None:
    """Guard against tools that let a model point Mealie at arbitrary endpoints."""
    banned = ("webhook", "notif", "user", "admin", "backup", "token", "group", "household")
    for name in READ_TOOLS | WRITE_TOOLS:
        assert not any(b in name for b in banned), name


async def test_search_recipes_maps_params(client: Client[Any], mealie: respx.Router) -> None:
    route = mealie.get("/api/recipes").respond(
        json={
            "page": 1,
            "total": 1,
            "total_pages": 1,
            "items": [RECIPE | {"description": "x" * 500}],
        }
    )
    out = await call(client, "search_recipes", query="chili", tags=["dinner", "quick"], per_page=5)
    params = route.calls.last.request.url.params
    assert params["search"] == "chili"
    assert params.get_list("tags") == ["dinner", "quick"]
    assert params["perPage"] == "5"
    recipe = out["recipes"][0]
    assert recipe["url"] == "http://mealie.test/g/home/r/chili"
    assert len(recipe["description"]) == 200
    assert "groupId" not in recipe


async def test_get_recipe_encodes_path(client: Client[Any], mealie: respx.Router) -> None:
    route = mealie.get(url__regex=r"/api/recipes/.+").respond(json=RECIPE)
    await call(client, "get_recipe", recipe="../admin?x=1")
    assert route.calls.last.request.url.raw_path == b"/api/recipes/..%2Fadmin%3Fx%3D1"


async def test_mealie_errors_become_tool_errors(client: Client[Any], mealie: respx.Router) -> None:
    mealie.get("/api/recipes/nope").respond(404, json={"detail": {"message": "No Entry Found"}})
    out = await call(client, "get_recipe", recipe="nope")
    assert "404" in out["error"] and "No Entry Found" in out["error"]


async def test_auth_errors_hint_at_token(client: Client[Any], mealie: respx.Router) -> None:
    mealie.get("/api/households/shopping/lists").respond(401, json={"detail": "Not authenticated"})
    out = await call(client, "list_shopping_lists")
    assert "MEALIE_API_TOKEN" in out["error"]


async def test_unreachable_mealie(client: Client[Any], mealie: respx.Router) -> None:
    mealie.get("/api/households/shopping/lists").mock(side_effect=httpx.ConnectError("boom"))
    out = await call(client, "list_shopping_lists")
    assert "Could not reach Mealie" in out["error"]


async def test_create_recipe_from_url(client: Client[Any], mealie: respx.Router) -> None:
    scrape = mealie.post("/api/recipes/create/url").respond(201, json="chili")
    mealie.get("/api/recipes/chili").respond(
        json=RECIPE | {"recipeIngredient": [{"note": "beans"}], "orgURL": "https://site/x"}
    )
    out = await call(client, "create_recipe_from_url", url="https://site/x")
    assert body(scrape) == {
        "url": "https://site/x",
        "includeTags": False,
        "includeCategories": False,
    }
    assert out["ingredient_count"] == 1 and out["slug"] == "chili"


@pytest.mark.parametrize("url", ["file:///etc/passwd", "javascript:alert(1)", "not a url"])
async def test_create_recipe_from_url_rejects_bad_urls(
    client: Client[Any], mealie: respx.Router, url: str
) -> None:
    scrape = mealie.post("/api/recipes/create/url")
    out = await call(client, "create_recipe_from_url", url=url)
    assert "error" in out and not scrape.called


async def test_create_recipe_parses_and_resolves_ingredients(
    client: Client[Any], mealie: respx.Router
) -> None:
    mealie.post("/api/recipes").respond(201, json="chili")
    mealie.post("/api/parser/ingredients").respond(
        json=[
            {
                "input": "2 cups beans, drained",
                "ingredient": {
                    "quantity": 2.0,
                    "unit": {"id": None, "name": "cup"},
                    "food": {"id": "food-beans", "name": "beans"},
                    "note": "drained",
                },
            },
            {
                "input": "a pinch of love",
                "ingredient": {
                    "quantity": 0.0,
                    "unit": None,
                    "food": None,
                    "note": "a pinch of love",
                },
            },
        ]
    )
    mealie.get("/api/units").respond(
        json={"items": [{"id": "unit-cup", "name": "Cup", "abbreviation": "c"}]}
    )
    mealie.get("/api/foods").respond(json={"items": []})
    create_food = mealie.post("/api/foods").respond(201, json={"id": "food-cumin", "name": "cumin"})
    mealie.get("/api/organizers/tags").respond(
        json={"items": [{"id": "t1", "name": "Dinner", "slug": "dinner"}]}
    )
    patch = mealie.patch("/api/recipes/chili").respond(json=RECIPE)

    await call(
        client,
        "create_recipe",
        name="Chili",
        ingredients=[
            {"text": "2 cups beans, drained"},
            {"quantity": 1, "food": "cumin", "title": "Spices"},
            {"text": "a pinch of love"},
        ],
        instructions=["Cook.", {"title": "Serve", "text": "Eat."}],
        tags=["dinner"],
        parse_ingredients=True,
    )
    sent = body(patch)
    assert all(uuid.UUID(i.pop("referenceId")) for i in sent["recipeIngredient"])
    assert sent["recipeIngredient"][0] == {
        "quantity": 2.0,
        "unit": {"id": "unit-cup", "name": "Cup"},
        "food": {"id": "food-beans", "name": "beans"},
        "note": "drained",
        "title": None,
        "originalText": "2 cups beans, drained",
    }
    assert sent["recipeIngredient"][1]["food"] == {"id": "food-cumin", "name": "cumin"}
    assert sent["recipeIngredient"][1]["title"] == "Spices"
    assert body(create_food) == {"name": "cumin"}
    assert sent["recipeIngredient"][2]["note"] == "a pinch of love"
    assert sent["recipeIngredient"][2]["food"] is None
    assert sent["recipeInstructions"] == [
        {"text": "Cook.", "title": None, "ingredientReferences": []},
        {"text": "Eat.", "title": "Serve", "ingredientReferences": []},
    ]
    assert sent["tags"] == [{"id": "t1", "name": "Dinner", "slug": "dinner"}]
    assert "name" not in sent


async def test_ingredient_falls_back_to_note_without_organize_permission(
    client: Client[Any], mealie: respx.Router
) -> None:
    mealie.get("/api/recipes/chili").respond(json=RECIPE)
    mealie.get("/api/foods").respond(json={"items": []})
    mealie.post("/api/foods").respond(403, json={"detail": "forbidden"})
    patch = mealie.patch("/api/recipes/chili").respond(json=RECIPE)
    await call(
        client,
        "update_recipe",
        recipe="chili",
        ingredients=[{"quantity": 1, "food": "saffron", "note": "a few threads"}],
    )
    ing = body(patch)["recipeIngredient"][0]
    assert ing["food"] is None and ing["note"] == "saffron a few threads"


async def test_update_recipe_only_sends_given_fields(
    client: Client[Any], mealie: respx.Router
) -> None:
    mealie.get("/api/recipes/chili").respond(json=RECIPE)
    patch = mealie.patch("/api/recipes/chili").respond(json=RECIPE | {"description": "New"})
    out = await call(client, "update_recipe", recipe="chili", description="New", servings=6)
    assert body(patch) == {"description": "New", "recipeServings": 6.0}
    assert out["description"] == "New"


async def test_update_recipe_without_parsing_keeps_text(
    client: Client[Any], mealie: respx.Router
) -> None:
    mealie.get("/api/recipes/chili").respond(json=RECIPE)
    parser = mealie.post("/api/parser/ingredients")
    patch = mealie.patch("/api/recipes/chili").respond(json=RECIPE)
    await call(
        client,
        "update_recipe",
        recipe="chili",
        ingredients=[{"text": "2 cups beans"}],
        parse_ingredients=False,
    )
    assert not parser.called
    assert body(patch)["recipeIngredient"][0]["note"] == "2 cups beans"


async def test_meal_plan_tools(client: Client[Any], mealie: respx.Router) -> None:
    listing = mealie.get("/api/households/mealplans").respond(
        json={
            "items": [
                {
                    "id": 2,
                    "date": "2026-11-05",
                    "entryType": "dinner",
                    "recipe": RECIPE,
                    "recipeScale": 1.0,
                },
                {
                    "id": 1,
                    "date": "2026-11-05",
                    "entryType": "breakfast",
                    "title": "Toast",
                    "text": "",
                },
            ]
        }
    )
    out = await call(client, "list_meal_plans", start_date="2026-11-05")
    params = listing.calls.last.request.url.params
    assert (params["start_date"], params["end_date"]) == ("2026-11-05", "2026-11-11")
    assert [e["id"] for e in out["entries"]] == [1, 2]
    assert out["entries"][1]["recipe"] == {"id": RECIPE["id"], "slug": "chili", "name": "Chili"}

    assert "error" in await call(client, "list_meal_plans", start_date="2026-13-01")
    assert "error" in await call(
        client, "list_meal_plans", start_date="2026-11-05", end_date="2026-11-01"
    )

    mealie.get("/api/recipes/chili").respond(json=RECIPE)
    create = mealie.post("/api/households/mealplans").respond(
        201, json={"id": 3, "date": "2026-11-06", "entryType": "lunch", "recipe": RECIPE}
    )
    await call(client, "create_meal_plan_entry", day="2026-11-06", meal="lunch", recipe="chili")
    assert body(create) == {
        "date": "2026-11-06",
        "entryType": "lunch",
        "title": "",
        "text": "",
        "recipeId": RECIPE["id"],
    }
    assert "error" in await call(client, "create_meal_plan_entry", day="2026-11-06")

    delete = mealie.delete("/api/households/mealplans/3").respond(200, json={})
    assert await call(client, "delete_meal_plan_entry", entry_id=3) == {"deleted": 3}
    assert delete.called


async def test_check_items_sends_full_items(client: Client[Any], mealie: respx.Router) -> None:
    item = {
        "id": "i1",
        "shoppingListId": "l1",
        "display": "2 Milk",
        "note": "Milk",
        "quantity": 2.0,
        "checked": False,
        "foodId": None,
    }
    mealie.get("/api/households/shopping/lists/l1").respond(
        json={"id": "l1", "name": "Weekly", "listItems": [item]}
    )
    put = mealie.put("/api/households/shopping/items").respond(json={"updatedItems": []})
    out = await call(
        client, "set_shopping_list_items_checked", list_id="l1", item_ids=["i1", "zzz"]
    )
    assert body(put) == [item | {"checked": True}]
    assert out == {
        "updated": [{"id": "i1", "text": "2 Milk", "checked": True}],
        "not_found": ["zzz"],
    }


async def test_remove_checked_items(client: Client[Any], mealie: respx.Router) -> None:
    mealie.get("/api/households/shopping/lists/l1").respond(
        json={
            "id": "l1",
            "listItems": [
                {"id": "a", "checked": True},
                {"id": "b", "checked": False},
                {"id": "c", "checked": True},
            ],
        }
    )
    delete = mealie.delete("/api/households/shopping/items").respond(json={})
    out = await call(client, "remove_shopping_list_items", list_id="l1", all_checked=True)
    assert delete.calls.last.request.url.params.get_list("ids") == ["a", "c"]
    assert out == {"deleted": 2}


async def test_add_items_and_recipe(client: Client[Any], mealie: respx.Router) -> None:
    bulk = mealie.post("/api/households/shopping/items/create-bulk").respond(
        201, json={"createdItems": [{"id": "n", "display": "2 Milk", "checked": False}]}
    )
    out = await call(
        client, "add_shopping_list_items", list_id="l1", items=[{"text": "Milk", "quantity": 2}]
    )
    assert body(bulk) == [
        {"shoppingListId": "l1", "note": "Milk", "quantity": 2.0, "checked": False}
    ]
    assert out == {"added": [{"id": "n", "text": "2 Milk", "checked": False}]}

    add = mealie.post("/api/households/shopping/lists/l1/recipe").respond(
        json={"id": "l1", "name": "Weekly", "listItems": []}
    )
    await call(client, "add_recipe_to_shopping_list", list_id="l1", recipe=RECIPE["id"], scale=2)
    assert body(add) == [{"recipeId": RECIPE["id"], "recipeIncrementQuantity": 2.0}]
