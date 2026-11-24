"""Measure 3: does the same comparison give the same answer every time? Our tool vs a plain AI chatbot.

Each comparison in eval_inputs/comparisons.json is run 3 times through the tool, and 3 times by asking the
same AI a plain question with the same ingredient lists (no rules, no checks, like typing it into a chatbot).
Run:  python -m scripts.eval.consistency                 (all comparisons)
      python -m scripts.eval.consistency --limit 2       (just the first 2, for a quick try)
Writes eval_results/consistency.json, consistency.csv and consistency_raw.json (every answer, word for word).
Then run  python -m scripts.eval.hallucination  to count made-up claims in those answers.
"""
import argparse
import json

from scripts.eval.common import INPUTS, need, pause, save_csv, save_json, stamp

CHATBOT_PROMPT = """I'm comparing {n} {ptype} products. My concerns: {concerns}.{profile}
Here are their ingredient lists:

{products}

Which one suits my concerns most? Explain briefly. On the very last line, write the order from most to least
suitable exactly like this, using the product names:  ORDER: name > name"""


def chatbot_prompt(comp: dict, data: dict) -> str:
    types = {t["product_type"]: t["label"].lower() for t in data["product_types"]}
    phrases = {c["concern_id"]: c.get("phrase") or c["label"].lower() for c in data["concerns"]}
    prof = comp.get("profile") or {}
    bits = [f"{k.replace('_', ' ')}: {v}" for k, v in prof.items() if v not in (None, False, "")]
    return CHATBOT_PROMPT.format(
        n=len(comp["products"]), ptype=types.get(comp["product_type"], comp["product_type"]),
        concerns=", ".join(phrases.get(c, c) for c in comp["concerns"]),
        profile=(" About me: " + "; ".join(bits) + ".") if bits else "",
        products="\n\n".join(f"{p['display_name']}: {p.get('ingredients_text', '')}" for p in comp["products"]))


def run_tool(comp: dict, services) -> dict:
    from app import db
    from app.models import CompareRequest
    from app.services import compare as compare_service
    from scripts.eval.scoring import tool_order
    req = CompareRequest(**{k: comp[k] for k in ("product_type", "concerns", "products", "profile") if k in comp})
    conn = db.connect()
    try:
        res = compare_service.run(req, conn, services)
    finally:
        conn.close()
    return {"order": tool_order(res["ranking"]), "text": res["summary"], "source": res["summary_provider"]}


def run_chatbot(comp: dict, data: dict, chain) -> dict:
    from app.services.llm_client import run_chain
    from scripts.eval.scoring import parse_order
    text, name = run_chain(list(chain), call=lambda fn: (fn(chatbot_prompt(comp, data)) or "").strip(),
                           label="Chatbot")
    names = [p["display_name"] for p in comp["products"]]
    return {"order": parse_order(text or "", names), "text": text or "", "source": name or "no AI answered"}


def same_every_time(orders: list[str]) -> bool:
    return bool(orders) and all(o == orders[0] and o for o in orders)


def evaluate(comps, tool, chatbot, runs: int = 3, gap: float = 0.0) -> dict:
    """tool(comp) and chatbot(comp) return {"order", "text", "source"}. chatbot=None runs the tool only."""
    from scripts.eval.scoring import first_choice
    raw, rows = [], []
    for i, comp in enumerate(comps, start=1):
        label = comp.get("label") or f"Comparison {i}"
        t_runs, c_runs = [], []
        for _ in range(runs):
            t_runs.append(tool(comp))
            if chatbot:
                pause(gap)
                c_runs.append(chatbot(comp))
            pause(gap)
        t_orders, c_orders = [r["order"] for r in t_runs], [r["order"] for r in c_runs]
        rows.append({"comparison": label, "product_type": comp["product_type"],
                     "tool_orders": " | ".join(t_orders), "tool_same_every_time": same_every_time(t_orders),
                     "chatbot_orders": " | ".join(o or "(no order given)" for o in c_orders),
                     "chatbot_same_every_time": same_every_time(c_orders),
                     "chatbot_same_first_choice": bool(c_orders) and len({first_choice(o) for o in c_orders}) == 1
                     and bool(c_orders[0]),
                     "chatbot_agrees_with_tool": bool(c_orders) and all(o == t_orders[0] for o in c_orders)})
        raw.append({"comparison": label, "products": comp["products"], "tool": t_runs, "chatbot": c_runs})
        print(f"  {label}: tool {'same' if rows[-1]['tool_same_every_time'] else 'CHANGED'}" +
              (f", chatbot {'same' if rows[-1]['chatbot_same_every_time'] else 'changed'}" if chatbot else ""))
    n = len(rows)

    def pct(key):
        return round(100 * sum(r[key] for r in rows) / n, 1) if n else 0.0
    return {"rows": rows, "raw": raw, "summary": {
        "comparisons": n, "runs_each": runs, "chatbot_ran": chatbot is not None,
        "tool_pct_same_every_time": pct("tool_same_every_time"),
        "chatbot_pct_same_every_time": pct("chatbot_same_every_time"),
        "chatbot_pct_same_first_choice": pct("chatbot_same_first_choice"),
        "chatbot_pct_agrees_with_tool": pct("chatbot_agrees_with_tool")}}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--limit", type=int, default=0, help="only the first N comparisons")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--gap", type=float, default=4.0, help="seconds between AI calls (free AI limits)")
    args = ap.parse_args(argv)
    path = INPUTS / "comparisons.json"
    if not need(path, "check the comparisons"):
        return 1
    comps = json.loads(path.read_text(encoding="utf-8-sig"))["comparisons"]
    comps = comps[:args.limit] if args.limit else comps
    from app.deps import get_services
    from app.services import llm_client
    services = get_services()
    chain = llm_client.summary_providers()
    if not chain:
        print("No AI key found in .env, so the chatbot side can't be run. Add GEMINI_API_KEY or GROQ_API_KEY.")
        return 1
    print(f"Running {len(comps)} comparisons x {args.runs} (tool and chatbot). This takes a few minutes...")
    out = evaluate(comps, lambda c: run_tool(c, services), lambda c: run_chatbot(c, services.data, chain),
                   runs=args.runs, gap=args.gap)
    out["summary"]["when"] = stamp()
    save_csv("consistency.csv", out["rows"])
    save_json("consistency_raw.json", out["raw"])
    save_json("consistency.json", out["summary"])
    s = out["summary"]
    print(f"\nDone: tool gave the same order {s['tool_pct_same_every_time']}% of the time, the chatbot "
          f"{s['chatbot_pct_same_every_time']}%. Next: python -m scripts.eval.hallucination")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
