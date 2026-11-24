# Update 0.9.1: final check for the submission

## What's new
- **One command checks everything:** `python -m scripts.final_check`. It ends with **RESULT: PASS** or
  **RESULT: FAIL**, and writes `eval_results\RESULTS.md` for your write-up.
- **113 new end-to-end tests:** all 12 product types with every concern, barcode, name search, paste and
  photo (using your shampoo and conditioner photos), ties, close calls, sulfate cautions, label position,
  AI failures and backups, plain language, banned words and the disclaimer.
- **Pore-clogging check for acne-prone skin** (toner, serum, moisturiser, face mask and sunscreen). A
  product with none of the listed ingredients gets a green **"No pore-clogging ingredients found"** tag. A
  product that has them gets a "Worth knowing" line naming them, for example *"it has pore-clogging
  ingredients (isopropyl myristate and cocoa butter), which may not suit acne-prone skin"*, and ranks lower.
  The list comes from two dermatology studies (JAAD 1984 and J Soc Cosmet Chem 1989), with source links.
  Sunscreen now offers the acne-prone concern too.
- Cautions now name the actual ingredient, for example "sulfate cleansers (sodium laureth sulfate)".
- **One bug fixed:** pasting text with no real ingredient names (only commas or spaces) was ranked as if it
  were a product. It's now listed as "couldn't find ingredients" instead.
- User testing is marked "not done (out of scope for this submission)" in the results sheet.

## Install (Windows PowerShell): copy and paste these lines one at a time
1. Close every PowerShell window that is running the app (or press Ctrl + C in each).
2. Download `skincare-compare-update-0.9.1.zip` (it goes to your Downloads folder).
3. Then:

```powershell
cd D:\Claude_comparison_project1
$zip = Get-ChildItem "$HOME\Downloads\skincare-compare-update-0.9.1*.zip" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
$zip.FullName
Expand-Archive -Path $zip.FullName -DestinationPath "D:\Claude_comparison_project1" -Force
cd skincare-compare
.\.venv\Scripts\Activate.ps1
python -c "from app import config; print(config.APP_VERSION)"
```
- The `$zip.FullName` line shows which file was found. If it shows nothing, the zip isn't in Downloads.
- The last line must print **0.9.1**.

4. Run the final check (about 10 minutes; leave the window open):
```powershell
python -m scripts.final_check
notepad eval_results\RESULTS.md
```
The tests inside it should show **456 passed** (a few "skipped" is fine).
For a 2-minute version without the measurements: `python -m scripts.final_check --quick`

5. Start the app as usual: `python -m scripts.run_app`. The page shows **Version 0.9.1** under the title.

WARN lines are fine (for example, one AI being busy). If it says **RESULT: FAIL**, send me the lines under it.

Your `.env`, `data\my_products.csv`, `data\seed_products.csv`, `eval_inputs\` and `eval_results\` are not in
the zip, so they're never overwritten.
