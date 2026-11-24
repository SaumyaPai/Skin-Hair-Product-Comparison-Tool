# Update 0.8.4: faster photo reading, and a better offline reader

## Why 0.8.3 felt slower than the old Read button
The old Read button made one quick call per AI on a shrunken photo and accepted the first answer, even when it
was cut short (that's how lists ended in "..."). 0.8.3 always made two calls per AI (find the list, then read
it), retried Groq up to 3 more times when it refused the photo, and asked the next AI whenever a list looked
short. Correct, but slow.

## What changed
- **One quick read first.** The app reads the whole photo in one call. It only zooms in on the list (two more
  calls) if that answer looks cut short.
- **No knocking on closed doors.** An AI that has used up its free limit, or refuses the photo, is skipped for
  30 minutes (briefly busy ones for 5), so the next photo moves on instantly. No Groq retries on a refused photo.
- **The reader that worked goes first next time**, and if it needed the close-up, it starts with the close-up.
- **You can see what's happening:** "Trying Gemini (gemini-3.5-flash-lite) (3 of 5)..." on the product card,
  and the rest of the page no longer fades out while it reads.
- **Better offline reader (no AI).** It now finds the word "INGREDIENTS", cuts out just that block of small print,
  enlarges it, and stops at the batch code "(F.I.L." or "FOR MFD". On your conditioner photo it now reads:
  *AQUA / WATER, CETEARYL, ALCOHOL, DIMETHICONE, GLYCERIN, BEHENTRIMONIUM CHLORIDE, CI 17200 / RED 35, CI 42090 /
  BLUE i, LACTIC ACID, SODIUM UAURETH SULFATE, SODIUM HYDROXIDE, SODIUM HYALURONATE, PHENOXYETHANOL, IMONENE,
  AMODIMETHICONE, iSOPROPYL A COHOL, CETRIMONIUM CHLORIDE, PARFUM / FRAGRANCE*
  (close, with a few letters lost at the curved edge: please fix those before comparing).
  If an offline read has fewer than 3 ingredients we recognise, it isn't shown; you get "We couldn't read this
  photo reliably without AI. Please paste the ingredient list..." instead of junk.

## See the real timing on your PC
```powershell
python -m scripts.check_photo "C:\Users\YOU\Downloads\Conditioner_jpg.jpg"
```
It prints how long each reader took and whether its list looks complete.

## Install (Windows PowerShell): copy and paste these lines one at a time
1. Close every PowerShell window that is running the app (or press Ctrl + C in each).
2. Download `skincare-compare-update-0.8.4.zip` (it goes to your Downloads folder).
3. Then:

```powershell
cd D:\Claude_comparison_project1
$zip = Get-ChildItem "$HOME\Downloads\skincare-compare-update-0.8.4*.zip" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
$zip.FullName
Expand-Archive -Path $zip.FullName -DestinationPath "D:\Claude_comparison_project1" -Force
cd skincare-compare
.\.venv\Scripts\Activate.ps1
python -c "from app import config; print(config.APP_VERSION)"
```
- The `$zip.FullName` line shows which file was found. If it shows nothing, the zip isn't in Downloads.
- The last line must print **0.8.4**.

4. Check and start:
```powershell
python -m pytest -q
python -m scripts.run_app
```
The tests should show **317 passed** (a few "skipped" is fine). The page shows **Version 0.8.4** under the title.

Your `.env`, `data\my_products.csv` and `data\seed_products.csv` are not in the zip, so they're never overwritten.
