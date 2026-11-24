"""Measure 5: the user test. Fill eval_inputs/user_test.csv while 5 to 8 people try the tool
(follow docs/guides/USER_TEST_SCRIPT.md), then run:  python -m scripts.eval.user_test
Writes eval_results/user_test.json.
"""
from scripts.eval.common import INPUTS, need, read_csv, save_json, stamp


def _num(v):
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    return n if 1 <= n <= 5 else None


def _yes(v):
    return (v or "").strip().lower() in ("y", "yes", "true", "1")


def evaluate(rows: list[dict]) -> dict:
    done = [r for r in rows if any(r.get(k) for k in ("q1_clear_1to5", "q2_trust_1to5", "q3_noticed_sources_yes_no"))]
    clear = [n for n in (_num(r.get("q1_clear_1to5")) for r in done) if n]
    trust = [n for n in (_num(r.get("q2_trust_1to5")) for r in done) if n]
    return {"people": len(done), "enough_people": len(done) >= 5,
            "avg_clear": round(sum(clear) / len(clear), 1) if clear else None,
            "avg_trust": round(sum(trust) / len(trust), 1) if trust else None,
            "noticed_sources": sum(_yes(r.get("q3_noticed_sources_yes_no")) for r in done),
            "felt_medical": sum(_yes(r.get("q4_felt_like_medical_advice_yes_no")) for r in done),
            "finished_both": sum(_yes(r.get("comparison_1_done")) and _yes(r.get("comparison_2_done")) for r in done),
            "confusions": [r["q5_what_confused_you"] for r in done if r.get("q5_what_confused_you")],
            "quotes": [r["quote"] for r in done if r.get("quote")]}


def main(argv=None) -> int:
    path = INPUTS / "user_test.csv"
    if not need(path, "fill in the answers"):
        return 1
    s = evaluate(read_csv(path))
    s["when"] = stamp()
    save_json("user_test.json", s)
    print(f"{s['people']} people: clarity {s['avg_clear']}/5, trust {s['avg_trust']}/5, "
          f"{s['noticed_sources']} noticed the sources, {s['felt_medical']} felt it was medical advice.")
    if s["people"] < 5:
        print("The plan needs at least 5 people.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
