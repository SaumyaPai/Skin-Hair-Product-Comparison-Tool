"""The local SQLite file (data/app.db). It only stores public product data and a
request log. No user, profile, or photo is ever saved here."""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS products_cache (
    barcode          TEXT PRIMARY KEY,
    product_name     TEXT NOT NULL DEFAULT '',
    brand            TEXT NOT NULL DEFAULT '',
    category_tags    TEXT NOT NULL DEFAULT '',
    ingredients_text TEXT NOT NULL DEFAULT '',
    source           TEXT NOT NULL,
    fetched_at       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS request_log (
    request_id     TEXT PRIMARY KEY,
    timestamp      TEXT NOT NULL,
    endpoint       TEXT NOT NULL,
    status_code    INTEGER NOT NULL,
    error_code     TEXT NOT NULL DEFAULT '',
    product_type   TEXT NOT NULL DEFAULT '',
    n_products     INTEGER NOT NULL DEFAULT 0,
    n_unresolved   INTEGER NOT NULL DEFAULT 0,
    summary_source TEXT NOT NULL DEFAULT '',
    latency_ms     INTEGER NOT NULL DEFAULT 0
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    """Open the database file (creating it and its tables if needed)."""
    path = Path(path or config.DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def save_product(conn, barcode, product_name, brand, ingredients_text, source,
                 category_tags="", fetched_at=None) -> None:
    conn.execute(
        """INSERT INTO products_cache (barcode, product_name, brand, category_tags,
                                       ingredients_text, source, fetched_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(barcode) DO UPDATE SET
               product_name=excluded.product_name, brand=excluded.brand,
               category_tags=excluded.category_tags, ingredients_text=excluded.ingredients_text,
               source=excluded.source, fetched_at=excluded.fetched_at""",
        (barcode, product_name, brand, category_tags, ingredients_text, source, fetched_at or now_iso()),
    )
    conn.commit()


def get_product(conn, barcode):
    row = conn.execute("SELECT * FROM products_cache WHERE barcode = ?", (barcode,)).fetchone()
    return dict(row) if row else None


def count_products(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM products_cache").fetchone()[0]
