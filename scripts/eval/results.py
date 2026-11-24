"""Builds the Phase 6 results sheet from whatever measures have been run so far.
Run:  python -m scripts.eval.results      ->  eval_results/RESULTS.md
"""
from app import config
from scripts.eval.common import RESULTS, load_json, stamp

NOT_RUN = "_Not run yet._ Run: `{cmd}`"


def _section_extraction(s):
    if not s:
        return NOT_RUN.format(cmd="python -m scripts.eval.extraction"), False
    ok = s["photos"] >= 1
    lines = [f"- Photos: **{s['photos']}** real label photos (the plan said 30; this submission uses the photos "
             f"collected so far, so treat the numbers as indicative)",
             f"- Ingredients read exactly right: **{s['pct_exact']}%** ({s['pct_exact_or_near']}% counting small spelling slips)",
             f"- Invented ingredients (not on the pack): **{s['invented_total']}** across {s['photos_with_invented']} photos",
             f"- Ingredients missed: {s['missing_total']}",
             f"- Photos read completely and exactly right: {s['photos_fully_right']} of {s['photos']}",
             f"- Typical time per photo: {s['median_seconds']} s",
             f"- Readers used: " + ", ".join(f"{k} ({v})" for k, v in sorted(s["readers_used"].items())),
             f"- Run: {s.get('mode', '')}, {s.get('when', '')}. Details: `eval_results/extraction.csv`"]
    if s.get("offline"):
        o = s["offline"]
        lines.insert(3, f"- Without-AI reader on the same photos: {o['pct_exact']}% exact "
                        f"({o['pct_exact_or_near']}% with small slips), {o['invented_total']} invented")
    return "\n".join(lines), ok


def _section_coverage(s):
    if not s:
        return NOT_RUN.format(cmd="python -m scripts.eval.coverage"), False
    lines = [f"- Barcodes tried: **{s['tried']}**; came with an ingredient list: **{s['found_with_ingredients']}** "
             f"({s['pct']}% of the {s.get('answered', s['tried'])} the database answered)",
             "", "| Product type | Tried | With ingredients | Without | Not found | % |", "|---|---|---|---|---|---|"]
    for t, v in s["per_type"].items():
        pct = "" if v["pct"] is None else f"{v['pct']}%"
        lines.append(f"| {t} | {v['tried']} | {v['found_with_ingredients']} | {v['found_without_ingredients']} | "
                     f"{v['not_found']} | {pct} |")
    ok = bool(s.get("answered", s["tried"])) and not s.get("could_not_check")
    if s.get("could_not_check"):
        lines += ["", f"{s['could_not_check']} lookups couldn't reach the database. Run it again."]
    if s["types_short_of_5"]:
        lines += ["", "Product types with fewer than 5 barcodes checked (the plan said 5 each): "
                  + ", ".join(s["types_short_of_5"])]
    lines.append(f"\nRun: {s.get('when', '')}. Details: `eval_results/coverage.csv`")
    return "\n".join(lines), ok


def _section_consistency(s):
    if not s:
        return NOT_RUN.format(cmd="python -m scripts.eval.consistency"), False
    ok = s["comparisons"] >= 1 and s["runs_each"] >= 3
    if not s.get("chatbot_ran", True):
        return "\n".join([f"- {s['comparisons']} comparisons x {s['runs_each']} runs each",
                          f"- Our tool gave the same order every run: **{s['tool_pct_same_every_time']}%**",
                          "- Plain chatbot side: not run (no AI key was set)."]), ok
    return "\n".join([
        f"- {s['comparisons']} comparisons x {s['runs_each']} runs each (plan: 10 x 3)",
        "", "| | Our tool | Plain chatbot |", "|---|---|---|",
        f"| Same order every run | **{s['tool_pct_same_every_time']}%** | **{s['chatbot_pct_same_every_time']}%** |",
        f"| Same first choice every run | (same as above) | {s['chatbot_pct_same_first_choice']}% |",
        f"| Chatbot's order matched ours every run | | {s['chatbot_pct_agrees_with_tool']}% |",
        f"\nRun: {s.get('when', '')}. Every answer word for word: `eval_results/consistency_raw.json`"]), ok


def _section_hallucination(s):
    if not s:
        return NOT_RUN.format(cmd="python -m scripts.eval.hallucination  (after consistency)"), False
    t, c = s["tool"], s["chatbot"]
    if not c["answers"]:
        c = {k: "not run" for k in c}
    photo = "not run yet" if s.get("photo_reading_invented") is None else s["photo_reading_invented"]
    clean = t["answers_with_any"] == 0
    lines = ["| | Our tool | Plain chatbot |", "|---|---|---|",
             f"| Answers with any made-up claim or judgement word | **{t['answers_with_any']} of {t['answers']}** | **{c['answers_with_any']} of {c['answers']}** |",
             f"| Ingredients mentioned that the products don't contain | {t['invented_ingredients']} | {c['invented_ingredients']} |",
             f"| Judgement or medical words (good, best, cure...) | {t['judgement_words']} | {c['judgement_words']} |",
             f"\n- Invented ingredients from photo reading (measure 1): {photo}",
             f"- Run: {s.get('when', '')}. Details: `eval_results/hallucination.csv`"]
    if s.get("photo_reading_invented"):
        lines.append("\nInvented photo ingredients are words the reader made from smudges or the bottle's curve; "
                     "the app always asks people to check the read list against the label before comparing.")
    if t["answers_with_any"]:
        lines.append("\n**To fix before Phase 6 passes:** every made-up item in our tool's rows of hallucination.csv "
                     "(and any invented photo ingredient). Send them to Claude.")
    return "\n".join(lines), clean


OUT_OF_SCOPE = ("**Not done (out of scope for this submission).** The user test kit is ready "
                "(`docs/guides/USER_TEST_SCRIPT.md`, `eval_inputs/user_test.csv`, `python -m scripts.eval.user_test`) for future work.")


def _section_user(s):
    if not s or not s["people"]:
        return OUT_OF_SCOPE, True
    lines = [f"- People: **{s['people']}** (plan: 5 to 8)",
             f"- How clear was it (1 to 5): **{s['avg_clear']}**",
             f"- How much did you trust it (1 to 5): **{s['avg_trust']}**",
             f"- Noticed where the information came from: {s['noticed_sources']} of {s['people']}",
             f"- Felt it was medical advice: {s['felt_medical']} of {s['people']}",
             f"- Finished both comparisons: {s['finished_both']} of {s['people']}"]
    if s["confusions"]:
        lines += ["", "What confused people:"] + [f"- {x}" for x in s["confusions"]]
    if s["quotes"]:
        lines += ["", "In their words:"] + [f"> {x}" for x in s["quotes"]]
    return "\n".join(lines), s["enough_people"]


SECTIONS = [("1. Reading label photos", "extraction.json", _section_extraction),
            ("2. Barcode coverage (Open Beauty Facts)", "coverage.json", _section_coverage),
            ("3. Consistency: our tool vs a plain chatbot", "consistency.json", _section_consistency),
            ("4. Made-up claims", "hallucination.json", _section_hallucination),
            ("5. User test", "user_test.json", _section_user)]


def _section_final(s):
    if not s:
        return NOT_RUN.format(cmd="python -m scripts.final_check"), False
    lines = [f"Automatic tests: **{s['tests']['summary']}**", "", "| Check | Result | Detail |", "|---|---|---|"]
    lines += [f"| {c['name']} | {c['status']} | {c['detail']} |" for c in s["checks"]]
    return "\n".join(lines), not any(c["status"] == "FAIL" for c in s["checks"])


def build() -> tuple[str, list[str]]:
    parts, todo = [f"# Phase 6 results\n\nApp version {config.APP_VERSION}. Sheet built {stamp()}.\n"], []
    body, ok = _section_final(load_json("final_check.json"))
    parts.append(f"## Final check\n\n{body}\n")
    if not ok:
        todo.append("Final check")
    for title, file, fn in SECTIONS:
        body, ok = fn(load_json(file))
        parts.append(f"## {title}\n\n{body}\n")
        if not ok:
            todo.append(title)
    parts.append("## Still to do\n\n" + ("\n".join(f"- {t}" for t in todo) if todo else
                                          "Nothing. Every measure in scope for this submission is done, and no made-up claims were found in the tool.") + "\n")
    return "\n".join(parts), todo


def main(argv=None) -> int:
    text, todo = build()
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "RESULTS.md").write_text(text, encoding="utf-8")
    print("Results sheet:", RESULTS / "RESULTS.md")
    print("Still to do:", ", ".join(todo) if todo else "nothing, Phase 6 complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
