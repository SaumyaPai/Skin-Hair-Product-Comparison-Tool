# Phase 5 guide: the shopper's page (Windows)

This phase builds the page shoppers actually use. It runs in your web browser and only talks to your API. It never calls Open Beauty Facts, Gemini or Groq itself.

What the page does, top to bottom:
1. **Product type:** choose one of the 12 types.
2. **Concerns:** a list filtered to that type, built from your rule table. You can pick up to 3.
3. **About you:** skin type (or scalp type for hair products), "sensitive", and "avoid fragrance".
4. **Products:** 2 to 4, each added one of 4 ways:
   - **Barcode:** type it, and optionally press **Check barcode**.
   - **Search by name:** search, then pick the right product from the list. The page never picks for you.
   - **Paste ingredients.**
   - **Label photo:** upload it, press **Read label**, then **check and fix** the text before comparing.
5. **Compare:** greyed out until everything is filled in. A note under it says what's still missing.
6. **Results:** the ranking (ties marked "tied"), the summary, each product's ✅ "may suit" and ⚠️ "may not suit" flags with the reason and a **Source** link, ingredients not in your tables, products that couldn't be found with what to do next, and the not-medical-advice line at the bottom.

## Step 1. Apply the update

Save `skincare-compare-update-phase5.zip` into `D:\Claude_comparison_project1\`, then:

```powershell
cd D:\Claude_comparison_project1
Expand-Archive .\skincare-compare-update-phase5.zip -DestinationPath . -Force
cd .\skincare-compare
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

**Remember:** you need `(.venv)` at the start of the line before any `python` command. If it's missing, run `.\.venv\Scripts\Activate.ps1` again. The install adds **Streamlit**, which is free. It's a bigger download and may take a few minutes.

## Step 2. Run all tests

```powershell
python -m pytest -v
```

**Phase 5 passes when** you see **210 passed**. A skip that gives a clear reason, like "Gemini is busy", also counts. The new tests drive the real page without a browser: they pick a type, fill in products all 4 ways, press Compare, and check the results.

## Step 3. Start the whole app with one command

```powershell
python -m scripts.run_app
```

This starts the API, then the page, and opens **http://localhost:8501** in your browser. Keep this window open while you use the app, and press `Ctrl + C` in it to stop everything.

## Step 4. Click through this checklist

- [ ] Change the product type. The concerns list changes. Serum shows Dark circles, but Face wash doesn't.
- [ ] With 0 concerns or an empty product, **Compare** stays greyed out, and the note says what's missing.
- [ ] **Barcode:** `4070765077490` (your Balea toner), then **Check barcode**. It says what it found.
- [ ] **Search by name:** search for one of your products and pick it from the list.
- [ ] **Paste ingredients:** paste a list from a pack.
- [ ] **Label photo:** upload a real label photo, press **Read label**, check the text, and fix anything wrong.
- [ ] Press **Compare**. You see the ranking, flags with **Source** links, the summary, and the disclaimer at the bottom.
- [ ] Nowhere does it say "good", "bad", "best", a score, or "cure".
- [ ] Stop the app (`Ctrl + C`), then refresh the page in your browser. You get a friendly "isn't running" message, not a crash.

## Explain it back

> "I built the page shoppers actually use. It walks them through picking a type, concerns, and
> products, then shows the ranking with reasons and sources. The page never talks to the AI or the
> product database itself; it only asks my API, so all the honesty rules still apply."
