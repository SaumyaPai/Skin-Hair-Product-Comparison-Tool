# Phase 4 guide: the API and its connections (Windows)

This phase turns the engine into a working web API. You can try every part of it in your browser at `http://localhost:8000/docs`.

| Address | What it does |
|---|---|
| `GET /health` | Says the API is running and how many rules are loaded. |
| `GET /v1/meta/options` | Lists the product types, and the concerns that have rules for each one. The screen in Phase 5 builds its dropdowns from this. |
| `GET /v1/products/lookup` | Finds a product by `barcode` or by name (`q`). It checks your local database first, then Open Beauty Facts, and saves what it finds for 30 days. |
| `POST /v1/products/extract` | Upload a label photo, and Gemini copies the ingredient text. You always check that text before comparing. |
| `POST /v1/compare` | The full comparison: ranking, sourced flags, a summary and the disclaimer. |

How it stays honest and keeps working:
- **The summary:** Gemini only sees the finished flags. Code checks every summary it writes. If the summary uses a banned word, mentions an ingredient that isn't in the flags, or doesn't name the product ranked first, it's thrown away and the **template summary** is used instead. The same happens if Gemini is busy or not set up.
- **Products it can't find:** a missing product, a product with no ingredients listed, or a database that's down is reported as **unresolved**, with what to do next. Nothing is guessed. If Open Beauty Facts is down, the API uses an older saved copy if it has one, and says so.
- **Errors:** every error has the same simple shape (`code`, `message`, `request_id`), and the error codes are 200, 422, 404 and 502. A raw crash message never reaches the shopper.
- **The request log** (`request_log` table in `data/app.db`) saves only counts and timings, never ingredients, concerns or profiles.

## Step 1. Apply the update and install 2 new packages

Save `skincare-compare-update-phase4.zip` into `D:\Claude_comparison_project1\`, then:

```powershell
cd D:\Claude_comparison_project1
Expand-Archive .\skincare-compare-update-phase4.zip -DestinationPath . -Force
cd .\skincare-compare
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

The new packages are Pillow, which shrinks photos, and python-multipart, which handles photo uploads. Both are free. Your `.env`, `my_products.csv` and `seed_products.csv` are not touched.

## Step 2. Run all tests

```powershell
python -m pytest -v
```

**Phase 4 passes when** you see **150 passed**. If Gemini is busy, you'll see 149 passed and 1 skipped, which also counts. These tests use fake stand-ins for Gemini and Open Beauty Facts, so they don't use your free quota.

## Step 3. Try the real thing in your browser

Load your seed products into the database (only needed once), then start the API:

```powershell
python -m scripts.seed_cache
python -m uvicorn app.main:app --reload
```

Leave that window running and open **http://localhost:8000/docs**. To try a request:

1. Click **POST /v1/compare**, then **Try it out**.
2. Replace the example text with the JSON below, then click **Execute**.
3. Scroll down to see the answer.

This compares your Balea toner (by barcode) with a toner whose ingredients you paste:

```json
{
  "product_type": "toner",
  "concerns": ["dryness"],
  "profile": {"sensitive": true, "avoid_fragrance": false},
  "products": [
    {"display_name": "Balea toner", "barcode": "4070765077490"},
    {"display_name": "Pasted toner", "ingredients_text": "Aqua, Glycerin, Sodium Hyaluronate, Parfum"}
  ]
}
```

Check that:
- **ranking** lists both toners.
- Each flag has a **reason** and a **source** link.
- **summary_source** is `llm`. If it's `template`, Gemini was busy or its summary was rejected, which is also fine.
- The **disclaimer** is there.

Also try:
- **POST /v1/products/extract**: **Try it out**, choose a photo of an ingredient label, **Execute**. Compare the text with the label.
- **GET /v1/products/lookup**: put `4070765077490` in **barcode**, **Execute**. Run it again, and `cached` should now be `true`.
- **A broken request:** in compare, change `"dryness"` to `"wrinkles"`. You should get a 422 with a plain message.

Press `Ctrl + C` in the terminal to stop the API.

## Explain it back

> "I connected the brain to the outside world. The app can now look up products, read label photos,
> and write a summary. Gemini only reads photos and words the summary, and code checks everything it
> writes. If the product database or the AI is down, the app still gives an honest answer instead of
> crashing, and errors are always polite and simple."
