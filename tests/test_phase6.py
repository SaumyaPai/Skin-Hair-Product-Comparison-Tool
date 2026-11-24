"""Phase 6 evaluation scripts, checked with fakes (no internet, no AI keys)."""
import json

import pytest

from app.data_loader import load_all
from app.services.normalizer import from_data
from scripts.eval import common, consistency, coverage, extraction, hallucination, results, setup, user_test
from scripts.eval.scoring import ClaimChecker, parse_order, score_reading, tool_order

DATA = load_all()
NORM = from_data(DATA)


@pytest.fixture
def folders(tmp_path, monkeypatch):
    for mod in (common, setup, extraction, coverage, consistency, hallucination, user_test, results):
        for name, sub in (("INPUTS", "eval_inputs"), ("RESULTS", "eval_results")):
            if hasattr(mod, name):
                monkeypatch.setattr(mod, name, tmp_path / sub)
    return tmp_path


# ---- yardsticks ----

def test_reading_score_counts_exact_near_missing_invented():
    s = score_reading("Aqua, Glycerin, Niacinamide, Panthenol", "Water, Glycerln, Niacinamide, Menthol", NORM)
    assert s["true_count"] == 4 and s["exact"] == 2          # aqua = water, niacinamide
    assert s["near"] == 1 and s["missing"] == 1 and s["invented"] == 1
    assert s["invented_items"] == ["menthol"] and s["pct_exact"] == 50.0


def test_perfect_and_empty_reads():
    assert score_reading("Aqua, Glycerin", "aqua, glycerin", NORM)["pct_exact"] == 100.0
    empty = score_reading("Aqua, Glycerin", "", NORM)
    assert empty["missing"] == 2 and empty["invented"] == 0


def test_claim_checker_finds_invented_ingredient_and_judgement_words():
    c = ClaimChecker(DATA)
    texts = ["Aqua, Niacinamide, Glycerin"]
    ok = c.check("Serum A has niacinamide, commonly used for pigmentation.", texts, ["Serum A"])
    assert ok["count"] == 0
    bad = c.check("Serum A is the best: its retinol will treat dark spots.", texts, ["Serum A"])
    assert "retinol" in bad["invented_ingredients"]
    assert {"best", "treat"} <= set(bad["judgement_words"])


def test_claim_checker_accepts_other_names_and_groups():
    c = ClaimChecker(DATA)
    assert c.check("It contains water and anti-dandruff ingredients.", ["Aqua, Zinc Pyrithione"])["count"] == 0
    assert c.check("Its vitamin C and silicones, plus AHAs.", ["Ascorbic Acid, Dimethicone, Glycolic Acid"])["count"] == 0
    assert c.check("The ceramides help.", ["Aqua, Ceramide NP"])["count"] == 0


def test_parse_order_and_tool_order():
    names = ["Serum A", "Serum B", "Serum C"]
    assert parse_order("blah\nORDER: Serum B > serum a > Serum C", names) == "Serum B > Serum A > Serum C"
    assert parse_order("**ORDER:** Serum A = Serum B > Serum C.", names) == "Serum A = Serum B > Serum C"
    assert parse_order("no order here", names) == ""
    ranking = [{"rank": 1, "display_name": "B"}, {"rank": 2, "display_name": "C"}, {"rank": 2, "display_name": "A"}]
    assert tool_order(ranking) == "B > A = C"


# ---- setup ----

def test_setup_creates_files_and_never_overwrites(folders):
    assert setup.main() == 0
    inputs = folders / "eval_inputs"
    for name in ("comparisons.json", "user_test.csv", "coverage.csv", "photos/HOW_TO.txt"):
        assert (inputs / name).exists()
    comps = json.loads((inputs / "comparisons.json").read_text())["comparisons"]
    assert len(comps) == 10
    rows = common.read_csv(inputs / "coverage.csv")
    for t in {r["product_type"] for r in rows}:
        assert sum(r["product_type"] == t for r in rows) >= 5
    (inputs / "user_test.csv").write_text("mine")
    setup.main()
    assert (inputs / "user_test.csv").read_text() == "mine"


def test_starter_comparisons_are_valid_requests():
    from app.models import CompareRequest
    comps = json.loads((common.TEMPLATES / "comparisons.json").read_text())["comparisons"]
    allowed = __import__("app.data_loader", fromlist=["dropdown_concerns"]).dropdown_concerns(DATA)
    for c in comps:
        CompareRequest(**{k: c[k] for k in ("product_type", "concerns", "products", "profile")})
        assert set(c["concerns"]) <= set(allowed[c["product_type"]])


# ---- measures ----

def test_extraction_with_fake_reader(folders):
    photos = folders / "photos"
    photos.mkdir()
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (60, 40), "white").save(buf, "JPEG")
    (photos / "a.jpg").write_bytes(buf.getvalue())
    (photos / "a.txt").write_text("Aqua, Glycerin, Niacinamide")
    (photos / "b.jpg").write_bytes(buf.getvalue())             # no truth file: skipped
    pairs, no_truth = extraction.find_pairs(photos)
    assert len(pairs) == 1 and no_truth == ["b.jpg"]
    fake = [("fake", lambda img, mime: {"readable": True, "ingredients_text": "Aqua, Glycerin, Parfum",
                                        "confidence_note": ""})]
    out = extraction.evaluate(pairs, fake, NORM)
    row = out["rows"][0]
    assert row["reader"] == "fake" and row["exact"] == 2 and row["invented"] == 1 and row["missing"] == 1
    assert out["summary"]["invented_total"] == 1 and out["summary"]["photos"] == 1


def test_coverage_counts_per_type():
    answers = {"1": "found", "2": "no_ingredients", "3": "not_found", "4": "error"}
    rows = [{"product_type": "toner", "barcode": b} for b in "1234"] + [{"product_type": "toner", "barcode": ""}]
    out = coverage.evaluate(rows, lambda bc: {"status": answers[bc]}, ["toner", "shampoo"])
    t = out["summary"]["per_type"]["toner"]
    assert (t["tried"], t["found_with_ingredients"], t["found_without_ingredients"], t["not_found"]) == (4, 1, 1, 1)
    assert out["summary"]["could_not_check"] == 1           # site unreachable: not counted as missing
    assert set(out["summary"]["types_short_of_5"]) == {"toner", "shampoo"}
    assert out["summary"]["pct"] == pytest.approx(33.3)


def test_consistency_compares_tool_and_chatbot():
    comp = {"label": "x", "product_type": "serum", "concerns": ["pigmentation"],
            "products": [{"display_name": "A", "ingredients_text": "Aqua"}, {"display_name": "B", "ingredients_text": "Aqua"}]}
    answers = iter(["A > B", "B > A", "A > B"])
    out = consistency.evaluate([comp], lambda c: {"order": "A > B", "text": "t", "source": "template"},
                               lambda c: {"order": next(answers), "text": "c", "source": "fake"}, runs=3)
    s = out["summary"]
    assert s["tool_pct_same_every_time"] == 100.0 and s["chatbot_pct_same_every_time"] == 0.0
    assert s["chatbot_pct_agrees_with_tool"] == 0.0 and len(out["raw"][0]["chatbot"]) == 3


def test_chatbot_prompt_has_lists_and_order_line():
    comps = json.loads((common.TEMPLATES / "comparisons.json").read_text())["comparisons"]
    p = consistency.chatbot_prompt(comps[1], DATA)
    assert "Serum A: Aqua, Niacinamide" in p and "ORDER:" in p and "sensitive: True" in p


def test_tool_run_is_the_same_every_time():
    from app.deps import build_services
    services = build_services(summarize=None, extract=[], obf_lookup=lambda b: {"status": "not_found"})
    comp = json.loads((common.TEMPLATES / "comparisons.json").read_text())["comparisons"][1]
    runs = [consistency.run_tool(comp, services) for _ in range(3)]
    assert len({r["order"] for r in runs}) == 1 and runs[0]["order"].startswith("Serum A")
    checker = ClaimChecker(DATA)
    texts = [p["ingredients_text"] for p in comp["products"]]
    assert checker.check(runs[0]["text"], texts, [p["display_name"] for p in comp["products"]])["count"] == 0


def test_hallucination_counts_each_side():
    raw = [{"comparison": "x", "products": [{"display_name": "A", "ingredients_text": "Aqua, Glycerin"}],
            "tool": [{"text": "A has glycerin, commonly used for dryness.", "source": "template"}],
            "chatbot": [{"text": "A is good and its ceramides heal skin.", "source": "fake"}]}]
    s = hallucination.evaluate(raw, ClaimChecker(DATA))["summary"]
    assert s["tool"]["answers_with_any"] == 0
    assert s["chatbot"]["answers_with_any"] == 1 and s["chatbot"]["judgement_words"] >= 2
    assert s["chatbot"]["invented_ingredients"] == 1              # ceramides aren't in either product


def test_user_test_summary():
    rows = [{"participant": "P1", "q1_clear_1to5": "4", "q2_trust_1to5": "5", "q3_noticed_sources_yes_no": "yes",
             "q4_felt_like_medical_advice_yes_no": "no", "q5_what_confused_you": "the tie", "quote": "handy",
             "comparison_1_done": "y", "comparison_2_done": "y"},
            {"participant": "P2", "q1_clear_1to5": "2", "q2_trust_1to5": "x", "q3_noticed_sources_yes_no": "no"},
            {"participant": "P3"}]
    s = user_test.evaluate(rows)
    assert s["people"] == 2 and s["avg_clear"] == 3.0 and s["avg_trust"] == 5.0
    assert s["noticed_sources"] == 1 and s["finished_both"] == 1 and not s["enough_people"]
    assert s["confusions"] == ["the tie"]


def test_results_sheet_marks_missing_measures(folders):
    text, todo = results.build()
    assert "Not run yet" in text and len(todo) == 5          # final check + measures 1 to 4
    assert "out of scope for this submission" in text
    common.save_json("user_test.json", user_test.evaluate(
        [{"participant": f"P{i}", "q1_clear_1to5": "4", "q2_trust_1to5": "4"} for i in range(5)]))
    common.save_json("hallucination.json", {"tool": {"answers": 30, "answers_with_any": 1, "invented_ingredients": 1,
                                                     "judgement_words": 0},
                                            "chatbot": {"answers": 30, "answers_with_any": 20, "invented_ingredients": 9,
                                                        "judgement_words": 25}, "photo_reading_invented": 0})
    text, todo = results.build()
    assert "5. User test" not in todo and "4. Made-up claims" in todo
    assert "To fix before Phase 6 passes" in text and results.main() == 0
    assert (folders / "eval_results" / "RESULTS.md").exists()


def test_scripts_say_what_to_do_when_inputs_are_missing(folders, capsys):
    assert extraction.main([]) == 1 and coverage.main([]) == 1 and consistency.main([]) == 1
    assert hallucination.main([]) == 1 and user_test.main([]) == 1
    assert "scripts.eval.setup" in capsys.readouterr().out


def test_a_name_split_in_two_is_a_slip_not_an_invention():
    s = score_reading("Aqua, Cetearyl Alcohol, Glycerin", "Aqua, Cetearyl, Glycerin", NORM)
    assert s["invented"] == 0 and s["near"] == 1 and s["missing"] == 0


def test_final_check_quick_prints_pass(folders, monkeypatch, capsys):
    from scripts import final_check
    from app.services import llm_client, obf_client
    monkeypatch.setattr(final_check, "checks", [])
    monkeypatch.setattr(final_check, "run_tests", lambda: {"summary": "10 passed", "ok": True, "failed": 0, "errors": 0})
    monkeypatch.setattr(obf_client, "get_product", lambda bc: {"status": "found"})
    monkeypatch.setattr(llm_client, "summary_providers", lambda: [("fake", lambda p: "OK")])
    assert final_check.main(["--quick"]) == 0
    out = capsys.readouterr().out
    assert "RESULT: PASS" in out
    saved = json.loads((folders / "eval_results" / "final_check.json").read_text())
    assert any(c["name"] == "Open Beauty Facts reachable" and c["status"] == "PASS" for c in saved["checks"])
    assert "Final check" in (folders / "eval_results" / "RESULTS.md").read_text()


def test_final_check_reports_fail(folders, monkeypatch, capsys):
    from scripts import final_check
    from app.services import llm_client, obf_client
    monkeypatch.setattr(final_check, "checks", [])
    monkeypatch.setattr(final_check, "run_tests", lambda: final_check.record("FAIL", "Automatic tests", "1 failed")
                        or {"summary": "1 failed", "ok": False, "failed": 1, "errors": 0})
    monkeypatch.setattr(obf_client, "get_product", lambda bc: {"status": "error", "message": "down"})
    monkeypatch.setattr(llm_client, "summary_providers", lambda: [])
    assert final_check.main(["--quick"]) == 1
    assert "RESULT: FAIL" in capsys.readouterr().out


def test_pore_rules_are_sourced_and_cautious():
    rules = {r["rule_id"]: r for r in DATA["rules"]}
    for rid in ("R043", "R044"):
        r = rules[rid]
        assert r["flag_type"] == "may_not_suit" and r["severity"] == "low"
        assert r["relevant_profiles"] == "concern:acne-prone" and r["source"].startswith("https://")
        assert "vary" in r["rationale"]
