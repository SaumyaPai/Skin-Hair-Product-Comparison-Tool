"""Shows which AI models your keys can use, and the backup order the app will try.

Run from the project folder:  python -m scripts.list_models
If a model in the chain isn't in your list, change GEMINI_FALLBACK_MODELS (or GROQ_MODEL) in .env.
"""
import sys

import httpx

from app import config
from app.services import llm_client, ocr


GEMINI_MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"


def short_reason(exc: Exception) -> str:
    """A one-line reason that never includes your key."""
    if isinstance(exc, httpx.HTTPStatusError):
        try:
            msg = exc.response.json()["error"]["message"]
        except Exception:
            msg = exc.response.text[:200]
        return f"error {exc.response.status_code}: {msg}"
    text = str(exc).replace(config.GEMINI_API_KEY, "***") if config.GEMINI_API_KEY else str(exc)
    return f"{type(exc).__name__}: {text[:200]}"


def gemini_flash_models(http=None) -> list[str]:
    """Asks Google directly (plain web request) which models this key can use for generating text."""
    own = http is None
    http = http or httpx.Client(timeout=15)
    names, token = [], None
    try:
        while True:
            params = {"pageSize": 1000, **({"pageToken": token} if token else {})}
            r = http.get(GEMINI_MODELS_URL, params=params, headers={"x-goog-api-key": config.GEMINI_API_KEY})
            r.raise_for_status()
            body = r.json()
            for m in body.get("models", []):
                name = (m.get("name") or "").removeprefix("models/")
                if "flash" in name and "generateContent" in (m.get("supportedGenerationMethods") or []):
                    names.append(name)
            token = body.get("nextPageToken")
            if not token:
                return sorted(names)
    finally:
        if own:
            http.close()


def main() -> int:
    print("Backup order for the summary:")
    for name, _ in llm_client.summary_providers():
        print(f"  - {name}")
    print("  - template (always works)")
    print("\nBackup order for label photos:")
    for name, _ in llm_client.extract_providers():
        print(f"  - {name}{'' if name != 'offline_ocr' or ocr.is_available() else '  (NOT INSTALLED: see docs/guides/PHASE4_ADDON_GUIDE.md)'}")

    if config.GEMINI_API_KEY:
        print("\nGemini 'flash' models your key can use:")
        try:
            for name in gemini_flash_models():
                print(f"  {name}")
        except Exception as exc:
            print(f"  Could not list Gemini models: {short_reason(exc)}")
    else:
        print("\nNo GEMINI_API_KEY in .env.")

    if config.GROQ_API_KEY:
        print("\nGroq models your key can use:")
        try:
            r = httpx.get(f"{config.GROQ_BASE_URL}/models", timeout=10,
                          headers={"Authorization": f"Bearer {config.GROQ_API_KEY}"})
            r.raise_for_status()
            for m in sorted(x["id"] for x in r.json().get("data", [])):
                print(f"  {m}")
        except Exception as exc:
            print(f"  Could not list Groq models ({type(exc).__name__}).")
    else:
        print("\nNo GROQ_API_KEY in .env (optional), so Groq is skipped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
