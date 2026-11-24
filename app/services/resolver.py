"""Finds each product's ingredient list, or says honestly that it couldn't. Never guesses.

Order: pasted text -> photo text -> barcode (cache, then Open Beauty Facts, then old cache) -> unresolved.
"""
from datetime import datetime, timedelta, timezone

from app import config, db
from app.services import obf_client

MESSAGES = {
    "not_found": "This barcode isn't in Open Beauty Facts. Paste the ingredients or upload a label photo to include it.",
    "no_ingredients_listed": "This product is in Open Beauty Facts but nobody has added its ingredients. "
                             "Paste them or upload a label photo to include it.",
    "source_unavailable": "The product database isn't responding right now. Paste the ingredients or try again later.",
}


def _is_fresh(fetched_at: str) -> bool:
    try:
        when = datetime.fromisoformat(fetched_at)
    except ValueError:
        return False
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - when < timedelta(days=config.CACHE_FRESH_DAYS)


def _split_tags(value) -> list[str]:
    if isinstance(value, list):
        return value
    return [t for t in (value or "").split("|") if t]


def lookup_barcode(conn, barcode: str, obf_lookup=obf_client.get_product) -> dict:
    """Cache first, then Open Beauty Facts. Returns a dict with status:
    found / no_ingredients / not_found / error, plus 'cached' and 'stale' notes."""
    cached = db.get_product(conn, barcode)
    if cached and cached["ingredients_text"] and (cached["source"] == "seed" or _is_fresh(cached["fetched_at"])):
        return {**cached, "category_tags": _split_tags(cached["category_tags"]), "status": "found",
                "cached": True, "stale": False}

    live = obf_lookup(barcode)
    if live["status"] in ("found", "no_ingredients"):
        db.save_product(conn, barcode, live["product_name"], live["brand"], live["ingredients_text"],
                        source="open_beauty_facts", category_tags="|".join(live.get("category_tags", [])))
        return {**live, "source": "open_beauty_facts", "cached": False, "stale": False}
    if live["status"] == "error" and cached and cached["ingredients_text"]:
        # The site is down but we have an older copy: use it, and say so.
        return {**cached, "category_tags": _split_tags(cached["category_tags"]), "status": "found",
                "cached": True, "stale": True}
    return {**live, "cached": False, "stale": False}


def detect_type_mismatch(category_tags: list[str], product_type: str, product_types: list[dict]) -> str | None:
    """If Open Beauty Facts clearly files this product as a DIFFERENT type, return that type's label."""
    tags = set(category_tags or [])
    if not tags:
        return None
    by_type = {t["product_type"]: set(_split_tags(t.get("obf_category_tags", ""))) for t in product_types}
    if tags & by_type.get(product_type, set()):
        return None
    for t in product_types:
        if t["product_type"] != product_type and tags & by_type[t["product_type"]]:
            return t["label"]
    return None


def resolve(conn, product, product_type: str, product_types: list[dict],
            obf_lookup=obf_client.get_product) -> dict:
    """product is a ProductIn. Returns a resolved or unresolved record."""
    base = {"display_name": product.display_name}
    if (product.ingredients_text or "").strip():
        return {**base, "resolved": True, "ingredient_source": "pasted_text",
                "ingredients_text": product.ingredients_text.strip()}
    if (product.extracted_text or "").strip():
        return {**base, "resolved": True, "ingredient_source": "label_photo",
                "ingredients_text": product.extracted_text.strip()}

    found = lookup_barcode(conn, product.barcode, obf_lookup)
    if found["status"] == "found":
        rec = {**base, "resolved": True,
               "ingredient_source": "open_beauty_facts (cached)" if found["cached"] else "open_beauty_facts",
               "ingredients_text": found["ingredients_text"], "barcode": product.barcode,
               "product_name": found.get("product_name", ""), "brand": found.get("brand", ""),
               "mismatch_type": detect_type_mismatch(found.get("category_tags", []), product_type, product_types)}
        if found.get("source") == "seed":
            rec["ingredient_source"] = "seed (your own list)"
        if found["stale"]:
            rec["note"] = "The product database was unavailable, so an older saved copy was used. It may be out of date."
        return rec
    reason = {"not_found": "not_found", "no_ingredients": "no_ingredients_listed"}.get(found["status"], "source_unavailable")
    return {**base, "resolved": False, "barcode": product.barcode, "reason": reason, "message": MESSAGES[reason]}
