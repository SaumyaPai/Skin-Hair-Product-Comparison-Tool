"""Runs one comparison from start to finish. Steps match ARCHITECTURE.md section 3.2."""
from app import config
from app.errors import ApiError
from app.services import resolver, summary
from app.services.ranking import near_top, rank

INTERNAL_FLAG_KEYS = {"matched_tags", "sensitivity_rule"}


def run(req, conn, services) -> dict:
    data = services.data
    types = {t["product_type"]: t for t in data["product_types"]}

    # Step 2: product type and concerns must be real for this type
    ptype = types.get(req.product_type)
    if not ptype:
        raise ApiError(422, "UNKNOWN_PRODUCT_TYPE", f"'{req.product_type}' isn't a product type we support.",
                       [{"field": "product_type", "issue": "unknown"}])
    allowed = services.dropdown[req.product_type]
    bad = [c for c in req.concerns if c not in allowed]
    if bad:
        raise ApiError(422, "UNKNOWN_CONCERN",
                       f"'{bad[0]}' isn't a concern we have rules for with {ptype['label'].lower()}.",
                       [{"field": "concerns", "issue": f"unknown: {c}"} for c in bad])

    # Step 3: resolve each product
    records = [resolver.resolve(conn, p, req.product_type, data["product_types"], services.obf_lookup)
               for p in req.products]

    # Step 4: same type only
    for i, r in enumerate(records):
        if r.get("mismatch_type"):
            raise ApiError(422, "PRODUCT_TYPE_MISMATCH",
                           f"{r['display_name']} looks like a {r['mismatch_type'].lower()} in the product database. "
                           f"Only products of the same type can be compared.",
                           [{"field": f"products[{i}]", "issue": "type_mismatch"}])

    # Steps 5 and 6: normalize and apply rules
    profile = req.profile.model_dump()
    products_out, unresolved = [], []
    for r in records:
        if not r["resolved"]:
            unresolved.append({k: r[k] for k in ("display_name", "reason", "message")})
            continue
        n = services.normalizer.normalize(r["ingredients_text"])
        if not n.ingredients:                       # e.g. only commas or spaces were pasted
            unresolved.append({"display_name": r["display_name"], "reason": "no_ingredients_listed",
                               "message": "We couldn't find any ingredient names in that text. Please check it, "
                                          "or add a label photo instead."})
            continue
        flags = services.engine.evaluate(req.product_type, n.ingredients, req.concerns, profile)
        out = {"display_name": r["display_name"], "resolved": True, "ingredient_source": r["ingredient_source"],
               "flags": flags, "not_recognised": n.not_recognised, "ingredients": n.ingredients}
        tag = pore_tag(req.product_type, req.concerns, flags, data["rules"], data["product_types"])
        out["tags"] = [tag] if tag else []
        for k in ("product_name", "brand", "note"):
            if r.get(k):
                out[k] = r[k]
        products_out.append(out)

    # Step 7: rank (only if at least 2 products have ingredients)
    ranking = rank(products_out, ptype["application"], req.profile.sensitive) if len(products_out) >= 2 else []
    order = {r["display_name"]: i for i, r in enumerate(ranking)}
    products_out.sort(key=lambda p: order.get(p["display_name"], 99))

    # Step 7b: say in plain words why the order is what it is (built from the flags only)
    phrases = {c["concern_id"]: c.get("phrase") or c["label"].lower() for c in data["concerns"]}
    explain = explain_order(ranking, products_out, [phrases[c] for c in req.concerns])

    # Step 8: summary
    facts = summary.build_facts(ptype["label"], [phrases[c] for c in req.concerns], ranking, products_out, unresolved)
    facts["close_call"] = explain["close_call"]
    text, source, provider = summary.write(facts, data, services.summarize)

    for p in products_out:
        p["flags"] = [{k: v for k, v in f.items() if k not in INTERNAL_FLAG_KEYS} for f in p["flags"]]
    return {
        "status": "ok" if ranking else "insufficient_data",
        "product_type": req.product_type,
        "concerns": req.concerns,
        "ranking": [{"rank": r["rank"], "display_name": r["display_name"], "tied": r["tied"],
                     "why": explain["why"][r["display_name"]],
                     "worth_knowing": explain["worth_knowing"][r["display_name"]],
                     "tags": next(p["tags"] for p in products_out if p["display_name"] == r["display_name"])}
                    for r in ranking],
        "order_note": explain["order_note"],
        "close_call": explain["close_call"],
        "order_source": explain["order_source"],
        "products": products_out,
        "unresolved": unresolved,
        "summary": text,
        "summary_source": source,
        "summary_provider": provider,
        "disclaimer": config.DISCLAIMER,
    }


RANK_WORDS = {1: "first", 2: "second", 3: "third", 4: "fourth"}

POSITION_TIP = ("Higher up the list usually means more of it: labels list ingredients from the largest amount "
                "to the smallest.")


def _join(items: list[str]) -> str:
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _groups(flags: list[dict], flag_type: str) -> list[dict]:
    """Each kind of ingredient once (best place on the label), in label order."""
    best: dict[str, dict] = {}
    for f in flags:
        if f["flag_type"] != flag_type:
            continue
        fam = f["ingredient_family"]
        if fam in best:                    # two sources, one kind: name every ingredient found, in label order
            keep = best[fam] if (best[fam].get("position") or 0) <= (f.get("position") or 0) else f
            merged = list(dict.fromkeys(best[fam].get("matched_ingredients", []) + f.get("matched_ingredients", [])))
            best[fam] = {**keep, "matched_ingredients": merged}
        else:
            best[fam] = f
    return sorted(best.values(), key=lambda f: (f.get("position") or 0, f["ingredient_family"]))


def _where(f: dict) -> str:
    if not config.USE_LABEL_POSITION or not f.get("position"):
        return ""
    return " high up in the formula" if near_top(f["position"], f.get("list_length")) else " lower in the formula"


def _plain(f: dict) -> str:
    return (f.get("plain_name") or f["ingredient_family"]) + _where(f)


def _named(f: dict) -> str:
    """The family name, plus the actual ingredients when they differ: 'pore-clogging ingredients (isopropyl myristate)'."""
    base = _plain(f)
    own = [m for m in f.get("matched_ingredients", []) if m != (f.get("plain_name") or f["ingredient_family"])]
    return f"{base} ({_join(own)})" if own else base


PORE_TAG = "No pore-clogging ingredients found"
PORE_RULES = {"R043", "R044"}


def pore_tag(product_type: str, concerns: list[str], flags: list[dict], rules: list[dict],
             product_types: list[dict]) -> str:
    """For acne-prone skin, on product types the pore-clogging check covers: say when none were found.
    An observation from our list, never a promise (the product can still clog pores)."""
    if "acne-prone" not in concerns:
        return ""
    from app.data_loader import types_matched
    covered = any(r["rule_id"] in PORE_RULES and product_type in types_matched(r["applies_to"], product_types)
                  for r in rules)
    if not covered or any(f["rule_id"] in PORE_RULES for f in flags):
        return ""
    return PORE_TAG


def _caution_text(f: dict) -> str:
    label = f.get("label", "")
    if label.startswith("May not suit "):
        return f"{_named(f)}, which may not suit {label[len('May not suit '):]}"
    return f"{_named(f)} ({label[0].lower() + label[1:]})" if label else _named(f)


def explain_order(ranking: list[dict], products: list[dict], concerns: list[str] | None = None) -> dict:
    """Shopper-language reasons for the order, built only from the flags (never from AI).
    'Close' means neighbouring products differ by one kind of ingredient or less."""
    concern_text = _join(concerns) if concerns else "your concerns"
    by_name = {p["display_name"]: p for p in products}
    why, worth, counts = {}, {}, []
    for r in ranking:
        p = by_name[r["display_name"]]
        suit, caution = _groups(p["flags"], "may_suit"), _groups(p["flags"], "may_not_suit")
        counts.append((len(suit), len(caution)))
        place = RANK_WORDS.get(r["rank"], f"number {r['rank']}")
        lead = f"Why it's tied for {place}" if r["tied"] else f"Why it's ranked {place}"
        if suit:
            text = f"{lead}: it has {_join([_plain(f) for f in suit])}, commonly used for {concern_text}"
            text += "." if caution else ", and nothing we know of that may not suit you."
        else:
            text = f"{lead}: we didn't spot ingredients commonly used for {concern_text} in this one"
            text += "." if caution else ", and nothing we know of that may not suit you."
        why[r["display_name"]] = text
        worth[r["display_name"]] = ("Worth knowing: it has " + "; ".join(_caution_text(f) for f in caution) + ".") \
            if caution else ""

    tip = POSITION_TIP if config.USE_LABEL_POSITION else ""
    out = {"why": why, "worth_knowing": worth, "close_call": False, "order_note": "",
           "order_source": config.POSITION_SOURCE if tip else ""}
    if len(ranking) < 2:
        return out
    if all(r["rank"] == 1 for r in ranking):
        return {**out, "close_call": True, "order_source": "",
                "order_note": "These are tied: we didn't find a difference between them for your concerns."}
    gaps = [abs(a[0] - b[0]) + abs(a[1] - b[1]) for a, b in zip(counts, counts[1:])]
    if min(gaps) == 0 and tip:
        return {**out, "close_call": True,
                "order_note": "These are close: they have the same kinds of ingredients, so the order comes from how "
                              "high up the list those ingredients appear. " + tip}
    if min(gaps) <= 1:
        return {**out, "close_call": True,
                "order_note": ("These are close, so the difference is small and either may suit you. "
                               + tip).strip()}
    return {**out, "order_note": tip}
