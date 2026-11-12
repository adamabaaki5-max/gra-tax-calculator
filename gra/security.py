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

from . import store

AUTH_KEY = "gra:auth"
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

def _result_key(token: str):
    return "gra:bulk:" + token if re.fullmatch(r"[a-f0-9]{16}", token or "") else None


def store_results(token: str, payload: dict) -> bool:
    """Keep results for the download buttons. The database deletes them by itself after the time limit."""
    key = _result_key(token)
    if key is None:
        return False
    blob = base64.b64encode(zlib.compress(json.dumps(payload, separators=(",", ":")).encode(), 6)).decode()
    try:
        store.put(key, blob, ex=retention_minutes() * 60)
    except store.StoreError:
        return False
    session["bulk_token"] = token
    return True


def load_results(token: str):
    """Results of this browser session, or None if missing or expired."""
    key = _result_key(token)
    if key is None or not hmac.compare_digest(str(session.get("bulk_token", "")), token):
        return None
    try:
        blob = store.get(key)
        return json.loads(zlib.decompress(base64.b64decode(blob))) if blob else None
    except (store.StoreError, ValueError, zlib.error):
        return None


def delete_results(token: str) -> None:
    key = _result_key(token)
    if key:
        try:
            store.delete(key)
        except store.StoreError:
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
        d = json.loads(store.get(AUTH_KEY) or "{}")
        return d if isinstance(d, dict) else {}
    except (store.StoreError, ValueError):
        return {}


def _save_auth(d: dict) -> bool:
    try:
        store.put(AUTH_KEY, json.dumps(d))
        return True
    except store.StoreError:
        return False


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
    d = _auth()
    d["hash"] = generate_password_hash(pw)
    return _save_auth(d)


def locked_seconds() -> int:
    return max(0, int(_auth().get("locked_until", 0)) - int(time.time()))


def record_failure() -> None:
    d = _auth()
    d["fails"] = int(d.get("fails", 0)) + 1
    if d["fails"] >= 5:
        d["locked_until"] = int(time.time()) + 300
        d["fails"] = 0
    _save_auth(d)


def clear_failures() -> None:
    d = _auth()
    if "fails" in d or "locked_until" in d:
        d.pop("fails", None)
        d.pop("locked_until", None)
        _save_auth(d)


def settings_unlocked() -> bool:
    if not session.get("settings_ok") or time.time() - float(session.get("settings_seen", 0)) > settings_idle_seconds():
        session.pop("settings_ok", None)
        session.pop("settings_seen", None)
        return False
    session["settings_seen"] = time.time()
    return True
