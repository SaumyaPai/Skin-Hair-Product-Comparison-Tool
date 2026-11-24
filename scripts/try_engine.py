"""Phase 3: try the engine yourself, no internet needed.

1. Edit data/try_example.json (product type, concerns, and 2 to 4 ingredient lists).
2. Run from the project folder:  python -m scripts.try_engine
"""
import json
import sys

from app import config
from app.data_loader import load_all
from app.services.normalizer import from_data
from app.services.ranking import rank
from app.services.rule_engine import RuleEngine

DISCLAIMER = ("This is general information about ingredients, not medical advice. Patch test new products "
              "and talk to a dermatologist or doctor about skin or scalp conditions.")


def main(path=config.DATA_DIR / "try_example.json") -> int:
    data = load_all()
    req = json.loads(path.read_text(encoding="utf-8"))
    ptype, concerns, profile = req["product_type"], req["concerns"], req.get("profile", {})
    application = next(t["application"] for t in data["product_types"] if t["product_type"] == ptype)
    norm, engine = from_data(data), RuleEngine(data)

    products = []
    for p in req["products"]:
        n = norm.normalize(p["ingredients_text"])
        products.append({"display_name": p["display_name"], "normalized": n,
                         "flags": engine.evaluate(ptype, n.ingredients, concerns, profile)})
    ranking = rank(products, application, bool(profile.get("sensitive")))

    print(f"Comparing {len(products)} x {ptype} ({application.replace('_', '-')}) for: {', '.join(concerns)}\n")
    print("Ranking:")
    for r in ranking:
        print(f"  {r['rank']}. {r['display_name']}{'  (tied)' if r['tied'] else ''}")
    for p in products:
        print(f"\n{p['display_name']}")
        if not p["flags"]:
            print("  No rules in our table matched this product for your choices.")
        for f in p["flags"]:
            mark = "+ may suit    " if f["flag_type"] == "may_suit" else "! may not suit"
            print(f"  {mark} {f['label']} ({', '.join(f['matched_ingredients'])})")
            print(f"                 why: {f['reason']}")
            print(f"                 source: {f['source']}")
        if p["normalized"].not_recognised:
            print(f"  Not recognised: {', '.join(p['normalized'].not_recognised)}")
    print(f"\n{DISCLAIMER}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
