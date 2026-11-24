"""Phase 1 check: look up your own products in Open Beauty Facts.

1. Put your barcodes in data/my_products.csv (replace each REPLACE_ME).
2. Run from the project folder:  python -m scripts.check_obf
3. Results are printed and saved to scripts/results/obf_check_results.csv
"""
import csv
import sys
import time
from pathlib import Path

from app.services.obf_client import get_product

ROOT = Path(__file__).resolve().parent.parent
INPUT = ROOT / "data" / "my_products.csv"
OUTPUT = ROOT / "scripts" / "results" / "obf_check_results.csv"
PAUSE_SECONDS = 1.0  # be polite to the free service


def read_products(path: Path) -> list[dict]:
    """Read the barcode list, skipping rows still set to REPLACE_ME or blank. No file yet = no barcodes."""
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return [r for r in rows if (r.get("barcode") or "").strip() not in ("", "REPLACE_ME")]


def summarize(results: list[dict]) -> dict:
    counts = {"found": 0, "no_ingredients": 0, "not_found": 0, "invalid_barcode": 0, "error": 0}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    total = len(results)
    counts["total"] = total
    # Decision point from ARCHITECTURE.md: fewer than about 4 in 10 with ingredients
    # means pasted text and photos will do most of the work.
    counts["low_coverage"] = total > 0 and counts["found"] / total < 0.4
    return counts


def run(products: list[dict], lookup=get_product, pause: float = PAUSE_SECONDS) -> list[dict]:
    results = []
    for i, p in enumerate(products):
        r = lookup(p["barcode"].strip())
        r["my_name"] = p.get("my_name", "")
        results.append(r)
        if pause and i < len(products) - 1:
            time.sleep(pause)
    return results


def save(results: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = ["my_name", "barcode", "status", "product_name", "brand", "ingredients_text", "message"]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(results)


def main() -> int:
    products = read_products(INPUT)
    if not products:
        print(f"NOT READY: add your barcodes to {INPUT} (replace each REPLACE_ME).")
        return 1
    if len(products) < 10:
        print(f"Note: {len(products)} barcodes found. The Phase 1 goal is 10.")
    results = run(products)
    print(f"{'My name':<28} {'Barcode':<15} {'Result':<16} Name in database")
    for r in results:
        print(f"{r['my_name'][:27]:<28} {r['barcode']:<15} {r['status']:<16} {r['product_name'][:40]}")
    s = summarize(results)
    save(results, OUTPUT)
    print()
    print(f"With ingredients: {s['found']} of {s['total']}  |  no ingredients: {s['no_ingredients']}  |  "
          f"not found: {s['not_found']}  |  bad barcode: {s['invalid_barcode']}  |  errors: {s['error']}")
    if s["low_coverage"]:
        print("FINDING: low coverage. Pasted text and label photos will carry more of the load.")
    print(f"Saved results to {OUTPUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
