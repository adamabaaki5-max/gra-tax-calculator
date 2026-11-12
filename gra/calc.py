"""Tax calculations and display helpers."""
import math

CURRENCY = "GH₵"


def calc_tax(bands, income: float):
    """Income -> (tax, marginal rate)"""
    lower, rate, cum_tax = bands[0]
    for band in bands:
        if income >= band[0]:
            lower, rate, cum_tax = band
    return (income - lower) * rate + cum_tax, rate


def calc_income(bands, tax: float):
    """Tax -> (chargeable income, note)  (reverse calculation)"""
    if tax == 0.0:
        return bands[1][0], ("Any chargeable income from 0 up to this amount results in zero tax, "
                             "so this is the highest income that pays no tax.")
    lower, rate, cum_tax = bands[1]
    for band in bands[1:]:
        if tax > band[2]:
            lower, rate, cum_tax = band
    return lower + (tax - cum_tax) / rate, ""


def money(v: float) -> str:
    return "%s %s" % (CURRENCY, format(v, ",.2f"))


def n2(v) -> str:
    return format(float(v), ",.2f")


def fmt_rate(r: float) -> str:
    return ("%.2f" % (r * 100)).rstrip("0").rstrip(".") + "%"


def parse_amount(raw):
    """Form field -> amount (None if blank/invalid/negative)."""
    s = str(raw or "").replace(",", "").replace(" ", "").strip()
    if not s:
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    return v if math.isfinite(v) and v >= 0 else None


def band_rows(bands):
    """Rows for the on-screen band table, mirroring the GRA tables."""
    rows, n = [], len(bands)
    for i in range(n):
        frm, rate = bands[i][0], bands[i][1]
        if i < n - 1:
            to = bands[i + 1][0]
            w = to - frm
            rows.append(["First" if i == 0 else "Next", n2(w), fmt_rate(rate), n2(w * rate), n2(to), n2(bands[i + 1][2])])
        else:
            rows.append(["Exceeding", "Above " + n2(frm), fmt_rate(rate), "—", "—", "—"])
    return rows
