"""Fix 0.5.2: Groq refused label photos (400 Bad Request), and the offline reader couldn't find the list.
Run:  python -m pytest -q tests/test_groq_photo_fix.py"""
import base64
import io
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import config
from app.data_loader import load_all
from app.deps import build_services, get_services
from app.main import app
from app.routes.products import _offline_read
from app.services import llm_client, ocr
from app.services.photo_reader import LOCATE_PROMPT, read_label

FULL = "Aqua, Sodium Laureth Sulfate, Glycerin, Biotin, Collagen (Vegan Collagen)"
READ_OK = json.dumps({"readable": True, "complete": True, "ingredients_text": FULL, "confidence_note": ""})


def photo(size=(3000, 4000)):
    buf = io.BytesIO()
    Image.new("RGB", size, "white").save(buf, format="JPEG")
    return buf.getvalue()


def sent_image_size(body):
    url = body["messages"][0]["content"][1]["image_url"]["url"]
    return Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))).size


def groq(replies, bodies):
    """Fake Groq: answers in turn from `replies` (status, json) and records each request."""
    replies = iter(replies)

    def handler(request):
        bodies.append(json.loads(request.content))
        status, payload = next(replies)
        return httpx.Response(status, json=payload)
    return httpx.Client(transport=httpx.MockTransport(handler))


def answer(text):
    return 200, {"choices": [{"message": {"content": text}}]}


REFUSED = (400, {"error": {"code": "json_validate_failed", "message": "Failed to generate JSON."}})


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setattr(config, "GROQ_API_KEY", "secret-key")


def test_groq_refusal_shows_groqs_own_reason():
    with pytest.raises(llm_client.GroqRequestError) as e:
        llm_client._groq_chat("m", "hi", http=groq([REFUSED], []))
    line = llm_client.describe_failure(e.value)
    assert "json_validate_failed" in line and "Failed to generate JSON" in line and "secret-key" not in line


def test_groq_photo_stays_inside_size_limits_and_asks_for_long_answers():
    bodies = []
    r = llm_client.groq_extract_ingredients(photo(), http=groq([answer(READ_OK)], bodies))   # one call is enough
    assert r["ingredients_text"] == FULL
    read = bodies[-1]
    assert max(sent_image_size(read)) <= config.GROQ_MAX_IMAGE_SIDE_PX
    assert read["max_completion_tokens"] == 4096 and read["response_format"] == {"type": "json_object"}


def test_json_check_failure_is_retried_once_without_strict_json():
    bodies = []
    r = llm_client.groq_extract_ingredients(photo(), http=groq([REFUSED, answer("```json\n" + READ_OK + "\n```")], bodies))
    assert r["readable"] and r["ingredients_text"] == FULL
    assert len(bodies) == 2 and "response_format" not in bodies[-1]


def test_other_refusals_are_not_retried_and_groq_rests_for_30_minutes():
    bodies = []
    too_big = (400, {"error": {"code": "invalid_request_error", "message": "image too large"}})
    with pytest.raises(llm_client.GroqRequestError) as e:
        llm_client.groq_extract_ingredients(photo(), http=groq([too_big], bodies))
    assert len(bodies) == 1
    llm_client.note_failure("groq:x", e.value, now=0)
    assert llm_client.cooling_down("groq:x", now=config.AI_QUOTA_COOLDOWN_SECONDS - 1)


def test_wrong_key_is_not_retried():
    bodies = []
    with pytest.raises(llm_client.GroqRequestError):
        llm_client.groq_extract_ingredients(photo(), http=groq([(401, {"error": {"message": "Invalid API Key"}})], bodies))
    assert len(bodies) == 1


def test_big_photo_is_squeezed_under_the_byte_limit(monkeypatch):
    monkeypatch.setattr(config, "GROQ_MAX_IMAGE_BYTES", 60_000)
    noisy = Image.effect_noise((2000, 2000), 80).convert("RGB")
    buf = io.BytesIO()
    noisy.save(buf, format="JPEG", quality=95)
    out = llm_client._groq_image(buf.getvalue(), 2048)
    assert len(out) < len(buf.getvalue())


# ---------------- the offline reader uses the close-up an AI found ----------------

class FakeTesseract:
    def __init__(self, text):
        self.text, self.sizes = text, []

    def image_to_string(self, img, lang):
        self.sizes.append(img.size)
        return self.text


def test_found_list_area_is_kept_for_the_next_reader():
    calls = []

    def ask(jpeg, prompt):
        calls.append(prompt)
        if prompt == LOCATE_PROMPT:
            return {"found": True, "box": [300, 400, 500, 800]}
        return {"readable": True, "ingredients_text": "Aqua, Glycerin...", "confidence_note": ""}
    r = read_label(photo(), ask)
    assert r["box"] == [300, 400, 500, 800] and LOCATE_PROMPT in calls
    # the next reader gets the area and doesn't need to ask where the list is
    calls.clear()
    read_label(photo(), ask, box_hint=r["box"])
    assert LOCATE_PROMPT not in calls


def test_close_up_does_not_need_the_word_ingredients(monkeypatch):
    fake = FakeTesseract("Aqua, Sodium Laureth Sulfate, Glycerin, Biotin\nPRECAUTION: For external use only")
    monkeypatch.setattr(ocr, "_tesseract", lambda: fake)
    r = _offline_read(ocr.read_ingredients, photo(), [300, 400, 500, 800])
    assert r["readable"] and r["ingredients_text"] == "Aqua, Sodium Laureth Sulfate, Glycerin, Biotin"
    assert r["used_close_up"] and "offline" in r["incomplete_reason"]
    assert len(fake.sizes) == 1                                   # the close-up was enough


def test_without_a_box_the_old_rule_still_applies(monkeypatch):
    monkeypatch.setattr(ocr, "_tesseract", lambda: FakeTesseract("Aqua, Glycerin, Biotin"))
    assert _offline_read(ocr.read_ingredients, photo(), None)["readable"] is False


def test_white_text_on_dark_label_is_flipped():
    buf = io.BytesIO()
    Image.new("RGB", (2000, 1000), (20, 90, 100)).save(buf, format="JPEG")
    assert ocr._prepare(buf.getvalue()).getpixel((10, 10)) > 128


def test_route_passes_the_found_box_to_the_offline_reader(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "app.db")
    fake = FakeTesseract("Aqua, Sodium Laureth Sulfate, Glycerin, Biotin")
    monkeypatch.setattr(ocr, "_tesseract", lambda: fake)

    def groq_fails(img, mime):
        exc = llm_client.GroqRequestError("Groq refused the request (error 400): too large")
        exc.box = [300, 400, 500, 800]
        raise exc
    s = build_services(load_all())
    s.extract = [("groq:x", groq_fails), ("offline_ocr", ocr.read_ingredients)]
    app.dependency_overrides[get_services] = lambda: s
    try:
        r = TestClient(app).post("/v1/products/extract",
                                 files={"image": ("l.jpg", photo((1200, 1600)), "image/jpeg")}).json()
    finally:
        app.dependency_overrides.clear()
    assert r["reader"] == "offline_ocr" and r["readable"] and r["possibly_incomplete"] is True
    assert "may be incomplete" in r["warning"]
