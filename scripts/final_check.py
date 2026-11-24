"""Final check before submission: one command that tests everything and prints PASS / FAIL.

Run from the project folder (with the venv active):
    python -m scripts.final_check            everything (about 10 minutes, uses a little free AI quota)
    python -m scripts.final_check --quick    tests + live connection checks only (about 2 minutes)

It also builds the Phase 6 results sheet:  eval_results\\RESULTS.md
"""
import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LABELS = ROOT / "tests" / "fixtures" / "labels"
PASS, WARN, FAIL = "PASS", "WARN", "FAIL"
checks: list[tuple[str, str, str]] = []


def record(status: str, name: str, detail: str = ""):
    checks.append((status, name, detail))
    print(f"  [{status}] {name}" + (f": {detail}" if detail else ""), flush=True)


def step(title: str):
    print(f"\n== {title} ==", flush=True)


# ---------------------------------------------------------------- 1. automatic tests

def run_tests():
    step("1. Automatic tests (no internet needed)")
    t0 = time.monotonic()
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=ROOT,
                          capture_output=True, text=True)
    last = [ln for ln in proc.stdout.splitlines() if ln.strip()][-1:] or ["(no output)"]
    summary = last[0].strip("= ")
    failed = re.search(r"(\d+) failed", summary)
    errors = re.search(r"(\d+) error", summary)
    if proc.returncode == 0:
        record(PASS, "All automatic tests", summary)
    else:
        record(FAIL, "Automatic tests", summary)
        for ln in proc.stdout.splitlines():
            if ln.startswith(("FAILED", "ERROR")):
                print("      " + ln[:160])
    return {"summary": summary, "ok": proc.returncode == 0,
            "failed": int(failed.group(1)) if failed else 0, "errors": int(errors.group(1)) if errors else 0}


# ---------------------------------------------------------------- 2. live connections

def live_checks():
    from app import config
    from app.services import llm_client, obf_client
    step("2. Live connections")
    out = {}
    if config.APP_VERSION:
        record(PASS, "App version", config.APP_VERSION)
    for key in ("GEMINI_API_KEY", "GROQ_API_KEY"):
        val = getattr(config, key)
        record(PASS if val else WARN, f"{key} in .env", f"set (ends ...{val[-4:]})" if val else "not set")

    # product database
    barcode = _a_known_barcode()
    t0 = time.monotonic()
    res = obf_client.get_product(barcode)
    secs = time.monotonic() - t0
    ok = res["status"] in ("found", "no_ingredients", "not_found")
    record(PASS if ok else FAIL, "Open Beauty Facts reachable",
           f"barcode {barcode}: {res['status']} in {secs:.1f}s" if ok else res.get("message", res["status"]))
    out["obf"] = ok

    # each AI for summaries
    working = []
    for name, fn in llm_client.summary_providers():
        t0 = time.monotonic()
        try:
            reply = (fn("Reply with exactly: OK") or "").strip()
            working.append(name)
            record(PASS, f"AI summary: {name}", f"answered in {time.monotonic() - t0:.1f}s ({reply[:20]!r})")
        except Exception as exc:
            record(WARN, f"AI summary: {name}", llm_client.describe_failure(exc))
    if not working:
        record(FAIL if (config.GEMINI_API_KEY or config.GROQ_API_KEY) else WARN, "At least one AI answers",
               "none answered: summaries will use the built-in wording (the app still works)")
    out["ai_working"] = working
    return out


def _a_known_barcode() -> str:
    import csv
    for f in (ROOT / "data" / "seed_products.csv", ROOT / "data" / "my_products.csv"):
        if f.exists():
            with f.open(newline="", encoding="utf-8-sig") as fh:
                for r in csv.DictReader(fh):
                    if (r.get("barcode") or "").strip().isdigit():
                        return r["barcode"].strip()
    return "8901088136945"


# ---------------------------------------------------------------- 3. measures

def photo_accuracy():
    from app.data_loader import load_all
    from app.services import llm_client, ocr
    from app.services.normalizer import from_data
    from scripts.eval import extraction
    from scripts.eval.common import INPUTS, save_csv, save_json, stamp
    step("3. Reading label photos (your shampoo and conditioner photos, plus any in eval_inputs\\photos)")
    pairs, _ = extraction.find_pairs(LABELS)
    if (INPUTS / "photos").exists():
        pairs += extraction.find_pairs(INPUTS / "photos")[0]
    norm = from_data(load_all())
    results = {}
    for label, chain in (("same readers as the app", llm_client.extract_providers()),
                         ("without-AI reader only", [("offline_ocr", ocr.read_ingredients)])):
        print(f"  Reading {len(pairs)} photos with the {label}...", flush=True)
        out = extraction.evaluate(pairs, chain, norm, gap=2.0)
        for r in out["rows"]:
            r["mode"] = label
        results[label] = out
    main = results["same readers as the app"]["summary"]
    offline = results["without-AI reader only"]["summary"]
    main.update(when=stamp(), mode="same readers as the app", offline=offline)
    save_csv("extraction.csv", results["same readers as the app"]["rows"] + results["without-AI reader only"]["rows"])
    save_json("extraction.json", main)
    status = PASS if main["pct_exact_or_near"] >= 80 else (WARN if main["pct_exact_or_near"] else FAIL)
    record(status, "Photo reading accuracy", f"{main['pct_exact']}% exact, {main['pct_exact_or_near']}% with small "
           f"slips, {main['invented_total']} invented, about {main['median_seconds']}s per photo")
    if main["invented_total"]:
        record(WARN, "Photo reading invented ingredients", "see eval_results\\extraction.csv (invented_items)")
    record(PASS, "Without-AI reader (for comparison)",
           f"{offline['pct_exact']}% exact, {offline['pct_exact_or_near']}% with small slips")


def coverage_measure():
    import csv
    from app.data_loader import load_all
    from app.services import obf_client
    from scripts.eval import coverage
    from scripts.eval.common import INPUTS, read_csv, save_csv, save_json, stamp
    step("4. Barcode coverage (the barcodes you've used)")
    rows, seen = [], set()
    sources = [INPUTS / "coverage.csv", ROOT / "data" / "seed_products.csv", ROOT / "data" / "my_products.csv"]
    for f in sources:
        if not f.exists():
            continue
        for r in read_csv(f):
            bc = r.get("barcode", "")
            if bc.isdigit() and bc not in seen:
                seen.add(bc)
                rows.append({"product_type": r.get("product_type") or "saved product", "barcode": bc,
                             "name": r.get("name") or r.get("my_name") or r.get("product_name", "")})
    if not rows:
        record(WARN, "Barcode coverage", "no barcodes found to check")
        return
    types = [t["product_type"] for t in load_all()["product_types"]]
    types += sorted({r["product_type"] for r in rows} - set(types))
    out = coverage.evaluate(rows, obf_client.get_product, types, gap=1.0)
    out["summary"]["when"] = stamp()
    save_csv("coverage.csv", out["rows"])
    save_json("coverage.json", out["summary"])
    s = out["summary"]
    record(PASS if s["answered"] else FAIL, "Barcode coverage",
           f"{s['found_with_ingredients']} of {s['answered']} barcodes came with an ingredient list ({s['pct']}%)")


def consistency_and_claims(limit: int):
    from app.deps import get_services
    from app.services import llm_client
    from scripts.eval import consistency, hallucination
    from scripts.eval.common import INPUTS, TEMPLATES, save_csv, save_json, stamp
    from scripts.eval.scoring import ClaimChecker
    step("5. Same answer every time? Our tool vs a plain AI chatbot (3 runs each)")
    src = INPUTS / "comparisons.json" if (INPUTS / "comparisons.json").exists() else TEMPLATES / "comparisons.json"
    comps = json.loads(src.read_text(encoding="utf-8-sig"))["comparisons"][:limit]
    services = get_services()
    chain = llm_client.summary_providers()
    if chain:
        chatbot = lambda c: consistency.run_chatbot(c, services.data, chain)
    else:
        chatbot = None
        record(WARN, "Plain chatbot comparison", "skipped: no AI key in .env")
    print(f"  {len(comps)} comparisons x 3 runs. Waiting a few seconds between AI calls (free limits)...", flush=True)
    out = consistency.evaluate(comps, lambda c: consistency.run_tool(c, services), chatbot, runs=3,
                               gap=4.0 if chain else 0)
    out["summary"]["chatbot_ran"] = chatbot is not None
    out["summary"]["when"] = stamp()
    save_csv("consistency.csv", out["rows"])
    save_json("consistency_raw.json", out["raw"])
    save_json("consistency.json", out["summary"])
    s = out["summary"]
    record(PASS if s["tool_pct_same_every_time"] == 100 else FAIL, "Tool gives the same order every run",
           f"{s['tool_pct_same_every_time']}%" + (f" (plain chatbot: {s['chatbot_pct_same_every_time']}%)"
                                                  if chatbot else ""))

    step("6. Made-up claims")
    from app.data_loader import load_all
    h = hallucination.evaluate(out["raw"], ClaimChecker(load_all()))
    from scripts.eval.common import load_json
    ext = load_json("extraction.json")
    h["summary"]["photo_reading_invented"] = ext["invented_total"] if ext else None
    h["summary"]["when"] = stamp()
    save_csv("hallucination.csv", h["rows"])
    save_json("hallucination.json", h["summary"])
    t, c = h["summary"]["tool"], h["summary"]["chatbot"]
    record(PASS if t["answers_with_any"] == 0 else FAIL, "No made-up claims in the tool's answers",
           f"{t['answers_with_any']} of {t['answers']}" + (f" (plain chatbot: {c['answers_with_any']} of {c['answers']})"
                                                           if c["answers"] else ""))
    if t["answers_with_any"]:
        for r in h["rows"]:
            if r["who"] == "tool" and r["count"]:
                print(f"      {r['comparison']} run {r['run']}: {r['invented_ingredients']} {r['judgement_words']}")


# ---------------------------------------------------------------- main

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Final check: tests + live checks + Phase 6 measures")
    ap.add_argument("--quick", action="store_true", help="tests and live connections only")
    ap.add_argument("--limit", type=int, default=10, help="how many comparisons for the consistency check")
    args = ap.parse_args(argv)
    sys.path.insert(0, str(ROOT))
    import logging
    logging.getLogger("skincare").setLevel(logging.ERROR)     # keep the screen to PASS / WARN / FAIL lines
    started = time.monotonic()
    print("Final check: this prints PASS, WARN (works, but worth a look) or FAIL for each part.")
    tests = run_tests()
    live = live_checks()
    if not args.quick:
        for fn in (photo_accuracy, coverage_measure, lambda: consistency_and_claims(args.limit)):
            try:
                fn()
            except Exception as exc:                         # one broken measure shouldn't hide the others
                record(FAIL, getattr(fn, "__name__", "measure"), f"stopped: {type(exc).__name__}: {str(exc)[:150]}")
    from scripts.eval.common import save_json
    save_json("final_check.json", {"checks": [{"status": s, "name": n, "detail": d} for s, n, d in checks],
                                   "tests": tests, "quick": args.quick, "live": live})
    from scripts.eval import results
    results.main()
    fails = [c for c in checks if c[0] == FAIL]
    warns = [c for c in checks if c[0] == WARN]
    print("\n" + "=" * 60)
    print(f"RESULT: {'FAIL' if fails else 'PASS'}   ({len(checks) - len(fails) - len(warns)} passed, "
          f"{len(warns)} warnings, {len(fails)} failed, {time.monotonic() - started:.0f}s)")
    for s, n, d in fails + warns:
        print(f"  {s}: {n}" + (f" ({d})" if d else ""))
    print("Results sheet: eval_results\\RESULTS.md")
    print("=" * 60)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
