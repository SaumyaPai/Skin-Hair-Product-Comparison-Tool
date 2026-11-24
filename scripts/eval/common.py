"""Shared bits for the Phase 6 evaluation scripts.

Your own evaluation files live in two folders that updates never touch:
  eval_inputs/    what you fill in (photos and their true lists, barcodes, comparisons, user-test answers)
  eval_results/   what the scripts write (one file per measure, plus RESULTS.md)
"""
import csv
import json
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = Path(__file__).resolve().parent / "templates"
INPUTS = ROOT / "eval_inputs"
RESULTS = ROOT / "eval_results"


def stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def save_json(name: str, data) -> Path:
    RESULTS.mkdir(exist_ok=True)
    path = RESULTS / name
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def load_json(name: str):
    path = RESULTS / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def save_csv(name: str, rows: list[dict]) -> Path:
    RESULTS.mkdir(exist_ok=True)
    path = RESULTS / name
    with path.open("w", newline="", encoding="utf-8") as f:
        if rows:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
    return path


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return [{k.strip(): (v or "").strip() for k, v in r.items() if k} for r in csv.DictReader(f)]


def need(path: Path, what: str) -> bool:
    if path.exists():
        return True
    print(f"Missing {path}. Run  python -m scripts.eval.setup  first, then {what}.")
    return False


def pause(seconds: float):
    """A short gap between AI calls, to stay inside the free per-minute limits."""
    if seconds > 0:
        time.sleep(seconds)
