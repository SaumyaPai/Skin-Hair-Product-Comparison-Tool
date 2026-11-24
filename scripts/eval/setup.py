"""Creates your evaluation folders and starter files (never overwrites anything you've filled in).

Run:  python -m scripts.eval.setup
"""
import csv
import shutil

from scripts.eval.common import INPUTS, RESULTS, ROOT, TEMPLATES

PER_TYPE = 5


def coverage_rows() -> list[dict]:
    """Starts the barcode list with the products already in data/seed_products.csv, then blank rows so
    every product type has room for 5 barcodes."""
    from app.data_loader import load_all
    types = [t["product_type"] for t in load_all()["product_types"]]
    rows, seed = [], ROOT / "data" / "seed_products.csv"
    if seed.exists():
        with seed.open(newline="", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                bc = (r.get("barcode") or "").strip()
                if bc.isdigit() and r.get("product_type") in types:
                    rows.append({"product_type": r["product_type"], "barcode": bc,
                                 "name": " ".join(x for x in (r.get("brand", ""), r.get("product_name", "")) if x)})
    for t in types:
        for _ in range(PER_TYPE - sum(r["product_type"] == t for r in rows)):
            rows.append({"product_type": t, "barcode": "", "name": ""})
    rows.sort(key=lambda r: types.index(r["product_type"]))
    return rows


def main() -> int:
    INPUTS.mkdir(exist_ok=True)
    (INPUTS / "photos").mkdir(exist_ok=True)
    RESULTS.mkdir(exist_ok=True)
    made = []
    for name in ("comparisons.json", "user_test.csv", "photos/HOW_TO.txt"):
        target = INPUTS / name
        if not target.exists():
            shutil.copy(TEMPLATES / name, target)
            made.append(name)
    cov = INPUTS / "coverage.csv"
    if not cov.exists():
        with cov.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["product_type", "barcode", "name"])
            w.writeheader()
            w.writerows(coverage_rows())
        made.append("coverage.csv")
    print("Your evaluation folder:", INPUTS)
    print("Created:", ", ".join(made) if made else "nothing new (your files are kept as they are)")
    print("Results will be saved in:", RESULTS)
    print("Next: read docs/guides/PHASE6_GUIDE.md for what to fill in, then run each measure.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
