# Update 0.9.0: Phase 6, measuring how well the tool works

## What's new
- Scripts in `scripts\eval\` for the five Phase 6 measures: reading label photos, barcode coverage,
  consistency against a plain chatbot, made-up claims, and the user test.
- `python -m scripts.eval.results` builds one results sheet (`eval_results\RESULTS.md`) with everything
  measured so far and a "Still to do" list.
- `PHASE6_GUIDE.md` says what to fill in and what to run, step by step. `USER_TEST_SCRIPT.md` is the script
  for the user test (the 5 questions).
- The app itself works exactly as in 0.8.5.

## Install (Windows PowerShell): copy and paste these lines one at a time
1. Close every PowerShell window that is running the app (or press Ctrl + C in each).
2. Download `skincare-compare-update-0.9.0.zip` (it goes to your Downloads folder).
3. Then:

```powershell
cd D:\Claude_comparison_project1
$zip = Get-ChildItem "$HOME\Downloads\skincare-compare-update-0.9.0*.zip" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
$zip.FullName
Expand-Archive -Path $zip.FullName -DestinationPath "D:\Claude_comparison_project1" -Force
cd skincare-compare
.\.venv\Scripts\Activate.ps1
python -c "from app import config; print(config.APP_VERSION)"
```
- The `$zip.FullName` line shows which file was found. If it shows nothing, the zip isn't in Downloads.
- The last line must print **0.9.0**.

4. Check:
```powershell
python -m pytest -q
python -m scripts.eval.setup
```
The tests should show **339 passed** (a few "skipped" is fine). Setup creates your `eval_inputs\` folder.
Then follow `PHASE6_GUIDE.md`.

Your `.env`, `data\my_products.csv`, `data\seed_products.csv`, `eval_inputs\` and `eval_results\` are not in
the zip, so they're never overwritten.
