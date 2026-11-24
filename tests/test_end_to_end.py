"""End-to-end scenarios: the real API, real rules and real ranking, with the internet parts (product
database and AI) replaced by stand-ins, so every result is predictable. Covers every product type and
concern, all four ways to add a product, ties, close calls, cautions, label position, AI failures,
shopper language, banned words and the disclaimer.
Run:  python -m pytest tests/test_end_to_end.py -v
"""
import re
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config
from app.data_loader import dropdown_concerns, load_all
from app.deps import build_services, get_services
from app.main import app
from app.services.llm_client import LLMBusy
from scripts.eval.scoring import ClaimChecker, score_reading
from app.services.normalizer import from_data

DATA = load_all()
DROPDOWN = dropdown_concerns(DATA)
TYPES = {t["product_type"]: t for t in DATA["product_types"]}
CHECKER = ClaimChecker(DATA)
LABELS = Path(__file__).resolve().parent / "fixtures" / "labels"

# Two products per category: A has many ingredients commonly used for the concerns, B has common cautions.
SKIN_A = ("Aqua, Niacinamide, Salicylic Acid, Glycerin, Ceramide NP, Sodium Hyaluronate, Panthenol, Allantoin, "
          "Zinc PCA, Ascorbic Acid, Azelaic Acid, Iron Oxides, Caffeine, Shea Butter, Petrolatum, Centella Asiatica Extract")
SKIN_B = "Aqua, Alcohol Denat., Parfum, Sodium Lauryl Sulfate, Menthol, Limonene, Linalool, Isopropyl Myristate"
HAIR_A = ("Aqua, Zinc Pyrithione, Ketoconazole, Cetearyl Alcohol, Behentrimonium Chloride, Argan Oil, Panthenol, "
          "Polyquaternium-10, Rosmarinus Officinalis Leaf Oil, Caffeine, Glycerin, Dimethicone")
HAIR_B = "Aqua, Sodium Lauryl Sulfate, Alcohol Denat., Parfum, Menthol, Isopropyl Alcohol"

# words a shopper should never see: judgements, medical claims, and how the system works inside
SYSTEM_WORDS = ["flag", "rule", "our table", "may_suit", "may_not_suit", "severity", "weight", "score", "R0"]
BANNED = config.BANNED_WORDS + ["better", "recommend", "safe", "unsafe", "diagnose"]

FOUND = {
    "8901030000011": ("Moisture Shampoo", "BrandH", HAIR_A, ["en:shampoos"]),
    "8901030000028": ("Clarify Shampoo", "BrandH", HAIR_B, ["en:shampoos"]),
    "8901030000035": ("Glow Serum", "BrandS", SKIN_A, ["en:serums"]),
    "8901030000042": ("Daily Face Wash", "BrandS", SKIN_B, ["en:face-cleansers"]),
    "8901030000059": ("Mystery Product", "BrandX", "", ["en:shampoos"]),
}


def fake_lookup(barcode):
    base = {"barcode": barcode, "product_name": "", "brand": "", "ingredients_text": "", "category_tags": [],
            "message": ""}
    if barcode not in FOUND:
        return {**base, "status": "not_found"}
    name, brand, ingr, tags = FOUND[barcode]
    return {**base, "status": "found" if ingr else "no_ingredients", "product_name": name, "brand": brand,
            "ingredients_text": ingr, "category_tags": tags}


def fake_search(q):
    hits = [(bc, v) for bc, v in FOUND.items() if q.lower() in v[0].lower() and v[2]]
    return {"status": "ok", "results": [{"barcode": bc, "product_name": v[0], "brand": v[1], "ingredients_text": v[2],
                                         "category_tags": v[3]} for bc, v in hits]}


def busy(*a, **k):
    raise LLMBusy("503 UNAVAILABLE: high demand")


def ai_reads(text):
    return lambda img, mime, **k: {"readable": True, "ingredients_text": text, "confidence_note": ""}


@pytest.fixture
def api(tmp_path, monkeypatch):
    """A client for the real API. call api.use(...) to swap a stand-in for an outside service."""
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "e2e.db")
    services = build_services(DATA, obf_lookup=fake_lookup, obf_search=fake_search, summarize=[],
                              extract=[("gemini:fake", ai_reads("Aqua, Glycerin, Niacinamide"))])
    app.dependency_overrides[get_services] = lambda: services
    client = TestClient(app)
    client.use = lambda **kw: [setattr(services, k, v) for k, v in kw.items()]
    yield client
    app.dependency_overrides.clear()


def compare(api, ptype, concerns, products, profile=None, status=200):
    body = {"product_type": ptype, "concerns": list(concerns), "products": products}
    if profile:
        body["profile"] = profile
    r = api.post("/v1/compare", json=body)
    assert r.status_code == status, r.text
    return r.json()


def pasted(*lists, prefix="Product"):
    return [{"display_name": f"{prefix} {chr(65 + i)}", "ingredients_text": t} for i, t in enumerate(lists)]


def shopper_text(res) -> str:
    parts = [res["summary"], res["order_note"]] + [r["why"] + " " + r["worth_knowing"] for r in res["ranking"]]
    return " ".join(parts).lower()


def assert_shopper_safe(res):
    """What every result must look like, whatever went in."""
    assert res["disclaimer"] == config.DISCLAIMER
    text = shopper_text(res)
    for w in BANNED + SYSTEM_WORDS:
        assert not re.search(rf"(?<![a-z0-9]){re.escape(w.lower())}(?![a-z0-9])", text), f"'{w}' in: {text}"
    for p in res["products"]:
        for f in p["flags"]:
            assert f["source"].startswith("http"), f        # every statement has a source
    texts = [p.get("ingredients_text") or ", ".join(p["ingredients"]) for p in res["products"]]
    claims = CHECKER.check(res["summary"], texts, [p["display_name"] for p in res["products"]])
    assert claims["count"] == 0, claims


# ------------------------------------------------------------------ every product type x every concern

CASES = [(t, c) for t in TYPES for c in DROPDOWN[t]]


def test_every_type_has_concerns():
    assert len(TYPES) == 12 and all(DROPDOWN[t] for t in TYPES)


@pytest.mark.parametrize("ptype,concern", CASES, ids=[f"{t}-{c}" for t, c in CASES])
def test_every_type_and_concern(api, ptype, concern):
    a, b = (HAIR_A, HAIR_B) if TYPES[ptype]["category"] == "hair" else (SKIN_A, SKIN_B)
    res = compare(api, ptype, [concern], pasted(a, b))
    assert res["status"] == "ok" and len(res["ranking"]) == 2
    assert_shopper_safe(res)
    ranks = {r["display_name"]: r["rank"] for r in res["ranking"]}
    assert ranks["Product A"] <= ranks["Product B"]           # the one with more relevant ingredients never ranks lower
    a_flags = next(p for p in res["products"] if p["display_name"] == "Product A")["flags"]
    if any(f["flag_type"] == "may_suit" for f in a_flags):
        assert "commonly used for" in next(r["why"] for r in res["ranking"] if r["display_name"] == "Product A")


@pytest.mark.parametrize("ptype", list(TYPES))
def test_every_type_with_three_concerns_and_four_products(api, ptype):
    a, b = (HAIR_A, HAIR_B) if TYPES[ptype]["category"] == "hair" else (SKIN_A, SKIN_B)
    res = compare(api, ptype, DROPDOWN[ptype][:3], pasted(a, b, "Aqua, Glycerin", a + ", Parfum"),
                  profile={"sensitive": True, "avoid_fragrance": True})
    assert len(res["ranking"]) == 4
    assert_shopper_safe(res)


# ------------------------------------------------------------------ the four ways to add a product

def test_barcode_input(api):
    res = compare(api, "shampoo", ["dandruff"], [{"display_name": "x1", "barcode": "8901030000011"},
                                                 {"display_name": "x2", "barcode": "8901030000028"}])
    assert {p["ingredient_source"] for p in res["products"]} == {"open_beauty_facts"}
    assert res["ranking"][0]["display_name"] == "x1"
    assert_shopper_safe(res)
    again = compare(api, "shampoo", ["dandruff"], [{"display_name": "x1", "barcode": "8901030000011"},
                                                   {"display_name": "x2", "barcode": "8901030000028"}])
    assert "cached" in again["products"][0]["ingredient_source"]          # second time comes from the saved copy


def test_barcode_problems_are_explained(api):
    res = compare(api, "shampoo", ["dandruff"], [{"display_name": "Known", "barcode": "8901030000011"},
                                                 {"display_name": "Unknown", "barcode": "8901030000999"},
                                                 {"display_name": "Empty", "barcode": "8901030000059"}])
    reasons = {u["display_name"]: u["reason"] for u in res["unresolved"]}
    assert reasons == {"Unknown": "not_found", "Empty": "no_ingredients_listed"}
    assert res["status"] == "insufficient_data" and res["ranking"] == []
    assert res["disclaimer"] == config.DISCLAIMER and "paste" in res["summary"].lower()


def test_lookup_by_barcode_and_name(api):
    r = api.get("/v1/products/lookup", params={"barcode": "8901030000035"})
    assert r.status_code == 200 and r.json()["results"][0]["product_name"] == "Glow Serum"
    r = api.get("/v1/products/lookup", params={"q": "shampoo"})
    assert r.status_code == 200 and len(r.json()["results"]) == 2
    assert api.get("/v1/products/lookup", params={"q": "nothing like this"}).status_code == 404
    assert api.get("/v1/products/lookup", params={"barcode": "12ab"}).status_code == 422


def test_name_search_then_compare(api):
    hits = api.get("/v1/products/lookup", params={"q": "shampoo"}).json()["results"]
    products = [{"display_name": h["product_name"], "barcode": h["barcode"]} for h in hits]
    api.use(obf_lookup=lambda bc: {"status": "error"})                    # found by name, so saved: no internet needed
    res = compare(api, "shampoo", ["dandruff"], products)
    assert res["status"] == "ok" and res["ranking"][0]["display_name"] == "Moisture Shampoo"


def test_paste_with_no_real_ingredients_is_not_ranked(api):
    res = compare(api, "serum", ["pigmentation"], pasted(" , ,  ; ", SKIN_A, SKIN_B))
    assert [u["display_name"] for u in res["unresolved"]] == ["Product A"]
    assert len(res["ranking"]) == 2 and "Product A" in res["summary"]


def test_paste_input(api):
    res = compare(api, "serum", ["pigmentation"], pasted(SKIN_A, SKIN_B))
    assert {p["ingredient_source"] for p in res["products"]} == {"pasted_text"}


def test_photo_input_then_compare(api):
    truth = (LABELS / "conditioner.txt").read_text()
    api.use(extract=[("gemini:fake", ai_reads(truth))])
    r = api.post("/v1/products/extract", files={"image": ("c.jpg", (LABELS / "conditioner.jpg").read_bytes(),
                                                          "image/jpeg")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["readable"] and body["reader"] == "gemini:fake" and "check" in body["warning"].lower()
    res = compare(api, "conditioner", ["frizz"],
                  [{"display_name": "L'Oreal conditioner", "extracted_text": body["ingredients_text"]},
                   {"display_name": "Other", "ingredients_text": "Aqua, Cetyl Alcohol, Parfum"}])
    assert res["products"][0]["ingredient_source"] == "label_photo" or res["products"][1]["ingredient_source"] == "label_photo"
    ours = next(p for p in res["products"] if p["display_name"] == "L'Oreal conditioner")
    assert "sodium laureth sulfate" in ours["ingredients"]
    assert_shopper_safe(res)


def test_mixed_inputs_in_one_comparison(api):
    res = compare(api, "serum", ["pigmentation"], [
        {"display_name": "By barcode", "barcode": "8901030000035"},
        {"display_name": "Pasted", "ingredients_text": SKIN_B},
        {"display_name": "From photo", "extracted_text": "Aqua, Ascorbic Acid, Glycerin"}])
    assert {p["ingredient_source"] for p in res["products"]} == {"open_beauty_facts", "pasted_text", "label_photo"}


# ------------------------------------------------------------------ photo reading when AIs fail

def test_photo_backup_reader_used_when_first_ai_is_busy(api):
    api.use(extract=[("gemini:a", busy), ("groq:b", ai_reads("Aqua, Glycerin, Niacinamide"))])
    body = api.post("/v1/products/extract", files={"image": ("x.jpg", (LABELS / "conditioner.jpg").read_bytes(),
                                                             "image/jpeg")}).json()
    assert body["reader"] == "groq:b" and body["readable"]


def test_photo_offline_reader_on_real_label_when_all_ais_are_down(api):
    """The real without-AI reader on Saumya's conditioner photo."""
    if not shutil.which("tesseract") and not Path(config.TESSERACT_CMD or "").exists():
        pytest.skip("Tesseract isn't installed")
    from app.services import ocr
    api.use(extract=[("gemini:a", busy), ("groq:b", busy), ("offline_ocr", ocr.read_ingredients)])
    body = api.post("/v1/products/extract", files={"image": ("c.jpg", (LABELS / "conditioner.jpg").read_bytes(),
                                                             "image/jpeg")}).json()
    assert body["reader"] == "offline_ocr" and body["readable"]
    s = score_reading((LABELS / "conditioner.txt").read_text(), body["ingredients_text"], from_data(DATA))
    assert s["pct_exact_or_near"] >= 80, s


def test_all_photo_readers_down_says_why(api):
    api.use(extract=[("gemini:a", busy), ("groq:b", busy)])
    r = api.post("/v1/products/extract", files={"image": ("x.jpg", (LABELS / "conditioner.jpg").read_bytes(),
                                                          "image/jpeg")})
    assert r.status_code == 502 and "paste" in r.json()["error"]["message"].lower()


def test_photo_wrong_file_type(api):
    r = api.post("/v1/products/extract", files={"image": ("x.gif", b"GIF89a", "image/gif")})
    assert r.status_code == 422


# ------------------------------------------------------------------ AI summary failures

def test_summary_falls_back_when_ai_is_busy(api):
    api.use(summarize=[("gemini:a", busy), ("groq:b", busy)])
    res = compare(api, "serum", ["pigmentation"], pasted(SKIN_A, SKIN_B))
    assert res["summary_source"] == "template" and res["summary"]
    assert_shopper_safe(res)


def test_ai_summary_with_banned_words_is_never_shown(api):
    api.use(summarize=[("gemini:a", lambda p: "Product A is the best and will cure your acne.")])
    res = compare(api, "serum", ["acne-prone"], pasted(SKIN_A, SKIN_B))
    assert res["summary_source"] == "template" and "cure" not in res["summary"].lower()


def test_ai_summary_inventing_an_ingredient_is_never_shown(api):
    api.use(summarize=[("gemini:a", lambda p: "Product A has retinol, commonly used for pigmentation.")])
    res = compare(api, "serum", ["pigmentation"], pasted("Aqua, Niacinamide", SKIN_B))
    assert res["summary_source"] == "template" and "retinol" not in res["summary"].lower()


def test_ai_summary_backup_ai_used(api):
    good = "Product A is ranked first for pigmentation: it has niacinamide, commonly used for pigmentation."
    api.use(summarize=[("gemini:a", busy), ("groq:b", lambda p: good)])
    res = compare(api, "serum", ["pigmentation"], pasted("Aqua, Niacinamide", "Aqua, Glycerin"))
    assert res["summary_source"] == "llm" and res["summary_provider"] == "groq:b" and res["summary"] == good


def test_product_database_down_still_works_for_paste(api):
    api.use(obf_lookup=lambda bc: {"status": "error"}, obf_search=lambda q: {"status": "error", "results": []})
    res = compare(api, "serum", ["pigmentation"], pasted(SKIN_A, SKIN_B))
    assert res["status"] == "ok"
    assert api.get("/v1/products/lookup", params={"q": "serum"}).status_code == 502


# ------------------------------------------------------------------ ordering behaviour

def test_identical_products_are_tied(api):
    res = compare(api, "serum", ["pigmentation"], pasted(SKIN_A, SKIN_A))
    assert all(r["rank"] == 1 and r["tied"] for r in res["ranking"])
    assert res["close_call"] and "tied" in res["order_note"].lower()
    assert all("tied for first" in r["why"] for r in res["ranking"])


def test_nothing_relevant_in_either_is_a_tie(api):
    res = compare(api, "serum", ["dark-circles"], pasted("Aqua, Glycerin", "Water, Butylene Glycol"))
    assert all(r["rank"] == 1 for r in res["ranking"])
    assert "didn't spot" in res["ranking"][0]["why"]


def test_label_position_breaks_a_tie(api):
    high = "Aqua, Niacinamide, Glycerin, Butylene Glycol, Pentylene Glycol, Carbomer, Xanthan Gum, Sodium Benzoate"
    low = "Aqua, Glycerin, Butylene Glycol, Pentylene Glycol, Carbomer, Xanthan Gum, Sodium Benzoate, Niacinamide"
    res = compare(api, "serum", ["pigmentation"], [{"display_name": "Low", "ingredients_text": low},
                                                  {"display_name": "High", "ingredients_text": high}])
    assert [r["display_name"] for r in res["ranking"]] == ["High", "Low"]
    assert res["close_call"] and "how high up the list" in res["order_note"]
    assert "high up in the formula" in res["ranking"][0]["why"]
    assert res["order_source"].startswith("http")


def test_list_length_does_not_matter_only_place(api):
    short = "Aqua, Niacinamide"
    long = "Aqua, Niacinamide, " + ", ".join(["Glycerin", "Butylene Glycol", "Carbomer", "Xanthan Gum",
                                             "Sodium Benzoate", "Pentylene Glycol", "Tocopherol", "Citric Acid"])
    res = compare(api, "serum", ["pigmentation"], pasted(short, long))
    assert all(r["rank"] == 1 for r in res["ranking"])


def test_clear_difference_is_not_a_close_call(api):
    res = compare(api, "serum", ["pigmentation", "acne-prone"], pasted(SKIN_A, SKIN_B))
    assert not res["close_call"]
    assert res["ranking"][0]["display_name"] == "Product A"


def test_close_call_is_said_plainly(api):
    res = compare(api, "serum", ["pigmentation"], pasted("Aqua, Niacinamide, Ascorbic Acid", "Aqua, Niacinamide"))
    assert res["close_call"] and "close" in res["order_note"].lower()


def test_sulfate_caution_for_frizz(api):
    res = compare(api, "shampoo", ["frizz"], [
        {"display_name": "Sulfate", "ingredients_text": "Aqua, Sodium Lauryl Sulfate, Cocamidopropyl Betaine, Parfum"},
        {"display_name": "Gentle", "ingredients_text": "Aqua, Decyl Glucoside, Glycerin, Panthenol"}])
    first, second = res["ranking"]
    assert first["display_name"] == "Gentle" and second["display_name"] == "Sulfate"
    assert "worth knowing" in second["worth_knowing"].lower() and "sulfate" in second["worth_knowing"].lower()
    assert first["worth_knowing"] == ""


def test_fragrance_caution_only_when_profile_says_so(api):
    lists = pasted("Aqua, Niacinamide, Parfum", "Aqua, Niacinamide")
    plain = compare(api, "serum", ["pigmentation"], lists)
    avoid = compare(api, "serum", ["pigmentation"], lists, profile={"avoid_fragrance": True})
    assert avoid["ranking"][0]["display_name"] == "Product B"
    assert "fragrance" in avoid["ranking"][1]["worth_knowing"].lower()
    assert plain["ranking"][0]["rank"] <= avoid["ranking"][0]["rank"]


def test_same_comparison_gives_the_same_answer_every_time(api):
    runs = [compare(api, "conditioner", ["frizz", "hair-fall"], pasted(HAIR_A, HAIR_B, "Aqua, Cetyl Alcohol"))
            for _ in range(3)]
    assert len({str(r["ranking"]) for r in runs}) == 1 and len({r["summary"] for r in runs}) == 1


def test_blends_and_other_names_are_understood(api):
    res = compare(api, "shampoo", ["frizz"], pasted((LABELS / "shampoo.txt").read_text(), "Aqua, Sodium Lauryl Sulfate"))
    p = next(p for p in res["products"] if p["display_name"] == "Product A")
    assert "glycerin" in p["ingredients"] and "dimethicone" in p["ingredients"]       # split out of "(and)" blends
    assert "polyquaternium-22" in p["ingredients"]


# ------------------------------------------------------------------ requests that must be refused

def test_mixed_product_types_are_refused(api):
    r = api.post("/v1/compare", json={"product_type": "shampoo", "concerns": ["dandruff"], "products": [
        {"display_name": "S", "barcode": "8901030000011"}, {"display_name": "Serum", "barcode": "8901030000035"}]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "PRODUCT_TYPE_MISMATCH"


@pytest.mark.parametrize("body,code", [
    ({"product_type": "toothpaste", "concerns": ["dryness"]}, "UNKNOWN_PRODUCT_TYPE"),
    ({"product_type": "lip_balm", "concerns": ["acne-prone"]}, "UNKNOWN_CONCERN"),
])
def test_unknown_type_or_concern(api, body, code):
    r = api.post("/v1/compare", json={**body, "products": pasted("Aqua", "Aqua")})
    assert r.status_code == 422 and r.json()["error"]["code"] == code


@pytest.mark.parametrize("products", [pasted("Aqua"), pasted("Aqua", "Aqua", "Aqua", "Aqua", "Aqua"),
                                      [{"display_name": "A"}, {"display_name": "B", "ingredients_text": "Aqua"}]])
def test_wrong_number_of_products_or_missing_input(api, products):
    r = api.post("/v1/compare", json={"product_type": "serum", "concerns": ["dryness"], "products": products})
    assert r.status_code == 422


def test_more_than_three_concerns_refused(api):
    r = api.post("/v1/compare", json={"product_type": "serum", "concerns": DROPDOWN["serum"][:4],
                                      "products": pasted("Aqua", "Aqua")})
    assert r.status_code == 422


def test_health_reports_version(api):
    assert api.get("/health").json()["version"] == config.APP_VERSION


# ------------------------------------------------------------------ pore-clogging check (acne-prone skin)

PORE_TYPES = ["toner", "serum", "moisturizer", "face_mask", "sunscreen"]


@pytest.mark.parametrize("ptype", PORE_TYPES)
def test_pore_clogging_caution_and_tag(api, ptype):
    res = compare(api, ptype, ["acne-prone"], [
        {"display_name": "Heavy", "ingredients_text": "Aqua, Isopropyl Myristate, Glycerin, Cocos Nucifera Oil"},
        {"display_name": "Light", "ingredients_text": "Aqua, Glycerin, Dimethicone"}])
    first, second = res["ranking"]
    assert first["display_name"] == "Light" and second["display_name"] == "Heavy"
    assert first["tags"] == ["No pore-clogging ingredients found"] and second["tags"] == []
    assert "pore-clogging ingredients" in second["worth_knowing"]
    assert "isopropyl myristate" in second["worth_knowing"] and "coconut oil" in second["worth_knowing"]
    assert "may not suit acne-prone skin" in second["worth_knowing"]
    assert_shopper_safe(res)


def test_pore_tag_wording_never_promises():
    from app.services.compare import PORE_TAG
    assert PORE_TAG == "No pore-clogging ingredients found"
    assert "common" not in PORE_TAG.lower() and "non-comedogenic" not in PORE_TAG.lower()


def test_pore_check_label_names(api):
    res = compare(api, "moisturizer", ["acne-prone"], [
        {"display_name": "A", "ingredients_text": "Aqua, Theobroma Cacao (Cocoa) Seed Butter, Ethylhexyl Palmitate"},
        {"display_name": "B", "ingredients_text": "Aqua, Acetylated Lanolin, Isopropyl Palmitate"},
        {"display_name": "C", "ingredients_text": "Aqua, Glycerin"}])
    by = {r["display_name"]: r for r in res["ranking"]}
    assert "cocoa butter" in by["A"]["worth_knowing"] and "ethylhexyl palmitate" in by["A"]["worth_knowing"]
    assert "acetylated lanolin" in by["B"]["worth_knowing"] and "isopropyl palmitate" in by["B"]["worth_knowing"]
    assert by["C"]["rank"] == 1 and by["C"]["tags"]
    assert by["A"]["worth_knowing"].count("pore-clogging") == 1          # one kind, said once


def test_pore_tag_only_for_acne_prone_on_covered_types(api):
    other = compare(api, "moisturizer", ["dryness"], pasted("Aqua, Glycerin", "Aqua, Isopropyl Myristate"))
    assert all(r["tags"] == [] for r in other["ranking"])
    wash = compare(api, "face_wash", ["acne-prone"], pasted("Aqua, Glycerin", "Aqua, Isopropyl Myristate"))
    assert all(r["tags"] == [] for r in wash["ranking"])               # rinsed off: not checked
    hair = compare(api, "hair_oil_serum", ["dry-damaged-hair"], pasted("Coconut Oil", "Argan Oil"))
    assert "pore" not in shopper_text(hair)


def test_pore_check_counts_once_however_many_clogging_ingredients(api):
    res = compare(api, "serum", ["acne-prone"], pasted(
        "Aqua, Isopropyl Myristate, Isopropyl Palmitate, Cocoa Butter, Coconut Oil, Myristyl Myristate",
        "Aqua, Isopropyl Myristate, Glycerin"))
    assert all(r["rank"] == 1 for r in res["ranking"])                  # same kind of caution, both high up


def test_sunscreen_now_offers_acne_prone():
    assert "acne-prone" in DROPDOWN["sunscreen"]
