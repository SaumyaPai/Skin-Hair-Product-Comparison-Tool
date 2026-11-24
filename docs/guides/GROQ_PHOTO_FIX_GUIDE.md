# Fix 0.5.2: Groq said "400 Bad Request" on label photos

## What was wrong
After fix 0.5.1, the app sends the AI a sharp, enlarged close-up of the ingredient list. Gemini read
your shampoo list fully this way, but Groq refused the request with "400 Bad Request". Groq didn't
say why, because the app only printed the number. The two most likely reasons:
- the picture was larger than Groq is happy with, or
- the ingredient list is very long, and Groq's "strict JSON" check failed on the long answer.

The offline reader (Tesseract) also failed, because it looks for the word "Ingredients", and on your
curved, white-on-blue label it can't see that word.

## What changed
1. **Groq's own reason is shown.** If Groq refuses again, the log and the check script show its
   message (your key is never shown).
2. **Pictures sent to Groq stay small enough:** at most 2048 pixels and 3 MB. Groq shrinks pictures to
   this size anyway, so nothing is lost. Groq is also allowed a longer answer, for long ingredient lists.
3. **One safer retry.** If Groq still refuses, the app tries once more with a smaller picture and without
   the strict JSON check, before moving on to the next AI.
4. **Better offline reading.** If an AI found where the list is but then failed, the offline reader reads
   that close-up, so it no longer needs to see the word "Ingredients". It also turns white text on a dark
   label into dark text on white. Offline reading makes more mistakes, so its results always come with
   the "may be incomplete" warning.

## How to install (Windows PowerShell)
1. Close the app if it is running (Ctrl + C in its window).
2. Unzip `skincare-compare-fix-groq-photo.zip` **into** your `skincare-compare` folder and choose
   "Replace the files in the destination". Your `.env` and product files are not in the zip.
3. In PowerShell, in the `skincare-compare` folder:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pytest -q
python -m scripts.check_photo "C:\Users\YOU\Downloads\unnamed.jpg"
python -m scripts.run_app
```
The tests should show **266 passed** (a few may be "skipped", which is fine).
If Groq still fails in the check script, the line now ends with Groq's reason. Send that line to Claude.
