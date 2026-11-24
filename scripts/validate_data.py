"""Phase 2: checks every file in data/ for gaps and typos.

Run from the project folder:  python -m scripts.validate_data
It ends with "All checks passed" or a numbered list of problems to fix.
"""
import re
import sys
from pathlib import Path

from app import config
from app.data_loader import dropdown_concerns, load_all, split_list, types_matched

RULE_COLUMNS = ["rule_id", "ingredient_family", "plain_name", "match_terms", "applies_to", "relevant_profiles",
                "flag_type", "severity", "rationale", "source"]
FLAG_TYPES = {"may_suit", "may_not_suit"}
SEVERITIES = {"low", "medium", "high"}
CATEGORIES = {"skin", "hair"}
APPLICATIONS = {"leave_on", "rinse_off"}


def banned_words_in(text: str) -> list[str]:
    low = text.lower()
    return [w for w in config.BANNED_WORDS if re.search(rf"\b{re.escape(w)}\b", low)]


def check_unique(rows, key, label, errors):
    seen = set()
    for i, r in enumerate(rows, start=2):
        v = r.get(key, "")
        if not v:
            errors.append(f"{label} line {i}: '{key}' is empty")
        elif v in seen:
            errors.append(f"{label} line {i}: '{v}' appears more than once")
        seen.add(v)
    return seen


def validate(data: dict) -> tuple[list[str], list[str]]:
    """Returns (errors, notes). Errors must be fixed; notes are for your information."""
    errors, notes = [], []

    # product_types.csv
    type_ids = check_unique(data["product_types"], "product_type", "product_types.csv", errors)
    type_category = {}
    for i, t in enumerate(data["product_types"], start=2):
        if t.get("category") not in CATEGORIES:
            errors.append(f"product_types.csv line {i}: category must be skin or hair")
        if t.get("application") not in APPLICATIONS:
            errors.append(f"product_types.csv line {i}: application must be leave_on or rinse_off")
        type_category[t.get("product_type")] = t.get("category")

    # concerns.csv and profiles.csv
    concern_ids = check_unique(data["concerns"], "concern_id", "concerns.csv", errors)
    concern_category = {c["concern_id"]: c.get("category") for c in data["concerns"]}
    for i, c in enumerate(data["concerns"], start=2):
        if c.get("category") not in CATEGORIES:
            errors.append(f"concerns.csv line {i}: category must be skin or hair")
        if "phrase" in c and not c.get("phrase"):
            errors.append(f"concerns.csv line {i}: phrase is empty")
    profile_tags = check_unique(data["profiles"], "profile_tag", "profiles.csv", errors)

    # aliases.csv
    alias_names = check_unique(data["aliases"], "alias", "aliases.csv", errors)
    for i, a in enumerate(data["aliases"], start=2):
        alias, std = a.get("alias", ""), a.get("standard_name", "")
        if not std:
            errors.append(f"aliases.csv line {i}: standard_name is empty")
        if alias != alias.lower() or std != std.lower():
            errors.append(f"aliases.csv line {i}: use lowercase only")
        if alias and alias == std:
            errors.append(f"aliases.csv line {i}: alias and standard_name are the same")
        if std in alias_names:
            errors.append(f"aliases.csv line {i}: standard_name '{std}' is itself listed as an alias (no chains)")

    # rules.csv
    rules = data["rules"]
    if rules and set(RULE_COLUMNS) - set(rules[0].keys()):
        errors.append(f"rules.csv: missing columns {sorted(set(RULE_COLUMNS) - set(rules[0].keys()))}")
        return errors, notes
    check_unique(rules, "rule_id", "rules.csv", errors)
    for i, r in enumerate(rules, start=2):
        where = f"rules.csv line {i} ({r.get('rule_id', '?')})"
        for col in RULE_COLUMNS:
            if not r.get(col):
                errors.append(f"{where}: '{col}' is empty")
        if r.get("rule_id") and not re.fullmatch(r"R\d{3}", r["rule_id"]):
            errors.append(f"{where}: rule_id should look like R001")
        if r.get("flag_type") and r["flag_type"] not in FLAG_TYPES:
            errors.append(f"{where}: flag_type must be may_suit or may_not_suit")
        if r.get("severity") and r["severity"] not in SEVERITIES:
            errors.append(f"{where}: severity must be low, medium or high")
        src = r.get("source", "")
        if src and (not src.startswith(("http://", "https://")) or "TO_FILL" in src):
            errors.append(f"{where}: source must be a real web link (found '{src}')")
        bad = banned_words_in(r.get("rationale", ""))
        if bad:
            errors.append(f"{where}: rationale uses banned word(s): {', '.join(bad)}")
        for term in split_list(r.get("match_terms", "")):
            if term != term.lower():
                errors.append(f"{where}: match term '{term}' must be lowercase")
            if term in alias_names:
                errors.append(f"{where}: match term '{term}' is an alias; use its standard_name instead")
        targets = split_list(r.get("applies_to", ""))
        for t in targets:
            if t not in type_ids and t not in ("all", "skin_all", "hair_all"):
                errors.append(f"{where}: unknown product type '{t}' in applies_to")
        for tag in split_list(r.get("relevant_profiles", "")):
            if tag == "any":
                continue
            kind, _, name = tag.partition(":")
            if kind == "concern":
                if name not in concern_ids:
                    errors.append(f"{where}: unknown concern '{name}'")
                elif not any(type_category.get(t) == concern_category[name]
                             for t in types_matched(r.get("applies_to", ""), data["product_types"])):
                    errors.append(f"{where}: concern '{name}' is {concern_category[name]} "
                                  f"but applies_to only lists other product types")
            elif kind == "profile":
                if name not in profile_tags:
                    errors.append(f"{where}: unknown profile '{name}'")
            else:
                errors.append(f"{where}: tag '{tag}' must start with concern: or profile: (or be 'any')")

    # seed_products.csv
    seen = set()
    empty = 0
    for i, s in enumerate(data["seed_products"], start=2):
        bc = s.get("barcode", "")
        if not re.fullmatch(r"\d{8,14}", bc):
            errors.append(f"seed_products.csv line {i}: barcode '{bc}' must be 8 to 14 digits")
        if bc in seen:
            errors.append(f"seed_products.csv line {i}: barcode '{bc}' appears more than once")
        seen.add(bc)
        if s.get("product_type") not in type_ids:
            errors.append(f"seed_products.csv line {i}: unknown product_type '{s.get('product_type')}'")
        if not s.get("ingredients_text"):
            empty += 1
    if empty:
        notes.append(f"seed_products.csv: {empty} product(s) have no ingredients yet; they will be skipped when seeding")

    used = {c for cs in dropdown_concerns(data).values() for c in cs}
    for c in data["concerns"]:
        if c["concern_id"] not in used:
            notes.append(f"Concern '{c['label']}' has no rules, so it will NOT appear in the dropdown")
    return errors, notes


def main(data_dir: Path | None = None) -> int:
    data = load_all(data_dir)
    errors, notes = validate(data)
    print(f"Loaded {len(data['rules'])} rules, {len(data['aliases'])} aliases, "
          f"{len(data['product_types'])} product types, {len(data['seed_products'])} seed products.\n")
    print("Concerns the dropdown will show for each product type:")
    labels = {c["concern_id"]: c["label"] for c in data["concerns"]}
    for ptype, concerns in dropdown_concerns(data).items():
        shown = ", ".join(labels.get(c, c) for c in concerns) or "(none yet)"
        print(f"  {ptype:<16} {shown}")
    if notes:
        print("\nNotes:")
        for n in notes:
            print(f"  - {n}")
    print()
    if errors:
        print(f"{len(errors)} problem(s) found:")
        for k, e in enumerate(errors, 1):
            print(f"  {k}. {e}")
        return 1
    print("All checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
