"""Phase 4 add-on tests: the backup AI chain, Groq, and offline photo reading.
No internet or keys needed. Run from the project folder:  python -m pytest -v
"""
import io
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont

from app import config
from app.data_loader import load_all
from app.deps import build_services, get_services
from app.main import app
from app.services import llm_client, ocr, summary

DATA = load_all()


def busy(*a, **k):
    raise llm_client.LLMBusy("503")


def valid_summary(prompt):
    facts = json.loads(prompt.split("FACTS:\n", 1)[1])
    return f"{facts['products'][0]['name']} is ranked first for your concerns."


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    services = build_services(DATA, obf_lookup=lambda b: {"status": "not_found", "barcode": b},
                              obf_search=lambda q: {"status": "ok", "results": []},
                              extract=[], summarize=[])
    app.dependency_overrides[get_services] = lambda: services
    yield TestClient(app, raise_server_exceptions=False), services
    app.dependency_overrides.clear()


BODY = {"product_type": "serum", "concerns": ["pigmentation"], "profile": {"sensitive": True},
        "products": [{"display_name": "Serum A", "ingredients_text": "Aqua, Niacinamide"},
                     {"display_name": "Serum B", "ingredients_text": "Aqua, Parfum"}]}


# =====================  summary backup chain  =====================

def test_busy_main_model_moves_to_next(env):
    client, s = env
    s.summarize = [("gemini:main", busy), ("gemini:lite", valid_summary)]
    r = client.post("/v1/compare", json=BODY).json()
    assert r["summary_source"] == "llm" and r["summary_provider"] == "gemini:lite"


def test_every_provider_reply_is_checked(env):
    client, s = env
    s.summarize = [("gemini:main", lambda p: "Serum A is the best."),           # banned word
                   ("gemini:lite", lambda p: "Serum A ranked first; it has retinol."),  # not in flags
                   ("groq:x", valid_summary)]
    r = client.post("/v1/compare", json=BODY).json()
    assert r["summary_provider"] == "groq:x"


def test_all_providers_fail_uses_template(env):
    client, s = env
    s.summarize = [("gemini:main", busy), ("gemini:lite", busy), ("groq:x", lambda p: "Serum A is bad.")]
    r = client.post("/v1/compare", json=BODY).json()
    assert r["summary_source"] == "template" and r["summary_provider"] == "template"
    assert r["summary"].startswith("Serum A is ranked first")


def test_no_providers_uses_template(env):
    client, s = env
    s.summarize = []
    assert client.post("/v1/compare", json=BODY).json()["summary_source"] == "template"


def test_chain_order_groq_first_by_default(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "x")
    monkeypatch.setattr(config, "GROQ_API_KEY", "y")
    monkeypatch.setattr(config, "AI_FIRST", "groq")
    monkeypatch.setattr(config, "GEMINI_MODEL", "main-model")
    monkeypatch.setattr(config, "GEMINI_FALLBACK_MODELS", ["lite-model", "main-model"])
    assert [n for n, _ in llm_client.summary_providers()] == [f"groq:{config.GROQ_MODEL}", "gemini:main-model",
                                                               "gemini:lite-model"]
    assert [n for n, _ in llm_client.extract_providers()] == [f"groq:{config.GROQ_VISION_MODEL}", "gemini:main-model",
                                                               "gemini:lite-model", "offline_ocr"]


def test_chain_order_gemini_first_if_chosen(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "x")
    monkeypatch.setattr(config, "GROQ_API_KEY", "y")
    monkeypatch.setattr(config, "AI_FIRST", "gemini")
    monkeypatch.setattr(config, "GEMINI_FALLBACK_MODELS", [])
    assert [n for n, _ in llm_client.summary_providers()][-1].startswith("groq:")


def test_chain_skips_providers_without_keys(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    monkeypatch.setattr(config, "GROQ_API_KEY", "")
    assert llm_client.summary_providers() == []
    assert [n for n, _ in llm_client.extract_providers()] == ["offline_ocr"]


# =====================  photo backup chain  =====================

def png():
    buf = io.BytesIO()
    Image.new("RGB", (300, 200), "white").save(buf, format="PNG")
    return buf.getvalue()


def test_photo_falls_back_to_offline_reader(env):
    client, s = env
    s.extract = [("gemini:main", busy), ("gemini:lite", busy),
                 ("offline_ocr", lambda img, mime: {"readable": True, "ingredients_text": "Aqua, Glycerin, Niacinamide",
                                                    "confidence_note": "offline"})]
    r = client.post("/v1/products/extract", files={"image": ("l.png", png(), "image/png")})
    assert r.status_code == 200 and r.json()["reader"] == "offline_ocr"


def test_unreadable_answer_tries_the_next_reader(env):
    # Changed in 0.5.1: one AI saying "unreadable" no longer stops the others from trying.
    client, s = env
    s.extract = [("gemini:main", lambda img, mime: {"readable": False, "ingredients_text": "", "confidence_note": "blurry"}),
                 ("offline_ocr", lambda img, mime: {"readable": True, "ingredients_text": "Aqua, Glycerin, Niacinamide",
                                                    "confidence_note": "offline"})]
    r = client.post("/v1/products/extract", files={"image": ("l.png", png(), "image/png")}).json()
    assert r["readable"] is True and r["reader"] == "offline_ocr"


def test_every_reader_unreadable_is_reported_honestly(env):
    client, s = env
    no = lambda img, mime: {"readable": False, "ingredients_text": "", "confidence_note": "blurry"}
    s.extract = [("gemini:main", no), ("offline_ocr", no)]
    r = client.post("/v1/products/extract", files={"image": ("l.png", png(), "image/png")}).json()
    assert r["readable"] is False and r["ingredients_text"] == ""


def test_photo_all_readers_fail_is_502(env):
    client, s = env
    s.extract = [("gemini:main", busy), ("offline_ocr", lambda img, mime: (_ for _ in ()).throw(ocr.OCRUnavailable()))]
    r = client.post("/v1/products/extract", files={"image": ("l.png", png(), "image/png")})
    assert r.status_code == 502 and r.json()["error"]["code"] == "EXTRACTION_FAILED"


# =====================  Groq  =====================

def groq_http(status=200, content="ok", seen=None):
    def handler(request):
        if seen is not None:
            seen["auth"] = request.headers.get("authorization")
            seen["body"] = json.loads(request.content)
        if status != 200:
            return httpx.Response(status, json={"error": {"message": "busy"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_groq_summary(monkeypatch):
    monkeypatch.setattr(config, "GROQ_API_KEY", "k")
    seen = {}
    out = llm_client.groq_write_summary("hi", http=groq_http(content="<think>hmm</think> Serum A ranked first.", seen=seen))
    assert out == "Serum A ranked first."
    assert seen["auth"] == "Bearer k" and seen["body"]["model"] == config.GROQ_MODEL


@pytest.mark.parametrize("status", [429, 503])
def test_groq_busy(monkeypatch, status):
    monkeypatch.setattr(config, "GROQ_API_KEY", "k")
    with pytest.raises(llm_client.LLMBusy):
        llm_client.groq_write_summary("hi", http=groq_http(status=status))


def test_groq_photo_sends_image_and_asks_for_json(monkeypatch):
    monkeypatch.setattr(config, "GROQ_API_KEY", "k")
    seen = {}
    r = llm_client.groq_extract_ingredients(png(), http=groq_http(
        content='{"readable": true, "ingredients_text": "Aqua", "confidence_note": ""}', seen=seen))
    assert r["ingredients_text"] == "Aqua"
    parts = seen["body"]["messages"][0]["content"]
    assert parts[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert seen["body"]["response_format"] == {"type": "json_object"}
    assert seen["body"]["model"] == config.GROQ_VISION_MODEL


def test_groq_without_key_is_skipped(monkeypatch):
    monkeypatch.setattr(config, "GROQ_API_KEY", "")
    with pytest.raises(llm_client.LLMNotConfigured):
        llm_client.groq_write_summary("hi")


# =====================  offline reader (Tesseract)  =====================

LABEL = """NOURISHING BODY LOTION
For dry skin. Net Vol. 200 ml
INGREDIENTS: Aqua, Glycerin, Cetearyl Alcohol, Petro-
latum, Niacinamide, Parfum.
Directions: apply daily.
Mfd. by Example Ltd."""


def test_ingredient_section_keeps_only_the_list():
    assert ocr.ingredient_section(LABEL) == "Aqua, Glycerin, Cetearyl Alcohol, Petrolatum, Niacinamide, Parfum"


def test_ingredient_section_without_the_word_ingredients():
    assert ocr.ingredient_section("Aqua, Glycerin") == ""


def test_read_ingredients_with_fake_tesseract():
    class FakeTess:
        @staticmethod
        def image_to_string(img, lang="eng"):
            return LABEL
    r = ocr.read_ingredients(png(), tesseract=FakeTess)
    assert r["readable"] is True and r["ingredients_text"].startswith("Aqua, Glycerin")
    assert "check" in r["confidence_note"]


def test_read_ingredients_unreadable_is_honest():
    class FakeTess:
        @staticmethod
        def image_to_string(img, lang="eng"):
            return "blurry nonsense"
    r = ocr.read_ingredients(png(), tesseract=FakeTess)
    assert r == {"readable": False, "ingredients_text": "", "confidence_note": r["confidence_note"]}


@pytest.mark.live
def test_live_tesseract_reads_a_printed_label():
    if not ocr.is_available():
        pytest.skip("Tesseract isn't installed on this computer (see PHASE4_ADDON_GUIDE.md)")
    img = Image.new("RGB", (1400, 260), "white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=44)
    draw.text((30, 40), "Ingredients: Aqua, Glycerin, Niacinamide,", fill="black", font=font)
    draw.text((30, 120), "Sodium Hyaluronate, Phenoxyethanol.", fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    r = ocr.read_ingredients(buf.getvalue())
    assert r["readable"] is True
    text = r["ingredients_text"].lower()
    assert "glycerin" in text and "niacinamide" in text


# =====================  list_models helper  =====================

def test_list_models_reads_googles_answer(monkeypatch):
    from scripts import list_models
    monkeypatch.setattr(config, "GEMINI_API_KEY", "secret-key")

    def handler(request):
        assert request.headers["x-goog-api-key"] == "secret-key"
        assert "secret-key" not in str(request.url)          # key never goes in the address
        return httpx.Response(200, json={"models": [
            {"name": "models/gemini-3.8-flash", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-3.5-flash-lite", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/text-embedding-004", "supportedGenerationMethods": ["embedContent"]}]})
    names = list_models.gemini_flash_models(http=httpx.Client(transport=httpx.MockTransport(handler)))
    assert names == ["gemini-3.5-flash-lite", "gemini-3.8-flash"]


def test_list_models_explains_errors_without_the_key(monkeypatch):
    from scripts import list_models
    monkeypatch.setattr(config, "GEMINI_API_KEY", "secret-key")
    handler = lambda req: httpx.Response(400, json={"error": {"message": "API key not valid."}})
    with pytest.raises(httpx.HTTPStatusError) as e:
        list_models.gemini_flash_models(http=httpx.Client(transport=httpx.MockTransport(handler)))
    reason = list_models.short_reason(e.value)
    assert reason == "error 400: API key not valid." and "secret-key" not in reason
    assert "secret-key" not in list_models.short_reason(RuntimeError("bad secret-key here"))


# =====================  timeouts (Gemini refuses anything under 10 seconds)  =====================

@pytest.fixture
def captured_clients(monkeypatch):
    from google import genai
    seen = []

    class FakeClient:
        def __init__(self, api_key, http_options):
            seen.append(http_options.timeout)

            class models:
                @staticmethod
                def generate_content(**kw):
                    return type("R", (), {"text": '{"readable": true, "ingredients_text": "Aqua", "confidence_note": ""}'})()
            self.models = models
    monkeypatch.setattr(genai, "Client", FakeClient)
    monkeypatch.setattr(config, "GEMINI_API_KEY", "k")
    return seen


def test_summary_timeout_is_at_least_10_seconds(captured_clients):
    llm_client.write_summary("hi")
    assert captured_clients[-1] >= 10_000


def test_photo_timeout_is_longer(captured_clients):
    llm_client.extract_ingredients(png(), "image/jpeg")
    assert captured_clients[-1] == config.LLM_PHOTO_TIMEOUT_SECONDS * 1000 >= 10_000


def test_timeout_never_below_googles_minimum(captured_clients, monkeypatch):
    monkeypatch.setattr(config, "LLM_TIMEOUT_SECONDS", 3)
    llm_client.write_summary("hi")
    assert captured_clients[-1] == 10_000


def test_setting_error_moves_on_and_is_logged(env, caplog):
    client, s = env

    def bad_setting(prompt):
        raise RuntimeError("400 INVALID_ARGUMENT. Manually set deadline 8s is too short.")
    s.summarize = [("gemini:main", bad_setting), ("groq:x", valid_summary)]
    with caplog.at_level("WARNING", logger="skincare"):
        r = client.post("/v1/compare", json=BODY).json()
    assert r["summary_provider"] == "groq:x"
    assert "gemini:main skipped" in caplog.text and "deadline 8s is too short" in caplog.text


def test_photo_skip_is_logged(env, caplog):
    client, s = env
    s.extract = [("gemini:main", busy), ("offline_ocr", lambda img, mime: {"readable": True, "ingredients_text": "Aqua",
                                                                          "confidence_note": ""})]
    with caplog.at_level("WARNING", logger="skincare"):
        client.post("/v1/products/extract", files={"image": ("l.png", png(), "image/png")})
    assert "Photo: gemini:main failed after" in caplog.text


# =====================  cooldown  =====================

def test_busy_model_is_skipped_on_the_next_request(env):
    client, s = env
    calls = []

    def busy_once(prompt):
        calls.append(1)
        raise llm_client.LLMBusy("503")
    s.summarize = [("gemini:main", busy_once), ("groq:x", valid_summary)]
    client.post("/v1/compare", json=BODY)
    r = client.post("/v1/compare", json=BODY).json()
    assert len(calls) == 1                      # not tried again while cooling down
    assert r["summary_provider"] == "groq:x"


def test_cooldown_ends_after_the_wait(monkeypatch):
    monkeypatch.setattr(config, "AI_COOLDOWN_SECONDS", 300)
    llm_client.note_failure("gemini:main", llm_client.LLMBusy("503"), now=1000)
    assert llm_client.cooling_down("gemini:main", now=1299)
    assert not llm_client.cooling_down("gemini:main", now=1301)


@pytest.mark.parametrize("exc", [TimeoutError(), httpx.ReadTimeout("slow"), RuntimeError("504 DEADLINE_EXCEEDED")])
def test_slow_models_cool_down_too(exc):
    llm_client.note_failure("gemini:main", exc)
    assert llm_client.cooling_down("gemini:main")


def test_setting_errors_do_not_cool_down():
    llm_client.note_failure("gemini:main", RuntimeError("400 INVALID_ARGUMENT bad setting"))
    assert not llm_client.cooling_down("gemini:main")


def test_offline_reader_never_cools_down():
    llm_client.note_failure("offline_ocr", TimeoutError())
    assert not llm_client.cooling_down("offline_ocr")


def test_everything_cooling_down_still_gives_an_answer(env):
    client, s = env
    s.summarize = [("groq:x", busy), ("gemini:main", busy)]
    client.post("/v1/compare", json=BODY)
    r = client.post("/v1/compare", json=BODY).json()
    assert r["summary_source"] == "template"
    s.extract = [("groq:x", busy), ("offline_ocr", lambda img, mime: {"readable": True, "ingredients_text": "Aqua",
                                                                      "confidence_note": ""})]
    client.post("/v1/products/extract", files={"image": ("l.png", png(), "image/png")})
    r2 = client.post("/v1/products/extract", files={"image": ("l.png", png(), "image/png")}).json()
    assert r2["reader"] == "offline_ocr"


def test_empty_vision_model_skips_groq_for_photos(monkeypatch):
    monkeypatch.setattr(config, "GROQ_API_KEY", "y")
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    monkeypatch.setattr(config, "GROQ_VISION_MODEL", "")
    assert [n for n, _ in llm_client.extract_providers()] == ["offline_ocr"]
    assert [n for n, _ in llm_client.summary_providers()] == [f"groq:{config.GROQ_MODEL}"]
