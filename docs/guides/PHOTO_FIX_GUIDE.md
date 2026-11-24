# Fix 0.5.1: label photos that only showed part of the ingredient list

## What was wrong
Your shampoo photo is very large (4284 x 5712 pixels). The app shrank every photo to 1600 pixels
before sending it to the AI, to save free quota. The ingredient list on that bottle is small, curved
white text, so after shrinking it was too blurry to read. The AI then read the first few words,
guessed at the rest of the picture, and ended the list with "...". So yes: the AI did not read all
the ingredients, and the app did not tell you.

## What changed
1. **Two-step reading.** The AI first finds where the ingredient list is on the photo. The app then
   cuts that part out of the full-size photo, enlarges it if the text is small, and asks the AI to
   read only that sharp close-up. If the list can't be found, it reads the whole photo at a much
   higher sharpness (2400 px instead of 1600 px). Gemini is also asked to look at the photo in high detail.
2. **Stricter instructions.** The AI is told this is one photo, to copy every item (including
   "(and)" items), never to shorten or end with "...", and to say honestly if part is cut off.
3. **Cut-short check.** If an answer ends with "...", "(and)", "and" or a comma, or the AI says part was
   hard to see, the app tries the next AI and keeps the most complete answer.
4. **A warning on the page.** If every AI still gives a list that may be incomplete, you see a yellow
   message: *"This ingredient list may be incomplete..."*. Compare it with the label and add what's missing,
   or paste the list.
5. Photos up to **10 MB** are accepted (was 5 MB), and sideways phone photos are turned upright.

**Tip:** crop the photo to just the ingredient list, straight on and in good light. It reads best.

## How to install (Windows PowerShell)
1. Close the app if it is running (press Ctrl + C in its PowerShell window).
2. Unzip `skincare-compare-fix-photo-reading.zip` **into** your `skincare-compare` folder and choose
   "Replace the files in the destination". Your `.env`, `my_products.csv` and `seed_products.csv` are not in the zip.
3. Open PowerShell in the `skincare-compare` folder and run:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pytest -q
```
You should see **256 passed** (a few may say "skipped", which is fine).

## See which AI reads your photo fully
```powershell
python -m scripts.check_photo "C:\Users\YOU\Downloads\shampoo-label.jpg"
```
Put the real path of your photo in the quotes. For each AI it prints how many ingredients it read and
whether the list looks complete, then the list itself. Each AI uses about two requests from your free quota.

## Then start the app
```powershell
python -m scripts.run_app
```
