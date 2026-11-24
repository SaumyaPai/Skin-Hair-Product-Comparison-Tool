"""Reads the CSV files in data/. Every other part of the app gets the rules from here."""
import csv
from pathlib import Path

from app import config

LIST_SEP = "|"


def read_csv(path: Path) -> list[dict]:
    with Path(path).open(newline="", encoding="utf-8-sig") as f:  # -sig copes with Excel's hidden marker
        return [{k.strip(): (v or "").strip() for k, v in row.items() if k} for row in csv.DictReader(f)]


def split_list(value: str) -> list[str]:
    return [part.strip() for part in (value or "").split(LIST_SEP) if part.strip()]


def load_all(data_dir: Path | None = None) -> dict:
    d = Path(data_dir or config.DATA_DIR)
    return {
        "product_types": read_csv(d / "product_types.csv"),
        "concerns": read_csv(d / "concerns.csv"),
        "profiles": read_csv(d / "profiles.csv"),
        "rules": read_csv(d / "rules.csv"),
        "aliases": read_csv(d / "aliases.csv"),
        "seed_products": read_csv(d / "seed_products.csv") if (d / "seed_products.csv").exists() else [],
    }


def types_matched(applies_to: str, product_types: list[dict]) -> set[str]:
    """Turn an applies_to value (e.g. 'skin_all' or 'toner|serum') into product type ids."""
    out = set()
    for item in split_list(applies_to):
        if item == "all":
            out |= {t["product_type"] for t in product_types}
        elif item in ("skin_all", "hair_all"):
            cat = item.split("_")[0]
            out |= {t["product_type"] for t in product_types if t["category"] == cat}
        else:
            out.add(item)
    return out


def dropdown_concerns(data: dict) -> dict[str, list[str]]:
    """For each product type, the concerns that have at least one rule behind them.
    This is the ONLY list the UI may show, so a concern with no rule never appears."""
    result = {t["product_type"]: set() for t in data["product_types"]}
    for rule in data["rules"]:
        concerns = [tag.split(":", 1)[1] for tag in split_list(rule["relevant_profiles"])
                    if tag.startswith("concern:")]
        for ptype in types_matched(rule["applies_to"], data["product_types"]):
            if ptype in result:
                result[ptype].update(concerns)
    order = [c["concern_id"] for c in data["concerns"]]
    return {p: sorted(cs, key=lambda c: order.index(c) if c in order else 999) for p, cs in result.items()}
