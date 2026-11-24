# Findings

These are the results of Phase 6, from one run of `python -m scripts.final_check` on version 0.9.1 (1.0.0 adds only these documents)
(23 November 2026, Windows, free AI tiers). The full sheet is written to `eval_results/RESULTS.md` each
time the check runs, and the raw files sit next to it. Each number below links to the script that
produced it.

## Results at a glance

| Measure | Result | Produced by |
|---|---|---|
| Automatic tests (Phases 1 to 6) | **455 passed**, 2 skipped, 0 failed | [`scripts/final_check.py`](scripts/final_check.py) (runs `tests/`) |
| Same order every run: our tool | **100%** (10 comparisons × 3 runs) | [`scripts/eval/consistency.py`](scripts/eval/consistency.py) |
| Same order every run: plain AI chatbot | **0%** (10 comparisons × 3 runs) | [`scripts/eval/consistency.py`](scripts/eval/consistency.py) |
| Answers with a made-up claim or judgement word: our tool | **0 of 30** | [`scripts/eval/hallucination.py`](scripts/eval/hallucination.py), [`scoring.py`](scripts/eval/scoring.py) |
| Answers with a made-up claim or judgement word: plain chatbot | **4 of 30** | [`scripts/eval/hallucination.py`](scripts/eval/hallucination.py) |
| Label photo reading, AI readers | **94.4%** of ingredients exact, **98.6%** counting small spelling slips, **0 invented** | [`scripts/eval/extraction.py`](scripts/eval/extraction.py) |
| Label photo reading, offline (no AI) | 15.5% exact, 22.5% counting small slips | [`scripts/eval/extraction.py`](scripts/eval/extraction.py) |
| Time to read a photo | 2.7 s (conditioner, Groq) to 16.5 s (shampoo, Gemini Flash-Lite) | [`scripts/eval/extraction.py`](scripts/eval/extraction.py) |
| Barcodes found with an ingredient list | **3 of 10** (1 found without ingredients, 6 not found) | [`scripts/eval/coverage.py`](scripts/eval/coverage.py) |
| User test | Not done (out of scope for this submission) | Kit ready: [`scripts/eval/user_test.py`](scripts/eval/user_test.py), [`docs/guides/USER_TEST_SCRIPT.md`](docs/guides/USER_TEST_SCRIPT.md) |

## What worked
- **Repeatability is the clearest win.** The tool gave the same order every time in all 10 comparisons.
  A plain chatbot, given the same ingredient lists, changed its order at least once in every one.
  This is the main reason to use rules and code instead of asking a chatbot.
- **No made-up claims got through.** None of the tool's 30 answers named an ingredient the products
  don't contain, or used words like good, best, cure or treat. The plain chatbot did in 4 of 30. In
  the tool, every AI summary is checked by code and replaced by the template if it breaks a rule.
- **Photo reading with AI is accurate.** On two real, curved, small-print labels, 94.4% of
  ingredients were read exactly and none were invented. That includes a 54-ingredient shampoo list in
  light text on a blue bottle.
- **The backups work.** During the check, one Gemini model was busy. The other readers and writers took
  over and the result was still PASS.

## What didn't work as well
- **Barcode coverage is low for these products.** Only 3 of 10 of the barcodes used came with an
  ingredient list in Open Beauty Facts. Most were Indian brands. Pasting the list or taking a label
  photo is therefore the main way in, not the fallback.
- **Offline photo reading is weak.** Without AI, Tesseract read 15.5% of ingredients exactly. It managed
  the dark-on-light conditioner label (about 65%) but nothing from the light-on-blue shampoo. The app
  marks offline reads as "check every word".
- **Photos can be slow.** A long list can take about 16 seconds when the faster AI is busy.

## Limits
- **Small samples:** 2 label photos (the plan was 30), 10 barcodes (the plan was at least 5 per type) and 10
  comparisons. The numbers show direction, not precise rates.
- **No user test,** so we haven't measured clarity, trust, or whether shoppers read it as medical advice.
- **The made-up claims check is automatic.** It catches named ingredients and banned words, not every
  possible misleading sentence. The raw answers are saved in `eval_results/consistency_raw.json`
  for a human to read.
- **The rule table is small** (44 rules) and only knows the ingredients it lists. Anything else is shown
  in the full ingredient list, never guessed.
- **Evidence varies.** Some rules (for example pore-clogging ingredients, caffeine for hair fall) rest on
  lab or small studies, and their rationale says so.
- **Free AI tiers** can be busy or change their limits.

## Next steps
1. Run the user test with 5 to 8 people (the kit is ready).
2. Measure 30 label photos and at least 5 barcodes per product type, using the same scripts with `eval_inputs/`.
3. Add more sourced rules and aliases, especially for Indian brands' common ingredients.
4. Optional: free online hosting so others can try it without installing.

## How to reproduce
```powershell
python -m scripts.final_check
notepad eval_results\RESULTS.md
```
See [`docs/guides/PHASE6_GUIDE.md`](docs/guides/PHASE6_GUIDE.md) to run each measure on its own or with more data.
