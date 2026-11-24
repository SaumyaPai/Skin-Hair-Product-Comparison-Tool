# Installing update 0.8.1 (and why the last update didn't show)

## Why you still saw the old page
The last zip had its files at the top level (`app\...`, `ui\...`) with no `skincare-compare` folder.
When it was unzipped into `D:\Claude_comparison_project1`, or with Windows "Extract All" (which makes a new
folder named after the zip), the new files landed next to your app instead of replacing it. Your app kept
running the old code, so the buttons, the name box and the ties were all still there.

This zip has the `skincare-compare` folder inside it, so one command puts every file in the right place.

## Install (Windows PowerShell)
1. Stop the app: press **Ctrl + C** in the PowerShell window where it runs, and close the browser tab.
2. Put the zip in your Downloads folder, then run these lines one at a time:

```powershell
cd D:\Claude_comparison_project1
Expand-Archive -Path "$HOME\Downloads\skincare-compare-update-0.8.1.zip" -DestinationPath "D:\Claude_comparison_project1" -Force
cd skincare-compare
.\.venv\Scripts\Activate.ps1
python -c "from app import config; print(config.APP_VERSION)"
```
The last line must print **0.8.1**. If it prints something else, the files didn't land in the right place.

3. Check and start:
```powershell
python -m scripts.validate_data
python -m pytest -q
python -m scripts.run_app
```
You should see "All checks passed", then **295 passed** (a few "skipped" is fine).
The page now shows **Version 0.8.1** under the title. If the browser still shows the old page, press **Ctrl + F5**.

Your `.env`, `data\my_products.csv` and `data\seed_products.csv` are not in the zip, so they are never overwritten.

## What's in 0.8.1 (everything since 0.5.2)
- Results in plain words: "Why it's ranked first", "Worth knowing", and a closed "Full ingredient list".
- Photos are read as soon as you add them, search and barcode run when you press Enter, and there's no name box.
- **Ties broken by position, step by step.** Every place down the ingredient list counts 5% less (1st = full,
  2nd = 0.95, and so on, never below half from the 11th place). So two conditioners with the same kind of
  conditioner at 2nd and 4th place are no longer tied, and the page says the order comes from how high up the
  list it appears. Only the place counts, not how long the list is. Two products with the same ingredients in
  the same places stay tied, because nothing tells them apart.
- A sourced "may not suit" rule for sulfate cleansers in shampoo, for frizz.
- "(and)" blends split, and spelling variants like "Polyquaternium 44" are recognised.
