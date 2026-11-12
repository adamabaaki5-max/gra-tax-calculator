"""
Small key-value store used for the saved tax bands, the Rate Settings password and the
temporary bulk-calculation results.

Vercel's file system is read-only and not shared between requests, so the real store on Vercel is
a Redis database (Upstash Redis from the Vercel Marketplace, or Vercel KV). It is used automatically
when these variables exist (Vercel adds them when you connect the database to the project):
    KV_REST_API_URL + KV_REST_API_TOKEN      or      UPSTASH_REDIS_REST_URL + UPSTASH_REDIS_REST_TOKEN

Without them (for example on your own computer) a folder of small files is used instead.
Redis deletes expired keys by itself, which is what removes the uploaded data after the time limit.
"""
import hashlib
import json
import os
import tempfile
import time
import urllib.request


class StoreError(Exception):
    pass


def _redis_cfg():
    url = os.environ.get("KV_REST_API_URL") or os.environ.get("UPSTASH_REDIS_REST_URL")
    tok = os.environ.get("KV_REST_API_TOKEN") or os.environ.get("UPSTASH_REDIS_REST_TOKEN")
    return (url.rstrip("/"), tok) if url and tok else None


def using_redis() -> bool:
    return _redis_cfg() is not None


def _redis(*args):
    url, tok = _redis_cfg()
    req = urllib.request.Request(
        url, data=json.dumps([str(a) for a in args]).encode(), method="POST",
        headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            d = json.loads(r.read())
    except Exception as ex:  # network / auth problems
        raise StoreError("Could not reach the database: %s" % ex) from ex
    if isinstance(d, dict) and d.get("error"):
        raise StoreError(str(d["error"]))
    return d.get("result") if isinstance(d, dict) else None


# ---- file fallback (local use only) ----

def _dir() -> str:
    d = os.environ.get("GRA_DATA_DIR") or os.path.join(tempfile.gettempdir(), "gra-data")
    os.makedirs(d, exist_ok=True)
    return d


def _path(key: str) -> str:
    return os.path.join(_dir(), hashlib.sha256(key.encode()).hexdigest() + ".json")


def _file_purge() -> None:
    now = time.time()
    for n in os.listdir(_dir()):
        p = os.path.join(_dir(), n)
        try:
            with open(p, encoding="utf-8") as f:
                exp = json.load(f).get("exp")
            if exp and exp < now:
                os.remove(p)
        except (OSError, ValueError):
            pass


# ---- public API ----

def get(key: str):
    if using_redis():
        return _redis("GET", key)
    p = _path(key)
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    if d.get("exp") and d["exp"] < time.time():
        try:
            os.remove(p)
        except OSError:
            pass
        return None
    return d.get("v")


def put(key: str, value: str, ex=None) -> None:
    """Save a value; `ex` = seconds until it is deleted automatically."""
    if using_redis():
        if ex:
            _redis("SET", key, value, "EX", int(ex))
        else:
            _redis("SET", key, value)
        return
    _file_purge()
    p = _path(key)
    tmp = p + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"v": value, "exp": time.time() + ex if ex else None}, f)
        os.replace(tmp, p)
    except OSError as err:
        raise StoreError("Could not write to the data folder: %s" % err) from err


def delete(key: str) -> None:
    if using_redis():
        _redis("DEL", key)
        return
    try:
        os.remove(_path(key))
    except OSError:
        pass
