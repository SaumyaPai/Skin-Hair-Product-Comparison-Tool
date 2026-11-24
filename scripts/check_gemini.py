"""Phase 1 check: send one short prompt to Gemini and print the reply.

Run from the project folder:  python -m scripts.check_gemini
"""
import sys

from app import config
from app.services.llm_client import LLMBusy, LLMNotConfigured, ask

PROMPT = "Reply with exactly this sentence and nothing else: Gemini is connected."


def main() -> int:
    print(f"Using model: {config.GEMINI_MODEL}")
    try:
        reply = ask(PROMPT)
    except LLMNotConfigured as exc:
        print(f"NOT READY: {exc}")
        return 1
    except LLMBusy as exc:
        print(f"BUSY: {exc}")
        return 1
    except Exception as exc:  # show a short reason, not a wall of technical text
        print(f"FAILED: Gemini did not answer ({type(exc).__name__}: {str(exc)[:200]})")
        return 1
    print(f"Gemini replied: {reply}")
    print("PASS: Gemini is working.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
