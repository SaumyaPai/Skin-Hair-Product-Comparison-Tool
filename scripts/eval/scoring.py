"""The yardsticks used by the measures. Kept in one place, with no internet, so tests can check them."""
import difflib
import re

from app.data_loader import split_list
from app.services.normalizer import from_data

NEAR = 0.85
# Common ingredient names a chatbot likes to mention, on top of everything in our own tables, so a
# made-up "its ceramides..." is caught even when our rules don't cover ceramides.
COMMON_INGREDIENTS = [
    "ceramide", "peptide", "retinol", "retinoid", "hyaluronic acid", "sodium hyaluronate", "vitamin c", "vitamin e",
    "vitamin a", "vitamin b5", "panthenol", "niacinamide", "salicylic acid", "glycolic acid", "lactic acid",
    "mandelic acid", "azelaic acid", "kojic acid", "arbutin", "tranexamic acid", "squalane", "shea butter",
    "cocoa butter", "jojoba oil", "argan oil", "coconut oil", "castor oil", "almond oil", "rosemary oil",
    "tea tree oil", "aloe vera", "centella", "green tea", "licorice", "allantoin", "urea", "glycerin",
    "dimethicone", "silicone", "keratin", "biotin", "collagen", "zinc oxide", "titanium dioxide", "spf",
    "fragrance", "parfum", "essential oil", "alcohol", "sulfate", "paraben", "menthol", "benzoyl peroxide",
    "sulfur", "zinc pyrithione", "ketoconazole", "caffeine", "bakuchiol", "snail mucin", "mineral oil",
    "petrolatum", "lanolin", "beeswax", "oat", "honey", "clay", "charcoal", "ahas", "bhas", "aha", "bha",
]          # two names this similar count as "nearly right" (a letter or two off)


def ingredient_list(text: str, normalizer) -> list[str]:
    return normalizer.normalize(text or "").ingredients


def score_reading(truth_text: str, read_text: str, normalizer) -> dict:
    """Compares what a reader got with the true list typed from the pack.
    exact   = true ingredients read exactly right
    near    = read with a small spelling slip (still counted as not exact)
    missing = true ingredients not read at all
    invented = read items that are not on the pack at all (the hallucination count)"""
    truth = ingredient_list(truth_text, normalizer)
    read = ingredient_list(read_text, normalizer)
    left = list(read)
    exact, near, missing = [], [], []
    for t in truth:
        if t in left:
            exact.append(t)
            left.remove(t)
    for t in [t for t in truth if t not in exact]:
        close = difflib.get_close_matches(t, left, n=1, cutoff=NEAR)
        if close:
            near.append((t, close[0]))
            left.remove(close[0])
        else:
            missing.append(t)
    # a name cut in two by a line break or a misread mark ("cetearyl" for "cetearyl alcohol") is a slip, not an invention
    for t in list(missing):
        part = next((r for r in left if len(r) >= 4 and (r in t or t in r
                                                          or difflib.SequenceMatcher(None, t, r).ratio() >= 0.75)), None)
        if part:
            near.append((t, part))
            missing.remove(t)
            left.remove(part)
    total = len(truth)
    return {"true_count": total, "read_count": len(read), "exact": len(exact), "near": len(near),
            "missing": len(missing), "invented": len(left),
            "pct_exact": round(100 * len(exact) / total, 1) if total else 0.0,
            "pct_exact_or_near": round(100 * (len(exact) + len(near)) / total, 1) if total else 0.0,
            "near_pairs": [f"{a} -> {b}" for a, b in near], "missing_items": missing, "invented_items": left}


def _phrase_in(text: str, phrase: str) -> bool:
    """Whole words only; a plain plural counts too ("ceramides" for "ceramide")."""
    return re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?:e?s)?(?![a-z0-9])", text) is not None


class ClaimChecker:
    """Counts made-up or rule-breaking statements in any comparison text (ours or a chatbot's):
      invented_ingredients: an ingredient (or ingredient group) named in the text that none of the products contain
      judgement_words: good / bad / best / better, scores, medical words (cure, treat, heal, diagnose, ...)"""

    def __init__(self, data: dict):
        from app import config
        self.normalizer = from_data(data)
        self.family_terms: dict[str, set[str]] = {}
        for r in data["rules"]:
            self.family_terms.setdefault(r["ingredient_family"].lower(), set()).update(split_list(r["match_terms"]))
        vocab = set(self.family_terms)
        for terms in self.family_terms.values():
            vocab |= terms
        for a in data["aliases"]:
            vocab.add(a["alias"])
            vocab.add(a["standard_name"])
        vocab |= set(COMMON_INGREDIENTS)
        self.vocab = sorted({v.lower() for v in vocab if len(v) >= 3}, key=len, reverse=True)
        self.groups = {"ahas": ["glycolic acid", "lactic acid", "mandelic acid", "citric acid"],
                       "aha": ["glycolic acid", "lactic acid", "mandelic acid", "citric acid"],
                       "bhas": ["salicylic acid"], "bha": ["salicylic acid"], "sulfate": ["sulfate"],
                       "paraben": ["paraben"], "silicone": ["dimethicone", "siloxane", "dimethiconol"],
                       "alcohol": ["alcohol"], "vitamin c": ["ascorbic", "ascorbyl"], "vitamin e": ["tocopher"],
                       "vitamin b5": ["panthenol"], "vitamin a": ["retin"], "spf": ["zinc oxide", "titanium dioxide",
                       "homosalate", "octocrylene", "avobenzone", "methoxycinnamate"], "essential oil": ["oil"],
                       "aloe vera": ["aloe"], "centella": ["centella"], "oat": ["avena"], "green tea": ["camellia"],
                       "retinoid": ["retin"], "fragrance": ["parfum", "fragrance", "linalool", "limonene"],
                       "parfum": ["parfum", "fragrance"]}
        self.judgement = sorted(set(config.BANNED_WORDS) | {
            "better", "superior", "score", "out of 10", "out of 100", "/10", "diagnose", "prescribe", "recommend",
            "safe", "unsafe", "toxic", "harmful", "clinically"}, key=len, reverse=True)

    def check(self, text: str, product_texts: list[str], product_names: list[str] = ()) -> dict:
        low = " " + (text or "").lower() + " "
        for name in product_names:                      # a product called "Glow Serum" isn't an ingredient claim
            low = re.sub(rf"(?<![a-z0-9]){re.escape(name.lower())}(?![a-z0-9])", " ", low)
        present: set[str] = set()
        raw_all = " ".join(t.lower() for t in product_texts)
        for t in product_texts:
            present |= set(self.normalizer.normalize(t).ingredients)
        invented, seen = [], low
        for term in self.vocab:
            if not _phrase_in(seen, term):
                continue
            seen = re.sub(rf"(?<![a-z0-9]){re.escape(term)}(?:e?s)?(?![a-z0-9])", " ", seen)
            if term in self.groups and any(g in raw_all for g in self.groups[term]):
                ok = True
            elif term in self.family_terms:
                ok = bool(self.family_terms[term] & present) or _phrase_in(raw_all, term)
            else:
                std = self.normalizer.lookup(term) or term
                ok = std in present or _phrase_in(raw_all, term)
            if not ok:
                invented.append(term)
        judgement = [w for w in self.judgement if _phrase_in(low, w)]
        return {"invented_ingredients": invented, "judgement_words": judgement,
                "count": len(invented) + len(judgement)}


def parse_order(text: str, names: list[str]) -> str:
    """Finds the chatbot's 'ORDER: A > B > C' line and returns it tidied ('' if it gave none)."""
    m = None
    for m in re.finditer(r"ORDER\s*:\s*(.+)", text or "", flags=re.I):
        pass
    if not m:
        return ""
    found = []
    for part in re.split(r">", m.group(1)):
        part = part.strip(" .*`")
        groups = [g.strip(" .*`") for g in re.split(r"=", part)]
        tidy = []
        for g in groups:
            match = next((n for n in names if n.lower() == g.lower()), None) or \
                next((n for n in names if n.lower() in g.lower()), None)
            if match:
                tidy.append(match)
        if tidy:
            found.append(" = ".join(sorted(tidy)))
    return " > ".join(found)


def tool_order(ranking: list[dict]) -> str:
    """Our ranking as 'A > B = C' (ties joined with =)."""
    levels: dict[int, list[str]] = {}
    for r in ranking:
        levels.setdefault(r["rank"], []).append(r["display_name"])
    return " > ".join(" = ".join(sorted(v)) for _, v in sorted(levels.items()))


def first_choice(order: str) -> str:
    return order.split(" > ")[0] if order else ""
