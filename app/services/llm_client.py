"""The only file that talks to AI services. They are used for exactly two jobs:
(a) reading the ingredient text on a label photo, and (b) wording the summary from flags.
They never decide flags or rankings, and are never asked what a product contains.

Backup chain (each step is tried only if the one before fails or is busy):
  Groq (if you added a key) -> main Gemini model -> lighter Gemini models -> no AI
  (set AI_FIRST=gemini in .env to put Gemini first). A busy model is skipped for 5 minutes.
For the summary, "no AI" means the template. For photos it means offline Tesseract (Phase 4 add-on).
"""
import base64
import io
import json
import re
import time

import logging

import httpx

from app import config

log = logging.getLogger("skincare")

RETRY_WAITS_SECONDS = (2, 5)   # used by the Phase 1 check only; the backup chain replaces retries elsewhere


class LLMNotConfigured(Exception):
    """Raised when there is no API key for a provider."""


class LLMBusy(Exception):
    """Raised when a provider is overloaded (error 503/429) even after retrying. That's their side, not a bug here."""


def _is_busy(exc: Exception) -> bool:
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    return code in (429, 500, 502, 503, 504) or "UNAVAILABLE" in str(exc)


# ---------------- Gemini ----------------

def _timeout_ms(seconds: float) -> int:
    return int(max(seconds, config.LLM_MIN_TIMEOUT_SECONDS) * 1000)


def _gemini_client(timeout_seconds: float | None = None):
    if not config.GEMINI_API_KEY:
        raise LLMNotConfigured("No GEMINI_API_KEY found. Add it to your .env file.")
    from google import genai
    from google.genai import types

    return genai.Client(api_key=config.GEMINI_API_KEY,
                        http_options=types.HttpOptions(timeout=_timeout_ms(timeout_seconds or config.LLM_TIMEOUT_SECONDS)))


def _generate(contents, client=None, sleep=time.sleep, retry_waits=RETRY_WAITS_SECONDS, gen_config=None, model=None):
    client = client or _gemini_client()
    kwargs = {"model": model or config.GEMINI_MODEL, "contents": contents}
    if gen_config is not None:
        kwargs["config"] = gen_config
    for attempt in range(len(retry_waits) + 1):
        try:
            response = client.models.generate_content(**kwargs)
            break
        except Exception as exc:
            if not _is_busy(exc):
                raise
            if attempt == len(retry_waits):
                raise LLMBusy("The AI is busy right now (their side). Try again in a few minutes.") from exc
            sleep(retry_waits[attempt])
    text = (getattr(response, "text", "") or "").strip()
    if not text:
        raise RuntimeError("The AI answered with an empty reply.")
    return text


def ask(prompt: str, client=None, sleep=time.sleep) -> str:
    """Send one text prompt to the main Gemini model (used by the Phase 1 check)."""
    return _generate(prompt, client=client, sleep=sleep)


# ---------------- Groq (second free provider, optional) ----------------

class GroqRequestError(RuntimeError):
    """Groq refused the request itself (error 400). The message carries Groq's own reason."""


def _groq_reason(resp) -> str:
    try:
        err = resp.json().get("error", {})
        return " ".join(str(x) for x in (err.get("code") or err.get("type") or "", err.get("message", "")) if x)[:300]
    except Exception:
        return (resp.text or "")[:300]


def _groq_chat(model: str, content, json_mode: bool = False, http=None, timeout_seconds: float | None = None,
               max_tokens: int | None = None) -> str:
    if not config.GROQ_API_KEY:
        raise LLMNotConfigured("No GROQ_API_KEY in .env")
    body = {"model": model, "messages": [{"role": "user", "content": content}], "temperature": 0.1}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    if max_tokens:
        body["max_completion_tokens"] = max_tokens
    own = http is None
    http = http or httpx.Client(timeout=max(timeout_seconds or config.LLM_TIMEOUT_SECONDS, config.LLM_MIN_TIMEOUT_SECONDS))
    try:
        resp = http.post(f"{config.GROQ_BASE_URL}/chat/completions", json=body,
                         headers={"Authorization": f"Bearer {config.GROQ_API_KEY}"})
    finally:
        if own:
            http.close()
    if resp.status_code in (429, 500, 502, 503, 504):
        raise LLMBusy(f"Groq is busy (error {resp.status_code}).")
    if 400 <= resp.status_code < 500:
        exc = GroqRequestError(f"Groq refused the request (error {resp.status_code}): {_groq_reason(resp)}")
        exc.status = resp.status_code
        raise exc
    resp.raise_for_status()
    text = (resp.json()["choices"][0]["message"].get("content") or "")
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()   # some models show their thinking
    if not text:
        raise RuntimeError("Groq answered with an empty reply.")
    return text


# ---------------- (a) reading a label photo ----------------
# The two-step reading (find the list, then read a sharp close-up) lives in photo_reader.py.
# Each provider below only supplies "send this picture + this instruction, give me JSON back".

def _parse_json(text: str) -> dict:
    text = text.strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)          # tolerate ```json fences
    try:
        return json.loads(m.group(0) if m else text)
    except (ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("The AI's reply about the photo wasn't in the expected format.") from exc


def _gemini_ask_json(client, model, sleep, retry_waits):
    real = not hasattr(client, "_fake")
    def ask(jpeg: bytes, prompt: str) -> dict:
        gen_config = None
        if real:
            from google.genai import types
            contents = [types.Part.from_bytes(data=jpeg, mime_type="image/jpeg"), prompt]
            gen_config = types.GenerateContentConfig(temperature=0, response_mime_type="application/json",
                                                     media_resolution=types.MediaResolution.MEDIA_RESOLUTION_HIGH,
                                                     max_output_tokens=4096)
        else:
            contents = [{"image_bytes": jpeg, "mime_type": "image/jpeg"}, prompt]
        return _parse_json(_generate(contents, client=client, sleep=sleep, gen_config=gen_config, model=model,
                                     retry_waits=retry_waits))
    return ask


def extract_ingredients(image_bytes: bytes, mime_type: str = "image/jpeg", client=None, sleep=time.sleep,
                        model=None, retry_waits=RETRY_WAITS_SECONDS, box_hint=None, zoom_first=False) -> dict:
    """Read the ingredient list from a label photo with one Gemini model."""
    from app.services import photo_reader
    if client is None:
        client = _gemini_client(config.LLM_PHOTO_TIMEOUT_SECONDS)
    else:
        try:
            client._fake = True                               # test stand-in: skip Google-only settings
        except AttributeError:
            pass
    return photo_reader.read_label(image_bytes, _gemini_ask_json(client, model, sleep, retry_waits), box_hint,
                                   zoom_first)


def _groq_image(jpeg: bytes, side: int) -> bytes:
    """Keep a picture inside Groq's limits: at most `side` pixels and GROQ_MAX_IMAGE_BYTES."""
    from PIL import Image
    img = Image.open(io.BytesIO(jpeg)).convert("RGB")
    img.thumbnail((side, side), Image.LANCZOS)
    for quality in (90, 80, 70, 60):
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=quality)
        if out.tell() <= config.GROQ_MAX_IMAGE_BYTES:
            break
    return out.getvalue()


def groq_extract_ingredients(image_bytes: bytes, mime_type: str = "image/jpeg", http=None, box_hint=None,
                             zoom_first=False) -> dict:
    from app.services import photo_reader

    def send(jpeg: bytes, prompt: str, json_mode: bool) -> dict:
        url = f"data:image/jpeg;base64,{base64.b64encode(jpeg).decode('ascii')}"
        content = [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": url}}]
        return _parse_json(_groq_chat(config.GROQ_VISION_MODEL, content, json_mode=json_mode, http=http,
                                      timeout_seconds=config.LLM_PHOTO_TIMEOUT_SECONDS, max_tokens=4096))

    def ask(jpeg: bytes, prompt: str) -> dict:
        try:
            return send(_groq_image(jpeg, config.GROQ_MAX_IMAGE_SIDE_PX), prompt, json_mode=True)
        except GroqRequestError as exc:
            if getattr(exc, "status", 400) != 400 or "json" not in str(exc).lower():
                raise                      # a size or key problem won't be fixed by trying again right away
            # Groq's strict-JSON check failed on a long list: one more try without it (same picture).
            log.warning("Photo: Groq's JSON check failed, trying once without it (%s)", describe_failure(exc))
            return send(_groq_image(jpeg, config.GROQ_MAX_IMAGE_SIDE_PX), prompt, json_mode=False)
    return photo_reader.read_label(image_bytes, ask, box_hint, zoom_first)


# ---------------- (b) wording the summary ----------------

def write_summary(prompt: str, client=None, model=None) -> str:
    """One Gemini model, no retries: the backup chain moves on instead."""
    gen_config = None
    if client is None:
        from google.genai import types
        client = _gemini_client()
        gen_config = types.GenerateContentConfig(temperature=0.2, max_output_tokens=400)
    return _generate(prompt, client=client, retry_waits=(), gen_config=gen_config, model=model)


def groq_write_summary(prompt: str, http=None) -> str:
    return _groq_chat(config.GROQ_MODEL, prompt, http=http)


# ---------------- the backup chains ----------------

def _gemini_models() -> list[str]:
    models = [config.GEMINI_MODEL] + [m for m in config.GEMINI_FALLBACK_MODELS if m != config.GEMINI_MODEL]
    return list(dict.fromkeys(models))


def _ordered(gemini: list, groq: list) -> list:
    return gemini + groq if config.AI_FIRST == "gemini" else groq + gemini


def summary_providers() -> list[tuple[str, object]]:
    """[(name, function(prompt) -> text)] in the order they are tried. Providers without a key are left out."""
    gemini = [(f"gemini:{m}", (lambda p, m=m: write_summary(p, model=m))) for m in _gemini_models()] \
        if config.GEMINI_API_KEY else []
    groq = [(f"groq:{config.GROQ_MODEL}", groq_write_summary)] if config.GROQ_API_KEY else []
    return _ordered(gemini, groq)


def _with_box(fn):
    fn.accepts_box = True                            # can reuse where an earlier AI found the list
    return fn


def extract_providers() -> list[tuple[str, object]]:
    """[(name, function(image_bytes, mime) -> dict)] in the order they are tried, ending with offline OCR."""
    from app.services import ocr

    gemini = [(f"gemini:{m}", _with_box(lambda img, mime, box_hint=None, zoom_first=False, m=m:
                                        extract_ingredients(img, mime, model=m, retry_waits=(), box_hint=box_hint,
                                                            zoom_first=zoom_first)))
              for m in _gemini_models()] if config.GEMINI_API_KEY else []
    groq = [(f"groq:{config.GROQ_VISION_MODEL}",
             _with_box(lambda img, mime, box_hint=None, zoom_first=False:
                       groq_extract_ingredients(img, mime, box_hint=box_hint, zoom_first=zoom_first)))] \
        if config.GROQ_API_KEY and config.GROQ_VISION_MODEL else []     # empty GROQ_VISION_MODEL = no Groq for photos
    return _ordered(gemini, groq) + [("offline_ocr", ocr.read_ingredients)]


# ---------------- cooldown: don't keep knocking on a busy door ----------------

_cooling_until: dict[str, float] = {}


def _is_busy_or_slow(exc: Exception) -> bool:
    text = str(exc).upper()
    return (isinstance(exc, (LLMBusy, TimeoutError, httpx.TimeoutException)) or _is_busy(exc)
            or "DEADLINE_EXCEEDED" in text or "TIMED OUT" in text or "TIMEOUT" in text)


def cooling_down(name: str, now=None) -> bool:
    return _cooling_until.get(name, 0) > (now if now is not None else time.monotonic())


def _is_quota(exc: Exception) -> bool:
    """Used up its free limit (rate limit or daily quota): no point asking again for a while."""
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None) or getattr(exc, "status", None)
    text = str(exc).upper()
    return code == 429 or "429" in text or "RESOURCE_EXHAUSTED" in text or "QUOTA" in text or "RATE LIMIT" in text \
        or "RATE_LIMIT" in text


def note_failure(name: str, exc: Exception, now=None) -> None:
    """A busy or slow AI is skipped for AI_COOLDOWN_SECONDS. One that hit its free limit, or refused the
    photo itself, is skipped for AI_QUOTA_COOLDOWN_SECONDS, so the next photo moves on instantly.
    Other errors (like a wrong setting) are not, so they keep showing up in the log until fixed."""
    if name == "offline_ocr":
        return
    now = now if now is not None else time.monotonic()
    if _is_quota(exc) or (isinstance(exc, GroqRequestError) and getattr(exc, "status", 400) == 400):
        _cooling_until[name] = now + config.AI_QUOTA_COOLDOWN_SECONDS
    elif _is_busy_or_slow(exc):
        _cooling_until[name] = now + config.AI_COOLDOWN_SECONDS


# The reader that last gave a complete answer is tried first next time (no point starting with one
# that keeps failing). Only an order, kept in memory; nothing about your photos is stored.
_last_good_reader: dict[str, str] = {}


_needed_zoom: dict[str, bool] = {}


def remember_good_reader(kind: str, name: str, used_close_up: bool = False) -> None:
    if name != "offline_ocr":
        _last_good_reader[kind] = name
        _needed_zoom[name] = used_close_up


def needed_zoom(name: str) -> bool:
    """Did this reader need the close-up last time? Then start with it (saves one call)."""
    return _needed_zoom.get(name, False)


def best_first(kind: str, chain: list) -> list:
    good = _last_good_reader.get(kind)
    if not good or good not in [n for n, _ in chain]:
        return list(chain)
    return [c for c in chain if c[0] == good] + [c for c in chain if c[0] != good]


def reset_cooldowns() -> None:
    _cooling_until.clear()
    _last_good_reader.clear()
    _needed_zoom.clear()


def run_chain(chain, call, accept=lambda result: [], label="AI"):
    """Try each (name, fn) in order. call(fn) does the work; accept(result) returns a list of
    problems (empty = accepted). Returns (result, name), or (None, None) if nothing worked."""
    for name, fn in chain:
        if cooling_down(name):
            log.info("%s: %s skipped (cooling down after being busy)", label, name)
            continue
        try:
            result = call(fn)
        except Exception as exc:
            note_failure(name, exc)
            log.warning("%s: %s skipped (%s)", label, name, describe_failure(exc))
            continue
        problems = accept(result)
        if not problems:
            return result, name
        log.warning("%s: %s reply rejected by the safety check (%s)", label, name, "; ".join(problems))
    return None, None


def describe_failure(exc: Exception) -> str:
    """One short line for the log, so a skipped provider is never silent. Never includes keys."""
    text = str(exc)
    for key in (config.GEMINI_API_KEY, config.GROQ_API_KEY):
        if key:
            text = text.replace(key, "***")
    return f"{type(exc).__name__}: {text[:300]}"
