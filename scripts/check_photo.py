"""Tries EVERY photo reader on one label photo and shows how much of the list each one read.
Use it to see which AI reads your photos fully.

Run from the project folder:  python -m scripts.check_photo "C:\\path\\to\\label.jpg"
"""
import sys
import time
from pathlib import Path

from app.routes.products import _normalise, _offline_read, _prepare_image
from app.services import llm_client, photo_reader


def main() -> int:
    if len(sys.argv) != 2 or not Path(sys.argv[1]).is_file():
        print('Usage: python -m scripts.check_photo "C:\\path\\to\\label.jpg"')
        return 1
    prepared = _prepare_image(Path(sys.argv[1]).read_bytes())
    box = None                                   # where an AI found the list; the offline reader reuses it
    for name, fn in llm_client.extract_providers():
        start = time.monotonic()
        try:
            r = _normalise(_offline_read(fn, prepared, box) if name == "offline_ocr" else fn(prepared, "image/jpeg"))
        except Exception as exc:
            box = box or getattr(exc, "box", None)
            print(f"\n{name}: FAILED - {llm_client.describe_failure(exc)}")
            continue
        box = box or r.get("box")
        secs = time.monotonic() - start
        if not r["readable"]:
            print(f"\n{name}: could not read a list ({secs:.0f}s). Note: {r['confidence_note']}")
            continue
        status = "MAY BE INCOMPLETE - " + r["incomplete_reason"] if r["possibly_incomplete"] else "looks complete"
        close = "close-up" if r.get("used_close_up") else "whole photo"
        print(f"\n{name}: {photo_reader.item_count(r)} ingredients, {status} ({close}, {secs:.0f}s)")
        print("  " + r["ingredients_text"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
