"""
Tax rate tables, stored in the tax_years and tax_bands tables.
A table is a list of rows [chargeable income in the band, rate %]; the last row has a None width
and is the "Exceeding" band. Cumulative columns are always worked out from these rows.
"""
import time
from decimal import ROUND_HALF_UP, Decimal

from flask import g

from .db import DbError, get_db


def r2(x: float) -> float:
    """Round to 2 decimals, halves away from zero (same as the original program)."""
    return float(Decimal(repr(float(x))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def default_rates() -> dict:
    return {
        2026: {
            "annual": [[5880, 0], [1320, 5], [1560, 10], [38000, 17.5], [192000, 25], [366240, 30], [None, 35]],
            "monthly": [[490, 0], [110, 5], [130, 10], [3166.67, 17.5], [16000, 25], [30520, 30], [None, 35]],
        },
        2027: {
            "annual": [[7056, 0], [960, 5], [1200, 10], [34800, 17.5], [192000, 25], [363984, 30], [None, 35]],
            "monthly": [[588, 0], [80, 5], [100, 10], [2900, 17.5], [16000, 25], [30334, 30], [None, 35]],
        },
    }


def _write_year(db, year: int, tables: dict) -> None:
    now = int(time.time())
    db.execute("INSERT INTO tax_years (year, updated_at) VALUES (%s, %s) "
               "ON CONFLICT (year) DO UPDATE SET updated_at = EXCLUDED.updated_at", (year, now))
    db.execute("DELETE FROM tax_bands WHERE year = %s", (year,))
    for period, rows in tables.items():
        for pos, (w, r) in enumerate(rows):
            db.execute("INSERT INTO tax_bands (year, period, position, width, rate) VALUES (%s, %s, %s, %s, %s)",
                       (year, period, pos, None if w is None else float(w), float(r)))


def load_rates(fresh: bool = False) -> dict:
    """All tax years: {year: {'annual': rows, 'monthly': rows}} (a period is missing if the year has no such table)."""
    if not fresh and "rates" in g:
        return g.rates
    db = get_db()
    if not db.query("SELECT 1 FROM tax_years LIMIT 1"):          # first run: put in the built-in tables
        with db.transaction():
            for y, t in default_rates().items():
                _write_year(db, y, t)
    rates: dict = {}
    for year, period, width, rate in db.query(
            "SELECT year, period, width, rate FROM tax_bands ORDER BY year, period, position"):
        rates.setdefault(int(year), {}).setdefault(period, []).append([None if width is None else float(width), float(rate)])
    g.rates = dict(sorted(rates.items()))
    g.pop("tables", None)
    return g.rates


def save_rates(rates: dict) -> bool:
    """Make the database match `rates`. Years that are not in `rates` are deleted (their temporary results go too)."""
    try:
        db = get_db()
        with db.transaction():
            keep = [int(y) for y in rates]
            for (y,) in db.query("SELECT year FROM tax_years"):
                if int(y) not in keep:
                    db.execute("DELETE FROM tax_years WHERE year = %s", (int(y),))
            for y, tables in rates.items():
                _write_year(db, int(y), tables)
    except DbError:
        return False
    load_rates(fresh=True)
    return True


def rows_to_bands(rows):
    """Rows -> [(cumulative income at band start, rate as fraction, cumulative tax at band start)]."""
    bands, cum, tax = [], 0.0, 0.0
    for w, rate in rows:
        bands.append((cum, rate / 100, tax))
        if w is None:
            break
        tax = r2(tax + r2(w * rate / 100))
        cum = r2(cum + w)
    return bands


def tax_tables() -> dict:
    """{year: {'annual': bands, 'monthly': bands}}"""
    if "tables" not in g:
        g.tables = {y: {p: rows_to_bands(rows) for p, rows in t.items()} for y, t in load_rates().items()}
    return g.tables
