"""Reduce Mealie's verbose JSON to what an agent needs.

Mealie responses repeat group/household ids, timestamps and full food/unit
objects everywhere. Agents pay for every token, so each shape below keeps only
fields that help answer a question or make a follow-up call.
"""

from __future__ import annotations

from typing import Any

Obj = dict[str, Any]

_EMPTY: tuple[Any, ...] = (None, "", [], {})


def compact(d: Obj) -> Obj:
    """Drop keys whose value is empty."""
    return {k: v for k, v in d.items() if not any(v is e or v == e for e in _EMPTY)}


def name_of(obj: Any) -> str | None:
    return obj.get("name") if isinstance(obj, dict) else None


def _names(items: Any) -> list[str]:
    return [n for n in (name_of(i) for i in items or []) if n]


def num(value: Any) -> Any:
    """Render 2.0 as 2 to save tokens and read naturally."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _truncate(text: str | None, limit: int) -> str | None:
    if not text or len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def recipe_link(base_url: str, group_slug: str | None, slug: str | None) -> str | None:
    if not group_slug or not slug:
        return None
    return f"{base_url}/g/{group_slug}/r/{slug}"


def recipe_summary(r: Obj, *, link: str | None = None) -> Obj:
    return compact(
        {
            "id": r.get("id"),
            "slug": r.get("slug"),
            "name": r.get("name"),
            "description": _truncate(r.get("description"), 200),
            "tags": _names(r.get("tags")),
            "categories": _names(r.get("recipeCategory")),
            "total_time": r.get("totalTime"),
            "rating": r.get("rating"),
            "url": link,
        }
    )


def ingredient(i: Obj) -> Obj:
    out = compact(
        {
            "title": i.get("title"),
            "text": i.get("display") or i.get("note") or i.get("originalText"),
            "quantity": num(i.get("quantity")) or None,
            "unit": name_of(i.get("unit")),
            "food": name_of(i.get("food")),
            "note": i.get("note"),
            "recipe": name_of(i.get("referencedRecipe")),
        }
    )
    # Unparsed ingredients only carry free text; don't repeat it as a note.
    if out.keys() <= {"title", "text", "note"} and out.get("note") == out.get("text"):
        out.pop("note", None)
    return out


def instruction(step: Obj) -> Obj:
    return compact({"title": step.get("title"), "text": step.get("text")})


def nutrition(n: Obj | None) -> Obj:
    if not n:
        return {}
    return compact({k.removesuffix("Content"): v for k, v in n.items()})


def recipe_detail(r: Obj, *, link: str | None = None) -> Obj:
    return compact(
        {
            "id": r.get("id"),
            "slug": r.get("slug"),
            "name": r.get("name"),
            "description": r.get("description"),
            "servings": num(r.get("recipeServings")) or None,
            "yield": r.get("recipeYield") or (num(r.get("recipeYieldQuantity")) or None),
            "prep_time": r.get("prepTime"),
            "cook_time": r.get("cookTime") or r.get("performTime"),
            "total_time": r.get("totalTime"),
            "tags": _names(r.get("tags")),
            "categories": _names(r.get("recipeCategory")),
            "tools": _names(r.get("tools")),
            "rating": r.get("rating"),
            "ingredients": [ingredient(i) for i in r.get("recipeIngredient") or []],
            "instructions": [instruction(s) for s in r.get("recipeInstructions") or []],
            "notes": [
                compact({"title": n.get("title"), "text": n.get("text")})
                for n in r.get("notes") or []
            ],
            "nutrition": nutrition(r.get("nutrition")),
            "source_url": r.get("orgURL"),
            "last_made": r.get("lastMade"),
            "url": link,
        }
    )


def meal_plan_entry(e: Obj) -> Obj:
    recipe = e.get("recipe") or {}
    return compact(
        {
            "id": e.get("id"),
            "date": e.get("date"),
            "meal": e.get("entryType"),
            "title": e.get("title"),
            "note": e.get("text"),
            "recipe": compact(
                {"id": recipe.get("id"), "slug": recipe.get("slug"), "name": recipe.get("name")}
            )
            or None,
            "recipe_scale": num(e.get("recipeScale"))
            if e.get("recipeScale") not in (None, 1, 1.0)
            else None,
        }
    )


_MEAL_ORDER = {
    m: i
    for i, m in enumerate(["breakfast", "lunch", "dinner", "side", "snack", "drink", "dessert"])
}


def meal_plan_sort_key(e: Obj) -> tuple[str, int]:
    return (str(e.get("date") or ""), _MEAL_ORDER.get(str(e.get("meal")), 99))


def shopping_item(i: Obj) -> Obj:
    return compact(
        {
            "id": i.get("id"),
            "text": i.get("display") or i.get("note"),
            "checked": bool(i.get("checked")),
            "label": name_of(i.get("label")),
        }
    )


def shopping_list_summary(sl: Obj) -> Obj:
    return compact(
        {
            "id": sl.get("id"),
            "name": sl.get("name"),
            "recipes": _names(ref.get("recipe") for ref in sl.get("recipeReferences") or []),
            "updated_at": sl.get("updatedAt") or sl.get("updateAt"),
        }
    )


def shopping_list_detail(sl: Obj, *, include_checked: bool) -> Obj:
    items = sl.get("listItems") or []
    unchecked = [shopping_item(i) for i in items if not i.get("checked")]
    checked = [shopping_item(i) for i in items if i.get("checked")]
    out = shopping_list_summary(sl) | {
        "unchecked_count": len(unchecked),
        "checked_count": len(checked),
        "items": unchecked + (checked if include_checked else []),
    }
    return out
