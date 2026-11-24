"""The only file that talks to Open Beauty Facts. It never guesses ingredients."""
import re

import httpx

from app import config

FIELDS = "code,product_name,brands,ingredients_text,ingredients_text_en,categories_tags"


def is_valid_barcode(barcode: str) -> bool:
    """A barcode is 8 to 14 digits, nothing else."""
    return bool(re.fullmatch(r"\d{8,14}", barcode or ""))


def get_product(barcode: str, client: httpx.Client | None = None) -> dict:
    """Look up one barcode. Always returns a dict with a `status`:

    found            product exists and has an ingredient list
    no_ingredients   product exists but nobody has entered its ingredients
    not_found        Open Beauty Facts doesn't know this barcode
    invalid_barcode  the barcode isn't 8 to 14 digits
    error            the site couldn't be reached or answered strangely
    """
    result = {"barcode": barcode, "status": "error", "product_name": "", "brand": "",
              "ingredients_text": "", "category_tags": [], "message": ""}
    if not is_valid_barcode(barcode):
        result.update(status="invalid_barcode", message="Barcodes are 8 to 14 digits.")
        return result

    own_client = client is None
    if own_client:
        client = httpx.Client(timeout=config.OBF_TIMEOUT_SECONDS,
                              headers={"User-Agent": config.OBF_USER_AGENT})
    try:
        resp = client.get(f"{config.OBF_BASE_URL}/api/v2/product/{barcode}.json",
                          params={"fields": FIELDS})
        if resp.status_code == 404:
            result.update(status="not_found", message="Not in Open Beauty Facts.")
            return result
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        result.update(status="error", message=f"Could not reach Open Beauty Facts ({type(exc).__name__}).")
        return result
    finally:
        if own_client:
            client.close()

    if data.get("status") != 1 or not data.get("product"):
        result.update(status="not_found", message="Not in Open Beauty Facts.")
        return result

    product = data["product"]
    ingredients = (product.get("ingredients_text_en") or product.get("ingredients_text") or "").strip()
    result.update(product_name=product.get("product_name", "") or "",
                  brand=product.get("brands", "") or "",
                  ingredients_text=ingredients,
                  category_tags=list(product.get("categories_tags") or []))
    if ingredients:
        result.update(status="found", message="Has an ingredient list.")
    else:
        result.update(status="no_ingredients", message="Product found, but no ingredients listed.")
    return result


def _new_client() -> httpx.Client:
    return httpx.Client(timeout=config.OBF_TIMEOUT_SECONDS, headers={"User-Agent": config.OBF_USER_AGENT})


def search_products(query: str, client: httpx.Client | None = None, limit: int = 10) -> dict:
    """Search by product name. Returns {"status": "ok"|"error", "results": [...]}.
    The shopper picks from the results; the app never picks one by itself."""
    own_client = client is None
    client = client or _new_client()
    try:
        resp = client.get(f"{config.OBF_BASE_URL}/cgi/search.pl",
                          params={"search_terms": query, "search_simple": 1, "action": "process",
                                  "json": 1, "page_size": limit, "fields": FIELDS})
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        return {"status": "error", "results": [], "message": f"Could not reach Open Beauty Facts ({type(exc).__name__})."}
    finally:
        if own_client:
            client.close()
    results = []
    for p in (data.get("products") or [])[:limit]:
        code = str(p.get("code") or "")
        if not is_valid_barcode(code):
            continue
        ingredients = (p.get("ingredients_text_en") or p.get("ingredients_text") or "").strip()
        results.append({"barcode": code, "product_name": p.get("product_name", "") or "",
                        "brand": p.get("brands", "") or "", "ingredients_text": ingredients,
                        "category_tags": list(p.get("categories_tags") or [])})
    return {"status": "ok", "results": results, "message": ""}
