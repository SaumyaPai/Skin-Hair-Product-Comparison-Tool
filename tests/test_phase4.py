"""Phase 4 tests: the five endpoints, caching, Gemini photo reading and summary, and errors.

Gemini and Open Beauty Facts are replaced by fakes here, so these tests use no internet
and none of your free quota. Run from the project folder:  python -m pytest -v
"""
import io
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import config, db
from app.data_loader import load_all
from app.deps import build_services, get_services
from app.main import app
from app.services import llm_client, summary

DATA = load_all()

SERUM_A = {"status": "found", "barcode": "1234567890123", "product_name": "Serum A Real Name", "brand": "BrandA",
           "ingredients_text": "Aqua, Niacinamide, Glycerin", "category_tags": ["en:serums"], "message": ""}
SHAMPOO_X = {"status": "found", "barcode": "5555555555555", "product_name": "Shampoo X", "brand": "B",
             "ingredients_text": "Aqua, Sodium Laureth Sulfate", "category_tags": ["en:shampoos"], "message": ""}
NO_INGR = {"status": "no_ingredients", "barcode": "7777777777777", "product_name": "Mystery", "brand": "",
           "ingredients_text": "", "category_tags": [], "message": ""}


class FakeOBF:
    def __init__(self, down=False):
        self.down, self.calls = down, 0
        self.products = {p["barcode"]: p for p in (SERUM_A, SHAMPOO_X, NO_INGR)}

    def lookup(self, barcode):
        self.calls += 1
        if self.down:
            return {"status": "error", "barcode": barcode, "product_name": "", "brand": "", "ingredients_text": "",
                    "category_tags": [], "message": "down"}
        return dict(self.products.get(barcode) or {"status": "not_found", "barcode": barcode, "product_name": "",
                                                   "brand": "", "ingredients_text": "", "category_tags": [],
                                                   "message": ""})

    def search(self, q):
        if self.down:
            return {"status": "error", "results": [], "message": "down"}
        hits = [p for p in self.products.values() if q.lower() in p["product_name"].lower()]
        return {"status": "ok", "results": [{k: p[k] for k in ("barcode", "product_name", "brand",
                                                                 "ingredients_text", "category_tags")} for p in hits]}


def good_summary(prompt):
    facts = json.loads(prompt.split("FACTS:\n", 1)[1])
    top = facts["products"][0]["name"]
    return f"{top} is ranked first for your concerns."


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A fresh empty database and fake outside services for every test."""
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    obf = FakeOBF()
    services = build_services(DATA, obf_lookup=obf.lookup, obf_search=obf.search,
                              extract=lambda img, mime: {"readable": True, "ingredients_text": "Aqua, Glycerin",
                                                         "confidence_note": ""},
                              summarize=good_summary)
    app.dependency_overrides[get_services] = lambda: services
    client = TestClient(app, raise_server_exceptions=False)
    yield client, services, obf
    app.dependency_overrides.clear()


def compare_body(**overrides):
    body = {
        "product_type": "serum",
        "concerns": ["acne-prone", "pigmentation"],
        "profile": {"skin_type": "oily", "sensitive": True, "avoid_fragrance": False},
        "products": [
            {"display_name": "Serum A", "barcode": "1234567890123"},
            {"display_name": "Serum B", "ingredients_text": "Aqua, Salicylic Acid, Parfum"},
            {"display_name": "Serum C", "extracted_text": "Water, Linalool"},
            {"display_name": "Serum D", "barcode": "9999999999999"},
        ],
    }
    body.update(overrides)
    return body


def assert_error(resp, status, code):
    assert resp.status_code == status, resp.text
    err = resp.json()["error"]
    assert err["code"] == code
    assert err["message"] and err["request_id"].startswith("req_")
    assert "Traceback" not in resp.text


# =====================  /health and /v1/meta/options  =====================

def test_health(env):
    client, *_ = env
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["rules_loaded"] == len(DATA["rules"])


def test_options_come_from_the_rule_table(env):
    client, *_ = env
    body = client.get("/v1/meta/options").json()
    types = {t["id"]: t for t in body["product_types"]}
    assert len(types) == 12
    shampoo = [c["id"] for c in types["shampoo"]["concerns"]]
    assert "dandruff" in shampoo and "hair-fall" in shampoo
    assert "dark-circles" not in [c["id"] for c in types["face_wash"]["concerns"]]


# =====================  /v1/products/lookup  =====================

def test_lookup_barcode_then_cached(env):
    client, _, obf = env
    first = client.get("/v1/products/lookup", params={"barcode": "1234567890123"})
    assert first.status_code == 200
    assert first.json()["results"][0]["has_ingredients"] is True
    second = client.get("/v1/products/lookup", params={"barcode": "1234567890123"}).json()
    assert second["results"][0]["cached"] is True
    assert obf.calls == 1                              # second time came from the cache


def test_lookup_unknown_barcode_is_404(env):
    assert_error(env[0].get("/v1/products/lookup", params={"barcode": "9999999999999"}), 404, "PRODUCT_NOT_FOUND")


def test_lookup_product_without_ingredients(env):
    r = env[0].get("/v1/products/lookup", params={"barcode": "7777777777777"}).json()
    assert r["results"][0]["has_ingredients"] is False


def test_lookup_site_down_is_502(env):
    client, _, obf = env
    obf.down = True
    assert_error(client.get("/v1/products/lookup", params={"barcode": "1234567890123"}), 502, "UPSTREAM_UNAVAILABLE")


def test_lookup_site_down_uses_old_copy(env):
    client, _, obf = env
    old = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    conn = db.connect()
    db.save_product(conn, "1234567890123", "Old", "B", "Aqua", "open_beauty_facts", fetched_at=old)
    obf.down = True
    r = client.get("/v1/products/lookup", params={"barcode": "1234567890123"}).json()
    assert r["results"][0]["ingredients_text"] == "Aqua" and "older saved copy" in r["results"][0]["note"]


def test_old_cache_is_refreshed_when_site_is_up(env):
    client, _, obf = env
    old = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    db.save_product(db.connect(), "1234567890123", "Old", "B", "Aqua", "open_beauty_facts", fetched_at=old)
    r = client.get("/v1/products/lookup", params={"barcode": "1234567890123"}).json()
    assert r["results"][0]["ingredients_text"] == SERUM_A["ingredients_text"] and obf.calls == 1


@pytest.mark.parametrize("params", [{}, {"barcode": "1234567890123", "q": "serum"}, {"barcode": "12ab"},
                                    {"barcode": "123"}])
def test_lookup_bad_requests_are_422(env, params):
    assert_error(env[0].get("/v1/products/lookup", params=params), 422, "VALIDATION_ERROR")


def test_lookup_by_name(env):
    r = env[0].get("/v1/products/lookup", params={"q": "serum a"})
    assert r.status_code == 200 and r.json()["results"][0]["barcode"] == "1234567890123"
    assert_error(env[0].get("/v1/products/lookup", params={"q": "nothing like this"}), 404, "PRODUCT_NOT_FOUND")


def test_lookup_by_name_site_down(env):
    env[2].down = True
    assert_error(env[0].get("/v1/products/lookup", params={"q": "serum"}), 502, "UPSTREAM_UNAVAILABLE")


# =====================  /v1/products/extract  =====================

def png_bytes(size=(400, 300)):
    buf = io.BytesIO()
    Image.new("RGB", size, "white").save(buf, format="PNG")
    return buf.getvalue()


def test_extract_reads_a_photo(env):
    r = env[0].post("/v1/products/extract", files={"image": ("label.png", png_bytes(), "image/png")})
    assert r.status_code == 200
    body = r.json()
    assert body["readable"] is True and body["ingredients_text"] == "Aqua, Glycerin"
    assert body["source"] == "label_photo" and "check" in body["warning"]


def test_extract_shrinks_big_photos_before_sending(env):
    client, services, _ = env
    seen = {}

    def spy(img, mime):
        seen["size"] = Image.open(io.BytesIO(img)).size
        return {"readable": False, "ingredients_text": "", "confidence_note": "blurry"}
    services.extract = spy
    r = client.post("/v1/products/extract", files={"image": ("big.png", png_bytes((4000, 3000)), "image/png")})
    assert r.status_code == 200 and r.json()["readable"] is False
    assert max(seen["size"]) <= config.MAX_IMAGE_SIDE_PX


@pytest.mark.parametrize("name, content, ctype", [
    ("notes.txt", b"hello", "text/plain"),
    ("fake.png", b"this is not really a picture", "image/png"),
    ("empty.png", b"", "image/png"),
])
def test_extract_rejects_non_images(env, name, content, ctype):
    assert_error(env[0].post("/v1/products/extract", files={"image": (name, content, ctype)}), 422, "INVALID_IMAGE")


def test_extract_rejects_over_5mb(env):
    big = b"\x89PNG" + b"0" * (config.MAX_IMAGE_BYTES + 10)
    assert_error(env[0].post("/v1/products/extract", files={"image": ("big.png", big, "image/png")}),
                 422, "INVALID_IMAGE")


@pytest.mark.parametrize("exc", [llm_client.LLMBusy("busy"), llm_client.LLMNotConfigured("no key"), RuntimeError("x")])
def test_extract_gemini_failure_is_502(env, exc):
    client, services, _ = env

    def boom(img, mime):
        raise exc
    services.extract = boom
    assert_error(client.post("/v1/products/extract", files={"image": ("l.png", png_bytes(), "image/png")}),
                 502, "EXTRACTION_FAILED")


def test_extract_parses_gemini_json_without_inventing():
    class Fake:
        class models:
            @staticmethod
            def generate_content(model, contents, **kw):
                return type("R", (), {"text": '```json\n{"readable": false, "ingredients_text": "Aqua", '
                                              '"confidence_note": "cut off"}\n```'})()
    r = llm_client.extract_ingredients(png_bytes(), client=Fake())
    assert r["readable"] is False and r["ingredients_text"] == "" and r["confidence_note"] == "cut off"


# =====================  /v1/compare  =====================

def test_compare_full_example(env):
    r = env[0].post("/v1/compare", json=compare_body())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert [x["display_name"] for x in body["ranking"]] == ["Serum A", "Serum B", "Serum C"]
    assert body["unresolved"][0]["display_name"] == "Serum D"
    assert body["unresolved"][0]["reason"] == "not_found"
    assert body["summary_source"] == "llm"
    assert body["disclaimer"] == config.DISCLAIMER
    assert body["request_id"].startswith("req_")
    sources = {p["display_name"]: p["ingredient_source"] for p in body["products"]}
    assert sources == {"Serum A": "open_beauty_facts", "Serum B": "pasted_text", "Serum C": "label_photo"}


def test_compare_never_shows_points_or_scores(env):
    text = env[0].post("/v1/compare", json=compare_body()).text.lower()
    for word in ("points", "score", "/100", "sensitivity_rule", "matched_tags"):
        assert word not in text


def test_every_flag_has_reason_and_source(env):
    body = env[0].post("/v1/compare", json=compare_body()).json()
    for p in body["products"]:
        for f in p["flags"]:
            assert f["reason"] and f["source"].startswith("https://") and f["label"]


@pytest.mark.parametrize("change", [
    {"products": [{"display_name": "Only one", "ingredients_text": "Aqua"}]},
    {"products": [{"display_name": f"P{i}", "ingredients_text": "Aqua"} for i in range(5)]},
    {"concerns": []},
    {"concerns": ["acne-prone", "pigmentation", "dullness", "redness"]},
    {"concerns": ["acne-prone", "acne-prone"]},
    {"products": [{"display_name": "Same", "ingredients_text": "Aqua"}, {"display_name": "same", "ingredients_text": "Aqua"}]},
    {"products": [{"display_name": "A"}, {"display_name": "B", "ingredients_text": "Aqua"}]},
    {"products": [{"display_name": "A", "barcode": "12ab"}, {"display_name": "B", "ingredients_text": "Aqua"}]},
    {"profile": {"skin_type": "purple"}},
    {"surprise_field": True},
])
def test_compare_bad_requests_are_422(env, change):
    assert_error(env[0].post("/v1/compare", json=compare_body(**change)), 422, "VALIDATION_ERROR")


def test_compare_unknown_product_type(env):
    assert_error(env[0].post("/v1/compare", json=compare_body(product_type="lipstick")), 422, "UNKNOWN_PRODUCT_TYPE")


@pytest.mark.parametrize("concerns", [["wrinkles"], ["dandruff"]])   # dandruff exists, but not for serums
def test_compare_concern_must_have_rules_for_this_type(env, concerns):
    assert_error(env[0].post("/v1/compare", json=compare_body(concerns=concerns)), 422, "UNKNOWN_CONCERN")


def test_compare_different_product_types_rejected(env):
    body = compare_body(products=[{"display_name": "Serum A", "barcode": "1234567890123"},
                                  {"display_name": "Shampoo X", "barcode": "5555555555555"}])
    r = env[0].post("/v1/compare", json=body)
    assert_error(r, 422, "PRODUCT_TYPE_MISMATCH")
    assert "Shampoo X" in r.json()["error"]["message"]


def test_compare_site_down_marks_product_unresolved(env):
    client, _, obf = env
    obf.down = True
    body = client.post("/v1/compare", json=compare_body()).json()
    reasons = {u["display_name"]: u["reason"] for u in body["unresolved"]}
    assert reasons == {"Serum A": "source_unavailable", "Serum D": "source_unavailable"}
    assert body["status"] == "ok"            # B and C still compared


def test_compare_no_ingredients_listed(env):
    body = compare_body(products=[{"display_name": "Mystery", "barcode": "7777777777777"},
                                  {"display_name": "B", "ingredients_text": "Aqua, Niacinamide"}])
    r = env[0].post("/v1/compare", json=body).json()
    assert r["status"] == "insufficient_data" and r["ranking"] == []
    assert r["unresolved"][0]["reason"] == "no_ingredients_listed"
    assert "Mystery" in r["summary"]


@pytest.mark.parametrize("summarize", [
    None,
    lambda p: (_ for _ in ()).throw(llm_client.LLMBusy("busy")),
    lambda p: (_ for _ in ()).throw(TimeoutError()),
    lambda p: "Serum A is the best choice.",                       # banned word
    lambda p: "Serum A ranked first because it has retinol.",      # ingredient not in the flags
    lambda p: "",                                                  # empty
    lambda p: "Serum A ranked first. " + "word " * 200,            # too long
    lambda p: "Serum B ranked first for you.",                     # names the wrong product as first
])
def test_compare_falls_back_to_template(env, summarize):
    client, services, _ = env
    services.summarize = summarize
    body = client.post("/v1/compare", json=compare_body()).json()
    assert body["summary_source"] == "template"
    assert body["summary"].startswith("Serum A is ranked first")


def test_seed_products_say_where_they_came_from(env):
    client, *_ = env
    db.save_product(db.connect(), "1111111111111", "My Serum", "Me", "Aqua, Niacinamide", "seed")
    body = compare_body(products=[{"display_name": "Mine", "barcode": "1111111111111"},
                                  {"display_name": "Other", "ingredients_text": "Aqua"}])
    r = client.post("/v1/compare", json=body).json()
    assert r["products"][0]["ingredient_source"] == "seed (your own list)"


def test_compare_ties_shown_as_ties(env):
    body = compare_body(products=[{"display_name": "Twin 1", "ingredients_text": "Aqua, Niacinamide"},
                                  {"display_name": "Twin 2", "ingredients_text": "Water, Nicotinamide"}])
    r = env[0].post("/v1/compare", json=body).json()
    assert [(x["rank"], x["tied"]) for x in r["ranking"]] == [(1, True), (1, True)]


# =====================  summary safety check  =====================

def _facts():
    flags = [{"flag_type": "may_suit", "ingredient_family": "niacinamide", "label": "Contains ingredients commonly used for uneven pigmentation",
              "matched_ingredients": ["niacinamide"]}]
    products = [{"display_name": "A", "flags": flags}, {"display_name": "B", "flags": []}]
    ranking = [{"rank": 1, "display_name": "A", "tied": False}, {"rank": 2, "display_name": "B", "tied": False}]
    return summary.build_facts("Serum", ["uneven pigmentation"], ranking, products, [{"display_name": "C"}])


def test_check_summary_allows_honest_text():
    assert summary.check_summary("A ranked first. It contains niacinamide, commonly used for uneven pigmentation.",
                                 _facts(), DATA) == []


@pytest.mark.parametrize("text, problem", [
    ("A ranked first and has vitamin C.", "not in the flags"),
    ("A is good.", "banned word"),
    ("A gets a score of 80 out of 100.", "banned word"),
    ("B ranked first.", "does not name"),
])
def test_check_summary_rejects(text, problem):
    assert any(problem in p for p in summary.check_summary(text, _facts(), DATA))


def test_template_always_passes_its_own_check(env):
    client, services, _ = env
    services.summarize = None
    for body in (compare_body(), compare_body(concerns=["dryness"]), compare_body(concerns=["redness"])):
        r = client.post("/v1/compare", json=body).json()
        facts = summary.build_facts("Serum", r["concerns"], r["ranking"],
                                    [{"display_name": p["display_name"], "flags": p["flags"]} for p in r["products"]],
                                    r["unresolved"])
        assert summary.check_summary(r["summary"], facts, DATA) == [], r["summary"]


# =====================  errors and logging  =====================

def test_unexpected_crash_gives_safe_502(env):
    client, services, _ = env

    class Broken:
        def evaluate(self, *a, **k):
            raise ZeroDivisionError("secret internal detail")
    services.engine = Broken()
    r = client.post("/v1/compare", json=compare_body())
    assert_error(r, 502, "INTERNAL_ERROR")
    assert "secret internal detail" not in r.text and "ZeroDivisionError" not in r.text


def test_unknown_address_is_404_in_our_shape(env):
    r = env[0].get("/v1/nothing-here")
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"


def test_request_log_saves_counts_not_personal_data(env):
    client, *_ = env
    client.post("/v1/compare", json=compare_body())
    client.get("/v1/products/lookup", params={"barcode": "9999999999999"})
    rows = [dict(r) for r in db.connect().execute("SELECT * FROM request_log ORDER BY timestamp")]
    assert len(rows) == 2
    compare_row = next(r for r in rows if r["endpoint"] == "/v1/compare")
    assert compare_row["status_code"] == 200 and compare_row["n_products"] == 4
    assert compare_row["n_unresolved"] == 1 and compare_row["summary_source"] == "llm"
    lookup_row = next(r for r in rows if r["endpoint"] == "/v1/products/lookup")
    assert lookup_row["status_code"] == 404 and lookup_row["error_code"] == "PRODUCT_NOT_FOUND"
    everything = json.dumps(rows).lower()
    assert "niacinamide" not in everything and "oily" not in everything and "acne" not in everything


# =====================  live check (your computer only)  =====================

@pytest.mark.live
def test_live_name_search_works():
    from app.services.obf_client import search_products
    r = search_products("shampoo", limit=3)
    if r["status"] == "error":
        pytest.skip("Open Beauty Facts could not be reached from this computer")
    assert isinstance(r["results"], list)
