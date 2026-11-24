"""Offline label reading with Tesseract: free, runs on your own computer, no AI and no internet.
Used only when no AI service answers. It is less accurate than AI, so the shopper must always
check the text, and it never fills in missing words."""
import io
import os
import re

from PIL import Image, ImageFilter, ImageOps, ImageStat

from app import config


class OCRUnavailable(Exception):
    """Tesseract isn't installed (or can't be found)."""


START = re.compile(r"\bingr[eé]dients?\b\s*[:\-.]?", re.IGNORECASE)
STOP = re.compile(r"\b(directions|how to use|caution|warnings?|precautions?|mfd|mfg|manufactured|marketed by|"
                  r"batch|b\.?\s?no|exp(iry)?|best before|use before|net (wt|vol|weight|quantity)|storage|"
                  r"for external use|made in|customer care|distributed by|how to use|for mfd)\b"
                  r"|\(\s*f\s*[.,]?\s*[i1l]{1,2}\s*[.,]?\s*l\b", re.IGNORECASE)      # "(F.I.L. 123...)" batch code


def _tesseract():
    try:
        import pytesseract
    except ImportError as exc:
        raise OCRUnavailable("The pytesseract package isn't installed.") from exc
    if config.TESSERACT_CMD and os.path.exists(config.TESSERACT_CMD):
        pytesseract.pytesseract.tesseract_cmd = config.TESSERACT_CMD
    try:
        pytesseract.get_tesseract_version()
    except Exception as exc:
        raise OCRUnavailable("Tesseract isn't installed on this computer.") from exc
    return pytesseract


def is_available() -> bool:
    try:
        _tesseract()
        return True
    except OCRUnavailable:
        return False


LINE_START_JUNK = re.compile(r"^[^A-Za-z0-9(]*(?:(?!C[Il1]\b)[A-Za-z]{1,2}[^A-Za-z0-9(\s]*\s+)?[^A-Za-z0-9(]*")


def ingredient_section(text: str, block: bool = False) -> str:
    """From all the text on a label, keep only the part after 'Ingredients' and before things like 'Directions'."""
    m = START.search(text or "")
    if not m:
        return ""
    rest = text[m.end():]
    stop = STOP.search(rest)
    if stop:
        rest = rest[:stop.start()]
    if block:      # a cut-out block read line by line: drop specks the curve of the bottle adds at line starts
        lines = [ln for ln in rest.splitlines() if ln.strip()]
        rest = "\n".join([lines[0].strip()] + [LINE_START_JUNK.sub("", ln.strip()) for ln in lines[1:]]) if lines else ""
    else:
        blank = re.search(r"\n\s*\n", rest.strip())
        if blank:
            rest = rest.strip()[:blank.start()]
    rest = re.sub(r"-\s*\n\s*", "", rest)            # "Glyc-\nerin" -> "Glycerin"
    rest = re.sub(r"\s*\n\s*", " ", rest)
    rest = re.sub(r"[^A-Za-z0-9 ,./()'&+%:;\-éè]", " ", rest)   # stray marks OCR adds (| _ \ © ~ “)
    rest = re.sub(r"\s+([,.])", r"\1", rest)
    rest = re.sub(r"\.\s+(?=[A-Za-z])", ", ", rest)     # a full stop between two names is a misread comma
    rest = re.sub(r"(^|,)\s*[-.]+\s*", r"\1 ", rest)
    rest = re.sub(r"\s+", " ", rest).strip(" .;:,")
    return rest


def _prepare(image_bytes: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(image_bytes))
    img = ImageOps.exif_transpose(img).convert("L")
    if max(img.size) < 1500:                         # small text reads better when enlarged
        scale = 1500 / max(img.size)
        img = img.resize((int(img.width * scale), int(img.height * scale)))
    img = ImageOps.autocontrast(img)
    if ImageStat.Stat(img).mean[0] < 110:            # light text on a dark label: flip it to dark on light
        img = ImageOps.invert(img)
    return img


def whole_text(text: str) -> str:
    """For a close-up that holds only the ingredient list: keep all of it, up to a stop word."""
    stop = STOP.search(text or "")
    rest = (text or "")[:stop.start()] if stop else (text or "")
    rest = re.sub(r"-\s*\n\s*", "", rest)
    rest = re.sub(r"\s+", " ", rest).strip(" .;:,")
    return rest if len(re.findall(r"[A-Za-z]{3,}", rest)) >= 3 else ""


def _find_word_box(tess, img, pattern=r"(?i)^ingr[eé]dients?\W*$"):
    """Where is the word 'Ingredients' on the photo? (left, top, width, height) or None."""
    data = tess.image_to_data(img, config="--psm 6", output_type=tess.Output.DICT)
    for i, word in enumerate(data.get("text", [])):
        if re.match(pattern, (word or "").strip()):
            return data["left"][i], data["top"][i], data["width"][i], data["height"][i]
    return None


def _list_block(img: Image.Image, box) -> Image.Image:
    """Cut out the block of text that starts at 'Ingredients', enlarged and sharpened for reading."""
    left, top, width, height = box
    region = (max(0, int(left - width * 1.4)), max(0, int(top - height)),
              min(img.width, int(left + width * 5)), min(img.height, int(top + height * 18)))
    crop = img.crop(region)
    crop = crop.resize((crop.width * 2, crop.height * 2), Image.LANCZOS)
    return crop.filter(ImageFilter.SHARPEN)


def read_ingredients(image_bytes: bytes, mime_type: str = "image/jpeg", tesseract=None, close_up: bool = False) -> dict:
    """close_up=True means the picture is already cut down to the ingredient list (found by an AI),
    so the word "Ingredients" doesn't have to be visible.
    Otherwise: find the word "Ingredients", cut out the block of text under it, and read that closely
    (small print next to big bold address text confuses a whole-photo read)."""
    tess = tesseract or _tesseract()
    img = _prepare(image_bytes)
    section = ""
    if not close_up and hasattr(tess, "image_to_data"):
        try:
            box = _find_word_box(tess, img)
        except Exception:
            box = None
        if box:
            section = ingredient_section(tess.image_to_string(_list_block(img, box), config="--psm 6"), block=True)
    if not section:
        raw = tess.image_to_string(img, config="--psm 6") if hasattr(tess, "image_to_data") \
            else tess.image_to_string(img, lang="eng")
        section = ingredient_section(raw) or (whole_text(raw) if close_up else "")
    if not section:
        return {"readable": False, "ingredients_text": "",
                "confidence_note": "Read offline without AI, but the word 'Ingredients' wasn't found. "
                                   "Try a sharper, straight-on photo, or paste the list."}
    return {"readable": True, "ingredients_text": section,
            "confidence_note": "Read offline without AI, which makes more mistakes. Please check every word."}
