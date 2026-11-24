"""Phase 5 tests: the Streamlit page. These drive the real page without a browser,
connected to the real API with fake outside services (no internet, no quota).
Run from the project folder:  python -m pytest -v
"""
import re
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from app import config
from app.data_loader import load_all
from app.deps import build_services, get_services
from app.main import app
from ui import api_client
from ui.logic import build_request, problems, product_payload

ROOT = Path(__file__).resolve().parent.parent
PAGE = str(ROOT / "ui" / "streamlit_app.py")
DATA = load_all()
FOUND = {"status": "found", "barcode": "1234567890123", "product_name": "Glow Serum", "brand": "BrandA",
         "ingredients_text": "Aqua, Niacinamide, Glycerin", "category_tags": ["en:serums"], "message": ""}


def fake_lookup(barcode):
    if barcode == FOUND["barcode"]:
        return dict(FOUND)
    return {"status": "not_found", "barcode": barcode, "product_name": "", "brand": "", "ingredients_text": "",
            "category_tags": [], "message": ""}


def fake_search(q):
    hits = [FOUND] if "glow" in q.lower() else []
    return {"status": "ok", "results": [{k: p[k] for k in ("barcode", "product_name", "brand", "ingredients_text",
                                                          "category_tags")} for p in hits]}


@pytest.fixture
def page(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "ui.db")
    services = build_services(DATA, obf_lookup=fake_lookup, obf_search=fake_search,
                              extract=[("fake", lambda img, mime: {"readable": True, "ingredients_text": "Aqua, Glycerin",
                                                                   "confidence_note": ""})],
                              summarize=[])
    app.dependency_overrides[get_services] = lambda: services
    monkeypatch.setattr(api_client, "make_client", lambda: api_client.ApiClient(http=TestClient(app)))
    at = AppTest.from_file(PAGE, default_timeout=30).run()
    assert not at.exception
    yield at
    app.dependency_overrides.clear()


def pids(at):
    return [p["id"] for p in at.session_state["products"]]


def start(at, ptype="serum", concerns=("pigmentation",)):
    at.selectbox(key="ptype").select(ptype).run()
    ms = at.multiselect(key=f"concerns_{ptype}")
    for c in concerns:
        ms.select(c)
    at.run()
    return at


def fill_paste(at, texts):
    ids = pids(at)
    for pid in ids:
        at.radio(key=f"method_{pid}").set_value("Paste ingredients")       # names default to Product 1, 2...
    at.run()
    for pid, text in zip(ids, texts):
        at.text_area(key=f"pasted_{pid}").input(text)
    return at.run()


def all_text(at) -> str:
    parts = [e.value for kind in ("markdown", "caption", "info", "warning", "error", "success", "title",
                                  "header", "subheader") for e in getattr(at, kind)]
    return "\n".join(str(p) for p in parts)


# =====================  1. dropdowns come from the API  =====================

def test_page_loads_without_errors(page):
    assert "Compare skincare and haircare products" in all_text(page)
    assert "not medical advice" in all_text(page)          # disclaimer shown from the start


def test_product_types_match_the_api(page):
    opts = TestClient(app).get("/v1/meta/options").json()
    assert page.selectbox(key="ptype").options == [t["label"] for t in opts["product_types"]]


@pytest.mark.parametrize("ptype", ["serum", "shampoo", "lip_balm"])
def test_concerns_change_with_type_and_match_api(page, ptype):
    opts = {t["id"]: t for t in TestClient(app).get("/v1/meta/options").json()["product_types"]}
    page.selectbox(key="ptype").select(ptype).run()
    shown = page.multiselect(key=f"concerns_{ptype}").options
    assert shown == [c["label"] for c in opts[ptype]["concerns"]]


def test_hair_type_asks_about_scalp_not_skin(page):
    start(page, "shampoo", ["dandruff"])
    keys = [s.key for s in page.selectbox]
    assert "scalp_type" in keys and "skin_type" not in keys


def test_at_most_three_concerns(page):
    page.selectbox(key="ptype").select("serum").run()
    ms = page.multiselect(key="concerns_serum")
    assert ms.max_selections == 3


# =====================  2. Compare stays off until ready  =====================

def test_compare_disabled_without_concerns(page):
    page.selectbox(key="ptype").select("serum").run()
    fill_paste(page, ["Aqua", "Aqua, Glycerin"])
    assert page.button(key="compare").disabled
    assert "Choose at least one concern" in all_text(page)


def test_compare_disabled_until_both_products_filled(page):
    start(page)
    fill_paste(page, ["Aqua, Niacinamide", ""])
    assert page.button(key="compare").disabled
    assert "paste its ingredient list" in all_text(page)


def test_add_and_remove_products_between_2_and_4(page):
    start(page)
    assert len(pids(page)) == 2 and not [b for b in page.button if b.key.startswith("remove_")]
    page.button(key="add_product").click().run()
    page.button(key="add_product").click().run()
    assert len(pids(page)) == 4
    assert "add_product" not in [b.key for b in page.button]   # can't add a 5th
    page.button(key=f"remove_{pids(page)[0]}").click().run()
    assert len(pids(page)) == 3


# =====================  3. all four ways to add a product  =====================

def test_full_flow_with_all_four_methods(page):
    start(page, concerns=["pigmentation"])
    page.button(key="add_product").click().run()
    page.button(key="add_product").click().run()
    a, b, c, d = pids(page)
    for pid, method in [(a, "Barcode"), (b, "Search by name"), (c, "Paste ingredients"), (d, "Label photo")]:
        page.radio(key=f"method_{pid}").set_value(method)
    page.run()
    # there is no name box at all: real product names, or Product 1, 2...
    assert not [t for t in page.text_input if (t.key or "").startswith("name_")]
    # barcode, with the optional check
    page.text_input(key=f"barcode_{a}").input(FOUND["barcode"]).run()    # Enter looks it up; no button
    assert "Found BrandA Glow Serum" in all_text(page)
    # search and pick
    page.text_input(key=f"query_{b}").input("glow").run()          # Enter searches; there is no button
    assert not [x for x in page.button if (x.key or "").startswith(("searchbtn_", "read_", "check_"))]
    page.selectbox(key=f"picked_{b}").select(FOUND["barcode"]).run()
    # paste
    page.text_area(key=f"pasted_{c}").input("Aqua, Parfum, Kojic Acid").run()
    # photo: the upload itself needs a browser, so we put the text the photo reader returned in place
    page.session_state[f"extracted_{d}"] = "Aqua, Glycerin"
    page.run()
    assert page.text_area(key=f"extracted_{d}").value == "Aqua, Glycerin"   # shown and editable
    assert not page.button(key="compare").disabled
    page.button(key="compare").click().run()
    assert not page.exception
    result = page.session_state["result"]
    assert len(result["ranking"]) == 4
    sources = {p["display_name"]: p["ingredient_source"] for p in result["products"]}
    assert sources["Product 3"] == "pasted_text" and sources["Product 4"] == "label_photo"
    assert sources["BrandA Glow Serum"].startswith("open_beauty_facts")
    assert sources["BrandA Glow Serum (2)"].startswith("open_beauty_facts")      # same product twice: told apart


def test_photo_reading_goes_through_the_api(tmp_path, monkeypatch):
    """The page's photo button calls this; check it reaches the API and comes back."""
    import io

    from PIL import Image
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "p.db")
    services = build_services(DATA, extract=[("fake", lambda img, mime: {"readable": True, "ingredients_text": "Aqua",
                                                                         "confidence_note": ""})], summarize=[])
    app.dependency_overrides[get_services] = lambda: services
    try:
        buf = io.BytesIO()
        Image.new("RGB", (200, 100), "white").save(buf, format="PNG")
        r = api_client.ApiClient(http=TestClient(app)).extract(buf.getvalue(), "l.png", "image/png")
        assert r["ingredients_text"] == "Aqua" and r["reader"] == "fake"
    finally:
        app.dependency_overrides.clear()


# =====================  4. results  =====================

def compared(page, texts=("Aqua, Niacinamide", "Aqua, Parfum"), sensitive=True):
    start(page)
    if sensitive:
        page.checkbox(key="sensitive").check().run()
    fill_paste(page, list(texts))
    page.button(key="compare").click().run()
    assert not page.exception
    return page


def test_results_show_ranking_flags_sources_summary_disclaimer(page):
    at = compared(page)
    text = all_text(at)
    assert at.caption[-1].value == config.DISCLAIMER          # disclaimer is the last thing on the page
    assert '<span class="num">1</span><span class="name">Product 1</span>' in text
    assert '<span class="num">2</span><span class="name">Product 2</span>' in text
    assert "✓ May suit" in text and "! May not suit" in text          # text labels, not colour alone
    assert text.count('href="https://') >= 2
    assert "Product 1 is ranked first" in text
    visible = re.sub(r"<[^>]+>", " ", re.sub(r"<style>.*?</style>", " ", text, flags=re.DOTALL)).lower()
    for system_word in ("our table", "not in our tables", "flag", "rule", "ingredient group"):
        assert system_word not in visible                       # shopper words only


def test_ties_are_labelled(page):
    text = all_text(compared(page, ("Aqua, Niacinamide", "Water, Nicotinamide"), sensitive=False))
    assert text.count('<span class="tag">tied</span>') == 2


def test_unresolved_product_explained(page):
    start(page)
    a, b = pids(page)
    page.radio(key=f"method_{b}").set_value("Paste ingredients").run()
    page.text_input(key=f"barcode_{a}").input("9999999999999")
    page.text_area(key=f"pasted_{b}").input("Aqua, Niacinamide").run()
    page.button(key="compare").click().run()
    text = all_text(page)
    assert "Not in the product database" in text
    assert "need ingredients for at least 2 products" in text


def test_no_good_bad_scores_or_cures_anywhere(page):
    text = re.sub(r"<[^>]+>", " ", all_text(compared(page))).lower()     # visible words only
    for word in ["good", "bad", "best", "worst", "score", "/100", "cure", "treat", "heal", "guarantee"]:
        assert not re.search(rf"\b{re.escape(word)}\b", text), word


def test_api_error_message_is_shown_plainly(page, monkeypatch):
    start(page)
    fill_paste(page, ["Aqua", "Aqua"])
    monkeypatch.setattr(config, "DB_PATH", "/this/folder/does/not/exist/x.db")   # force a server-side failure
    page.button(key="compare").click().run()
    text = all_text(page)
    assert not page.exception
    assert "Traceback" not in text


# =====================  5. API not running  =====================

def test_friendly_message_when_api_is_off(monkeypatch):
    def refuse(request):
        raise httpx.ConnectError("refused")
    monkeypatch.setattr(api_client, "make_client",
                        lambda: api_client.ApiClient(http=httpx.Client(transport=httpx.MockTransport(refuse),
                                                                       base_url="http://x")))
    at = AppTest.from_file(PAGE, default_timeout=30).run()
    assert not at.exception
    assert "isn't running" in all_text(at) and "python -m scripts.run_app" in all_text(at)


# =====================  6. small pieces  =====================

def test_product_payload_per_method():
    assert product_payload({"method": "Barcode", "barcode": " 1234 5678 "}, 1) == \
        {"display_name": "Product 1", "barcode": "12345678"}
    assert product_payload({"method": "Barcode", "barcode": "12345678", "found_name": "Moxie Shampoo",
                            "found_barcode": "12345678"}, 1)["display_name"] == "Moxie Shampoo"
    assert product_payload({"method": "Barcode", "barcode": "87654321", "found_name": "Moxie Shampoo",
                            "found_barcode": "12345678"}, 2)["display_name"] == "Product 2"   # barcode changed since
    assert product_payload({"method": "Search by name", "picked_barcode": None}) is None
    assert product_payload({"method": "Search by name", "picked_barcode": "1", "picked_name": "Moxie Shampoo"}) == \
        {"display_name": "Moxie Shampoo", "barcode": "1"}
    assert product_payload({"method": "Paste ingredients", "pasted": " Aqua "}, 2) == \
        {"display_name": "Product 2", "ingredients_text": "Aqua"}
    assert product_payload({"name": " ", "method": "Label photo", "extracted": "Aqua"}, 3) == \
        {"display_name": "Product 3", "extracted_text": "Aqua"}


def test_problems_lists_everything_missing():
    out = problems(None, [], [{"name": "", "method": "Barcode"}])
    assert "Choose a product type." in out and "Choose at least one concern." in out
    assert "Add at least 2 products." in out and "Product 1: type its barcode." in out
    assert not any("name" in o for o in out)                         # a name is never required now


def test_same_names_are_told_apart_automatically():
    ps = [{"method": "Search by name", "picked_barcode": "1", "picked_name": "Same"},
          {"method": "Search by name", "picked_barcode": "2", "picked_name": "same"}]
    assert problems("serum", ["dryness"], ps) == []
    body = build_request("serum", ["dryness"], {}, ps)
    assert [p["display_name"] for p in body["products"]] == ["Same", "same (2)"]


def test_build_request_drops_empty_profile_fields():
    body = build_request("serum", ["dryness"], {"skin_type": None, "sensitive": True},
                         [{"name": "A", "method": "Paste ingredients", "pasted": "Aqua"}])
    assert body["profile"] == {"sensitive": True}


def test_api_client_turns_errors_into_plain_messages():
    def handler(request):
        return httpx.Response(422, json={"error": {"code": "UNKNOWN_CONCERN", "message": "Plain words."}})
    c = api_client.ApiClient(http=httpx.Client(transport=httpx.MockTransport(handler), base_url="http://x"))
    with pytest.raises(api_client.ApiProblem) as e:
        c.compare({})
    assert e.value.message == "Plain words." and e.value.code == "UNKNOWN_CONCERN"


def test_page_never_calls_outside_services_directly():
    src = open(PAGE, encoding="utf-8").read() + open(ROOT / "ui" / "api_client.py", encoding="utf-8").read()
    for forbidden in ("openbeautyfacts.org", "import google", "genai", "api.groq.com", "from app", "import app"):
        assert forbidden not in src.lower(), forbidden


# =====================  7. look and feel  =====================

def test_theme_colours_are_set():
    import tomllib
    theme = tomllib.loads((ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8"))["theme"]
    assert theme["backgroundColor"] == "#F8ECEA" and theme["headingFont"] == "serif"
    assert theme["buttonRadius"] == "full"


def _contrast(a: str, b: str) -> float:
    def lum(h):
        c = [int(h.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4)]
        c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
    la, lb = lum(a), lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


@pytest.mark.parametrize("text, background", [
    ("#2A2321", "#F8ECEA"), ("#2A2321", "#F1DAD8"), ("#2A2321", "#EBCFCD"),   # charcoal on blush and roses
    ("#6B5753", "#E3EEDF"), ("#6B5753", "#FBE3CF"), ("#6B5753", "#EBCFCD"),   # muted text on flag cards
    ("#8F4310", "#F8ECEA"), ("#8F4310", "#FFFFFF"), ("#2F5D3A", "#FFFFFF"),   # links and pill labels
    ("#FFFFFF", "#1E1A19"),                                                   # button text
])
def test_text_colours_are_readable(text, background):
    assert _contrast(text, background) >= 4.5


def test_product_names_are_escaped(page):
    start(page)
    a, b = pids(page)
    page.radio(key=f"method_{b}").set_value("Paste ingredients").run()
    # a product name from the database could contain anything; pretend the barcode check found this one
    page.session_state[f"barcode_{a}"] = FOUND["barcode"]
    page.session_state[f"found_barcode_{a}"] = FOUND["barcode"]
    page.session_state[f"found_name_{a}"] = "<b>Bold</b>"
    page.run()
    page.text_area(key=f"pasted_{b}").input("Aqua").run()
    page.button(key="compare").click().run()
    assert "&lt;b&gt;Bold&lt;/b&gt;" in all_text(page)       # escaped wherever the page writes its own HTML
