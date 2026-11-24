import io
import time
import logging

from fastapi import APIRouter, Depends, File, Header, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from PIL import Image, ImageOps, UnidentifiedImageError

from app import config, db
from app.deps import Services, get_services
from app.errors import ApiError
from app.services import ocr, photo_reader, resolver
from app.services.llm_client import (best_first, cooling_down, describe_failure, needed_zoom, note_failure,
                                     remember_good_reader)
from app.services.obf_client import is_valid_barcode

log = logging.getLogger("skincare")
router = APIRouter(prefix="/v1/products")


def _public(p: dict, cached: bool) -> dict:
    return {"barcode": p["barcode"], "product_name": p.get("product_name", ""), "brand": p.get("brand", ""),
            "category_tags": p.get("category_tags", []), "has_ingredients": bool(p.get("ingredients_text")),
            "ingredients_text": p.get("ingredients_text", ""), "source": "open_beauty_facts", "cached": cached}


@router.get("/lookup")
def lookup(barcode: str | None = Query(None), q: str | None = Query(None, max_length=100),
           services: Services = Depends(get_services)):
    barcode = (barcode or "").strip() or None
    q = (q or "").strip() or None
    if bool(barcode) == bool(q):
        raise ApiError(422, "VALIDATION_ERROR", "Please give either a barcode or a product name (q), not both.",
                       [{"field": "barcode/q", "issue": "exactly one required"}])
    conn = db.connect()
    try:
        if barcode:
            if not is_valid_barcode(barcode):
                raise ApiError(422, "VALIDATION_ERROR", "Barcodes are 8 to 14 digits.",
                               [{"field": "barcode", "issue": "invalid"}])
            found = resolver.lookup_barcode(conn, barcode, services.obf_lookup)
            if found["status"] in ("found", "no_ingredients"):
                body = _public({**found, "barcode": barcode}, found.get("cached", False))
                if found.get("stale"):
                    body["note"] = "The product database was unavailable, so an older saved copy was used."
                return {"results": [body]}
            if found["status"] == "not_found":
                raise ApiError(404, "PRODUCT_NOT_FOUND",
                               "We couldn't find this barcode in Open Beauty Facts. You can paste the ingredient "
                               "list or upload a label photo instead.")
            raise ApiError(502, "UPSTREAM_UNAVAILABLE",
                           "The product database isn't responding right now. Please try again, or paste the ingredients.")

        found = services.obf_search(q)
        if found["status"] != "ok":
            raise ApiError(502, "UPSTREAM_UNAVAILABLE",
                           "The product database isn't responding right now. Please try again, or paste the ingredients.")
        if not found["results"]:
            raise ApiError(404, "PRODUCT_NOT_FOUND",
                           "No products matched that name. Try the barcode, or paste the ingredient list.")
        for p in found["results"]:
            if p["ingredients_text"]:
                db.save_product(conn, p["barcode"], p["product_name"], p["brand"], p["ingredients_text"],
                                source="open_beauty_facts", category_tags="|".join(p["category_tags"]))
        return {"results": [_public(p, False) for p in found["results"]]}
    finally:
        conn.close()


def _prepare_image(raw: bytes) -> bytes:
    """Check it really is an image, turn it the right way up, and keep it SHARP.
    (Shrinking a whole label photo made small ingredient text unreadable, so we only cap huge photos.)"""
    try:
        img = Image.open(io.BytesIO(raw))
        img.verify()
        img = Image.open(io.BytesIO(raw))
        img = ImageOps.exif_transpose(img).convert("RGB")
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise ApiError(422, "INVALID_IMAGE", f"That file doesn't look like a photo. Please upload a JPEG or PNG "
                                             f"under {config.MAX_IMAGE_MB} MB.")
    img.thumbnail((config.MAX_IMAGE_SIDE_PX, config.MAX_IMAGE_SIDE_PX), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=92)
    return out.getvalue()


def _normalise(result: dict) -> dict:
    """Make every reader's answer the same shape, and mark answers that look cut short."""
    text = str(result.get("ingredients_text") or "").strip()
    note = str(result.get("confidence_note") or "")
    readable = bool(result.get("readable")) and bool(text)
    reason = result.get("incomplete_reason")
    if reason is None:
        reason = photo_reader.incomplete_reason(text, note, result.get("complete")) if readable else ""
    return {**result, "readable": readable, "ingredients_text": text if readable else "",
            "confidence_note": note, "possibly_incomplete": bool(reason) if readable else False,
            "incomplete_reason": reason if readable else ""}


UNRELIABLE_OFFLINE = ("We couldn't read this photo reliably without AI. Please paste the ingredient list, or try the "
                      "photo again in a few minutes when the AI readers are free.")
_known = {}


def _known_count(text: str) -> int:
    """How many items in the text are ingredients we recognise. Junk from a bad read has almost none."""
    if "norm" not in _known:
        from app.data_loader import load_all
        from app.services.normalizer import from_data
        _known["norm"] = from_data(load_all())
    n = _known["norm"].normalize(text)
    return len(n.ingredients) - len(n.not_recognised)


def _offline_read(fn, prepared: bytes, box):
    r = _offline_read_raw(fn, prepared, box)
    if r.get("readable") and _known_count(r.get("ingredients_text", "")) < config.OFFLINE_MIN_KNOWN:
        log.info("Photo: offline read looked unreliable, not shown")
        return {"readable": False, "ingredients_text": "", "confidence_note": UNRELIABLE_OFFLINE}
    return r


def _offline_read_raw(fn, prepared: bytes, box):
    """The offline reader can't find the list by itself on a busy label, so if an AI already found
    where it is, read that close-up first. Otherwise (or if that fails) read the whole photo."""
    close = photo_reader.close_up_jpeg(prepared, box) if box and fn is ocr.read_ingredients else None
    if close:
        r = fn(close, "image/jpeg", close_up=True)
        if r.get("readable"):
            return {**r, "used_close_up": True,
                    "incomplete_reason": "it was read offline without AI, so words may be missing or wrong"}
    return fn(prepared, "image/jpeg")


def friendly_reader(name: str) -> str:
    if name.startswith("groq:"):
        return "Groq"
    if name.startswith("gemini:"):
        return "Gemini (" + name.split(":", 1)[1] + ")"
    return "the offline reader" if name == "offline_ocr" else name


# What each photo reading is doing right now, so the page can say "Trying Groq (1 of 4)...".
# Short-lived status only: removed when the reading ends, and nothing about the photo is kept.
PROGRESS: dict[str, dict] = {}


def read_photo(chain, prepared: bytes, clock=time.monotonic, on_try=lambda name, n, total: None):
    """Try each reader in order. Stop at the first complete answer. An unreadable or possibly cut-short
    answer moves on to the next AI, and at the end the best answer is kept. Offline reading is only
    used when no AI managed to read anything. After PHOTO_TOTAL_SECONDS no more AIs are tried (offline
    reading is quick, so it still runs), so you're never left waiting for minutes.
    Returns (result, reader_name, notes) where notes = {"busy": [...], "out_of_time": bool}."""
    best, best_name, any_ai_read, box = None, None, False, None
    notes = {"busy": [], "out_of_time": False}
    started = clock()
    chain = best_first("photo", chain)
    for n, (name, fn) in enumerate(chain, start=1):
        if name == "offline_ocr" and any_ai_read:
            break
        if name != "offline_ocr" and clock() - started > config.PHOTO_TOTAL_SECONDS:
            notes["out_of_time"] = True
            log.info("Photo: %s skipped (out of time)", name)
            continue
        if cooling_down(name):
            notes["busy"].append(name)
            log.info("Photo: %s skipped (cooling down after being busy)", name)
            continue
        on_try(name, n, len(chain))
        t0 = clock()
        try:
            if name == "offline_ocr":
                raw = _offline_read(fn, prepared, box)
            elif getattr(fn, "accepts_box", False) and (box or needed_zoom(name)):
                raw = fn(prepared, "image/jpeg", box_hint=box, zoom_first=needed_zoom(name))
            else:
                raw = fn(prepared, "image/jpeg")
            result = _normalise(raw)
        except Exception as exc:
            box = box or getattr(exc, "box", None)
            note_failure(name, exc)
            if cooling_down(name):
                notes["busy"].append(name)
            log.warning("Photo: %s failed after %.1fs (%s)", name, clock() - t0, describe_failure(exc))
            continue
        log.info("Photo: %s took %.1fs: %s%s", name, clock() - t0,
                 "unreadable" if not result["readable"] else
                 ("may be incomplete" if result["possibly_incomplete"] else "complete"),
                 " (close-up)" if result.get("used_close_up") else "")
        box = box or result.get("box")
        if result["readable"] and name != "offline_ocr":
            any_ai_read = True
        if best is None or photo_reader.better(best, result) is result:
            best, best_name = result, name
        if result["readable"] and not result["possibly_incomplete"]:
            remember_good_reader("photo", name, bool(result.get("used_close_up")))
            break
        log.info("Photo: %s answer %s, trying the next reader", name,
                 "looks incomplete (" + result["incomplete_reason"] + ")" if result["readable"] else "was unreadable")
    log.info("Photo: finished in %.1fs total, answer from %s", clock() - started, best_name or "nobody")
    return best, best_name, notes


BUSY_MESSAGE = ("The AI photo readers are busy or have reached their free limit right now. Please try again in a "
                "few minutes, or paste the ingredient list instead.")


@router.get("/extract/progress/{progress_id}")
def extract_progress(progress_id: str):
    """Which reader is being tried right now for this photo (empty when finished or unknown)."""
    return PROGRESS.get(progress_id[:64], {"reader": "", "n": 0, "of": 0})


@router.post("/extract")
async def extract(image: UploadFile = File(...), services: Services = Depends(get_services),
                  x_progress_id: str | None = Header(None)):
    if image.content_type not in config.ALLOWED_IMAGE_TYPES:
        raise ApiError(422, "INVALID_IMAGE", f"Please upload a JPEG or PNG under {config.MAX_IMAGE_MB} MB.",
                       [{"field": "image", "issue": f"type {image.content_type}"}])
    raw = await image.read(config.MAX_IMAGE_BYTES + 1)
    if len(raw) > config.MAX_IMAGE_BYTES:
        raise ApiError(422, "INVALID_IMAGE", f"That photo is over {config.MAX_IMAGE_MB} MB. Please upload a smaller one.",
                       [{"field": "image", "issue": "too large"}])
    if not raw:
        raise ApiError(422, "INVALID_IMAGE", "The uploaded file is empty.")
    prepared = _prepare_image(raw)
    chain = [("ai", services.extract)] if callable(services.extract) else list(services.extract)
    pid = (x_progress_id or "")[:64]

    def on_try(name, n, total):
        if pid:
            PROGRESS[pid] = {"reader": friendly_reader(name), "n": n, "of": total}
    try:
        result, name, notes = await run_in_threadpool(read_photo, chain, prepared, time.monotonic, on_try)
    finally:
        PROGRESS.pop(pid, None)
    if name and not result["readable"] and notes["busy"]:
        result = {**result, "confidence_note": BUSY_MESSAGE}       # say WHY nothing was read
    if name:
        body = {**result, "source": "label_photo", "reader": name, "reader_label": friendly_reader(name),
                "warning": "Please check this text against the label before comparing."}
        if result["possibly_incomplete"]:
            body["warning"] = ("This list may be incomplete (" + result["incomplete_reason"] + "). Compare it with the "
                               "label and add anything missing, or paste the full list instead.")
        return body
    raise ApiError(502, "EXTRACTION_FAILED", BUSY_MESSAGE if notes["busy"] else
                   "We couldn't read the photo right now. Please try again, or paste the ingredients instead.")
