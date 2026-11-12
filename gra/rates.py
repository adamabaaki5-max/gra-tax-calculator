"""
Tax rate tables.
A table is stored as rows of [chargeable income in the band, rate %]; the last row has a None
width and is the "Exceeding" band. Cumulative columns are always worked out from these rows.
"""
import json
from decimal import ROUND_HALF_UP, Decimal

from flask import g

from . import store

RATES_KEY = "gra:rates"


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


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def clean_rows(rows):
    if not isinstance(rows, list) or len(rows) < 2:
        return None
    out, n = [], len(rows)
    for i, row in enumerate(rows):
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            return None
        w, r = row[0], row[1]
        if not _num(r) or r < 0 or r > 100:
            return None
        if i == n - 1:
            out.append([None, float(r)])
            continue
        if not _num(w) or w <= 0:
            return None
        out.append([round(float(w), 2), float(r)])
    return out


def load_rates(fresh: bool = False) -> dict:
    """All tax years: {year: {'annual': rows, 'monthly': rows}} (a period is missing if there is no such table)."""
    if not fresh and "rates" in g:
        return g.rates
    rates: dict = {}
    raw = store.get(RATES_KEY)
    if raw:
        try:
            data = json.loads(raw)
        except ValueError:
            data = {}
        for year, tables in (data.get("years") or {}).items():
            if not str(year).isdigit() or not isinstance(tables, dict):
                continue
            for p in ("annual", "monthly"):
                rows = clean_rows(tables.get(p))
                if rows is not None:
                    rates.setdefault(int(year), {})[p] = rows
    if not rates:
        rates = default_rates()
    g.rates = dict(sorted(rates.items()))
    g.pop("tables", None)
    return g.rates


def save_rates(rates: dict) -> bool:
    years = {str(y): t for y, t in sorted(rates.items())}
    try:
        store.put(RATES_KEY, json.dumps({"years": years}))
    except store.StoreError:
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
