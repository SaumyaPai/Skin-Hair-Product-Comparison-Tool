"""Turns messy ingredient text into clean, standard names. No AI, no guessing.

Example:  "Ingredients: Aqua, PARFUM (Fragrance)., Vitamin B3"
      ->  ingredients = ["water", "fragrance", "niacinamide"]
"""
import re
import unicodedata
from dataclasses import dataclass, field

LABEL_PREFIX = re.compile(r"^\s*(ingredients?|ingr[ée]dients?|inci)\s*[:\-]\s*", re.IGNORECASE)
MAY_CONTAIN = re.compile(r"^\s*(\[\s*)?(may contain|\+/-|\+/−)\s*[:\-]?\s*", re.IGNORECASE)
PERCENT = re.compile(r"\(?\s*\d+(?:[.,]\d+)?\s*%\s*\)?")
PARENS = re.compile(r"\s*\([^)]*\)")
AND_JOIN = re.compile(r"\s*\(\s*and\s*\)\s*", re.IGNORECASE)   # "Phenoxyethanol (and) Ethylhexylglycerin" = 2 ingredients
POLYQUAT = re.compile(r"\bpolyquaternium[\s\-]*(\d+)\b")


def compact(name: str) -> str:
    """'guar hydroxypropyl trimonium chloride' and 'guar hydroxypropyltrimonium chloride' -> same key."""
    return re.sub(r"[\s\-]", "", name)


@dataclass
class Normalized:
    ingredients: list[str] = field(default_factory=list)      # every ingredient, in label order, standard names where known
    not_recognised: list[str] = field(default_factory=list)   # ones not in our tables (shown to the user, never hidden)
    percentages: dict[str, str] = field(default_factory=dict)  # kept for later; not used by rules yet


def split_ingredients(text: str) -> list[str]:
    """Split on commas, semicolons, line breaks and "(and)", but not inside other round brackets."""
    text = LABEL_PREFIX.sub("", (text or "").strip())
    text = AND_JOIN.sub(", ", text)
    parts, buf, depth = [], [], 0
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")" and depth:
            depth -= 1
        if ch in ",;\n\r" and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return [p for p in parts if p.strip()]


def clean(item: str) -> tuple[str, str]:
    """Lowercase, tidy spaces and punctuation. Returns (clean_name, percentage_or_empty)."""
    s = unicodedata.normalize("NFKC", item).replace("–", "-").replace("—", "-")
    s = MAY_CONTAIN.sub("", s)
    pct = PERCENT.search(s)
    pct_text = pct.group(0).strip(" ()") if pct else ""
    s = PERCENT.sub(" ", s)
    s = s.replace("*", " ").replace("†", " ").replace("]", " ").replace("[", " ")
    s = re.sub(r"\(\s*\)", " ", s)                 # empty brackets left behind
    s = re.sub(r"\s+", " ", s).strip().strip(".").strip().lower()
    s = POLYQUAT.sub(r"polyquaternium-\1", s)        # "polyquaternium 44" -> "polyquaternium-44"
    return s, pct_text


class Normalizer:
    def __init__(self, aliases: list[dict], known_terms: set[str]):
        """aliases: rows of aliases.csv. known_terms: every standard name the rules use."""
        self.alias_map = {a["alias"]: a["standard_name"] for a in aliases}
        self.known = set(known_terms) | set(self.alias_map.values())
        self.compact_map = {compact(k): self.alias_map.get(k, k) for k in list(self.alias_map) + list(self.known)}

    def lookup(self, name: str) -> str | None:
        """Find the standard name for one cleaned item, or None if we don't know it."""
        candidates = [name]
        no_parens = PARENS.sub("", name).strip()
        if no_parens and no_parens != name:
            candidates.append(no_parens)                           # "aqua (water)" -> "aqua"
        candidates += [p.strip() for p in no_parens.split("/") if p.strip()]  # "aqua/water/eau"
        for c in candidates:
            if c in self.alias_map:
                return self.alias_map[c]
            if c in self.known:
                return c
        for c in candidates:                                      # same name, only spaces or hyphens differ
            if compact(c) in self.compact_map:
                return self.compact_map[compact(c)]
        return None

    def normalize(self, text: str) -> Normalized:
        out = Normalized()
        seen = set()
        for raw in split_ingredients(text):
            name, pct = clean(raw)
            if not name:
                continue
            standard = self.lookup(name)
            final = standard or name
            if final in seen:
                continue
            seen.add(final)
            out.ingredients.append(final)
            if pct:
                out.percentages[final] = pct
            if standard is None:
                out.not_recognised.append(name)
        return out


def from_data(data: dict) -> Normalizer:
    """Build a Normalizer from the loaded CSV files."""
    from app.data_loader import split_list
    terms = {t for r in data["rules"] for t in split_list(r["match_terms"])}
    return Normalizer(data["aliases"], terms)
