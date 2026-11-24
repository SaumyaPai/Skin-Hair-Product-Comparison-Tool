"""Measure 2: how often a barcode finds a product WITH its ingredient list in Open Beauty Facts.

Fill eval_inputs/coverage.csv with at least 5 real barcodes per product type (some are filled in for you).
Run:  python -m scripts.eval.coverage
Writes eval_results/coverage.csv and coverage.json.
"""
import argparse

from scripts.eval.common import INPUTS, need, pause, read_csv, save_csv, save_json, stamp

PER_TYPE = 5


def evaluate(rows: list[dict], lookup, types: list[str], gap: float = 0.0) -> dict:
    out, done = [], 0
    for r in rows:
        bc = r.get("barcode", "")
        if not bc:
            continue
        if done:
            pause(gap)
        done += 1
        try:
            status = lookup(bc).get("status", "error")
        except Exception as exc:
            status = f"error: {type(exc).__name__}"
        out.append({"product_type": r.get("product_type", ""), "barcode": bc, "name": r.get("name", ""),
                    "result": status})
        print(f"  {r.get('product_type', '')} {bc}: {status}")
    per_type = {}
    for t in types:
        mine = [o for o in out if o["product_type"] == t]
        found = sum(o["result"] == "found" for o in mine)
        answered = [o for o in mine if o["result"] in ("found", "no_ingredients", "not_found")]
        per_type[t] = {"tried": len(mine), "found_with_ingredients": found,
                       "found_without_ingredients": sum(o["result"] == "no_ingredients" for o in mine),
                       "not_found": sum(o["result"] == "not_found" for o in mine),
                       "other": sum(o["result"] not in ("found", "no_ingredients", "not_found") for o in mine),
                       "pct": round(100 * found / len(answered), 1) if answered else None,
                       "enough_barcodes": len(mine) >= PER_TYPE}
    # A lookup that couldn't reach the site says nothing about coverage, so it isn't counted in the %
    answered = [o for o in out if o["result"] in ("found", "no_ingredients", "not_found")]
    found = sum(o["result"] == "found" for o in out)
    return {"rows": out, "summary": {"tried": len(out), "answered": len(answered), "found_with_ingredients": found,
                                     "could_not_check": len(out) - len(answered),
                                     "pct": round(100 * found / len(answered), 1) if answered else 0.0,
                                     "types_short_of_5": [t for t, v in per_type.items() if not v["enough_barcodes"]],
                                     "per_type": per_type}}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--gap", type=float, default=1.0, help="seconds between lookups (be polite to the free database)")
    args = ap.parse_args(argv)
    path = INPUTS / "coverage.csv"
    if not need(path, "add barcodes"):
        return 1
    from app.data_loader import load_all
    from app.services import obf_client
    types = [t["product_type"] for t in load_all()["product_types"]]
    out = evaluate(read_csv(path), obf_client.get_product, types, gap=args.gap)
    out["summary"]["when"] = stamp()
    save_csv("coverage.csv", out["rows"])
    save_json("coverage.json", out["summary"])
    s = out["summary"]
    print(f"\nDone: {s['found_with_ingredients']} of {s['tried']} barcodes ({s['pct']}%) came with an ingredient list"
          f" (out of {s['answered']} the database answered).")
    if s["could_not_check"]:
        print(f"{s['could_not_check']} lookups couldn't reach Open Beauty Facts (not counted). Check your internet and "
              "run this again.")
    if s["types_short_of_5"]:
        print("Fewer than 5 barcodes for:", ", ".join(s["types_short_of_5"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
