"""Settings read from the .env file. Nothing secret is written in code."""
import os

from dotenv import load_dotenv

load_dotenv()

APP_VERSION = "1.0.0"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip()
OBF_USER_AGENT = os.getenv("OBF_USER_AGENT", "SkincareCompare/0.1 (personal learning project)").strip()
OBF_BASE_URL = "https://world.openbeautyfacts.org"
OBF_TIMEOUT_SECONDS = 10

# ---- Phase 2: data files and wording rules ----
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "app.db"

# Words that must never appear in a rule's rationale (or, later, in a summary).
# Matched as whole words, ignoring upper/lower case.
BANNED_WORDS = [
    "good", "bad", "best", "worst", "cure", "cures", "cured", "fix", "fixes", "fixed",
    "treat", "treats", "treated", "treatment", "heal", "heals", "healing",
    "guarantee", "guaranteed", "miracle", "clinically proven",
]

# ---- Phase 3: ranking settings (change here, nowhere else) ----
SEVERITY_WEIGHT = {"low": 1, "medium": 2, "high": 3}
SENSITIVITY_MULTIPLIER = 1.5          # cautions count more for sensitive users, on rules tagged profile:sensitive
APPLICATION_WEIGHT = {"leave_on": 1.0, "rinse_off": 0.5}

# ---- Phase 4: API settings ----
CACHE_FRESH_DAYS = 30
MAX_IMAGE_MB = 10
MAX_IMAGE_BYTES = MAX_IMAGE_MB * 1024 * 1024
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png"}
MAX_IMAGE_SIDE_PX = 4000            # only very large photos are capped; reading uses sharp close-ups
LLM_TIMEOUT_SECONDS = 15           # summary; Gemini refuses anything under 10 seconds
OFFLINE_MIN_KNOWN = 3              # an offline read must contain at least 3 ingredients we recognise, else it's junk
PHOTO_TOTAL_SECONDS = 40            # after this, no more AIs are tried for one photo (offline reading still is)
LLM_PHOTO_TIMEOUT_SECONDS = 30     # reading a photo takes longer
LLM_MIN_TIMEOUT_SECONDS = 10       # Google's minimum
SUMMARY_MAX_WORDS = 150
# Where an ingredient sits on the label. Labels list ingredients from most to least (for those above 1%,
# FDA 21 CFR 701.3), so one near the top is likely present in a larger amount than one lower down.
# "Near the top" = within the first third of the list (at least the first 5 ingredients).
# Switch: when False, position changes neither the order nor the "why" lines (approved and on).
USE_LABEL_POSITION = True
POSITION_TOP_MIN = 5
POSITION_STEP = 0.05                # each place down the label counts 5% less: 1st = 1.0, 2nd = 0.95 ...
POSITION_FLOOR = 0.5                # ... but never less than half (11th place and below)
POSITION_SOURCE = "https://www.fda.gov/cosmetics/cosmetics-labeling-regulations/summary-cosmetics-labeling-requirements"

# Extra words the AI summary must never use (on top of BANNED_WORDS)
SUMMARY_BANNED_EXTRA = ["score", "out of 100", "/100", "diagnose", "diagnosis", "prescribe", "safe", "unsafe",
                        "recommend", "recommended",
                        # claims about what a product is FOR: only the flags can say that
                        "designed", "formulated", "made for", "intended", "targets", "targeted", "specifically",
                        "suitable", "ideal", "perfect", "effective", "works", "both products are",
                        "leads", "clear winner", "superior", "better", "stronger",
                        # system words a shopper shouldn't have to read
                        "flag", "flags", "flagged", "our table", "rule", "rules", "ingredient group",
                        "ingredient groups", "ingredient family"]
DISCLAIMER = ("This is general information about ingredients, not medical advice. Patch test new products "
              "and talk to a dermatologist or doctor about skin or scalp conditions.")

# ---- Phase 4 add-on: backup AI chain and offline photo reading ----
GEMINI_FALLBACK_MODELS = [m.strip() for m in os.getenv(
    "GEMINI_FALLBACK_MODELS", "gemini-3.5-flash-lite,gemini-3.6-flash").split(",") if m.strip()]
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b").strip()
GROQ_VISION_MODEL = os.getenv("GROQ_VISION_MODEL", "qwen/qwen3.8-27b").strip()
GROQ_MAX_IMAGE_SIDE_PX = 2048       # Groq shrinks pictures anyway; sending bigger only risks a refusal
GROQ_MAX_IMAGE_BYTES = 3 * 1024 * 1024   # about 4 MB once encoded, inside Groq's limit for pictures sent directly
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
TESSERACT_CMD = os.getenv("TESSERACT_CMD", r"C:\Program Files\Tesseract-OCR\tesseract.exe").strip()

# ---- Backup chain order and cooldown ----
# Which provider goes first: "groq" (default) or "gemini". The other one becomes the backup.
AI_FIRST = os.getenv("AI_FIRST", "groq").strip().lower()
AI_COOLDOWN_SECONDS = int(os.getenv("AI_COOLDOWN_SECONDS", "300"))   # skip a busy model for 5 minutes
AI_QUOTA_COOLDOWN_SECONDS = 1800   # an AI that hit its free limit (or refused the photo) is skipped for 30 minutes
