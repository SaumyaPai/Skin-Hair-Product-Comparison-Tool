"""Puts products in order from their flags. The points are internal and never shown.

Each flag's weight = severity x application (rinse-off counts half). Sensitive shoppers: cautions on
sensitivity rules x 1.5. Label position (config.USE_LABEL_POSITION, on): the 1st ingredient counts fully, each step down the
label a little less (never below half), because labels list ingredients from the largest amount to the smallest.

points = sum of (severity weight x application weight) for "may suit" flags
       - sum of (severity weight x application weight x sensitivity multiplier) for "may not suit" flags

Extra rules:
  * One rule counts once per product (built into the rule engine).
  * If several rules flag the SAME ingredient family the SAME way (for example fragrance
    flagged for dryness, redness and sensitive skin), only the strongest one counts, so one
    ingredient can't be counted three times. All of them are still shown to the shopper.
  * Ties: equal points -> fewer "may not suit" flags ranks higher -> otherwise a real tie,
    sharing a rank number (1, 1, 3) and listed alphabetically.
"""
from app import config


def near_top(position: int | None, list_length: int | None) -> bool:
    """Is the ingredient in the upper part of the label (first third, and always the first 5)?"""
    if not position or not list_length:
        return True
    return position <= max(config.POSITION_TOP_MIN, -(-list_length // 3))


def position_factor(position: int | None, list_length: int | None = None) -> float:
    """1.0 for the 1st ingredient, a little less for each step down the label (0.95, 0.90...), and never
    below 0.5. It uses the place itself, not the length of the list, so adding extra ingredients at the
    end never changes anything. Same place = same factor, so real ties stay ties."""
    if not position:
        return 1.0
    return max(config.POSITION_FLOOR, 1.0 - config.POSITION_STEP * (position - 1))


def flag_weight(flag: dict, application: str, sensitive: bool) -> float:
    w = config.SEVERITY_WEIGHT[flag["severity"]] * config.APPLICATION_WEIGHT[application]
    if config.USE_LABEL_POSITION:
        w *= position_factor(flag.get("position"), flag.get("list_length"))
    if flag["flag_type"] == "may_not_suit" and sensitive and flag.get("sensitivity_rule"):
        w *= config.SENSITIVITY_MULTIPLIER
    return w


def product_points(flags: list[dict], application: str, sensitive: bool) -> float:
    strongest: dict[tuple[str, str], float] = {}
    for f in flags:
        key = (f["flag_type"], f["ingredient_family"])
        strongest[key] = max(strongest.get(key, 0.0), flag_weight(f, application, sensitive))
    total = sum(w if flag_type == "may_suit" else -w for (flag_type, _), w in strongest.items())
    return round(total, 6)


def rank(products: list[dict], application: str, sensitive: bool) -> list[dict]:
    """products: [{"display_name": ..., "flags": [...]}, ...] (resolved products only).
    Returns [{"rank", "display_name", "tied", "points", "n_may_suit", "n_may_not_suit"}].
    'points' is for tests and logs only; the API must not send it to the shopper."""
    scored = []
    for p in products:
        # kinds of ingredient, not rules: two sources about the same kind still count as one caution
        n_bad = len({f["ingredient_family"] for f in p["flags"] if f["flag_type"] == "may_not_suit"})
        scored.append({
            "display_name": p["display_name"],
            "points": product_points(p["flags"], application, sensitive),
            "n_may_suit": len({f["ingredient_family"] for f in p["flags"] if f["flag_type"] == "may_suit"}),
            "n_may_not_suit": n_bad,
        })
    scored.sort(key=lambda s: (-s["points"], s["n_may_not_suit"], s["display_name"].casefold()))

    result, prev_key, prev_rank = [], None, 0
    for position, s in enumerate(scored, start=1):
        key = (s["points"], s["n_may_not_suit"])
        current_rank = prev_rank if key == prev_key else position
        result.append({"rank": current_rank, **s, "tied": False})
        prev_key, prev_rank = key, current_rank
    for r in result:
        r["tied"] = sum(1 for o in result if o["rank"] == r["rank"]) > 1
    return result
