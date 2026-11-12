"""Retention of uploaded data, CSRF protection and the Rate Settings password."""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
import zlib

from flask import session
from werkzeug.security import check_password_hash, generate_password_hash

from .db import DbError, get_db

DEFAULT_PASSWORD = "GRA@Rates2026"


def retention_minutes() -> int:
    try:
        return max(1, int(os.environ.get("RETENTION_MINUTES", "30")))
    except ValueError:
        return 30


def settings_idle_seconds() -> int:
    try:
        return max(1, int(os.environ.get("SETTINGS_IDLE_MINUTES", "15"))) * 60
    except ValueError:
        return 900


# ---------- Temporary results (deleted automatically) ----------

def purge_expired() -> None:
    """Delete every stored result whose time limit has passed. Runs on every page request."""
    try:
        get_db().execute("DELETE FROM bulk_results WHERE expires_at <= %s", (int(time.time()),))
    except DbError:
        pass


def _valid_token(token: str) -> bool:
    return bool(re.fullmatch(r"[a-f0-9]{16}", token or ""))


def store_results(token: str, payload: dict) -> bool:
    """Keep results for the download buttons until the time limit. No uploaded file is ever stored."""
    if not _valid_token(token):
        return False
    blob = base64.b64encode(zlib.compress(json.dumps(payload["files"], separators=(",", ":")).encode(), 6)).decode()
    now = int(time.time())
    try:
        get_db().execute(
            "INSERT INTO bulk_results (token, tax_year, period, mode, data, created_at, expires_at) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (token, int(payload["year"]), payload["period"], payload["mode"], blob, now, now + retention_minutes() * 60))
    except DbError:
        return False
    session["bulk_token"] = token
    return True


def load_results(token: str):
    """Results of this browser session, or None if missing or expired."""
    if not _valid_token(token) or not hmac.compare_digest(str(session.get("bulk_token", "")), token):
        return None
    try:
        rows = get_db().query("SELECT tax_year, period, mode, data FROM bulk_results WHERE token = %s AND expires_at > %s",
                              (token, int(time.time())))
        if not rows:
            return None
        year, period, mode, blob = rows[0]
        return {"year": int(year), "period": period, "mode": mode,
                "files": json.loads(zlib.decompress(base64.b64decode(blob)))}
    except (DbError, ValueError, zlib.error):
        return None


def delete_results(token: str) -> None:
    if _valid_token(token):
        try:
            get_db().execute("DELETE FROM bulk_results WHERE token = %s", (token,))
        except DbError:
            pass
    session.pop("bulk_token", None)


# ---------- CSRF ----------

def csrf_token() -> str:
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


def csrf_ok(form) -> bool:
    return bool(session.get("csrf")) and hmac.compare_digest(session["csrf"], str(form.get("csrf", "")))


# ---------- Rate Settings password ----------

def _auth() -> dict:
    try:
        rows = get_db().query("SELECT password_hash, failed_attempts, locked_until FROM settings_auth WHERE id = 1")
    except DbError:
        return {}
    if not rows:
        return {}
    h, fails, locked = rows[0]
    return {"hash": h or "", "fails": int(fails or 0), "locked_until": int(locked or 0)}


def default_password() -> str:
    return os.environ.get("SETTINGS_DEFAULT_PASSWORD") or DEFAULT_PASSWORD


def using_default_password() -> bool:
    return not _auth().get("hash")


def check_password(pw: str) -> bool:
    h = _auth().get("hash")
    if h:
        return check_password_hash(h, pw)
    return hmac.compare_digest(default_password().encode(), pw.encode())


def set_password(pw: str) -> bool:
    try:
        get_db().execute("UPDATE settings_auth SET password_hash = %s, updated_at = %s WHERE id = 1",
                         (generate_password_hash(pw), int(time.time())))
        return True
    except DbError:
        return False


def locked_seconds() -> int:
    return max(0, int(_auth().get("locked_until", 0)) - int(time.time()))


def record_failure() -> None:
    try:
        db = get_db()
        fails = int(_auth().get("fails", 0)) + 1
        if fails >= 5:
            db.execute("UPDATE settings_auth SET failed_attempts = 0, locked_until = %s WHERE id = 1", (int(time.time()) + 300,))
        else:
            db.execute("UPDATE settings_auth SET failed_attempts = %s WHERE id = 1", (fails,))
    except DbError:
        pass


def clear_failures() -> None:
    try:
        get_db().execute("UPDATE settings_auth SET failed_attempts = 0, locked_until = 0 WHERE id = 1")
    except DbError:
        pass


def settings_unlocked() -> bool:
    if not session.get("settings_ok") or time.time() - float(session.get("settings_seen", 0)) > settings_idle_seconds():
        session.pop("settings_ok", None)
        session.pop("settings_seen", None)
        return False
    session["settings_seen"] = time.time()
    return True
