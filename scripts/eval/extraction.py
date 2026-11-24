"""Measure 1: how accurately label photos are read.

Put photos in eval_inputs/photos/ with the true list in a .txt file of the same name (see HOW_TO.txt).
Run:  python -m scripts.eval.extraction            (uses the same readers as the app, in the same order)
      python -m scripts.eval.extraction --offline  (only the without-AI reader)
Writes eval_results/extraction.csv and extraction.json.
"""
import argparse
import time

from scripts.eval.common import INPUTS, need, pause, save_csv, save_json, stamp

PHOTO_TYPES = (".jpg", ".jpeg", ".png")


def find_pairs(folder) -> tuple[list, list]:
    pairs, no_truth = [], []
    for img in sorted(p for p in folder.iterdir() if p.suffix.lower() in PHOTO_TYPES):
        truth = img.with_suffix(".txt")
        (pairs if truth.exists() else no_truth).append((img, truth) if truth.exists() else img.name)
    return pairs, no_truth


def evaluate(pairs, chain, normalizer, gap: float = 0.0, clock=time.monotonic) -> dict:
    from app.routes.products import _prepare_image, read_photo
    from scripts.eval.scoring import score_reading
    rows = []
    for i, (img, truth_file) in enumerate(pairs):
        if i:
            pause(gap)
        t0 = clock()
        try:
            result, reader, _ = read_photo(list(chain), _prepare_image(img.read_bytes()))
        except Exception as exc:                     # one bad photo shouldn't stop the whole run
            result, reader = None, f"error: {type(exc).__name__}"
        seconds = round(clock() - t0, 1)
        text = (result or {}).get("ingredients_text", "") if (result or {}).get("readable") else ""
        s = score_reading(truth_file.read_text(encoding="utf-8-sig"), text, normalizer)
        rows.append({"photo": img.name, "reader": reader or "nobody", "seconds": seconds,
                     "may_be_incomplete": bool((result or {}).get("possibly_incomplete")),
                     **{k: s[k] for k in ("true_count", "read_count", "exact", "near", "missing", "invented",
                                          "pct_exact", "pct_exact_or_near")},
                     "near_misses": "; ".join(s["near_pairs"]), "missing_items": "; ".join(s["missing_items"]),
                     "invented_items": "; ".join(s["invented_items"])})
        print(f"  {img.name}: {s['pct_exact']}% exact, {s['invented']} invented, {seconds}s ({reader})")
    true_total = sum(r["true_count"] for r in rows)
    exact = sum(r["exact"] for r in rows)
    near = sum(r["near"] for r in rows)
    return {"rows": rows, "summary": {
        "photos": len(rows),
        "pct_exact": round(100 * exact / true_total, 1) if true_total else 0.0,
        "pct_exact_or_near": round(100 * (exact + near) / true_total, 1) if true_total else 0.0,
        "invented_total": sum(r["invented"] for r in rows),
        "photos_with_invented": sum(1 for r in rows if r["invented"]),
        "missing_total": sum(r["missing"] for r in rows),
        "photos_fully_right": sum(1 for r in rows if r["true_count"] and r["exact"] == r["true_count"]
                                  and not r["invented"]),
        "median_seconds": sorted(r["seconds"] for r in rows)[len(rows) // 2] if rows else 0,
        "readers_used": {n: sum(1 for r in rows if r["reader"] == n) for n in {r["reader"] for r in rows}},
    }}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--offline", action="store_true", help="only the without-AI reader")
    ap.add_argument("--gap", type=float, default=3.0, help="seconds to wait between photos (free AI limits)")
    args = ap.parse_args(argv)
    folder = INPUTS / "photos"
    if not need(folder, "add photos"):
        return 1
    pairs, no_truth = find_pairs(folder)
    for name in no_truth:
        print(f"  Skipping {name}: no matching .txt file with the true list")
    if not pairs:
        print("No photo + .txt pairs found in", folder)
        return 1
    from app.data_loader import load_all
    from app.services import llm_client, ocr
    from app.services.normalizer import from_data
    chain = [("offline_ocr", ocr.read_ingredients)] if args.offline else llm_client.extract_providers()
    print(f"Reading {len(pairs)} photos with: {', '.join(n for n, _ in chain)}")
    out = evaluate(pairs, chain, from_data(load_all()), gap=args.gap)
    out["summary"].update(when=stamp(), mode="offline only" if args.offline else "same readers as the app")
    save_csv("extraction.csv", out["rows"])
    save_json("extraction.json", out["summary"])
    s = out["summary"]
    print(f"\nDone: {s['pct_exact']}% of ingredients exactly right ({s['pct_exact_or_near']}% counting small slips), "
          f"{s['invented_total']} invented. Details: eval_results/extraction.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
