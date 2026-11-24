# Update 0.6.0: a ranking you can understand, and no "Name to show" box

## Why Moxie came first before (and why that was partly wrong)
The order comes only from our rules table. Moxie matched one rule ("cationic conditioning agents")
through polyquaternium-10. Your other shampoo matched nothing, so Moxie came first.

But two things were unfair:
1. **Spelling.** Moxie's label wrote "Polyquaternium 44" and "Guar Hydroxypropyl Trimonium Chloride" with
   spaces. Our table had them without spaces, so they were skipped.
2. **"(and)" lists.** Labels often write blends like "Dimethiconol (and) TEA-Dodecylbenzenesulfonate".
   The app read that as ONE unknown ingredient, so silicones and conditioners in your shampoo were missed.

And the summary said "Both products are designed for frizz..." which the flags never said. That
made the ranking look random.

## What changed
- **"(and)" blends are split** into separate ingredients, and names that differ only by spaces or hyphens
  now match (for example "polyquaternium 44" = "polyquaternium-44"). More conditioning polymers were added
  to the same rule: polyquaternium-7, -11, -22, -44 and -67.
- **A "why" line under each product in the ranking**, for example:
  *"2 ingredient groups commonly used for your concerns (cationic conditioning agents, silicones); 0 that may
  not suit you. 6 ingredients are not in our table, so they didn't count either way."*
- **An honest "Why this order" note.** If products differ by one ingredient group or less, it says they are
  close and the difference is small. If nothing matched in either, it says they are tied.
- **The summary can't make claims the flags don't show.** Words like "designed for", "formulated for",
  "made for", "better", "leads" and "suitable" are rejected, and the fixed template is used instead.
- **No "Name to show" box.** Barcode and search use the product's real name. Pasted text and photos have
  one optional "Product name" box; leave it empty and it says "Product 1", "Product 2"... Two products with
  the same name get "(2)" added automatically.

## How to install (Windows PowerShell)
1. Close the app if it is running (Ctrl + C in its window).
2. Unzip `skincare-compare-update-ranking.zip` **into** your `skincare-compare` folder and choose
   "Replace the files in the destination". Your `.env`, `my_products.csv` and `seed_products.csv` are not in it.
   (`data/rules.csv` IS in it, because one rule gained new ingredient names.)
3. In PowerShell, in the `skincare-compare` folder:

```powershell
.\.venv\Scripts\Activate.ps1
python -m scripts.validate_data
python -m pytest -q
python -m scripts.run_app
```
You should see "All checks passed", then **286 passed** (a few "skipped" is fine).
Then run your two shampoos again.
