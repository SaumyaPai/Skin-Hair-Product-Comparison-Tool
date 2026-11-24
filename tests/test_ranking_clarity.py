"""Update 0.6.0: a ranking you can understand, and no "Name to show" box.
Run:  python -m pytest -q tests/test_ranking_clarity.py"""
import pytest
from fastapi.testclient import TestClient

from app import config
from app.data_loader import load_all
from app.deps import build_services, get_services
from app.main import app
from app.services import normalizer, summary
from app.services.compare import explain_order

DATA = load_all()

# The two shampoos from Saumya's comparison (shortened)
MOXIE = ("Aqua, Sodium Cocoyl Isethionate, Cocamidopropyl Betaine, Sodium Cocoyl Glycinate, Polyquaternium-10, "
         "Polyquaternium 44, Guar Hydroxypropyl Trimonium Chloride, Phenoxyethanol (and) Ethylhexylglycerin, "
         "Sodium Chloride")
PILGRIM = ("Aqua, Sodium Laureth Sulfate, Cocamidopropyl Betaine, Glycerin, Dimethiconol (and) "
           "TEA-Dodecylbenzenesulfonate, Dimethicone (and) Aminoethylaminopropyl PEG-6 Dimethicone, Fragrance, "
           "Guar Hydroxypropyltrimonium Chloride, Disodium EDTA, Polyquaternium-22, Biotin")


@pytest.fixture(scope="module")
def norm():
    return normalizer.from_data(DATA)


# ---------------- ingredients that were missed before ----------------

def test_and_joined_items_are_separate_ingredients(norm):
    out = norm.normalize("Phenoxyethanol (and) Ethylhexylglycerin, Dimethiconol (AND) TEA-Dodecylbenzenesulfonate").ingredients
    assert out == ["phenoxyethanol", "ethylhexylglycerin", "dimethiconol", "tea-dodecylbenzenesulfonate"]


def test_brackets_that_are_not_and_stay_together(norm):
    assert norm.normalize("Citrus Limon (Lemon) Fruit Extract").ingredients == ["citrus limon (lemon) fruit extract"]


@pytest.mark.parametrize("written, standard", [
    ("Polyquaternium 44", "polyquaternium-44"), ("POLYQUATERNIUM-7", "polyquaternium-7"),
    ("polyquaternium  22", "polyquaternium-22"),
    ("Guar Hydroxypropyl Trimonium Chloride", "guar hydroxypropyltrimonium chloride"),
    ("guar hydroxypropyl-trimonium chloride", "guar hydroxypropyltrimonium chloride")])
def test_spelling_variants_of_conditioners_are_recognised(norm, written, standard):
    n = norm.normalize(written)
    assert n.ingredients == [standard] and n.not_recognised == []


# ---------------- the comparison Saumya ran ----------------

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "app.db")
    s = build_services(DATA, summarize=[])
    app.dependency_overrides[get_services] = lambda: s
    yield TestClient(app)
    app.dependency_overrides.clear()


def compare(client, a, b, names=("Moxie shampoo", "My shampoo")):
    body = {"product_type": "shampoo", "concerns": ["frizz", "dry-damaged-hair"], "profile": {},
            "products": [{"display_name": names[0], "ingredients_text": a},
                         {"display_name": names[1], "ingredients_text": b}]}
    r = client.post("/v1/compare", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_both_shampoos_now_get_their_conditioner_flags(client):
    r = compare(client, MOXIE, PILGRIM)
    fams = {p["display_name"]: {f["ingredient_family"] for f in p["flags"]} for p in r["products"]}
    assert "cationic conditioning agents" in fams["Moxie shampoo"]
    assert {"cationic conditioning agents", "silicones"} <= fams["My shampoo"]
    moxie = next(p for p in r["products"] if p["display_name"] == "Moxie shampoo")
    assert "polyquaternium-44" in moxie["flags"][0]["matched_ingredients"]


def test_every_product_gets_a_why_line_in_shopper_words(client):
    r = compare(client, MOXIE, PILGRIM)
    why = {x["display_name"]: x["why"] for x in r["ranking"]}
    worth = {x["display_name"]: x["worth_knowing"] for x in r["ranking"]}
    assert why["Moxie shampoo"] == ("Why it's ranked first: it has smoothing conditioners high up in the formula, "
                                    "commonly used for frizz and dry or damaged hair, and nothing we know of that "
                                    "may not suit you.")
    assert why["My shampoo"].startswith("Why it's ranked second: it has smoothing silicones high up in the formula "
                                        "and smoothing conditioners lower in the formula")
    assert worth["My shampoo"] == "Worth knowing: it has sulfate cleansers high up in the formula (sodium laureth sulfate), which may not suit frizz."
    assert worth["Moxie shampoo"] == ""
    everything = " ".join(list(why.values()) + list(worth.values()) + [r["order_note"], r["summary"]]).lower()
    for system_word in ("flag", "rule", "our table", "ingredient group", " of 10", " of 13", "not in our"):
        assert system_word not in everything


def test_one_group_difference_is_called_close(client):
    r = compare(client, MOXIE, MOXIE.replace("Polyquaternium-10, Polyquaternium 44, Guar Hydroxypropyl Trimonium "
                                             "Chloride, ", ""), names=("A", "B"))
    assert r["close_call"] is True and "close" in r["order_note"] and "difference is small" in r["order_note"]
    assert r["order_source"].startswith("https://www.fda.gov/")
    assert "The products are close" in r["summary"]                    # template summary says it too


def test_sulfate_near_the_top_is_a_caution_for_frizz(client):
    r = compare(client, MOXIE, PILGRIM)
    mine = next(p for p in r["products"] if p["display_name"] == "My shampoo")
    caution = [f for f in mine["flags"] if f["flag_type"] == "may_not_suit"]
    assert [f["ingredient_family"] for f in caution] == ["sulfate cleansers"]
    assert caution[0]["source"] == "https://pmc.ncbi.nlm.nih.gov/articles/PMC4387693"
    assert [x["display_name"] for x in r["ranking"]] == ["Moxie shampoo", "My shampoo"]


def test_same_groups_are_told_apart_by_place_on_label(client):
    high = "Aqua, Polyquaternium-10, Glycerin, Sodium Chloride, Citric Acid, Biotin, Panthenol, Salt, Sugar"
    low = "Aqua, Glycerin, Sodium Chloride, Citric Acid, Biotin, Panthenol, Salt, Sugar, Polyquaternium-10"
    r = compare(client, low, high, names=("Low", "High"))
    assert [x["display_name"] for x in r["ranking"]] == ["High", "Low"] and not r["ranking"][0]["tied"]
    assert r["close_call"] is True and "Higher up the list usually means more of it" in r["order_note"]
    assert "high up in the formula" in r["ranking"][0]["why"] and "lower in the formula" in r["ranking"][1]["why"]


def test_same_groups_in_similar_places_stay_tied(client):
    a = "Aqua, Polyquaternium-10, Glycerin"
    r = compare(client, a, "Water, Polyquaternium 10, Glycerin", names=("A", "B"))
    assert all(x["rank"] == 1 and x["tied"] for x in r["ranking"]) and "tied" in r["order_note"]


def test_list_length_alone_never_changes_the_order(client):
    short = "Aqua, Polyquaternium-10, Glycerin"
    long = short + ", " + ", ".join(f"Plant Extract {i}" for i in range(30))
    r = compare(client, short, long, names=("Short", "Long"))
    assert all(x["tied"] for x in r["ranking"])                        # "fewer ingredients" is not a factor


def test_no_matches_says_so_plainly(client):
    r = compare(client, "Aqua, Sodium Chloride", "Aqua, Citric Acid", names=("A", "B"))
    assert all(x["why"].startswith("Why it's tied for first: we didn't spot ingredients") for x in r["ranking"])
    assert "tied" in r["order_note"]


def test_clear_difference_is_not_called_close():
    ranking = [{"display_name": "A", "rank": 1, "tied": False}, {"display_name": "B", "rank": 2, "tied": False}]
    flag = lambda t, fam: {"flag_type": t, "ingredient_family": fam}
    products = [{"display_name": "A", "flags": [flag("may_suit", "x"), flag("may_suit", "y"), flag("may_suit", "z")]},
                {"display_name": "B", "flags": [flag("may_not_suit", "w")]}]
    out = explain_order(ranking, products)
    assert out["close_call"] is False and "close" not in out["order_note"]


# ---------------- the summary may not claim what the flags don't show ----------------

def facts():
    return {"product_type": "Shampoo", "concerns": ["frizz"], "unresolved": [], "close_call": True,
            "products": [{"name": "Moxie shampoo", "rank": 1, "tied": False, "may_suit": [], "may_not_suit": [],
                          "_mentionable": []},
                         {"name": "My shampoo", "rank": 2, "tied": False, "may_suit": [], "may_not_suit": [],
                          "_mentionable": []}]}


@pytest.mark.parametrize("claim", [
    "Both products are designed for frizz and dry or damaged hair.",
    "My shampoo is formulated for frizz.", "Moxie shampoo is made for dry hair.",
    "Moxie shampoo leads in the ranking.", "Moxie shampoo is better for frizz.",
    "Moxie shampoo is suitable for frizz."])
def test_summary_claims_are_rejected(claim):
    text = "Moxie shampoo is ranked first. " + claim
    assert summary.check_summary(text, facts(), DATA)


def test_honest_close_summary_is_allowed():
    text = ("Moxie shampoo is ranked first and My shampoo second, but the products are close "
            "and the difference is small.")
    assert summary.check_summary(text, facts(), DATA) == []


def test_prompt_tells_the_ai_the_new_rules():
    p = summary.build_prompt(facts())
    assert "designed, made, formulated or intended" in p and "close_call" in p


def test_why_note_explains_label_order_plainly(client):
    high = "Aqua, Polyquaternium-10, Glycerin, Sodium Chloride, Citric Acid, Biotin, Panthenol, Salt, Sugar"
    low = "Aqua, Glycerin, Sodium Chloride, Citric Acid, Biotin, Panthenol, Salt, Sugar, Polyquaternium-10"
    r = compare(client, low, high, names=("Low", "High"))
    assert "labels list ingredients from the largest amount to the smallest" in r["order_note"]


def test_position_switch_off_ignores_place_on_label(client, monkeypatch):
    monkeypatch.setattr(config, "USE_LABEL_POSITION", False)
    high = "Aqua, Polyquaternium-10, Glycerin, Sodium Chloride, Citric Acid, Biotin, Panthenol, Salt, Sugar"
    low = "Aqua, Glycerin, Sodium Chloride, Citric Acid, Biotin, Panthenol, Salt, Sugar, Polyquaternium-10"
    r = compare(client, low, high, names=("Low", "High"))
    assert all(x["tied"] for x in r["ranking"]) and "formula" not in r["ranking"][0]["why"]


def test_conditioners_at_different_places_are_not_tied(client):
    # both near the top, but one is 2nd and the other 4th: the higher one ranks first
    a = "Aqua, Behentrimonium Chloride, Cetearyl Alcohol, Glycerin, Panthenol, Citric Acid, Salt, Sugar, Biotin, Zinc"
    b = "Aqua, Cetearyl Alcohol, Glycerin, Behentrimonium Chloride, Panthenol, Citric Acid, Salt, Sugar, Biotin, Zinc"
    r = compare(client, b, a, names=("Fourth", "Second"))
    assert [x["display_name"] for x in r["ranking"]] == ["Second", "Fourth"]
    assert not any(x["tied"] for x in r["ranking"])
    assert "how high up the list those ingredients appear" in r["order_note"]


def test_position_factor_steps_down_and_stops_at_half():
    from app.services.ranking import position_factor
    assert position_factor(1) == 1.0 and position_factor(2) == 0.95 and position_factor(6) == 0.75
    assert position_factor(11) == 0.5 and position_factor(40) == 0.5 and position_factor(None) == 1.0


def test_version_is_shown_on_the_page_and_matches_the_api():
    from pathlib import Path
    from ui.logic import UI_VERSION
    assert UI_VERSION == config.APP_VERSION
    assert "Version {UI_VERSION}" in (Path(__file__).parents[1] / "ui" / "streamlit_app.py").read_text(encoding="utf-8")
    assert TestClient(app).get("/health").json()["version"] == config.APP_VERSION
