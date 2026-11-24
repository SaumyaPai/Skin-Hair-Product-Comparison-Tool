# Phase 2 guide: data and rule table (Windows)

All commands are for **Windows PowerShell** inside VS Code. Copy each grey box exactly.

## What's new in this phase

| File | What it is |
|---|---|
| `data/rules.csv` | 41 starter rules. Each has a reason and a real source link that I opened and checked. |
| `data/aliases.csv` | 60 other names for the same ingredient (for example `parfum` is `fragrance`, `aqua` is `water`). |
| `data/product_types.csv` | The 12 product types, skin or hair, leave-on or rinse-off. |
| `data/concerns.csv`, `data/profiles.csv` | Labels for concerns and "about you" options. These are two small extra files so the checker can catch typos. |
| `data/seed_products.csv` | Your 10 products. You add their ingredients here (Step 4). |
| `app/db.py` | Creates the local database file `data/app.db`. |
| `scripts/validate_data.py` | Checks every data file and shows which concerns the dropdown will show. |
| `scripts/seed_cache.py` | Copies your seed products into the database. |
| `tests/test_phase2.py` | 29 new tests (with Phase 1's 18, that's 47 in total). |

## Step 1. Put the whole app in one folder

From now on the app lives in **one folder**, `D:\Claude_comparison_project1\skincare-compare`. Every later phase updates that same folder.

1. Save `skincare-compare.zip` into `D:\Claude_comparison_project1\`.
2. Open PowerShell (or a VS Code terminal) and run:

```powershell
cd D:\Claude_comparison_project1
Expand-Archive .\skincare-compare.zip -DestinationPath . -Force
Copy-Item .\skincare-compare-phase1\skincare-compare\.env .\skincare-compare\
Copy-Item .\skincare-compare-phase1\skincare-compare\data\my_products.csv .\skincare-compare\data\ -Force
Copy-Item .\skincare-compare-phase1\skincare-compare\scripts\results .\skincare-compare\scripts\ -Recurse -Force
```

3. In VS Code: **File → Open Folder** → pick `D:\Claude_comparison_project1\skincare-compare`.

Once Phase 2 passes, you can delete the old `skincare-compare-phase1` folder.

**For later phases:** run the same `Expand-Archive ... -Force` line on the new zip. It replaces the code but keeps your `.env` and `.venv`. Update zips will not include the files you edit yourself (`my_products.csv` and `seed_products.csv`), so your typing is never overwritten. If I ever change `rules.csv`, I'll tell you first.

## Step 2. Make this folder's package box

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

You should see `(.venv)` at the start of the line. If PowerShell says "running scripts is disabled", run this once and then run the Activate line again:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

## Step 3. Run the checker

```powershell
python -m scripts.validate_data
```

It should end with **`All checks passed`**. Above that it lists the concerns the dropdown will show for each product type. Every concern now appears for at least some types:
- **Dark circles** shows for serum and moisturizer, because that's where under-eye products fit.
- **Hair fall** shows for shampoo, conditioner, and hair oil or serum.

## Step 4. Add your products' ingredients (do at least 3)

Open `data/seed_products.csv` **in VS Code, not Excel**. Excel turns long barcodes into numbers like `8.90109E+12` and breaks them.

For each product, type the ingredient list from the pack after the last comma, **inside double quotes**, because ingredient lists contain commas:

```
8904417315141,Face Wash,DermaCo,face_wash,"Aqua, Glycerin, Salicylic Acid, ..."
```

Tips:
- For the 3 products Open Beauty Facts found (Balea toner, Vaseline serum-in-lotion, Pilgrim spray), you can copy the text from `scripts\results\obf_check_results.csv` in your Phase 1 folder. Check it against the pack first.
- Please check the `product_type` I guessed for each product. I guessed `hair_oil_serum` for the Pilgrim spray and the Dove leave-in, and `moisturizer` for the aloe gel.
- A product with no ingredients is fine. It is just skipped.

Then load them into the database and check again:

```powershell
python -m scripts.seed_cache
python -m scripts.validate_data
```

## Step 5. Run all tests

```powershell
python -m pytest -v
```

## Phase 2 passes when

- `validate_data` prints **All checks passed**
- `python -m pytest -v` shows **47 passed**. If Gemini is busy again (error 503), wait a few minutes and rerun. That's Google's free tier, not your code.
- You've read the dropdown list from Step 3 and you're happy with which concerns appear.

## Please review the rules (it's your rulebook)

Open `data/rules.csv` in VS Code. Each line reads:
*if a product of type `applies_to` contains one of `match_terms`, and the shopper picked a concern or profile in `relevant_profiles`, then flag it as `flag_type`, with this `severity`, because of `rationale`, according to `source`.*

The sources I used (all opened and checked on 22 Nov 2026):

| Source | Used for |
|---|---|
| [Mayo Clinic: Nonprescription acne treatment](https://www.mayoclinic.org/diseases-conditions/acne/in-depth/acne-treatments/art-20045814) | Acne-prone, acne marks, AHAs for dullness |
| [AAD: How to fade dark spots](https://aad.org/public/everyday-care/skin-care-secrets/routine/fade-dark-spots) | Pigmentation, acne marks, tinted sunscreen |
| [AAD: Tips for relieving dry skin](https://www.aad.org/public/everyday-care/skin-care-basics/dry/dermatologists-tips-relieve-dry-skin) | Dryness (what to look for and what to avoid) |
| [AAD: Rosacea skin care tips](https://www.aad.org/public/diseases/acne-and-rosacea/rosacea/6-rosacea-skin-care-tips-dermatologists-give-their-patients) | Redness |
| [AAD: How to treat dandruff](https://www.aad.org/public/everyday-care/hair-scalp-care/scalp/treat-dandruff) | Dandruff, flaky scalp, itchy scalp |
| [Topical Vitamin C and the Skin (J Clin Aesthet Dermatol, 2017)](https://pmc.ncbi.nlm.nih.gov/articles/PMC5605218/) | Vitamin C for pigmentation and dullness |
| [Niacinamide review (Antioxidants, 2021)](https://pubmed.ncbi.nlm.nih.gov/34439563/) | Niacinamide for pigmentation |
| [Azelaic Acid review (Clin Cosmet Investig Dermatol, 2024)](https://pmc.ncbi.nlm.nih.gov/articles/PMC11512533/) | Azelaic acid for pigmentation and redness |
| [European Commission: perfume allergies](https://ec.europa.eu/health/scientific_committees/opinions_layman/perfume-allergies/en/l-3/2-skin-problems.htm) | Fragrance for sensitive skin and "avoid fragrance" |
| [Hair Cosmetics: An Overview (Int J Trichology, 2015)](https://pmc.ncbi.nlm.nih.gov/articles/PMC4387693) | Conditioners and silicones for frizz and dry or damaged hair |
| [Coconut oil and hair damage (J Cosmet Sci, 2003)](https://library.scconline.org/v054n02/77) | Coconut oil for dry or damaged hair |
| [Mayo Clinic: Dark circles under eyes](https://www.mayoclinic.org/symptoms/dark-circles-under-eyes/basics/when-to-see-doctor/sym-20050624) | Caffeine, vitamin K and kojic acid for dark circles |
| [Mayo Clinic: Minoxidil (topical)](https://www.mayoclinic.org/drugs-supplements/minoxidil-topical-route/description/drg-20068750) | Minoxidil for hair fall, and its scalp irritation flag for sensitive scalps |
| [Caffeine against hair loss: systematic review (Healthcare, 2025)](https://pmc.ncbi.nlm.nih.gov/articles/PMC11855793/) | Caffeine for hair fall (weak evidence) |
| [Rosemary oil vs minoxidil 2% trial (Skinmed, 2015)](https://pubmed.ncbi.nlm.nih.gov/25842469/) | Rosemary oil for hair fall (one small trial) |

Things for you to decide (just tell me in the chat):
- **Severity values** (low, medium, high) are my starting suggestions. Change any you disagree with.
- **Vitamin C forms:** only `ascorbic acid` is matched right now. Products often use other forms (like sodium ascorbyl phosphate), but the sources mostly studied ascorbic acid, so I left them out.
- **Rosemary:** only rosemary *oil* is matched. Rosemary *water* or *extract* (like in your Pilgrim spray) wasn't the thing tested in the study, so it isn't flagged.

## Explain it back

> "I wrote the rulebook the app follows. Each rule says: if a product of this type contains this
> ingredient, and the shopper has this concern, flag it as 'may suit' or 'may not suit', and here is
> why and where that comes from. A checker makes sure my rulebook has no gaps or typos, and only
> concerns with rules behind them will ever show up in the dropdown."
