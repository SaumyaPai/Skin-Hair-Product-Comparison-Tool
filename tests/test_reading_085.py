"""0.8.5: the reading message and result always appear, each upload is read once, and a care tip shows
while you wait.  Run:  python -m pytest -q tests/test_reading_085.py"""
import logging
from pathlib import Path

from app import config
from app.routes.products import read_photo
from ui.logic import TIPS, tip_for

ROOT = Path(__file__).parents[1]
PAGE = (ROOT / "ui" / "streamlit_app.py").read_text(encoding="utf-8")


def test_reading_runs_as_a_background_job_that_survives_reruns():
    assert "_workers().submit(api.extract" in PAGE and 'ss[f"job_{pid}"]' in PAGE
    assert "@st.fragment(run_every=1.0)" in PAGE and "st.rerun()" in PAGE


def test_same_upload_is_never_read_twice():
    assert 'if ss.get(f"read_file_{pid}") == up.file_id' in PAGE


def test_reading_message_has_the_running_figure_and_a_tip():
    assert ":material/directions_run: Reading your photo..." in PAGE and "While you wait: " in PAGE
    assert "animation: jog" in (ROOT / "ui" / "style.css").read_text(encoding="utf-8")


def test_tips_match_the_product_and_change_without_any_call():
    assert tip_for("hair", 0) in TIPS["hair"] and tip_for("skin", 0) in TIPS["skin"]
    assert tip_for("hair", 0) != tip_for("hair", 6)                      # a new tip every 6 seconds
    assert tip_for(None, 0) in TIPS["hair"] + TIPS["skin"]


def test_tips_stay_general_and_neutral():
    words = config.BANNED_WORDS + config.SUMMARY_BANNED_EXTRA + ["will", "prevent", "stops", "%"]
    for tip in TIPS["hair"] + TIPS["skin"]:
        low = f" {tip.lower()} "
        for w in words:
            assert f" {w} " not in low and f" {w}," not in low and f" {w}." not in low, (tip, w)


def test_each_reader_time_is_written_to_the_api_window(caplog):
    chain = [("gemini:lite", lambda i, m: {"readable": True, "ingredients_text": "Aqua, Glycerin, Niacinamide",
                                           "confidence_note": ""})]
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (300, 200), "white").save(buf, format="JPEG")
    with caplog.at_level(logging.INFO, logger="skincare"):
        read_photo(chain, buf.getvalue())
    assert "Photo: gemini:lite took" in caplog.text and "complete" in caplog.text
    assert "Photo: finished in" in caplog.text
