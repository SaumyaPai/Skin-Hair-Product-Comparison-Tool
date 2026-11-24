# Update 0.7.0: telling similar products apart, and quicker adding

## How similar products are now told apart
1. **Where the ingredient sits on the label.** By law, labels list ingredients from the largest amount
   to the smallest (for everything above 1%). So an ingredient near the top of the list is likely there
   in a larger amount than one near the end. The app now counts an ingredient in the first third of the
   list (always the first 5) fully, and one lower down a bit less. The "why" line shows it, for example:
   *"cationic conditioning agents: 5th of 10, near the top"*.
   Source: [FDA cosmetics labeling](https://www.fda.gov/cosmetics/cosmetics-labeling-regulations/summary-cosmetics-labeling-requirements).
2. **A new "may not suit" rule:** sulfate cleansers (like sodium lauryl or laureth sulfate) in shampoo, when
   you choose Frizz. A hair-science review says these strong cleansers can add negative charge to the hair
   and increase frizz. Source: [Hair cosmetics: an overview](https://pmc.ncbi.nlm.nih.gov/articles/PMC4387693).
3. **Real ties stay ties.** If nothing in our table differs, the app says they're tied instead of inventing a winner.

## What we did NOT use, and why
- **"Fewer chemicals" or a shorter ingredient list.** Everything is a chemical, water included, and a
  short list isn't gentler or better by itself. There is no good evidence for it, so it would mislead you.
- **Drying alcohol for hair.** We looked for a trusted source on alcohol in hair products and didn't find
  one, so it isn't a rule yet. (For skin, the existing dry-skin rule still applies.)
- **Exact amounts.** Labels don't give percentages, so the app never guesses them.

## Quicker adding
- **Label photo:** reading starts as soon as you add the photo. There's no "Read label" button.
- **Search by name:** type the name and press Enter. There's no "Search" button.
- **Barcode:** type it and press Enter (the "Check barcode" button still works too).
- **No name box.** Barcode and search use the real product name. Pasted lists and photos are called
  "Product 1", "Product 2"...

## How to install (Windows PowerShell)
1. Close the app if it is running (Ctrl + C in its window).
2. Unzip `skincare-compare-update-tiebreak.zip` **into** your `skincare-compare` folder and choose
   "Replace the files in the destination". Your `.env`, `my_products.csv` and `seed_products.csv` are not in it.
   (`data/rules.csv` is, because of the new sulfate rule.)
3. In PowerShell, in the `skincare-compare` folder:

```powershell
.\.venv\Scripts\Activate.ps1
python -m scripts.validate_data
python -m pytest -q
python -m scripts.run_app
```
You should see "All checks passed", then **292 passed** (a few "skipped" is fine).
