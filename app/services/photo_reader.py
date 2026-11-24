"""Reads the ingredient list from a label photo with any AI that can see images: one quick read first,
and a zoomed-in second look only when the first answer looks cut short.

Why two steps: phone photos are big, and the ingredient list is often a small block of tiny,
curved text. Shrinking the whole photo makes that text unreadable (this is what cut lists short).
  Step 1 (locate): send a small copy and ask WHERE the ingredient list is (a box).
  Step 2 (read):   cut that box out of the FULL-size photo, enlarge it if needed, and ask the AI
                   to copy the text. If step 1 fails, step 2 reads the whole photo at high resolution.
Every answer is then checked for signs that the list was cut short.
"""
import io
import re

from PIL import Image, ImageOps

LOCATE_SIDE_PX = 1024      # small copy for finding the list
READ_SIDE_PX = 2400        # largest side sent for reading
MIN_CROP_WIDTH_PX = 1400   # small crops are enlarged to at least this width
MARGIN = 0.04              # extra border around the found box (4% of the photo)

LOCATE_PROMPT = """This is ONE photo of a cosmetic product label.
Find the block of text that is the ingredient list (it usually starts with "Ingredients" or "INCI").
Reply with JSON only:
{"found": true, "box": [ymin, xmin, ymax, xmax]}
where the numbers are positions from 0 to 1000 (0,0 is the top-left corner of the photo).
If there is no ingredient list, reply {"found": false, "box": []}."""

READ_PROMPT = """This is ONE photo (a single image) of a cosmetic product label.
Copy the COMPLETE ingredient list exactly as printed, from the first ingredient to the last, in order.
Rules:
- Start with the very first ingredient after the word "Ingredients" (often "Aqua" or "Water").
- Copy every item, including items joined with "(and)", brackets, and long chemical names.
- Never shorten, summarise or end with "..." or "etc.". Never add, guess or correct a word.
- Stop where the list ends (for example before "Precaution", "Directions" or "Caution").
- If part of the list is genuinely unreadable or cut off by the edge of the label, copy what you can
  read, set complete to false, and say exactly which part in confidence_note.
Reply with JSON only, in this exact shape:
{"readable": true, "complete": true, "ingredients_text": "Aqua, ...", "confidence_note": ""}
If there is no ingredient list in the photo: {"readable": false, "complete": false, "ingredients_text": "", "confidence_note": "why"}"""

TRUNCATION_ENDINGS = re.compile(r"(\.\.\.|…|\(and\)|\band\b|\(|,|-|/|\betc\.?)\s*$", re.IGNORECASE)
WORRYING_NOTES = re.compile(r"cut off|cut short|partial|partly|obscur|covered|hidden|blurr|not (fully )?visible|"
                            r"incomplete|truncat|multiple images|edge of|unreadable|illegible", re.IGNORECASE)


def _to_jpeg(img: Image.Image, quality: int = 90) -> bytes:
    out = io.BytesIO()
    img.convert("RGB").save(out, format="JPEG", quality=quality)
    return out.getvalue()


def _fit(img: Image.Image, side: int) -> Image.Image:
    img = img.copy()
    img.thumbnail((side, side), Image.LANCZOS)
    return img


def crop_box(img: Image.Image, box) -> Image.Image | None:
    """box = [ymin, xmin, ymax, xmax] from 0 to 1000. Returns the enlarged crop, or None if the box is unusable."""
    try:
        ymin, xmin, ymax, xmax = [float(v) for v in box]
    except (TypeError, ValueError):
        return None
    if not (0 <= ymin < ymax <= 1000 and 0 <= xmin < xmax <= 1000):
        return None
    if (ymax - ymin) < 20 or (xmax - xmin) < 20:          # too tiny to be a real ingredient block
        return None
    w, h = img.size
    m = MARGIN * 1000
    left, right = max(0, xmin - m) / 1000 * w, min(1000, xmax + m) / 1000 * w
    top, bottom = max(0, ymin - m) / 1000 * h, min(1000, ymax + m) / 1000 * h
    crop = img.crop((int(left), int(top), int(right), int(bottom)))
    if crop.width < MIN_CROP_WIDTH_PX:                     # enlarge small text
        scale = MIN_CROP_WIDTH_PX / crop.width
        crop = crop.resize((int(crop.width * scale), int(crop.height * scale)), Image.LANCZOS)
    return _fit(crop, READ_SIDE_PX)


def incomplete_reason(text: str, note: str, complete_flag) -> str:
    """Why this list might be cut short, or "" if it looks complete."""
    if complete_flag is False:
        return "the photo reader said it couldn't see the whole list"
    if TRUNCATION_ENDINGS.search(text or ""):
        return "the list stops in the middle"
    if WORRYING_NOTES.search(note or ""):
        return "the photo reader said part of the list was hard to see"
    return ""


def _result(data: dict, used_crop: bool) -> dict:
    text = str(data.get("ingredients_text") or "").strip()
    note = str(data.get("confidence_note") or "").strip()
    readable = bool(data.get("readable")) and bool(text)
    reason = incomplete_reason(text, note, data.get("complete")) if readable else ""
    return {"readable": readable, "ingredients_text": text if readable else "", "confidence_note": note,
            "possibly_incomplete": bool(reason), "incomplete_reason": reason, "used_close_up": used_crop}


def item_count(result: dict) -> int:
    return len([x for x in re.split(r"[,;]", result.get("ingredients_text", "")) if x.strip()])


def better(a: dict | None, b: dict) -> dict:
    """Pick the more useful of two answers: readable, then complete, then longer."""
    if a is None:
        return b
    key = lambda r: (r["readable"], not r.get("possibly_incomplete", False), item_count(r))
    return b if key(b) > key(a) else a


def read_label(image_bytes: bytes, ask_json, box_hint=None, zoom_first: bool = False) -> dict:
    """ask_json(jpeg_bytes, prompt) -> dict is one call to one AI.
    Fast path: ONE call that reads the whole photo (sharp, up to 2400 px). Most photos stop here.
    Only if that answer looks cut short or unreadable do we zoom in: find the list (skipped when an
    earlier AI already found it: box_hint), cut it out of the full-size photo, and read the close-up.
    The better of the two answers is kept. The list's position ("box") is kept on the answer or on
    the error, so the next AI and the offline reader can reuse it without asking again."""
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(image_bytes))).convert("RGB")
    box = list(box_hint) if box_hint else None
    if zoom_first:          # last time only the close-up worked: go straight to it
        first = _zoom(img, ask_json, box)
        if first and first[0]["readable"] and not first[0]["possibly_incomplete"]:
            return {**first[0], "box": first[1]}
    try:
        whole = _result(ask_json(_to_jpeg(_fit(img, READ_SIDE_PX)), READ_PROMPT), used_crop=False)
    except Exception as exc:
        exc.box = box
        raise
    if whole["readable"] and not whole["possibly_incomplete"]:
        return {**whole, "box": box}

    if zoom_first:
        return {**whole, "box": box}                         # we already tried the close-up above
    zoomed = _zoom(img, ask_json, box)
    if not zoomed:
        return {**whole, "box": box}                         # zooming in is optional; keep the first answer
    return {**better(whole, zoomed[0]), "box": zoomed[1]}


def _zoom(img, ask_json, box):
    """Find the list (unless we already know where it is) and read a sharp close-up of it.
    Returns (answer, box) or None if that didn't work."""
    crop = crop_box(img, box) if box else None
    if crop is None:
        try:
            found = ask_json(_to_jpeg(_fit(img, LOCATE_SIDE_PX), 85), LOCATE_PROMPT)
            if isinstance(found, dict) and found.get("found"):
                crop = crop_box(img, found.get("box"))
                box = list(found["box"]) if crop is not None else None
        except Exception:
            return None
    if crop is None:
        return None
    try:
        return _result(ask_json(_to_jpeg(crop), READ_PROMPT), used_crop=True), box
    except Exception:
        return None


def close_up_jpeg(image_bytes: bytes, box) -> bytes | None:
    """The enlarged close-up of the ingredient list, for the offline reader."""
    if not box:
        return None
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(image_bytes))).convert("RGB")
    crop = crop_box(img, box)
    return _to_jpeg(crop, 95) if crop is not None else None
