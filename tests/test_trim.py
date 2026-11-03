from __future__ import annotations

from mealie_agent_mcp import trim


def test_compact_drops_empty_but_keeps_false_and_zero() -> None:
    assert trim.compact({"a": None, "b": "", "c": [], "d": {}, "e": False, "f": 0, "g": "x"}) == {
        "e": False,
        "f": 0,
        "g": "x",
    }


def test_recipe_detail_is_compact() -> None:
    raw = {
        "id": "r1",
        "slug": "chili",
        "name": "Chili",
        "groupId": "g",
        "householdId": "h",
        "userId": "u",
        "recipeServings": 4.0,
        "recipeYieldQuantity": 0.0,
        "tags": [{"id": "t", "name": "Dinner", "slug": "dinner", "groupId": "g"}],
        "recipeCategory": [],
        "recipeIngredient": [
            {
                "quantity": 2.0,
                "unit": {"id": "u1", "name": "cup", "createdAt": "x"},
                "food": {"id": "f1", "name": "beans", "label": None},
                "note": "",
                "display": "2 cup beans",
                "referenceId": "abc",
            },
            {"quantity": 0.0, "unit": None, "food": None, "note": "salt", "display": "salt"},
        ],
        "recipeInstructions": [
            {"id": "s1", "title": None, "text": "Cook.", "ingredientReferences": []}
        ],
        "nutrition": {"calories": "300", "fatContent": None},
        "settings": {"public": False},
    }
    out = trim.recipe_detail(raw, link="http://m/g/home/r/chili")
    assert out == {
        "id": "r1",
        "slug": "chili",
        "name": "Chili",
        "servings": 4,
        "tags": ["Dinner"],
        "ingredients": [
            {"text": "2 cup beans", "quantity": 2, "unit": "cup", "food": "beans"},
            {"text": "salt"},
        ],
        "instructions": [{"text": "Cook."}],
        "nutrition": {"calories": "300"},
        "url": "http://m/g/home/r/chili",
    }


def test_shopping_list_detail_hides_checked_by_default() -> None:
    sl = {
        "id": "l1",
        "name": "Weekly",
        "listItems": [
            {"id": "a", "display": "Milk", "checked": False, "quantity": 1},
            {"id": "b", "display": "Eggs", "checked": True, "label": {"name": "Dairy"}},
        ],
    }
    out = trim.shopping_list_detail(sl, include_checked=False)
    assert out["items"] == [{"id": "a", "text": "Milk", "checked": False}]
    assert (out["unchecked_count"], out["checked_count"]) == (1, 1)
    full = trim.shopping_list_detail(sl, include_checked=True)
    assert full["items"][1] == {"id": "b", "text": "Eggs", "checked": True, "label": "Dairy"}


def test_meal_plan_sorting() -> None:
    entries = [
        trim.meal_plan_entry({"id": 1, "date": "2026-01-02", "entryType": "breakfast"}),
        trim.meal_plan_entry({"id": 2, "date": "2026-01-01", "entryType": "dinner"}),
        trim.meal_plan_entry({"id": 3, "date": "2026-01-01", "entryType": "lunch"}),
    ]
    assert [e["id"] for e in sorted(entries, key=trim.meal_plan_sort_key)] == [3, 2, 1]
