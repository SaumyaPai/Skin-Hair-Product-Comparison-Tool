"""Phase 2: copies products from data/seed_products.csv into the local database.

Run from the project folder:  python -m scripts.seed_cache
Only rows with an ingredient list are saved. Nothing is guessed for the others.
"""
import sys

from app import db
from app.data_loader import load_all


def seed(conn, seed_rows: list[dict]) -> dict:
    saved, skipped = [], []
    for row in seed_rows:
        if row.get("ingredients_text"):
            db.save_product(conn, row["barcode"], row.get("product_name", ""), row.get("brand", ""),
                            row["ingredients_text"], source="seed")
            saved.append(row)
        else:
            skipped.append(row)
    return {"saved": saved, "skipped": skipped}


def main() -> int:
    rows = load_all()["seed_products"]
    conn = db.connect()
    result = seed(conn, rows)
    for r in result["saved"]:
        print(f"  saved    {r['barcode']}  {r['brand']} {r['product_name']}")
    for r in result["skipped"]:
        print(f"  skipped  {r['barcode']}  {r['brand']} {r['product_name']}  (no ingredients yet)")
    print(f"\nSaved {len(result['saved'])}, skipped {len(result['skipped'])}. "
          f"Products now in the database: {db.count_products(conn)}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
