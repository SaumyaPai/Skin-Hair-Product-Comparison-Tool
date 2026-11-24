"""Checks that Groq answers for both jobs: writing a summary and reading a label photo.

Run from the project folder:  python -m scripts.check_groq
"""
import io
import sys

from PIL import Image, ImageDraw, ImageFont

from app import config
from app.services import llm_client


def label_photo() -> bytes:
    img = Image.new("RGB", (1400, 260), "white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=44)
    draw.text((30, 40), "Ingredients: Aqua, Glycerin, Niacinamide,", fill="black", font=font)
    draw.text((30, 120), "Sodium Hyaluronate, Phenoxyethanol.", fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def main() -> int:
    if not config.GROQ_API_KEY:
        print("NOT READY: no GROQ_API_KEY in .env")
        return 1
    ok = True
    try:
        reply = llm_client.groq_write_summary("Reply with exactly this sentence: Groq is connected.")
        print(f"Summary ({config.GROQ_MODEL}): PASS - {reply[:80]}")
    except Exception as exc:
        ok = False
        print(f"Summary ({config.GROQ_MODEL}): FAILED - {llm_client.describe_failure(exc)}")
    if not config.GROQ_VISION_MODEL:
        print("Photos: Groq is switched off for photos (GROQ_VISION_MODEL is empty).")
        return 0 if ok else 1
    try:
        r = llm_client.groq_extract_ingredients(label_photo())
        text = r["ingredients_text"].lower()
        if "glycerin" in text and "niacinamide" in text:
            print(f"Photos ({config.GROQ_VISION_MODEL}): PASS - read: {r['ingredients_text']}")
        else:
            ok = False
            print(f"Photos ({config.GROQ_VISION_MODEL}): FAILED - read the wrong text: {r}")
    except Exception as exc:
        ok = False
        print(f"Photos ({config.GROQ_VISION_MODEL}): FAILED - {llm_client.describe_failure(exc)}")
    if not ok:
        print("\nIf photos FAILED: add the line  GROQ_VISION_MODEL=  (nothing after =) to .env so photos skip Groq.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
