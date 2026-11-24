# Update 0.8.2: always open the NEW page

## Why you still saw "Name to show"
The new files were installed, but an **older copy of the app was still running** in the background
(from an earlier PowerShell window). It kept answering on the same address, so the browser showed the
old page. Starting the app again couldn't take over the address, and it didn't tell you.

## What changed
- `python -m scripts.run_app` now checks for an old copy first. If one is running, it stops it and says so:
  *"Port 8501 is already in use, probably by an older copy of the page... Stopping the old copy..."*
  It only stops copies of this app (Python). Any other program is left alone, and you're told what to do.
- It also checks the API version matches, and tells you the page version when it opens.
- The **"Check barcode"** button is gone: type the barcode and press Enter.

## Install (Windows PowerShell)
1. Close **every** PowerShell window that is running the app (or press Ctrl + C in each).
2. Put the zip in Downloads, then run these lines one at a time:

```powershell
cd D:\Claude_comparison_project1
Expand-Archive -Path "$HOME\Downloads\skincare-compare-update-0.8.2.zip" -DestinationPath "D:\Claude_comparison_project1" -Force
cd skincare-compare
.\.venv\Scripts\Activate.ps1
python -c "from app import config; print(config.APP_VERSION)"
python -m pytest -q
python -m scripts.run_app
```
The version line must print **0.8.2**, and the tests should show **300 passed** (a few "skipped" is fine).
The page shows **Version 0.8.2** under the title. If the browser still shows an old page, press **Ctrl + F5**.

Your `.env`, `data\my_products.csv` and `data\seed_products.csv` are not in the zip.
