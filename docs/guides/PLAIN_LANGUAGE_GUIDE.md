# Update 0.8.0: results in plain words

## What you'll see now
- Under each product in the ranking:
  - **"Why it's ranked first: it has smoothing conditioners high up in the formula, commonly used for frizz
    and dry or damaged hair, and nothing we know of that may not suit you."**
  - **"Worth knowing: it has sulfate cleansers high up in the formula, which may not suit frizz."** This line
    only appears when there is something to know.
- A short note: "Higher up the list usually means more of it: labels list ingredients from the largest
  amount to the smallest", with a Source link. When products are close, the note says so.
- The summary uses the same everyday words. If the AI writes things like "rules", "flags" or "our table",
  its summary is thrown away and the plain fixed summary is used.
- Each product card shows friendly names such as "Smoothing conditioners (polyquaternium-10)", with
  "May suit" or "May not suit" and the Source link, just like before.
- The long "Not in our tables" list is gone. A small **"Full ingredient list"** section, closed by default,
  shows every ingredient if you want it.

## What stays the same behind the scenes
The order still comes only from the sourced rules table (code decides, not AI). There are still no scores,
no "good" or "bad", no medical claims, and the not-medical-advice line is still shown.

## How to install (Windows PowerShell)
1. Close the app if it is running (Ctrl + C in its window).
2. Unzip `skincare-compare-update-plain-language.zip` **into** your `skincare-compare` folder and choose
   "Replace the files in the destination". Your `.env`, `my_products.csv` and `seed_products.csv` are not in it.
   (`data/rules.csv` is, because it has a new "plain_name" column.)
3. In PowerShell, in the `skincare-compare` folder:

```powershell
.\.venv\Scripts\Activate.ps1
python -m scripts.validate_data
python -m pytest -q
python -m scripts.run_app
```
You should see "All checks passed", then **295 passed** (a few "skipped" is fine).
