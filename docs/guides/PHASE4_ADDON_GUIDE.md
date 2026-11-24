# Phase 4 add-on: backup AI and offline photo reading (Windows)

Gemini's free tier is often busy (error 503). This add-on means that doesn't break anything.

**For the summary**, the app tries each step in order and stops at the first one that works:
1. Groq, a second free AI provider (only if you add a Groq key)
2. Your main Gemini model (`gemini-3.8-flash`)
3. Lighter Gemini models (`gemini-3.5-flash-lite`, then `gemini-3.6-flash`)
4. The **template summary**, which always works

If an AI is busy or too slow, it's **skipped for 5 minutes** instead of being tried again on every request.
To put Gemini first instead, add `AI_FIRST=gemini` to `.env`.

**For label photos**: Groq, then the same Gemini models, then **Tesseract**, a free program that reads text from photos on your own computer with no AI and no internet.

Every AI's summary goes through the same safety check (no banned words, no ingredients that aren't in the flags, must name the product ranked first). A reply that fails moves on to the next step. The answer now says who did the work: `summary_provider` for the summary and `reader` for photos.

## Step 1. Apply the update

Save `skincare-compare-update-phase4-addon.zip` into `D:\Claude_comparison_project1\`, then:

```powershell
cd D:\Claude_comparison_project1
Expand-Archive .\skincare-compare-update-phase4-addon.zip -DestinationPath . -Force
cd .\skincare-compare
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Step 2. Install Tesseract (free, about 2 minutes)

1. Download the 64-bit Windows installer from the page linked here:
   https://github.com/UB-Mannheim/tesseract/wiki
   The file is named like `tesseract-ocr-w64-setup-5.5.x.exe`.
2. Run it, keep the suggested folder (`C:\Program Files\Tesseract-OCR`), and click through with the defaults. English is included.
3. Close and reopen VS Code, then check it:

```powershell
& "C:\Program Files\Tesseract-OCR\tesseract.exe" --version
```

You should see `tesseract 5.x`. If you installed it in a different folder, add this line to your `.env` with your folder:
`TESSERACT_CMD=D:\your\folder\tesseract.exe`

## Step 3 (optional). Add a free Groq key

1. Sign up at https://console.groq.com and create a key at https://console.groq.com/keys.
2. Open your `.env` in VS Code and add this line:

```
GROQ_API_KEY=paste-your-key-here
```

Skip this step if you like. Without a key, the app just skips Groq. As with Gemini, only label photos and the finished flags are ever sent, never anything about you.

## Step 4. Check the backup order and run the tests

```powershell
python -m scripts.list_models
python -m pytest -v
```

`list_models` prints the order the app will try, plus the models your keys can actually use. If one of the lighter Gemini names isn't in your list, copy a "flash" name from the list into your `.env`:
`GEMINI_FALLBACK_MODELS=name-one,name-two`

**This passes when** you see **186 passed**. A skip with a clear reason (for example "Gemini is busy") also counts.

To check that Groq works for both jobs, run:

```powershell
python -m scripts.check_groq
```

If the **Photos** line says FAILED, add `GROQ_VISION_MODEL=` (with nothing after the `=`) to `.env`. Photos will then skip Groq and go straight to Gemini and Tesseract.

## Step 5. Try it

Start the API (`python -m uvicorn app.main:app --reload`), open http://localhost:8000/docs, and upload a label photo to **POST /v1/products/extract**. Look at `reader` in the answer to see which one read your photo. In **POST /v1/compare**, `summary_provider` shows who wrote the summary.

## Explain it back

> "Free AI services are often busy, so my app has a backup plan. It tries the main Gemini model,
> then lighter ones, then another free provider, and if none answer it still works: the summary
> comes from a fill-in-the-blanks template, and photos are read offline by Tesseract. Every AI
> answer is checked by the same rules before anyone sees it."
