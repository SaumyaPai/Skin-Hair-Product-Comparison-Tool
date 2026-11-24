"""Measure 4: made-up claims. Counts, for our tool and for the plain chatbot:
  - ingredients (or ingredient groups) mentioned that none of the compared products contain
  - judgement or medical words (good, bad, best, better, cure, treat, heal, safe, scores...)
and adds the invented ingredients from photo reading (measure 1).
Run after consistency:  python -m scripts.eval.hallucination
Writes eval_results/hallucination.json and hallucination.csv.
"""
from scripts.eval.common import RESULTS, load_json, save_csv, save_json, stamp


def evaluate(raw: list[dict], checker) -> dict:
    rows = []
    for item in raw:
        texts = [p.get("ingredients_text", "") for p in item["products"]]
        names = [p["display_name"] for p in item["products"]]
        for who in ("tool", "chatbot"):
            for n, run in enumerate(item[who], start=1):
                c = checker.check(run["text"], texts, names)
                rows.append({"comparison": item["comparison"], "who": who, "run": n, "answered_by": run["source"],
                             "invented_ingredients": "; ".join(c["invented_ingredients"]),
                             "judgement_words": "; ".join(c["judgement_words"]), "count": c["count"]})

    def side(who):
        mine = [r for r in rows if r["who"] == who]
        return {"answers": len(mine), "answers_with_any": sum(1 for r in mine if r["count"]),
                "invented_ingredients": sum(len([x for x in r["invented_ingredients"].split("; ") if x]) for r in mine),
                "judgement_words": sum(len([x for x in r["judgement_words"].split("; ") if x]) for r in mine)}
    return {"rows": rows, "summary": {"tool": side("tool"), "chatbot": side("chatbot")}}


def main(argv=None) -> int:
    raw = load_json("consistency_raw.json")
    if raw is None:
        print("Run  python -m scripts.eval.consistency  first (this measure checks its answers).")
        return 1
    from app.data_loader import load_all
    from scripts.eval.scoring import ClaimChecker
    out = evaluate(raw, ClaimChecker(load_all()))
    ext = load_json("extraction.json")
    out["summary"]["photo_reading_invented"] = ext["invented_total"] if ext else None
    out["summary"]["when"] = stamp()
    save_csv("hallucination.csv", out["rows"])
    save_json("hallucination.json", out["summary"])
    t, c = out["summary"]["tool"], out["summary"]["chatbot"]
    print(f"Tool: {t['answers_with_any']} of {t['answers']} answers had a made-up claim or judgement word.")
    print(f"Chatbot: {c['answers_with_any']} of {c['answers']} answers did.")
    if t["answers_with_any"]:
        print("Anything found in the TOOL must be fixed (Phase 6 rule). See", RESULTS / "hallucination.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
