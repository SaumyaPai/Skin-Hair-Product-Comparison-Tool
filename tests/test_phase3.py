"""Phase 3 tests: normalizer, rule engine and ranking. No internet, no Gemini key needed.

Run from the project folder:  python -m pytest -v
"""
import copy

import pytest

from app import config
from app.data_loader import load_all
from app.services import llm_client
from app.services.normalizer import clean, from_data, split_ingredients
from app.services.ranking import product_points, rank
from app.services.rule_engine import RuleEngine, user_tags


@pytest.fixture(scope="module")
def data():
    return load_all()


@pytest.fixture(scope="module")
def norm(data):
    return from_data(data)


@pytest.fixture(scope="module")
def engine(data):
    return RuleEngine(data)


def flags_for(engine, norm, ptype, text, concerns=(), **profile):
    return engine.evaluate(ptype, norm.normalize(text).ingredients, list(concerns), profile)


# =====================  1. NORMALIZER  =====================

def test_example_from_the_architecture_doc(norm):
    r = norm.normalize("Aqua, PARFUM (Fragrance)., Vitamin B3")
    assert r.ingredients == ["water", "fragrance", "niacinamide"]


def test_unknown_ingredient_is_listed_not_hidden(norm):
    r = norm.normalize("Aqua, Phenoxyethanol, Glycerin")
    assert r.not_recognised == ["phenoxyethanol"]
    assert "phenoxyethanol" in r.ingredients          # still kept, in order


def test_label_prefix_newlines_semicolons(norm):
    r = norm.normalize("INGREDIENTS: Aqua;\nGlycerin\r\nNiacinamide")
    assert r.ingredients == ["water", "glycerin", "niacinamide"]


def test_commas_inside_brackets_do_not_split(norm):
    assert split_ingredients("Parfum (Fragrance, Perfume), Aqua") == ["Parfum (Fragrance, Perfume)", " Aqua"]
    assert norm.normalize("Parfum (Fragrance, Perfume), Aqua").ingredients == ["fragrance", "water"]


def test_percentages_and_asterisks_removed_but_kept_as_notes(norm):
    r = norm.normalize("Niacinamide (5%), Salicylic Acid 2%, Aloe Barbadensis Leaf Juice*")
    assert r.ingredients[:2] == ["niacinamide", "salicylic acid"]
    assert r.percentages == {"niacinamide": "5%", "salicylic acid": "2%"}
    assert "aloe barbadensis leaf juice" in r.ingredients


def test_slash_and_bracket_name_forms(norm):
    assert norm.normalize("Aqua/Water/Eau").ingredients == ["water"]
    assert norm.normalize("Water (Aqua)").ingredients == ["water"]
    assert norm.normalize("Butyrospermum Parkii (Shea) Butter").ingredients == ["shea butter"]


def test_may_contain_colour_block(norm):
    r = norm.normalize("Aqua, [+/- CI 77491, CI 77492], May contain: CI 77891")
    assert r.ingredients == ["water", "iron oxides", "titanium dioxide"]


def test_fatty_alcohols_are_not_drying_alcohol(norm):
    r = norm.normalize("Cetearyl Alcohol, Cetyl Alcohol, Stearyl Alcohol")
    assert "alcohol" not in r.ingredients


def test_denatured_alcohol_is_alcohol(norm):
    assert norm.normalize("Alcohol Denat.").ingredients == ["alcohol"]


def test_duplicates_collapse(norm):
    assert norm.normalize("Aqua, Water, Eau").ingredients == ["water"]


@pytest.mark.parametrize("text", ["", "   ", "Ingredients:", ",,,"])
def test_empty_text_gives_empty_result(norm, text):
    r = norm.normalize(text)
    assert r.ingredients == [] and r.not_recognised == []


def test_clean_tidies_spacing_and_dashes():
    assert clean("  Alpha–Isomethyl   Ionone. ")[0] == "alpha-isomethyl ionone"


# =====================  2. RULE ENGINE  =====================

FRAGRANT_SERUM = "Aqua, Glycerin, Parfum, Phenoxyethanol"


def test_fragrance_flagged_for_sensitive_user(engine, norm):
    ids = [f["rule_id"] for f in flags_for(engine, norm, "serum", FRAGRANT_SERUM, sensitive=True)]
    assert "R029" in ids


def test_fragrance_not_flagged_for_user_who_did_not_ask(engine, norm):
    assert flags_for(engine, norm, "serum", FRAGRANT_SERUM, concerns=["acne-prone"]) == []


def test_avoid_fragrance_preference_works_on_hair_too(engine, norm):
    ids = [f["rule_id"] for f in flags_for(engine, norm, "shampoo", "Aqua, Parfum", avoid_fragrance=True)]
    assert ids == ["R030"]


def test_flag_carries_reason_source_and_matched_ingredients(engine, norm):
    f = flags_for(engine, norm, "serum", "Aqua, Linalool, Parfum", sensitive=True)[0]
    assert f["flag_type"] == "may_not_suit"
    assert f["matched_ingredients"] == ["linalool", "fragrance"]
    assert f["reason"] and f["source"].startswith("https://")


def test_rule_only_fires_for_its_product_types(engine, norm):
    # salicylic acid is an acne rule for face products; on a shampoo it's a dandruff ingredient
    assert flags_for(engine, norm, "shampoo", "Aqua, Salicylic Acid", concerns=["acne-prone"]) == []
    ids = [f["rule_id"] for f in flags_for(engine, norm, "shampoo", "Aqua, Salicylic Acid", concerns=["dandruff"])]
    assert ids == ["R031"]


def test_rule_only_fires_for_matching_concern(engine, norm):
    assert flags_for(engine, norm, "serum", "Niacinamide", concerns=["dryness"]) == []
    assert [f["rule_id"] for f in flags_for(engine, norm, "serum", "Niacinamide",
                                             concerns=["pigmentation"])] == ["R010"]


def test_may_suit_label_uses_commonly_used_for_wording(engine, norm):
    f = flags_for(engine, norm, "serum", "Niacinamide", concerns=["pigmentation"])[0]
    assert f["label"] == "Contains ingredients commonly used for uneven pigmentation"
    for word in config.BANNED_WORDS:
        assert word not in f["label"].lower().split()


def test_cautions_listed_first(engine, norm):
    fl = flags_for(engine, norm, "moisturizer", "Glycerin, Alcohol Denat.", concerns=["dryness"])
    assert [f["flag_type"] for f in fl] == ["may_not_suit", "may_suit"]
    assert fl[0]["label"] == "May not suit dry skin"


def test_hair_fall_and_dark_circles_rules_fire(engine, norm):
    hf = flags_for(engine, norm, "hair_oil_serum", "Rosmarinus Officinalis Leaf Oil, Caffeine", concerns=["hair-fall"])
    assert {f["rule_id"] for f in hf} == {"R040", "R041"}
    dc = flags_for(engine, norm, "serum", "Caffeine, Phytonadione", concerns=["dark-circles"])
    assert {f["rule_id"] for f in dc} == {"R035", "R036"}


def test_user_tags():
    assert user_tags(["dryness"], {"sensitive": True}) == {"concern:dryness", "profile:sensitive"}


# =====================  3. RANKING  =====================

def F(flag_type, severity, family="x", sensitivity_rule=False):
    return {"flag_type": flag_type, "severity": severity, "ingredient_family": family,
            "sensitivity_rule": sensitivity_rule}


def test_identical_flags_are_tied_with_same_rank():
    flags = [F("may_suit", "medium")]
    r = rank([{"display_name": "B", "flags": flags}, {"display_name": "A", "flags": flags}], "leave_on", False)
    assert [(x["rank"], x["display_name"], x["tied"]) for x in r] == [(1, "A", True), (1, "B", True)]


def test_tie_ranks_skip_like_1_1_3():
    good = [F("may_suit", "high")]
    r = rank([{"display_name": n, "flags": good} for n in ("A", "B")]
             + [{"display_name": "C", "flags": []}], "leave_on", False)
    assert [x["rank"] for x in r] == [1, 1, 3]
    assert r[2]["tied"] is False


def test_rinse_off_counts_half_of_leave_on():
    flags = [F("may_not_suit", "medium")]
    assert product_points(flags, "rinse_off", False) == product_points(flags, "leave_on", False) / 2


def test_sensitivity_multiplier_only_on_cautions():
    caution = [F("may_not_suit", "medium", sensitivity_rule=True)]
    benefit = [F("may_suit", "medium", sensitivity_rule=True)]
    assert product_points(caution, "leave_on", True) == -3.0     # 2 x 1.5
    assert product_points(caution, "leave_on", False) == -2.0
    assert product_points(benefit, "leave_on", True) == product_points(benefit, "leave_on", False) == 2.0


def test_multiplier_needs_a_sensitivity_rule():
    caution = [F("may_not_suit", "medium", sensitivity_rule=False)]
    assert product_points(caution, "leave_on", True) == -2.0


def test_same_family_counts_once_strongest_wins():
    flags = [F("may_not_suit", "medium", "fragrance"), F("may_not_suit", "high", "fragrance")]
    assert product_points(flags, "leave_on", False) == -3.0


def test_equal_points_fewer_cautions_ranks_higher():
    a = [F("may_suit", "high", "a"), F("may_not_suit", "low", "b")]      # 3 - 1 = 2
    b = [F("may_suit", "medium", "c")]                                    # 2
    r = rank([{"display_name": "A", "flags": a}, {"display_name": "B", "flags": b}], "leave_on", False)
    assert [x["display_name"] for x in r] == ["B", "A"]
    assert not any(x["tied"] for x in r)


def test_no_scores_out_of_100():
    r = rank([{"display_name": "A", "flags": [F("may_suit", "high")]}], "leave_on", False)
    assert abs(r[0]["points"]) < 100


# =====================  4. END TO END + DETERMINISM  =====================

def run_comparison(data, norm, engine, ptype, concerns, profile, products):
    application = next(t["application"] for t in data["product_types"] if t["product_type"] == ptype)
    scored = [{"display_name": n, "flags": engine.evaluate(ptype, norm.normalize(t).ingredients, concerns, profile)}
              for n, t in products]
    return rank(scored, application, bool(profile.get("sensitive")))


SERUMS = [
    ("Serum A", "Aqua, Niacinamide, Zinc PCA, Glycerin"),
    ("Serum B", "Water, Salicylic Acid, Parfum, Glycerin"),
    ("Serum C", "Aqua, Alcohol Denat., Linalool"),
]


def test_end_to_end_serum_comparison(data, norm, engine):
    r = run_comparison(data, norm, engine, "serum", ["acne-prone", "pigmentation"],
                       {"sensitive": True}, SERUMS)
    assert [x["display_name"] for x in r] == ["Serum A", "Serum B", "Serum C"]


def test_same_input_100_times_gives_identical_output(data, norm, engine):
    first = run_comparison(data, norm, engine, "serum", ["acne-prone", "pigmentation"], {"sensitive": True}, SERUMS)
    for _ in range(100):
        assert run_comparison(data, norm, engine, "serum", ["acne-prone", "pigmentation"],
                              {"sensitive": True}, SERUMS) == first


def test_order_of_products_entered_does_not_change_result(data, norm, engine):
    a = run_comparison(data, norm, engine, "serum", ["pigmentation"], {}, SERUMS)
    b = run_comparison(data, norm, engine, "serum", ["pigmentation"], {}, list(reversed(SERUMS)))
    assert a == b


def test_engine_does_not_change_the_rule_data(data):
    before = copy.deepcopy(data["rules"])
    RuleEngine(data).evaluate("serum", ["fragrance"], [], {"sensitive": True})
    assert data["rules"] == before


# =====================  5. GEMINI "BUSY" HANDLING  =====================

class BusyError(Exception):
    code = 503


class FlakyGemini:
    def __init__(self, fail_times):
        self.calls = 0
        outer = self

        class Models:
            def generate_content(self, model, contents):
                outer.calls += 1
                if outer.calls <= fail_times:
                    raise BusyError("503 UNAVAILABLE")
                return type("R", (), {"text": "ok"})()

        self.models = Models()


def test_gemini_retries_when_busy_then_succeeds():
    fake = FlakyGemini(fail_times=2)
    assert llm_client.ask("hi", client=fake, sleep=lambda s: None) == "ok"
    assert fake.calls == 3


def test_gemini_gives_clear_busy_error_after_retries():
    with pytest.raises(llm_client.LLMBusy):
        llm_client.ask("hi", client=FlakyGemini(fail_times=99), sleep=lambda s: None)


def test_gemini_other_errors_are_not_retried():
    class Broken:
        class models:
            @staticmethod
            def generate_content(model, contents):
                raise ValueError("bad key")
    with pytest.raises(ValueError):
        llm_client.ask("hi", client=Broken(), sleep=lambda s: None)
