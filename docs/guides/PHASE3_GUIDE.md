# Phase 3 guide: the core engine (Windows)

This phase builds the "brain" of the app. It isn't AI. It's three small pieces of code that always give the same answer for the same input.

| New file | What it does |
|---|---|
| `app/services/normalizer.py` | Cleans up an ingredient list: `"Aqua, PARFUM (Fragrance)., Vitamin B3"` becomes `water, fragrance, niacinamide`. Anything not in your tables goes on a "not recognised" list, so it's shown, not hidden or guessed. |
| `app/services/rule_engine.py` | Checks each product against `rules.csv` and creates the "may suit" and "may not suit" flags, each with its reason and source. |
| `app/services/ranking.py` | Puts the products in order using the weights in `app/config.py`. |
| `scripts/try_engine.py` + `data/try_example.json` | Lets you try the engine yourself, with no internet needed. |
| `tests/test_phase3.py` | 40 new tests. |

Also changed:
- **Gemini "busy" (503) errors:** the app now waits and retries twice. If Google is still busy, the live Gemini test is **skipped** with a clear message instead of failing, so a Google outage won't block a phase.
- **`data/concerns.csv`** has a new `phrase` column, so flags read naturally, like "May not suit dry skin".

## Step 1. Apply the update

Save `skincare-compare-update-phase3.zip` into `D:\Claude_comparison_project1\`, then in PowerShell:

```powershell
cd D:\Claude_comparison_project1
Expand-Archive .\skincare-compare-update-phase3.zip -DestinationPath . -Force
cd .\skincare-compare
.\.venv\Scripts\Activate.ps1
```

This doesn't touch your `.env`, `my_products.csv` or `seed_products.csv`. No new packages are needed.

## Step 2. Run all tests

```powershell
python -m pytest -v
```

**Phase 3 passes when** you see **87 passed**. If Gemini is busy, you'll see 86 passed and 1 skipped, which is also a pass. A skip says why it happened.

## Step 3. Try it yourself

```powershell
python -m scripts.try_engine
```

You'll see a ranking of three example serums, each flag with its reason and source, and the not-medical-advice line.
Now open `data/try_example.json` in VS Code and play with it. Things to try:
- Change `"sensitive": true` to `false` and run again. The fragrance warnings disappear.
- Paste the ingredient lists of two of your own products of the **same type**, and change `product_type` to match. Product type ids are listed in `data/product_types.csv`, for example `body_lotion` or `hair_oil_serum`.
- Change the concerns. Use ids from `data/concerns.csv`, for example `"dryness"` or `"hair-fall"`.

## How the ranking works (in plain words)

- Each "may suit" flag **adds** points and each "may not suit" flag **takes away** points: low = 1, medium = 2, high = 3.
- **Rinse-off** products (face wash, shampoo and so on) count **half**, because they're washed away.
- If you said you're **sensitive**, cautions on rules tagged for sensitive skin count **1.5 times**.
- If one ingredient, such as fragrance, is flagged by several rules, only the **strongest** one counts toward the order, but you still see all of them.
- **Ties:** equal points means the product with fewer cautions goes higher. If they're still equal, they share a rank (1, 1, 3).
- Shoppers never see the points, only the order, the flags and the reasons.

You can change any of these numbers in `app/config.py`.

## Explain it back

> "I built the brain of the app, and it isn't AI. It cleans up ingredient lists, checks them against
> my rulebook, and puts the products in order using fixed weights. Tests prove it gives the same
> answer every time, doesn't confuse things like cetearyl alcohol with drying alcohol, and handles
> ties fairly."
