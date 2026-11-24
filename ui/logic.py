"""Plain functions behind the screen, kept separate so they can be tested without a browser."""
import re

UI_VERSION = "1.0.0"                 # shown at the bottom of the page, so you can check an update installed

METHODS = ["Barcode", "Search by name", "Paste ingredients", "Label photo"]
MIN_PRODUCTS, MAX_PRODUCTS, MAX_CONCERNS = 2, 4, 3


NAME_MAX = 60


def auto_name(p: dict, index: int) -> str:
    """The name shown for a product. Barcode and search use the real product name from the database.
    Pasted text and photos are called "Product 1", "Product 2"... (no name box to fill in)."""
    method = p.get("method")
    if method == "Barcode":
        bc = re.sub(r"\s", "", p.get("barcode") or "")
        name = p.get("found_name") if bc and bc == p.get("found_barcode") else ""
    elif method == "Search by name":
        name = p.get("picked_name") or ""
    else:
        name = ""
    name = re.sub(r"\s+", " ", name).strip()
    return (name or f"Product {index}")[:NAME_MAX].strip()


def product_payload(p: dict, index: int = 1) -> dict | None:
    """Turn one product's form fields into what the API expects, or None if it isn't filled in yet.
    p: {"method", "barcode", "found_name", "found_barcode", "picked_barcode", "picked_name",
        "pasted", "extracted"}"""
    method = p.get("method")
    out = {"display_name": auto_name(p, index)}
    if method == "Barcode":
        bc = re.sub(r"\s", "", p.get("barcode") or "")
        if not bc:
            return None
        out["barcode"] = bc
    elif method == "Search by name":
        if not p.get("picked_barcode"):
            return None
        out["barcode"] = p["picked_barcode"]
    elif method == "Paste ingredients":
        if not (p.get("pasted") or "").strip():
            return None
        out["ingredients_text"] = p["pasted"].strip()
    elif method == "Label photo":
        if not (p.get("extracted") or "").strip():
            return None
        out["extracted_text"] = p["extracted"].strip()
    else:
        return None
    return out


def problems(product_type: str | None, concerns: list, products: list[dict]) -> list[str]:
    """What's still missing before Compare can be pressed. Empty list = ready."""
    out = []
    if not product_type:
        out.append("Choose a product type.")
    if not concerns:
        out.append("Choose at least one concern.")
    elif len(concerns) > MAX_CONCERNS:
        out.append(f"Choose at most {MAX_CONCERNS} concerns.")
    if len(products) < MIN_PRODUCTS:
        out.append(f"Add at least {MIN_PRODUCTS} products.")
    for i, p in enumerate(products, start=1):
        if product_payload(p, i) is None:
            hint = {"Barcode": "type its barcode", "Search by name": "search and pick a product",
                    "Paste ingredients": "paste its ingredient list",
                    "Label photo": "add a photo of the label"}.get(p.get("method"), "add it")
            out.append(f"Product {i}: {hint}.")
    return out


def unique_names(payloads: list[dict]) -> list[dict]:
    """Two products with the same name get "(2)", "(3)" added, so nobody has to rename anything."""
    seen: dict[str, int] = {}
    for pl in payloads:
        base = pl["display_name"]
        key = base.casefold()
        seen[key] = seen.get(key, 0) + 1
        if seen[key] > 1:
            suffix = f" ({seen[key]})"
            pl["display_name"] = base[:NAME_MAX - len(suffix)].strip() + suffix
    return payloads


def build_request(product_type: str, concerns: list, profile: dict, products: list[dict]) -> dict:
    return {"product_type": product_type, "concerns": list(concerns),
            "profile": {k: v for k, v in profile.items() if v is not None},
            "products": unique_names([product_payload(p, i) for i, p in enumerate(products, start=1)])}


SOURCE_LABELS = {
    "pasted_text": "ingredients you pasted",
    "label_photo": "ingredients read from your label photo",
    "open_beauty_facts": "Open Beauty Facts",
    "open_beauty_facts (cached)": "Open Beauty Facts (saved copy)",
    "seed (your own list)": "your own saved list",
}

REASON_LABELS = {"not_found": "Not in the product database", "no_ingredients_listed": "No ingredients listed",
                 "source_unavailable": "Product database not responding", "name_needs_selection": "Pick a product"}


# Little general care tips shown while a photo is read (no product claims, nothing medical).
TIPS = {
    "hair": [
        "Apply shampoo mainly to your scalp; rinsing carries it through the lengths.",
        "If your hair feels dry, spread conditioner along the whole length, not only the ends.",
        "Pat or squeeze hair dry with a towel instead of rubbing it.",
        "Lower heat settings on dryers and straighteners mean less heat on your hair.",
        "A wide-tooth comb glides through wet hair more gently than a fine brush.",
        "Tight ponytails and buns pull on hair; looser styles give it a break.",
    ],
    "skin": [
        "Patch-test a new product on a small area, like your inner arm, for a few days first.",
        "Lukewarm water is kinder to skin than hot water when you wash.",
        "Pat your skin dry with a towel instead of rubbing it.",
        "Apply moisturiser right after washing, while your skin is still slightly damp.",
        "Sunscreen is worth wearing every day, even when it's cloudy.",
        "Try one new product at a time, so you can tell how your skin takes to it.",
    ],
}


def tip_for(category: str | None, now: float) -> str:
    """A tip for this kind of product, changing every 6 seconds. No API call, no waiting."""
    tips = TIPS.get(category or "", TIPS["skin"] + TIPS["hair"])
    return tips[int(now // 6) % len(tips)]
