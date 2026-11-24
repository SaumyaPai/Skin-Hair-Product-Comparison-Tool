"""Phase 2 tests: the rule table, aliases, product types, seed cache and validator.

Run from the project folder:  python -m pytest -v
These tests need no internet and no Gemini key.
"""
import copy

import pytest

from app import db
from app.data_loader import dropdown_concerns, load_all, read_csv, split_list
from scripts import seed_cache, validate_data
from scripts.validate_data import validate


@pytest.fixture(scope="module")
def data():
    return load_all()


def errors_for(data, change):
    """Copy the real data, apply one change, and return the validator's errors."""
    d = copy.deepcopy(data)
    change(d)
    return validate(d)[0]


# ---------- 1. Your real data files pass every check ----------

def test_real_data_has_no_errors(data):
    errors, _ = validate(data)
    assert errors == [], "\n".join(errors)


def test_validator_script_says_all_checks_passed(capsys):
    assert validate_data.main() == 0
    assert "All checks passed" in capsys.readouterr().out


def test_all_twelve_product_types_exist(data):
    assert len(data["product_types"]) == 12


def test_every_rule_has_a_real_source_link(data):
    for r in data["rules"]:
        assert r["source"].startswith("https://"), r["rule_id"]
        assert "TO_FILL" not in r["source"], r["rule_id"]


def test_rationales_use_commonly_used_for_style_wording(data):
    for r in data["rules"]:
        assert validate_data.banned_words_in(r["rationale"]) == [], r["rule_id"]


# ---------- 2. The rule table drives the dropdown ----------

def test_concerns_without_rules_never_appear(data):
    d = copy.deepcopy(data)
    d["rules"] = [r for r in d["rules"] if "concern:hair-fall" not in r["relevant_profiles"]]
    shown = {c for cs in dropdown_concerns(d).values() for c in cs}
    assert "hair-fall" not in shown          # remove its rules and it disappears
    assert "hair-fall" in dropdown_concerns(data)["shampoo"]   # with rules, it's back


def test_dropdown_is_filtered_by_product_type(data):
    dd = dropdown_concerns(data)
    assert "dandruff" in dd["shampoo"]
    assert "dandruff" not in dd["conditioner"]
    assert "acne-prone" in dd["serum"]
    assert "dark-circles" in dd["serum"]
    assert "dark-circles" not in dd["face_wash"]
    assert "hair-fall" in dd["hair_oil_serum"]


def test_skin_and_hair_concerns_never_mix(data):
    category = {c["concern_id"]: c["category"] for c in data["concerns"]}
    ptype_cat = {t["product_type"]: t["category"] for t in data["product_types"]}
    for ptype, concerns in dropdown_concerns(data).items():
        for c in concerns:
            assert category[c] == ptype_cat[ptype], f"{c} shown for {ptype}"


# ---------- 3. The validator catches mistakes ----------

def _rule0(d):
    return d["rules"][0]


@pytest.mark.parametrize("change, expected", [
    (lambda d: _rule0(d).update(source="TO_FILL"), "source must be a real web link"),
    (lambda d: _rule0(d).update(rationale="This is the best ingredient."), "banned word"),
    (lambda d: _rule0(d).update(rationale="Will cure acne."), "banned word"),
    (lambda d: _rule0(d).update(flag_type="good"), "flag_type must be"),
    (lambda d: _rule0(d).update(severity="extreme"), "severity must be"),
    (lambda d: _rule0(d).update(applies_to="lipstick"), "unknown product type"),
    (lambda d: _rule0(d).update(relevant_profiles="concern:wrinkles"), "unknown concern"),
    (lambda d: _rule0(d).update(relevant_profiles="wrinkles"), "must start with concern:"),
    (lambda d: _rule0(d).update(match_terms="parfum"), "is an alias"),
    (lambda d: _rule0(d).update(match_terms="Salicylic Acid"), "must be lowercase"),
    (lambda d: _rule0(d).update(rationale=""), "'rationale' is empty"),
    (lambda d: _rule0(d).update(applies_to="shampoo", relevant_profiles="concern:acne-prone"),
     "concern 'acne-prone' is skin"),
    (lambda d: d["rules"].append(dict(d["rules"][0])), "appears more than once"),
    (lambda d: d["aliases"].append({"alias": "fragrance", "standard_name": "scent", "note": ""}),
     "is itself listed as an alias"),
    (lambda d: d["seed_products"].append({"barcode": "12AB", "product_name": "x", "brand": "",
                                          "product_type": "toner", "ingredients_text": ""}),
     "must be 8 to 14 digits"),
    (lambda d: d["product_types"][0].update(application="sometimes"), "application must be"),
])
def test_validator_catches(data, change, expected):
    errors = errors_for(data, change)
    assert any(expected in e for e in errors), f"expected '{expected}' in {errors}"


# ---------- 4. Seed cache and local database ----------

def test_seed_saves_only_products_with_ingredients(tmp_path):
    conn = db.connect(tmp_path / "test.db")
    rows = [
        {"barcode": "11111111", "product_name": "A", "brand": "B", "ingredients_text": "Aqua, Glycerin"},
        {"barcode": "22222222", "product_name": "C", "brand": "D", "ingredients_text": ""},
    ]
    result = seed_cache.seed(conn, rows)
    assert len(result["saved"]) == 1 and len(result["skipped"]) == 1
    saved = db.get_product(conn, "11111111")
    assert saved["ingredients_text"] == "Aqua, Glycerin" and saved["source"] == "seed"
    assert db.get_product(conn, "22222222") is None   # never guessed


def test_seeding_twice_does_not_duplicate(tmp_path):
    conn = db.connect(tmp_path / "test.db")
    rows = [{"barcode": "11111111", "product_name": "A", "brand": "B", "ingredients_text": "Aqua"}]
    seed_cache.seed(conn, rows)
    seed_cache.seed(conn, rows)
    assert db.count_products(conn) == 1


def test_database_has_both_tables(tmp_path):
    conn = db.connect(tmp_path / "test.db")
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"products_cache", "request_log"} <= names


# ---------- 5. Small helpers ----------

def test_csv_saved_by_excel_still_reads(tmp_path):
    f = tmp_path / "x.csv"
    f.write_bytes("﻿alias,standard_name\nparfum,fragrance\n".encode("utf-8"))
    assert read_csv(f)[0]["alias"] == "parfum"


def test_split_list():
    assert split_list(" a | b ||c ") == ["a", "b", "c"]
