"""GRA Annual and Monthly Tax Calculator - Flask app (deployable on Vercel)."""
import hashlib
import os
import secrets

from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for, Response
from werkzeug.exceptions import RequestEntityTooLarge

from gra import bulk, security, store
from gra.calc import CURRENCY, band_rows, calc_income, calc_tax, fmt_rate, money, n2, parse_amount
from gra.rates import load_rates, save_rates, tax_tables

app = Flask(__name__)

_secret = os.environ.get("SECRET_KEY")
if not _secret:
    # Set SECRET_KEY in the Vercel project settings. This fallback keeps sessions working if you forget.
    _seed = os.environ.get("KV_REST_API_TOKEN") or os.environ.get("UPSTASH_REDIS_REST_TOKEN") or "gra-local-development"
    _secret = hashlib.sha256(("gra-secret:" + _seed).encode()).hexdigest()
app.config.update(
    SECRET_KEY=_secret,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=bool(os.environ.get("VERCEL")),
    MAX_CONTENT_LENGTH=int(4.4 * 1024 * 1024),      # Vercel functions accept at most ~4.5 MB per request
)


@app.context_processor
def inject():
    return {"CURRENCY": CURRENCY, "csrf_token": security.csrf_token, "n2": n2,
            "retention": security.retention_minutes(), "max_mb": bulk.BULK_MAX_BYTES // 1048576}


@app.after_request
def headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    if request.endpoint != "static":
        resp.headers["Cache-Control"] = "no-store"
    return resp


# ---------- helpers ----------

def require_year(year):
    if year not in tax_tables():
        abort(redirect(url_for("index")))
    return year


def require_period(year, period):
    if period not in ("annual", "monthly") or period not in tax_tables()[year]:
        abort(redirect(url_for("year_page", year=year)))
    return period


def settings_required(fn):
    from functools import wraps

    @wraps(fn)
    def wrapper(*a, **kw):
        if not security.settings_unlocked():
            return redirect(url_for("settings_login"))
        return fn(*a, **kw)
    return wrapper


def alert(text):
    return {"type": "alert", "text": text}


# ---------- public pages ----------

@app.route("/")
def index():
    return render_template("index.html", years=tax_tables(), page_title="Select Tax Year")


@app.route("/year/<int:year>")
def year_page(year):
    require_year(year)
    return render_template("year.html", year=year, tables=tax_tables()[year], page_title="%d Tax Calculations" % year)


@app.route("/calculator/<int:year>/<period>", methods=["GET", "POST"])
def calculator(year, period):
    require_year(year)
    require_period(year, period)
    bands = tax_tables()[year][period]
    p_label = period.capitalize()

    tabs = {"tax": "Calculate Tax", "quarterly": "Quarterly Tax", "remaining": "Remaining Tax",
            "reverse": "Find Chargeable Income", "bulk": "Bulk Calculation"}
    if period == "monthly":
        tabs.pop("quarterly")           # quarterly payments apply to annual tax only

    action, msg, form, files = "", None, {}, []
    if request.method == "POST":
        try:
            form = request.form
            files = request.files.getlist("files")
            action = form.get("action", "")
        except RequestEntityTooLarge:
            action, msg = "bulk", alert("The upload was too large (limit about 4 MB per upload on this server). Try fewer or smaller files.")
    if action not in tabs:
        action = ""
    active = action or "tax"
    mode = bulk.bulk_mode(form.get("mode", "tax") if form else "tax", period)

    if msg is None and action:
        if action == "tax":
            income = parse_amount(form.get("income"))
            msg = alert("Please enter a valid chargeable income.") if income is None else \
                {"type": "result", "label": "%s tax payable" % p_label, "value": money(calc_tax(bands, income)[0])}
        elif action == "quarterly":
            tax = parse_amount(form.get("tax"))
            if tax is None:
                msg = alert("Please enter a valid tax amount.")
            else:
                q = tax / 4
                msg = {"type": "result", "label": "Each quarterly tax amount", "value": money(q),
                       "quarters": [("%d quarter%s" % (n, "s" if n > 1 else ""), money(q * n)) for n in range(1, 5)]}
        elif action == "remaining":
            tax, receipt, credit = (parse_amount(form.get(k)) for k in ("tax", "receipt", "credit"))
            if None in (tax, receipt, credit):
                msg = alert("Please enter valid amounts in all three fields.")
            else:
                paid = credit + receipt
                debt = tax - paid
                msg = {"type": "result", "label": "Remaining tax (debt)" if debt >= 0 else "Overpaid amount",
                       "value": money(abs(debt)), "meta": [("Tax amount", money(tax)), ("Credit + receipt", money(paid))]}
        elif action == "reverse":
            tax = parse_amount(form.get("tax"))
            if tax is None:
                msg = alert("Please enter a valid tax amount.")
            else:
                inc, note = calc_income(bands, tax)
                msg = {"type": "result", "label": "Chargeable income (%s)" % period, "value": money(inc),
                       "meta": [("Tax amount", money(tax))], "note": note}
        elif action == "bulk":
            msg = run_bulk(files, bands, year, period, mode)

    return render_template(
        "calculator.html", year=year, period=period, p_label=p_label, tabs=tabs, active=active, msg=msg,
        mode=mode, modes=bulk.bulk_modes_for(period), all_modes=bulk.bulk_modes(),
        band_rows=band_rows(bands), form=form, page_title="%d %s Tax" % (year, p_label), preview=bulk.BULK_PREVIEW_ROWS)


def run_bulk(files, bands, year, period, mode):
    ok, errors = bulk.run_bulk(files, bands, mode)
    token = secrets.token_hex(8)
    if ok and not security.store_results(token, {"year": year, "period": period, "mode": mode, "files": ok}):
        errors.append(("Results", "The results could not be prepared for download. If this happens again, the database "
                                  "connection may be missing (see the README), or the file has too many rows."))
    d = bulk.bulk_modes()[mode]
    summaries = []
    for f in ok:
        total, remarks = 0.0, set()
        for r in f["rows"]:
            if r["out"] is None:
                continue
            if mode == "tax":
                total += r["out"][0]
            if mode == "remaining":
                total += max(0.0, r["out"][1])
            if r["remark"]:
                remarks.add(r["remark"])
        info = "{:,} taxpayers calculated".format(len(f["rows"]) - f["invalid"])
        if mode == "tax":
            info += " · Total tax " + money(total)
        if mode == "remaining":
            info += " · Total remaining tax " + money(total)
        if f["invalid"]:
            info += " · %d row(s) with %s" % (f["invalid"], d["invalid"].lower())
        summaries.append({"info": info, "remarks": sorted(remarks), "count": len(f["rows"])})
    return {"type": "bulk", "errors": errors, "files": ok, "token": token, "mode": mode, "summaries": summaries,
            "total_rows": sum(x["count"] for x in summaries)}


# ---------- downloads ----------

@app.route("/download")
def download():
    fmt = "csv" if request.args.get("fmt") == "csv" else "xlsx"

    def send(header, rows, name):
        if fmt == "csv":
            return Response(bulk.build_csv(header, rows), mimetype="text/csv; charset=utf-8",
                            headers={"Content-Disposition": 'attachment; filename="%s.csv"' % name})
        return Response(bulk.build_xlsx(header, rows),
                        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": 'attachment; filename="%s.xlsx"' % name})

    if "template" in request.args:
        return send(bulk.BULK_HEADERS[:5], [], "tax-upload-template")

    token = request.args.get("t", "")
    if "clear" in request.args:
        if token and token == session.get("bulk_token"):
            security.delete_results(token)
        return "The uploaded data and results have been deleted. Go back to the calculator to start again.", 200

    b = security.load_results(token)
    if not b:
        return ("These results are no longer available (they are deleted automatically after %d minutes for security). "
                "Please upload the file(s) again to recalculate." % security.retention_minutes()), 410
    mode = b.get("mode") if b.get("mode") in bulk.bulk_modes() else "tax"
    names = {"tax": "tax", "income": "chargeable-income", "quarterly": "quarterly-tax", "remaining": "remaining-tax"}
    prefix = "%s-%s-%s" % (b["year"], b["period"], names[mode])
    f = request.args.get("f", "all")
    if f == "all":
        header, rows = bulk.export_table(b["files"], True, mode)
        return send(header, rows, prefix + "-all-files")
    if f.isdigit() and int(f) < len(b["files"]):
        file = b["files"][int(f)]
        header, rows = bulk.export_table([file], False, mode)
        import re
        stem = re.sub(r"[^A-Za-z0-9._-]+", "-", file["name"].rsplit(".", 1)[0]).strip("-") or "file"
        return send(header, rows, prefix + "-" + stem)
    abort(404)


# ---------- Rate Settings (password protected) ----------

@app.route("/settings/login", methods=["GET", "POST"])
def settings_login():
    if security.settings_unlocked():
        return redirect(url_for("settings"))
    error = ""
    if request.method == "POST":
        if not security.csrf_ok(request.form):
            error = "The page expired. Please try again."
        elif (wait := security.locked_seconds()) > 0:
            error = "Too many wrong attempts. Please wait %d minute(s) and try again." % -(-wait // 60)
        elif security.check_password(request.form.get("password", "")):
            security.clear_failures()
            session.clear()
            session["settings_ok"] = True
            session["settings_seen"] = __import__("time").time()
            return redirect(url_for("settings"))
        else:
            security.record_failure()
            __import__("time").sleep(0.6)
            error = "Wrong password."
    return render_template("settings_login.html", error=error, page_title="Rate Settings login")


@app.route("/settings", methods=["GET", "POST"])
@settings_required
def settings():
    error, ok_msg = "", ""
    action = request.form.get("action", "") if request.method == "POST" else ""
    if action and not security.csrf_ok(request.form):
        error, action = "The page expired. Please try again.", ""
    if action == "logout":
        session.pop("settings_ok", None)
        session.pop("settings_seen", None)
        return redirect(url_for("index"))
    if action == "password":
        cur, new, new2 = (request.form.get(k, "") for k in ("current", "new", "new2"))
        if not security.check_password(cur):
            error = "The current password is wrong."
        elif len(new) < 8:
            error = "The new password must be at least 8 characters."
        elif new != new2:
            error = "The two new passwords do not match."
        elif not security.set_password(new):
            error = "The password could not be saved. Check the database connection (see the README)."
        else:
            ok_msg = "The password was changed."
    if action == "delete":
        year = request.form.get("year", type=int) or 0
        rates = load_rates()
        if year not in rates:
            error = "That tax year was not found."
        elif len(rates) <= 1:
            error = "You cannot delete the only tax year. Add another one first."
        else:
            del rates[year]
            if save_rates(rates):
                return redirect(url_for("settings", deleted=year))
            error = "The change could not be saved. Check the database connection (see the README)."
    return render_template("settings.html", rates=load_rates(), error=error, ok_msg=ok_msg,
                           saved=request.args.get("saved", type=int), deleted=request.args.get("deleted", type=int),
                           default_pw=security.using_default_password(), persistent=store.using_redis(),
                           page_title="Rate Settings")


def skeleton_rows():
    return [["", ""] for _ in range(6)] + [[None, ""]]


def num_str(v):
    return "" if v is None else ("%.4f" % float(v)).rstrip("0").rstrip(".")


def rows_to_form(rows):
    if not rows:
        return skeleton_rows()
    return [[None if r[0] is None else num_str(r[0]), "" if r[1] is None else num_str(r[1])] for r in rows]


def read_table_form(key, title):
    """Returns (form rows, clean rows or None, errors). None rows + no errors = table left empty."""
    w = request.form.getlist(key + "_w")
    r = request.form.getlist(key + "_r")
    n = len(r)
    if n == 0:
        return skeleton_rows(), None, []
    form = [[w[i].strip() if i < n - 1 and i < len(w) else ("" if i < n - 1 else None), r[i].strip()] for i in range(n)]
    last = form.pop()
    body = [x for x in form if x[0] != "" or x[1] != ""]       # ignore blank rows
    if not body and last[1] == "":
        return form + [last], None, []
    errors, rows = [], []
    for i, (wv, rv) in enumerate(body, 1):
        wn, rn = wv.replace(",", ""), rv.replace("%", "").replace(",", "")
        try:
            wf = float(wn)
            if wf <= 0:
                raise ValueError
        except ValueError:
            errors.append("%s, band %d: enter the chargeable income as a number above 0." % (title, i))
            wf = 0.0
        try:
            rf = float(rn)
            if not 0 <= rf <= 100:
                raise ValueError
        except ValueError:
            errors.append("%s, band %d: enter the rate as a number from 0 to 100." % (title, i))
            rf = 0.0
        rows.append([round(wf, 2), rf])
    ln = last[1].replace("%", "").replace(",", "")
    try:
        lf = float(ln)
        if not 0 <= lf <= 100:
            raise ValueError
    except ValueError:
        errors.append("%s, Exceeding band: enter the rate as a number from 0 to 100." % title)
        lf = 0.0
    if not body:
        errors.append("%s needs at least one band before the Exceeding band." % title)
    rows.append([None, lf])
    return form + [last], (None if errors else rows), errors


@app.route("/settings/edit", methods=["GET", "POST"])
@settings_required
def settings_edit():
    titles = {"annual": "Annual tax bands", "monthly": "Monthly tax bands"}
    rates = load_rates()
    errors, forms = [], {"annual": skeleton_rows(), "monthly": skeleton_rows()}
    year_val = orig_year = ""

    if request.method == "POST" and request.form.get("action") == "save":
        orig_year = request.form.get("orig_year", "").strip()
        year_val = orig_year or request.form.get("year", "").strip()
        tables = {}
        for key, title in titles.items():
            forms[key], clean, errs = read_table_form(key, title)
            errors += errs
            if clean:
                tables[key] = clean
        if not security.csrf_ok(request.form):
            errors.append("The page expired. Please try again.")
        elif not (year_val.isdigit() and 2000 <= int(year_val) <= 2100):
            errors.append("Enter a valid tax year, for example 2028.")
        elif orig_year == "" and int(year_val) in rates:
            errors.append("The year %s already exists. Edit it from the Rate Settings page instead." % year_val)
        if not errors and not tables:
            errors.append("Fill in at least one table (annual or monthly).")
        if not errors:
            allr = dict(rates)
            allr[int(year_val)] = tables
            if save_rates(allr):
                return redirect(url_for("settings", saved=int(year_val)))
            errors.append("The bands could not be saved. Check the database connection (see the README).")
    else:
        y = request.args.get("year", type=int)
        if y is not None and y in rates:
            year_val = orig_year = str(y)
            for key in titles:
                forms[key] = rows_to_form(rates[y].get(key))
        elif "new" not in request.args:
            return redirect(url_for("settings"))

    editing = orig_year != ""
    return render_template("settings_edit.html", titles=titles, forms=forms, errors=errors, year_val=year_val,
                           orig_year=orig_year, editing=editing,
                           page_title="Edit %s tax bands" % orig_year if editing else "Add a tax year")


@app.errorhandler(RequestEntityTooLarge)
def too_large(_e):
    return "The upload was too large (limit about 4 MB per upload).", 413


if __name__ == "__main__":
    app.run(debug=True)
