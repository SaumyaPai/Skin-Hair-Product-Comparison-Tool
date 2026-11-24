"""Decides the flags. Pure code: the same input always gives the same output.

A rule fires for a product when ALL of these are true:
  1. the product's type is in the rule's applies_to
  2. the product contains at least one of the rule's match_terms
  3. the rule's relevant_profiles overlap the shopper's concerns or profile (or the rule says 'any')
"""
from dataclasses import dataclass

from app.data_loader import split_list, types_matched

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


@dataclass(frozen=True)
class Rule:
    rule_id: str
    ingredient_family: str
    plain_name: str
    match_terms: tuple[str, ...]
    product_types: frozenset[str]
    tags: frozenset[str]
    flag_type: str
    severity: str
    rationale: str
    source: str


def user_tags(concerns: list[str], profile: dict | None) -> set[str]:
    """Turn the shopper's choices into the same tags the rules use."""
    profile = profile or {}
    tags = {f"concern:{c}" for c in concerns}
    if profile.get("sensitive"):
        tags.add("profile:sensitive")
    if profile.get("avoid_fragrance"):
        tags.add("profile:avoid_fragrance")
    return tags


class RuleEngine:
    def __init__(self, data: dict):
        # "phrase" is how a concern reads inside a sentence, e.g. "dry skin"
        self.concern_phrases = {c["concern_id"]: c.get("phrase") or c["label"].lower() for c in data["concerns"]}
        self.rules = [
            Rule(
                rule_id=r["rule_id"],
                ingredient_family=r["ingredient_family"],
                plain_name=(r.get("plain_name") or r["ingredient_family"]).strip(),
                match_terms=tuple(split_list(r["match_terms"])),
                product_types=frozenset(types_matched(r["applies_to"], data["product_types"])),
                tags=frozenset(split_list(r["relevant_profiles"])),
                flag_type=r["flag_type"],
                severity=r["severity"],
                rationale=r["rationale"],
                source=r["source"],
            )
            for r in data["rules"]
        ]

    def _label(self, rule: Rule, matched_tags: list[str]) -> str:
        concerns = [self.concern_phrases.get(t.split(":", 1)[1], t)
                    for t in matched_tags if t.startswith("concern:")]
        if rule.flag_type == "may_suit":
            return "Contains ingredients commonly used for " + " and ".join(concerns or ["your selection"])
        parts = []
        if "profile:sensitive" in matched_tags:
            parts.append("May not suit sensitive skin or scalp")
        if "profile:avoid_fragrance" in matched_tags:
            parts.append("Contains fragrance, which you prefer to avoid")
        if concerns:
            parts.append("May not suit " + " or ".join(concerns))
        return "; ".join(parts) or "May not suit you"

    def evaluate(self, product_type: str, ingredients: list[str], concerns: list[str],
                 profile: dict | None = None) -> list[dict]:
        """Return the flags for one product, sorted so cautions come first, then by severity."""
        tags = user_tags(concerns, profile)
        present = set(ingredients)
        flags = []
        for rule in self.rules:
            if product_type not in rule.product_types:
                continue
            matched_tags = sorted(rule.tags & tags)
            if not matched_tags and "any" not in rule.tags:
                continue
            matched = [i for i in ingredients if i in rule.match_terms]   # keeps label order
            if not matched:
                continue
            flags.append({
                "rule_id": rule.rule_id,
                "flag_type": rule.flag_type,
                "ingredient_family": rule.ingredient_family,
                "plain_name": rule.plain_name,                      # how the shopper sees it
                "matched_ingredients": matched,
                "position": ingredients.index(matched[0]) + 1,      # 1 = first on the label
                "list_length": len(ingredients),
                "severity": rule.severity,
                "label": self._label(rule, matched_tags),
                "reason": rule.rationale,
                "source": rule.source,
                "matched_tags": matched_tags,
                "sensitivity_rule": "profile:sensitive" in rule.tags,
            })
        flags.sort(key=lambda f: (f["flag_type"] != "may_not_suit", SEVERITY_ORDER[f["severity"]], f["rule_id"]))
        return flags
