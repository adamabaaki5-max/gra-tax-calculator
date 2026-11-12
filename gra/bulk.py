"""Bulk (multi-file) tax calculation: read .xlsx / .csv uploads, calculate and build downloads."""
import csv
import io
import math
import re
from datetime import date, datetime

from openpyxl import Workbook, load_workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Font

from .calc import calc_income, calc_tax
from .rates import r2

BULK_MAX_FILES = 20
BULK_MAX_ROWS = 50000
BULK_MAX_BYTES = 4 * 1024 * 1024       # Vercel rejects request bodies above ~4.5 MB
BULK_PREVIEW_ROWS = 200
BULK_HEADERS = ["Serial Number", "TIN", "Taxpayer Name", "Phone Number", "Chargeable Income", "Tax Amount"]


class BulkError(Exception):
    pass


# ---------- Reading uploads ----------

def _cell_text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() and abs(v) < 1e15 else repr(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return str(v)


def read_uploaded_sheet(data: bytes, name: str) -> list:
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext == "csv":
        return read_csv_rows(data)
    if ext == "xlsx":
        return read_xlsx_rows(data)
    raise BulkError('Unsupported file type ".%s". Please upload .xlsx or .csv files.' % ext)


def read_csv_rows(data: bytes) -> list:
    try:
        raw = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raw = data.decode("cp1252", errors="replace")
    first = raw.split("\n", 1)[0]
    delim = max([",", ";", "\t"], key=lambda d: first.count(d))
    return [[str(c) for c in row] for row in csv.reader(io.StringIO(raw, newline=""), delimiter=delim) if row]


def read_xlsx_rows(data: bytes) -> list:
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        ws = wb.worksheets[0]
        rows = []
        for r in ws.iter_rows(values_only=True):
            line = [_cell_text(v) for v in r]
            while line and line[-1] == "":
                line.pop()
            rows.append(line)
            if len(rows) > BULK_MAX_ROWS + 25:
                break
        wb.close()
        return rows
    except Exception as ex:
        raise BulkError("The first worksheet could not be read. Make sure it is a valid .xlsx file.") from ex


# ---------- Modes ----------

def bulk_modes() -> dict:
    return {
        "tax": {"title": "Tax amount", "sub": "from chargeable income", "button": "Calculate tax for all rows",
                "req": "income", "in": {"income": "Chargeable Income"}, "out": ["Tax Amount"], "invalid": "Invalid income"},
        "income": {"title": "Chargeable income", "sub": "from tax amount", "button": "Calculate chargeable income for all rows",
                   "req": "tax", "in": {"tax": "Tax Amount"}, "out": ["Chargeable Income"], "invalid": "Invalid tax amount"},
        "quarterly": {"title": "Quarterly amounts", "sub": "from tax amount", "button": "Calculate quarterly amounts for all rows",
                      "req": "tax", "in": {"tax": "Tax Amount"}, "out": ["Each Quarter", "2 Quarters", "3 Quarters", "4 Quarters"],
                      "invalid": "Invalid tax amount", "annual_only": True},
        "remaining": {"title": "Remaining tax", "sub": "from tax amount, credit and receipt", "button": "Calculate remaining tax for all rows",
                      "req": "tax", "in": {"tax": "Tax Amount", "receipt": "Paid Amount (Receipt)", "credit": "Paid Amount (Credit)"},
                      "out": ["Credit + Receipt", "Remaining Tax"], "invalid": "Invalid amount"},
    }


def bulk_modes_for(period: str) -> dict:
    return {k: m for k, m in bulk_modes().items() if not m.get("annual_only") or period == "annual"}


def bulk_mode(requested: str, period: str) -> str:
    return requested if requested in bulk_modes_for(period) else "tax"


# ---------- Interpreting a sheet ----------

def norm_header(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def match_header(cells) -> dict:
    syn = {
        "sn": ["no", "sn", "sno", "slno", "serialnumber", "serialno", "number", "num"],
        "tin": ["tin", "tinnumber", "tinno", "taxidentificationnumber"],
        "name": ["taxpayername", "taxpayer", "name", "nameoftaxpayer", "fullname", "taxpayersname"],
        "phone": ["phonenumber", "phone", "phoneno", "telephone", "tel", "contact", "contactnumber", "mobile", "mobilenumber"],
    }
    tax_names = ["tax", "taxamount", "taxpayable", "taxdue", "incometax", "amountoftax"]
    m: dict = {}
    for i, c in enumerate(cells):
        n = norm_header(c)
        if n == "":
            continue
        if "income" not in m and ("chargeable" in n or n == "income"):
            m["income"] = i
            continue
        if "tax" not in m and (n in tax_names or n.startswith("taxamount") or n.startswith("taxpayable")):
            m["tax"] = i
            continue
        if "receipt" not in m and "receipt" in n:
            m["receipt"] = i
            continue
        if "credit" not in m and "credit" in n:
            m["credit"] = i
            continue
        for key, names in syn.items():
            if key not in m and n in names:
                m[key] = i
                break
    return m


def parse_income(raw: str):
    s = re.sub(r"[^0-9.\-eE]", "", str(raw))
    if s == "":
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    return v if math.isfinite(v) and v >= 0 else None


def extract_records(sheet: list, mode: str) -> list:
    d = bulk_modes()[mode]
    need = d["req"]
    mp, start = None, 0
    for i, row in enumerate(sheet[:20]):
        m = match_header(row)
        if need in m:
            mp, start = m, i + 1
            break
    if mp is None:
        label = d["in"][need]
        raise BulkError('Could not find a "%s" column. The first row of the file needs a column headed %s.' % (label, label))

    def get(r, k):
        return str(r[mp[k]]).strip() if k in mp and mp[k] < len(r) else ""

    records = []
    for r in sheet[start:]:
        rec = {"sn": get(r, "sn"), "tin": get(r, "tin"), "name": get(r, "name"), "phone": get(r, "phone"),
               "vals": {k: get(r, k) for k in d["in"]}}
        if not (rec["sn"] or rec["tin"] or rec["name"] or rec["phone"] or any(rec["vals"].values())):
            continue
        if len(records) >= BULK_MAX_ROWS:
            raise BulkError("Too many rows (limit {:,} per file).".format(BULK_MAX_ROWS))
        if "sn" not in mp:
            rec["sn"] = str(len(records) + 1)
        records.append(rec)
    if not records:
        raise BulkError("No taxpayer rows were found below the column headings.")
    return records


def calc_record(rec: dict, bands, mode: str) -> dict:
    d = bulk_modes()[mode]
    raw, given, bad = {}, {}, False
    for k in d["in"]:
        text = str(rec["vals"].get(k, "")).strip()
        raw[k] = text
        if text == "" and k != d["req"]:
            given[k] = 0.0          # a blank payment counts as 0
            continue
        given[k] = parse_income(text)
        if given[k] is None:
            bad = True
    row = {"sn": rec["sn"], "tin": rec["tin"], "name": rec["name"], "phone": rec["phone"],
           "raw": raw, "given": given, "out": None, "remark": ""}
    if bad:
        return row
    if mode == "tax":
        row["out"] = [r2(calc_tax(bands, given["income"])[0])]
    elif mode == "income":
        inc, note = calc_income(bands, given["tax"])
        row["out"] = [r2(inc)]
        if note:
            row["remark"] = "Highest income with no tax"
    elif mode == "quarterly":
        q = given["tax"] / 4
        row["out"] = [r2(q), r2(q * 2), r2(q * 3), r2(q * 4)]
    elif mode == "remaining":
        paid = given["credit"] + given["receipt"]
        rem = given["tax"] - paid
        row["out"] = [r2(paid), r2(rem)]
        if rem < 0:
            row["remark"] = "Overpaid"
    return row


def calculate_records(records, bands, mode):
    rows = [calc_record(r, bands, mode) for r in records]
    return {"rows": rows, "invalid": sum(1 for r in rows if r["out"] is None)}


def run_bulk(files, bands, mode):
    """files: list of werkzeug FileStorage. Returns (ok, errors). Nothing is written to disk."""
    ok, errors = [], []
    if not files:
        return ok, [("Upload", "Please choose at least one file to upload.")]
    if len(files) > BULK_MAX_FILES:
        return ok, [("Upload", "Please upload no more than %d files at a time." % BULK_MAX_FILES)]
    for f in files:
        name = (f.filename or "file").replace("\\", "/").split("/")[-1]
        try:
            data = f.read(BULK_MAX_BYTES + 1)
            if len(data) > BULK_MAX_BYTES:
                raise BulkError("The file is too large (limit %d MB)." % (BULK_MAX_BYTES // 1048576))
            res = calculate_records(extract_records(read_uploaded_sheet(data, name), mode), bands, mode)
            ok.append({"name": name, "rows": res["rows"], "invalid": res["invalid"]})
        except BulkError as ex:
            errors.append((name, str(ex)))
        except Exception:
            errors.append((name, "The file could not be read. Make sure it is a valid .xlsx or .csv file."))
        finally:
            data = None            # the uploaded document is dropped from memory straight away
    return ok, errors


# ---------- Building downloads ----------

def export_table(files, with_source: bool, mode: str):
    d = bulk_modes()[mode]
    header = ["Serial Number", "TIN", "Taxpayer Name", "Phone Number"] + list(d["in"].values()) + list(d["out"])
    has_remark = any(r["remark"] for f in files for r in f["rows"])
    if has_remark:
        header.append("Remark")
    if with_source:
        header.append("Source File")
    rows = []
    for f in files:
        for r in f["rows"]:
            row = [r["sn"], r["tin"], r["name"], r["phone"]]
            for k in d["in"]:
                row.append(("" if r["raw"][k] == "" else r["given"][k]) if r["given"][k] is not None else r["raw"][k])
            for j in range(len(d["out"])):
                row.append(r["out"][j] if r["out"] is not None else (d["invalid"] if j == 0 else ""))
            if has_remark:
                row.append(r["remark"])
            if with_source:
                row.append(f["name"])
            rows.append(row)
    return header, rows


_ILLEGAL = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F]")


def build_xlsx(header, rows) -> bytes:
    wb = Workbook(write_only=True)
    ws = wb.create_sheet("Results")
    for i, w in enumerate([14, 20, 32, 18] + [22] * max(0, len(header) - 4)):
        ws.column_dimensions[chr(65 + i)].width = w if i < 26 else 20
    head = []
    for h in header:
        c = WriteOnlyCell(ws, value=h)
        c.font = Font(bold=True)
        head.append(c)
    ws.append(head)
    for r in rows:
        line = []
        for v in r:
            if isinstance(v, float):
                c = WriteOnlyCell(ws, value=v)
                c.number_format = "#,##0.00"
                line.append(c)
            else:
                line.append(_ILLEGAL.sub("", str(v)))
        ws.append(line)
    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()


def build_csv(header, rows) -> bytes:
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\r\n")
    w.writerow(header)
    for r in rows:
        w.writerow([format(v, ".2f") if isinstance(v, float) else v for v in r])
    return b"\xef\xbb\xbf" + out.getvalue().encode("utf-8")
