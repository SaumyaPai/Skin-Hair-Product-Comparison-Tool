"""Fix 0.5.1: label photos that came back with only part of the ingredient list.
Run:  python -m pytest -q tests/test_photo_fix.py"""
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import config
from app.data_loader import load_all
from app.deps import build_services, get_services
from app.main import app
from app.routes.products import _prepare_image
from app.services import photo_reader
from app.services.photo_reader import LOCATE_PROMPT, READ_PROMPT, crop_box, incomplete_reason, read_label

# What the app showed for the shampoo photo before this fix (cut short, ending in "...")
CUT_SHORT = ("Aqua, Sodium Laureth Sulfate, Cocamidopropyl Betaine, Glycerin, Polyquaternium-10, "
             "Panthenol, Cera...")
FULL = "Aqua, Sodium Laureth Sulfate, Cocamidopropyl Betaine, Glycerin, Panthenol, Biotin, Collagen (Vegan Collagen)"


def photo(size=(4284, 5712), fmt="JPEG"):
    buf = io.BytesIO()
    Image.new("RGB", size, "white").save(buf, format=fmt)
    return buf.getvalue()


def size_of(jpeg):
    return Image.open(io.BytesIO(jpeg)).size


# ---------------- spotting a list that was cut short ----------------

@pytest.mark.parametrize("text", [CUT_SHORT, "Aqua, Glycerin…", "Aqua, Dimethiconol (and)", "Aqua, Glycerin,",
                                  "Aqua, Glycerin and", "Aqua, Glycerin, etc."])
def test_cut_short_endings_are_spotted(text):
    assert incomplete_reason(text, "", None) == "the list stops in the middle"


def test_complete_list_is_not_flagged():
    assert incomplete_reason(FULL, "Clear photo.", True) == ""


def test_ai_saying_incomplete_is_believed():
    assert incomplete_reason(FULL, "", False)


@pytest.mark.parametrize("note", ["The text appears to span multiple images", "Part of the list is cut off",
                                  "Some words are obscured by glare"])
def test_worrying_notes_are_spotted(note):
    assert incomplete_reason(FULL, note, None)


# ---------------- step 1 and step 2: find the list, read a sharp close-up ----------------

def test_crop_box_uses_full_size_photo_and_enlarges_small_text():
    img = Image.new("RGB", (4284, 5712))
    crop = crop_box(img, [600, 100, 750, 400])           # a small block lower down the bottle
    assert crop is not None and crop.width >= photo_reader.MIN_CROP_WIDTH_PX
    assert max(crop.size) <= photo_reader.READ_SIDE_PX


@pytest.mark.parametrize("box", [None, [], [1, 2, 3], [500, 500, 400, 600], [0, 0, 1200, 900], [10, 10, 15, 15], ["a", 1, 2, 3]])
def test_bad_boxes_are_ignored(box):
    assert crop_box(Image.new("RGB", (1000, 1000)), box) is None


def test_complete_first_read_needs_only_one_call():
    sent = []

    def ask(jpeg, prompt):
        sent.append((prompt, size_of(jpeg)))
        return {"readable": True, "complete": True, "ingredients_text": FULL, "confidence_note": ""}

    r = read_label(photo(), ask)
    assert [p for p, _ in sent] == [READ_PROMPT]                     # fast path: one call
    assert max(sent[0][1]) == photo_reader.READ_SIDE_PX and not r["used_close_up"]


def test_cut_short_first_read_zooms_in_and_keeps_the_better_answer():
    sent = []
    answers = iter([{"readable": True, "complete": True, "ingredients_text": CUT_SHORT, "confidence_note": ""},
                    {"found": True, "box": [600, 100, 750, 400]},
                    {"readable": True, "complete": True, "ingredients_text": FULL, "confidence_note": ""}])

    def ask(jpeg, prompt):
        sent.append((prompt, size_of(jpeg)))
        return next(answers)

    r = read_label(photo(), ask)
    assert [p for p, _ in sent] == [READ_PROMPT, LOCATE_PROMPT, READ_PROMPT]
    assert max(sent[1][1]) <= photo_reader.LOCATE_SIDE_PX                # small copy only for finding
    assert sent[2][1][0] >= photo_reader.MIN_CROP_WIDTH_PX                # sharp close-up for reading
    assert r["ingredients_text"] == FULL and r["used_close_up"] and not r["possibly_incomplete"]


def test_zoom_failing_keeps_the_first_answer():
    answers = iter([{"readable": True, "ingredients_text": CUT_SHORT, "confidence_note": ""},
                    {"found": True, "box": [600, 100, 750, 400]}])

    def ask(jpeg, prompt):
        try:
            return next(answers)
        except StopIteration:
            raise TimeoutError("slow")
    r = read_label(photo(), ask)
    assert r["ingredients_text"] == CUT_SHORT and r["possibly_incomplete"]


def test_locate_failure_falls_back_to_sharp_whole_photo():
    sent = []

    def ask(jpeg, prompt):
        sent.append((prompt, size_of(jpeg)))
        if prompt == LOCATE_PROMPT:
            raise RuntimeError("bad json")
        return {"readable": True, "ingredients_text": FULL, "confidence_note": ""}

    r = read_label(photo(), ask)
    assert r["readable"] and not r["used_close_up"]
    assert max(sent[-1][1]) == photo_reader.READ_SIDE_PX               # not shrunk to 1600 any more


def test_reading_error_is_passed_up_so_the_next_ai_can_try():
    def ask(jpeg, prompt):
        if prompt == READ_PROMPT:
            raise TimeoutError("slow")
        return {"found": False}
    with pytest.raises(TimeoutError):
        read_label(photo(), ask)


def test_read_prompt_forbids_shortening():
    assert "ONE photo" in READ_PROMPT and '"..."' in READ_PROMPT and "(and)" in READ_PROMPT
    assert '"complete"' in READ_PROMPT


# ---------------- photo preparation ----------------

def test_photo_is_no_longer_shrunk_to_1600():
    assert max(size_of(_prepare_image(photo((3000, 4000))))) == 4000 > 1600


def test_sideways_phone_photo_is_turned_upright():
    img = Image.new("RGB", (400, 200))
    exif = img.getexif()
    exif[0x0112] = 6                                                     # "rotate 90" tag from a phone
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    assert size_of(_prepare_image(buf.getvalue())) == (200, 400)


# ---------------- the photo route: try the next AI, keep the best, warn ----------------

@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "app.db")
    s = build_services(load_all())
    app.dependency_overrides[get_services] = lambda: s
    yield TestClient(app), s
    app.dependency_overrides.clear()


def post(client, data=None):
    return client.post("/v1/products/extract", files={"image": ("l.jpg", data or photo((800, 600)), "image/jpeg")})


def ok(text, **extra):
    return lambda img, mime: {"readable": True, "ingredients_text": text, "confidence_note": "", **extra}


def test_cut_short_answer_tries_next_ai_and_keeps_complete_one(env):
    client, s = env
    s.extract = [("groq:x", ok(CUT_SHORT)), ("gemini:main", ok(FULL)), ("offline_ocr", ok("Aqua"))]
    r = post(client).json()
    assert r["reader"] == "gemini:main" and r["ingredients_text"] == FULL and r["possibly_incomplete"] is False


def test_when_every_ai_is_cut_short_the_longest_is_kept_with_a_warning(env):
    client, s = env
    called = []
    s.extract = [("groq:x", ok("Aqua, Glycerin...")), ("gemini:main", ok(CUT_SHORT)),
                 ("offline_ocr", lambda img, mime: called.append(1))]
    r = post(client).json()
    assert r["reader"] == "gemini:main" and r["possibly_incomplete"] is True
    assert "may be incomplete" in r["warning"] and called == []       # offline reader not used: an AI read it


def test_first_complete_answer_stops_the_chain(env):
    client, s = env
    called = []
    s.extract = [("groq:x", ok(FULL)), ("gemini:main", lambda img, mime: called.append(1))]
    r = post(client).json()
    assert r["reader"] == "groq:x" and called == [] and r["possibly_incomplete"] is False
    assert r["warning"] == "Please check this text against the label before comparing."


def test_photo_reader_flag_is_kept(env):
    client, s = env
    s.extract = [("gemini:main", ok(FULL, possibly_incomplete=True, incomplete_reason="said so"))]
    r = post(client).json()
    assert r["possibly_incomplete"] is True and "said so" in r["warning"]


def test_ten_mb_limit(env):
    client, s = env
    s.extract = [("gemini:main", ok(FULL))]
    assert config.MAX_IMAGE_MB == 10
    big = b"\xff\xd8" + b"0" * (config.MAX_IMAGE_BYTES + 10)
    r = post(client, big)
    assert r.status_code == 422 and "10 MB" in r.json()["error"]["message"]


def test_page_shows_the_incomplete_warning_and_crop_tip():
    src = (config.ROOT_DIR if hasattr(config, "ROOT_DIR") else __import__("pathlib").Path(__file__).parents[1])
    page = (src / "ui" / "streamlit_app.py").read_text(encoding="utf-8")
    assert 'r.get("possibly_incomplete")' in page and "may be incomplete" in page
    assert "crop the photo to just the ingredient list" in page and "under 10 MB" in page


def test_check_photo_script_runs_every_reader(tmp_path, monkeypatch, capsys):
    from scripts import check_photo
    from app.services import llm_client
    f = tmp_path / "l.jpg"
    f.write_bytes(photo((800, 600)))
    monkeypatch.setattr(llm_client, "extract_providers", lambda: [
        ("groq:x", ok(CUT_SHORT)), ("gemini:main", ok(FULL))])
    monkeypatch.setattr("sys.argv", ["check_photo", str(f)])
    assert check_photo.main() == 0
    out = capsys.readouterr().out
    assert "groq:x: 7 ingredients, MAY BE INCOMPLETE" in out and "gemini:main: 7 ingredients, looks complete" in out
