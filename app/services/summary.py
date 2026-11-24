"""Writes the plain-language summary.

1. Only the structured result (names, ranks, flags) is given to Gemini. Never raw ingredient lists or profiles.
2. Code checks Gemini's reply. If it uses a banned word, mentions an ingredient that isn't in the
   flags, is empty or too long, it is thrown away.
3. If Gemini fails, is busy, or its reply is thrown away, a fill-in-the-blanks template is used.
The disclaimer is added by code elsewhere, never by the AI.
"""
import json
import logging
import re

from app import config
from app.data_loader import split_list

log = logging.getLogger("skincare")


def _place(flag: dict) -> str:
    from app.services.ranking import near_top
    if not flag.get("position") or not config.USE_LABEL_POSITION:
        return ""
    where = "near the top" if near_top(flag["position"], flag.get("list_length")) else "lower down"
    return f"{flag['position']} of {flag.get('list_length')}, {where}"


def build_facts(product_type_label: str, concern_phrases: list[str], ranking: list[dict],
                products: list[dict], unresolved: list[dict]) -> dict:
    by_name = {p["display_name"]: p for p in products}
    ordered = []
    for r in ranking:
        p = by_name[r["display_name"]]
        ordered.append({
            "name": r["display_name"], "rank": r["rank"], "tied": r["tied"],
            "may_suit": [{"ingredient_family": f["ingredient_family"], "plain_name": f.get("plain_name", ""),
                          "label": f["label"], "place_on_label": _place(f)}
                         for f in p["flags"] if f["flag_type"] == "may_suit"],
            "may_not_suit": [{"ingredient_family": f["ingredient_family"], "plain_name": f.get("plain_name", ""),
                              "label": f["label"], "place_on_label": _place(f)}
                             for f in p["flags"] if f["flag_type"] == "may_not_suit"],
            "_mentionable": sorted({f["ingredient_family"] for f in p["flags"]}
                                   | {f.get("plain_name", "") for f in p["flags"] if f.get("plain_name")}
                                   | {i for f in p["flags"] for i in f["matched_ingredients"]}),
        })
    return {"product_type": product_type_label, "concerns": concern_phrases, "products": ordered,
            "unresolved": [u["display_name"] for u in unresolved]}


def build_prompt(facts: dict) -> str:
    public = {**facts, "products": [{k: v for k, v in p.items() if not k.startswith("_")} for p in facts["products"]]}
    return (
        "Write a short plain-language summary (3 to 6 sentences, under 120 words) of this skincare or haircare "
        "product comparison for a shopper. Use ONLY the facts in the JSON below.\n"
        "Rules:\n"
        "- Never mention any ingredient or ingredient family that is not in the JSON.\n"
        "- Never use these words: good, bad, best, worst, cure, fix, treat, heal, guarantee, safe, recommend, score.\n"
        "- No numbers out of 100, no percentages, no medical claims.\n"
        "- Describe concerns only as 'ingredients commonly used for ...'.\n"
        "- Say 'ranked first' (not 'best'). If products are tied, say they are tied.\n"
        "- If 'unresolved' lists products, say their ingredients could not be found.\n"
        "- Never say what a product is designed, made, formulated or intended for. Only say what the flags say.\n"
        "- Never say both or all products share something unless every product's flags in the JSON show it.\n"
        "- If a product has no flags, say no ingredients in our table matched it.\n"
        "- place_on_label tells where the ingredient sits on the label; labels list ingredients from most to least, "
        "so you may say an ingredient is near the top or lower down. Never guess amounts or percentages.\n"
        "- If close_call is true, say plainly that the products are close and the difference between them is small.\n"
        "- Write for a shopper in everyday words. Use plain_name for ingredients. Never mention rules, tables, "
        "flags, ingredient groups, ingredient families, points or list positions as numbers.\n"
        "- Do not add a disclaimer; the app adds one.\n\n"
        f"FACTS:\n{json.dumps(public, indent=1)}"
    )


def _vocabulary(data: dict) -> set[str]:
    vocab = set()
    for r in data["rules"]:
        vocab.add(r["ingredient_family"])
        vocab.update(split_list(r["match_terms"]))
    for a in data["aliases"]:
        vocab.add(a["alias"])
        vocab.add(a["standard_name"])
    return {v for v in vocab if len(v) >= 4}


def _has_phrase(text: str, phrase: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", text) is not None


def check_summary(text: str, facts: dict, data: dict) -> list[str]:
    """Returns a list of problems. An empty list means the summary is allowed."""
    problems = []
    low = (text or "").lower()
    if not low.strip():
        return ["empty"]
    if len(low.split()) > config.SUMMARY_MAX_WORDS:
        problems.append("too long")
    for word in config.BANNED_WORDS + config.SUMMARY_BANNED_EXTRA:
        if _has_phrase(low, word):
            problems.append(f"banned word: {word}")
    allowed = {m.lower() for p in facts["products"] for m in p["_mentionable"]}
    stripped = low
    for phrase in sorted(allowed, key=len, reverse=True):
        stripped = re.sub(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", " ", stripped)
    for term in sorted(_vocabulary(data)):
        if _has_phrase(stripped, term):
            problems.append(f"mentions an ingredient not in the flags: {term}")
    if facts["products"]:
        top = facts["products"][0]["name"].lower()
        if not _has_phrase(low, top):
            problems.append("does not name the product ranked first")
    return problems


def _join(items: list[str]) -> str:
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _pname(f: dict) -> str:
    return f.get("plain_name") or f["ingredient_family"]


def template_summary(facts: dict) -> str:
    """The fallback. Built only from the facts, so it can't invent anything. Shopper language."""
    products, unresolved = facts["products"], facts["unresolved"]
    concerns = _join(facts["concerns"])
    sentences = []
    if len(products) < 2:
        sentences.append(f"We could only find ingredients for {len(products)} of your products, so we can't rank them yet.")
    else:
        top = [p["name"] for p in products if p["rank"] == 1]
        if len(top) > 1:
            sentences.append(f"{_join(top)} are tied for {concerns}.")
        else:
            sentences.append(f"{top[0]} is ranked first for {concerns}.")
            if facts.get("close_call"):
                sentences.append("The products are close, and the difference between them is small.")
    for p in products:
        if p["may_suit"]:
            names = _join(sorted({_pname(f) for f in p["may_suit"]}))
            sentences.append(f"{p['name']} has {names}, commonly used for {concerns}.")
        if p["may_not_suit"]:
            f = p["may_not_suit"][0]
            label = f["label"]
            tail = (f", which may not suit {label[len('May not suit '):]}" if label.startswith("May not suit ")
                    else f" ({label[0].lower() + label[1:]})")
            sentences.append(f"Worth knowing: {p['name']} has {_pname(f)}{tail}.")
        if not p["may_suit"] and not p["may_not_suit"]:
            sentences.append(f"We didn't spot ingredients commonly used for {concerns} in {p['name']}.")
    if unresolved:
        sentences.append(f"We could not find ingredients for {_join(unresolved)}; "
                         f"paste them or add a label photo to include {'it' if len(unresolved) == 1 else 'them'}.")
    return " ".join(sentences)


def write(facts: dict, data: dict, llm=None) -> tuple[str, str, str]:
    """Tries each AI in the backup chain; every reply goes through the same check_summary.
    llm can be None, one function, or a list of (name, function).
    Returns (summary_text, 'llm' or 'template', provider_name)."""
    if llm is None:
        chain = []
    elif callable(llm):
        chain = [("llm", llm)]
    else:
        chain = list(llm)
    if len(facts["products"]) >= 2 and chain:
        from app.services.llm_client import run_chain
        prompt = build_prompt(facts)
        text, name = run_chain(chain, call=lambda fn: (fn(prompt) or "").strip(),
                               accept=lambda t: check_summary(t, facts, data), label="Summary")
        if name:
            return text, "llm", name
    return template_summary(facts), "template", "template"
