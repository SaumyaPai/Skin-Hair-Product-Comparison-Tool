# Phase 1 guide: setup and feasibility

This is everything you do by hand for Phase 1. Copy each command exactly.
Lines starting with `#` are notes, not commands.

## Step 1. Install the free tools (one time)

1. **Python 3.11 or newer**: https://www.python.org/downloads/
   - Windows: on the first installer screen, tick **"Add python.exe to PATH"**.
2. **VS Code** (free code editor): https://code.visualstudio.com/
3. Download this `skincare-compare` folder to your computer, then in VS Code choose
   **File → Open Folder** and pick it. Open a terminal with **Terminal → New Terminal**.

## Step 2. Make the project's private package box (virtual environment)

```
# Mac
python3 -m venv .venv
source .venv/bin/activate

# Windows
python -m venv .venv
.venv\Scripts\activate
```

You should now see `(.venv)` at the start of the terminal line. Do this `activate` line every time you open a new terminal.

```
pip install -r requirements.txt
```

## Step 3. Get your free Gemini key

1. Go to https://aistudio.google.com/apikey and sign in with a Google account.
2. Click **Create API key** and copy it.
3. In VS Code, copy the file `.env.example` and name the copy `.env`.
4. Paste your key after `GEMINI_API_KEY=` (no spaces, no quotes). Save.

Never share `.env` or paste the key into a chat.

## Step 4. Add your 10 products

Open `data/my_products.csv`. For each product you own, replace `REPLACE_ME` with the
barcode number under the stripes (digits only), and change the name to something you'll recognise.

## Step 5. Run the checks

```
# 1) Start the API (leave this terminal running)
uvicorn app.main:app --reload
```
Open http://localhost:8000/health in your browser. You should see `"status":"ok"`.
Press `Ctrl + C` in the terminal to stop it when done.

```
# 2) Test Gemini
python -m scripts.check_gemini

# 3) Look up your 10 products
python -m scripts.check_obf

# 4) Run all Phase 1 tests
pytest -v
```

## Phase 1 passes when

- `/health` shows `"status":"ok"`
- `check_gemini` prints `PASS: Gemini is working.`
- `check_obf` prints a table for all 10 products and saves `scripts/results/obf_check_results.csv`
- `pytest -v` shows everything **passed**, with **0 skipped** (skips mean a key or barcodes are missing)

If fewer than about 4 of your 10 products have ingredients, that's a **finding**, not a failure:
it means pasted text and label photos will matter more.

## Explain it back

> "I set up my computer so it can run a small Python web service. I proved three things work:
> the service answers, the free AI answers, and the free product database knows about some of my
> own products. I now know roughly how often the database will have what I need."
