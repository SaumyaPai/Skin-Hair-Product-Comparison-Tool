"""Phase 1 tests. Run from the project folder:  pytest -v

Offline tests always run and use fake stand-ins, so they cost no quota.
Live tests (marked `live`) call the real Gemini and Open Beauty Facts,
and skip themselves with a clear reason if a key or barcodes are missing.
"""
import httpx
import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.services import llm_client, obf_client
from scripts import check_obf


# ---------- 1. The API answers /health ----------

def test_health_says_ok():
    resp = TestClient(app).get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "llm_configured" in body


def test_health_never_shows_the_key():
    body = TestClient(app).get("/health").text
    if config.GEMINI_API_KEY:
        assert config.GEMINI_API_KEY not in body


# ---------- 2. The Gemini client (with a fake Gemini) ----------

class FakeGemini:
    def __init__(self, text):
        self._text = text
        outer = self

        class Models:
            def generate_content(self, model, contents):
                outer.last_prompt = contents
                return type("R", (), {"text": outer._text})()

        self.models = Models()


def test_gemini_client_returns_reply_text():
    assert llm_client.ask("hi", client=FakeGemini("  Gemini is connected.  ")) == "Gemini is connected."


def test_gemini_client_rejects_empty_reply():
    with pytest.raises(RuntimeError):
        llm_client.ask("hi", client=FakeGemini(""))


def test_gemini_client_explains_missing_key(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    with pytest.raises(llm_client.LLMNotConfigured):
        llm_client.ask("hi")


# ---------- 3. The Open Beauty Facts client (with a fake website) ----------

def fake_obf(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_obf_found_with_ingredients():
    def handler(request):
        assert "/api/v2/product/1234567890123.json" in str(request.url)
        return httpx.Response(200, json={"status": 1, "product": {
            "product_name": "Test Wash", "brands": "TestBrand", "ingredients_text": "Aqua, Glycerin"}})
    r = obf_client.get_product("1234567890123", client=fake_obf(handler))
    assert r["status"] == "found"
    assert r["ingredients_text"] == "Aqua, Glycerin"
    assert r["product_name"] == "Test Wash"


def test_obf_found_but_no_ingredients_is_not_guessed():
    handler = lambda req: httpx.Response(200, json={"status": 1, "product": {"product_name": "Mystery"}})
    r = obf_client.get_product("1234567890123", client=fake_obf(handler))
    assert r["status"] == "no_ingredients"
    assert r["ingredients_text"] == ""


def test_obf_not_found():
    handler = lambda req: httpx.Response(404, json={"status": 0})
    assert obf_client.get_product("1234567890123", client=fake_obf(handler))["status"] == "not_found"


def test_obf_site_down_is_reported_not_crashed():
    def handler(request):
        raise httpx.ConnectError("down")
    assert obf_client.get_product("1234567890123", client=fake_obf(handler))["status"] == "error"


@pytest.mark.parametrize("bad", ["", "abc", "123", "12345678901234567", "12345 678"])
def test_obf_rejects_bad_barcodes(bad):
    assert obf_client.get_product(bad)["status"] == "invalid_barcode"


# ---------- 4. The 10-product check script ----------

def test_check_script_skips_placeholder_rows(tmp_path):
    f = tmp_path / "p.csv"
    f.write_text("barcode,my_name\nREPLACE_ME,a\n,b\n1234567890123,c\n")
    assert [p["my_name"] for p in check_obf.read_products(f)] == ["c"]


def test_check_script_counts_and_flags_low_coverage(tmp_path):
    statuses = ["found", "found", "found", "no_ingredients", "not_found",
                "not_found", "not_found", "error", "found", "not_found"]
    products = [{"barcode": str(10000000 + i), "my_name": f"p{i}"} for i in range(10)]
    fake_lookup = lambda bc: {"barcode": bc, "status": statuses[int(bc) - 10000000],
                              "product_name": "", "brand": "", "ingredients_text": "", "message": ""}
    results = check_obf.run(products, lookup=fake_lookup, pause=0)
    s = check_obf.summarize(results)
    assert s["total"] == 10 and s["found"] == 4 and s["not_found"] == 4
    assert s["low_coverage"] is False          # 4 of 10 is right at the line
    out = tmp_path / "out.csv"
    check_obf.save(results, out)
    assert out.read_text().count("\n") == 11   # header + 10 rows


# ---------- 5. Live checks (real services) ----------

@pytest.mark.live
def test_live_gemini_answers():
    if not config.GEMINI_API_KEY:
        pytest.skip("No GEMINI_API_KEY in .env yet")
    try:
        reply = llm_client.ask("Reply with exactly: Gemini is connected.")
    except llm_client.LLMBusy:
        pytest.skip("Gemini is busy (error 503, Google's side). Rerun later; this doesn't block the phase.")
    assert "connected" in reply.lower()


@pytest.mark.live
def test_live_obf_lookup_of_my_products():
    products = check_obf.read_products(check_obf.INPUT)
    if not products:
        pytest.skip("No barcodes in data/my_products.csv yet")
    results = check_obf.run(products)
    if all(r["status"] == "error" for r in results):
        pytest.skip("Open Beauty Facts could not be reached from this computer")
    assert all(r["status"] != "invalid_barcode" for r in results), "Fix the barcodes marked invalid_barcode"
    check_obf.save(results, check_obf.OUTPUT)
