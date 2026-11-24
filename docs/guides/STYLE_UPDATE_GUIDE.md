# New look: blush and rose colours (Windows)

The page now uses a soft blush background, dusty-rose rounded cards, an arch-shaped header, serif headings, black pill-shaped buttons and warm orange accents. Only the colours and feel are taken from your reference, not its pictures or brand.

The flags are still easy to read:
- **✓ May suit** is on a soft green card.
- **! May not suit** is on a soft peach card.
- Each one has a text label and a symbol, so they don't rely on colour alone.
- Every text colour was checked for readable contrast, and a test now checks this too.

## Apply it

Save `skincare-compare-update-style.zip` into `D:\Claude_comparison_project1\`, then:

```powershell
cd D:\Claude_comparison_project1
Expand-Archive .\skincare-compare-update-style.zip -DestinationPath . -Force
cd .\skincare-compare
.\.venv\Scripts\Activate.ps1
python -m pytest -v
python -m scripts.run_app
```

There's nothing new to install. The tests should show **222 passed**. A skip with a clear reason, like "Gemini is busy", also counts.

If the page still looks the old way, press `Ctrl + F5` in the browser to reload it fully.

## Changing the colours later

- The main colours are in `.streamlit/config.toml` (`backgroundColor`, `primaryColor` and so on).
- The cards, header, ranking and flags are styled in `ui/style.css`.
- Each colour has a comment saying where it's used.
