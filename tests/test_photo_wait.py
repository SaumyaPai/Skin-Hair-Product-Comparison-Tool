"""0.8.3: photo reading never leaves you waiting with no message.
Run:  python -m pytest -q tests/test_photo_wait.py"""
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import config
from app.data_loader import load_all
from app.deps import build_services, get_services
from app.main import app
from app.routes.products import BUSY_MESSAGE, read_photo
from app.services import llm_client


def jpeg():
    buf = io.BytesIO()
    Image.new("RGB", (600, 400), "white").save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "app.db")
    s = build_services(load_all())
    app.dependency_overrides[get_services] = lambda: s
    yield TestClient(app), s
    app.dependency_overrides.clear()


def busy(img, mime):
    raise llm_client.LLMBusy("429 rate limit")


def post(client):
    return client.post("/v1/products/extract", files={"image": ("l.jpg", jpeg(), "image/jpeg")})


def test_all_ais_busy_and_nothing_else_says_so_plainly(env):
    client, s = env
    s.extract = [("groq:x", busy), ("gemini:a", busy)]
    r = post(client)
    assert r.status_code == 502 and r.json()["error"]["message"] == BUSY_MESSAGE


def test_all_ais_busy_and_offline_reader_finds_nothing_explains_why(env):
    client, s = env
    s.extract = [("groq:x", busy), ("gemini:a", busy),
                 ("offline_ocr", lambda img, mime: {"readable": False, "ingredients_text": "",
                                                    "confidence_note": "word not found"})]
    r = post(client).json()
    assert r["readable"] is False and r["confidence_note"] == BUSY_MESSAGE


def test_no_more_ais_after_the_time_limit_but_offline_still_runs(monkeypatch):
    monkeypatch.setattr(config, "PHOTO_TOTAL_SECONDS", 50)
    now = [0.0]                                             # a pretend clock: the first AI takes 60 seconds
    called = []

    def slow_unreadable(img, mime):
        called.append("first")
        now[0] += 60
        return {"readable": False, "ingredients_text": "", "confidence_note": ""}
    chain = [("groq:x", slow_unreadable), ("gemini:a", lambda i, m: called.append("second")),
             ("offline_ocr", lambda i, m: called.append("offline") or
              {"readable": True, "ingredients_text": "Aqua, Glycerin, Niacinamide", "confidence_note": ""})]
    result, name, notes = read_photo(chain, jpeg(), clock=lambda: now[0])
    assert called == ["first", "offline"] and name == "offline_ocr" and notes["out_of_time"] is True


def test_page_reads_on_the_card_with_a_spinner_message():
    from pathlib import Path
    page = (Path(__file__).parents[1] / "ui" / "streamlit_app.py").read_text(encoding="utf-8")
    assert 'on_change=queue, args=("extract", pid)' in page and "Reading your photo..." in page
    assert 'run_queued("search", pid, do_search' in page and 'run_queued("lookup", pid, do_lookup' in page
    assert 'if "options" not in ss' in page                       # dropdown list fetched once, not on every click
