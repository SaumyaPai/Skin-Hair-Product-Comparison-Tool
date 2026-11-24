"""0.8.4: faster photo reading, progress you can see, and a better offline reader.
Run:  python -m pytest -q tests/test_speed_084.py"""
import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont

from app import config
from app.data_loader import load_all
from app.deps import build_services, get_services
from app.main import app
from app.routes import products
from app.routes.products import UNRELIABLE_OFFLINE, _offline_read, read_photo
from app.services import llm_client, ocr

FULL = "Aqua, Glycerin, Niacinamide, Dimethicone, Phenoxyethanol"


def jpeg(size=(600, 400)):
    buf = io.BytesIO()
    Image.new("RGB", size, "white").save(buf, format="JPEG")
    return buf.getvalue()


# ---------------- busy and out-of-quota AIs are skipped straight away ----------------

@pytest.mark.parametrize("message", ["429 Too Many Requests", "RESOURCE_EXHAUSTED: quota exceeded",
                                     "Rate limit reached for model"])
def test_used_up_free_limit_rests_for_30_minutes(message):
    llm_client.note_failure("gemini:x", RuntimeError(message), now=0)
    assert llm_client.cooling_down("gemini:x", now=config.AI_QUOTA_COOLDOWN_SECONDS - 1)
    assert config.AI_QUOTA_COOLDOWN_SECONDS >= 1800


def test_briefly_busy_rests_for_5_minutes():
    exc = RuntimeError("503 UNAVAILABLE")
    exc.code = 503
    llm_client.note_failure("gemini:y", exc, now=0)
    assert llm_client.cooling_down("gemini:y", now=config.AI_COOLDOWN_SECONDS - 1)
    assert not llm_client.cooling_down("gemini:y", now=config.AI_COOLDOWN_SECONDS + 1)


# ---------------- the reader that worked is tried first, the way it worked ----------------

def test_last_working_reader_goes_first_and_starts_with_the_close_up():
    seen = []

    def first(img, mime, box_hint=None, zoom_first=False):
        seen.append(("first", zoom_first))
        return {"readable": False, "ingredients_text": "", "confidence_note": ""}

    def second(img, mime, box_hint=None, zoom_first=False):
        seen.append(("second", zoom_first))
        return {"readable": True, "ingredients_text": FULL, "confidence_note": "", "used_close_up": True}
    first.accepts_box = second.accepts_box = True
    chain = [("groq:x", first), ("gemini:lite", second)]
    read_photo(chain, jpeg())
    assert seen == [("first", False), ("second", False)]
    seen.clear()
    _, name, _ = read_photo(chain, jpeg())
    assert name == "gemini:lite" and seen == [("second", True)]       # one reader, straight to the close-up


# ---------------- the page can show which reader is working ----------------

def test_progress_note_while_reading_and_cleared_after(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "app.db")
    seen = []

    def reader(img, mime):
        seen.append(dict(products.PROGRESS.get("abc", {})))
        return {"readable": True, "ingredients_text": FULL, "confidence_note": ""}
    s = build_services(load_all())
    s.extract = [("gemini:gemini-3.5-flash-lite", reader)]
    app.dependency_overrides[get_services] = lambda: s
    try:
        client = TestClient(app)
        r = client.post("/v1/products/extract", files={"image": ("l.jpg", jpeg(), "image/jpeg")},
                        headers={"X-Progress-Id": "abc"}).json()
        assert seen == [{"reader": "Gemini (gemini-3.5-flash-lite)", "n": 1, "of": 1}]
        assert r["reader_label"] == "Gemini (gemini-3.5-flash-lite)"
        assert client.get("/v1/products/extract/progress/abc").json()["reader"] == ""
    finally:
        app.dependency_overrides.clear()


def test_page_shows_progress_and_doesnt_fade():
    root = Path(__file__).parents[1]
    page = (root / "ui" / "streamlit_app.py").read_text(encoding="utf-8")
    assert "Trying {p['reader']} ({p['n']} of {p['of']})..." in page
    assert '[data-stale="true"] { opacity: 1 !important' in (root / "ui" / "style.css").read_text(encoding="utf-8")


# ---------------- offline reader ----------------

def label_photo() -> bytes:
    """Small print with the list, then big bold address text under it, like the conditioner bottle."""
    img = Image.new("RGB", (1600, 1500), (200, 190, 235))
    d = ImageDraw.Draw(img)
    small, big = ImageFont.load_default(size=30), ImageFont.load_default(size=70)
    lines = ["HOW TO USE: AFTER SHAMPOO, APPLY TO LENGTHS.", "INGREDIENTS: AQUA, CETEARYL ALCOHOL,",
             "DIMETHICONE, GLYCERIN, BEHENTRIMONIUM", "CHLORIDE, LACTIC ACID. (F.I.L. Z70045740/1).",
             "FOR MFD. SITE ADDRESS, READ THE LAST CHARACTER"]
    for i, line in enumerate(lines):
        d.text((300, 300 + i * 45), line, fill="black", font=small)
    d.text((150, 700), "MFD. BY: L'OREAL INDIA PVT.", fill="black", font=big)
    d.text((150, 800), "LTD., CHAKAN, PUNE - 410 501.", fill="black", font=big)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return buf.getvalue()


@pytest.mark.skipif(not ocr.is_available(), reason="Tesseract not installed")
def test_offline_reader_cuts_out_the_list_and_stops_at_the_batch_code():
    r = ocr.read_ingredients(label_photo())
    text = r["ingredients_text"].upper()
    assert r["readable"] and text.startswith("AQUA") and "BEHENTRIMONIUM" in text
    assert "F.I.L" not in text and "MFD" not in text and "PUNE" not in text and "HOW TO USE" not in text


def test_junk_offline_read_is_not_shown():
    junk = lambda img, mime: {"readable": True, "ingredients_text": "WOW 10 UGE AFTER, LENGTHS TO TIPS, "
                                                                   "AS IMETE BEHENTRIMONIUM CHL, HYALURONAT",
                              "confidence_note": ""}
    r = _offline_read(junk, jpeg(), None)
    assert r["readable"] is False and r["confidence_note"] == UNRELIABLE_OFFLINE


def test_good_offline_read_is_kept():
    good = lambda img, mime: {"readable": True, "ingredients_text": FULL, "confidence_note": ""}
    assert _offline_read(good, jpeg(), None)["readable"] is True


def test_stray_marks_and_full_stops_are_cleaned():
    text = "Ingredients: AQUA, GLYCERIN. SODIUM HYALURONATE, _ DIMETHICONE, PARFUM / © FRAGRANCE"
    assert ocr.ingredient_section(text) == "AQUA, GLYCERIN, SODIUM HYALURONATE, DIMETHICONE, PARFUM / FRAGRANCE"
