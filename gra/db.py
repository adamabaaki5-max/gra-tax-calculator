"""
Database access.

* On Vercel (or anywhere DATABASE_URL / POSTGRES_URL is set) the app uses PostgreSQL, e.g. Neon or Supabase.
* Without those variables (your own computer) it uses a SQLite file, so you can run the app with nothing installed.

The tables are described in schema.sql and are created automatically the first time the app runs.
"""
import os
import re
import sqlite3
import tempfile
import threading
from contextlib import contextmanager
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from flask import g

SCHEMA_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "schema.sql")
_ready = False
_lock = threading.Lock()


class DbError(Exception):
    pass


def database_url():
    url = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL") or ""
    if not url:
        return ""
    parts = urlsplit(url)
    # some providers add options that PostgreSQL's own client library rejects
    q = [(k, v) for k, v in parse_qsl(parts.query) if k not in ("supa", "pgbouncer", "connection_limit", "pool_timeout")]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(q), parts.fragment))


def is_persistent() -> bool:
    """True when a real (PostgreSQL) database is connected."""
    return bool(database_url())


class Db:
    def __init__(self):
        url = database_url()
        try:
            if url:
                import psycopg
                self.kind = "pg"
                self.conn = psycopg.connect(url, autocommit=True, connect_timeout=10)
            else:
                self.kind = "sqlite"
                d = os.environ.get("GRA_DATA_DIR") or os.path.join(tempfile.gettempdir(), "gra-data")
                os.makedirs(d, exist_ok=True)
                self.conn = sqlite3.connect(os.path.join(d, "gra.sqlite3"), isolation_level=None, timeout=10)
                self.conn.execute("PRAGMA foreign_keys = ON")
        except Exception as ex:
            raise DbError("Could not connect to the database: %s" % ex) from ex

    def _sql(self, sql):
        return sql if self.kind == "pg" else sql.replace("%s", "?")

    def query(self, sql, params=()):
        try:
            cur = self.conn.cursor()
            cur.execute(self._sql(sql), params)
            rows = cur.fetchall()
            cur.close()
            return rows
        except Exception as ex:
            raise DbError(str(ex)) from ex

    def execute(self, sql, params=()):
        try:
            cur = self.conn.cursor()
            cur.execute(self._sql(sql), params)
            n = cur.rowcount
            cur.close()
            return n
        except Exception as ex:
            raise DbError(str(ex)) from ex

    @contextmanager
    def transaction(self):
        try:
            if self.kind == "pg":
                with self.conn.transaction():
                    yield
            else:
                self.conn.execute("BEGIN")
                try:
                    yield
                    self.conn.execute("COMMIT")
                except Exception:
                    self.conn.execute("ROLLBACK")
                    raise
        except DbError:
            raise
        except Exception as ex:
            raise DbError(str(ex)) from ex

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass


def init_schema(db: Db) -> None:
    with open(SCHEMA_FILE, encoding="utf-8") as f:
        text = re.sub(r"--[^\n]*", "", f.read())
    for stmt in (s.strip() for s in text.split(";")):
        if stmt:
            db.execute(stmt)


def get_db() -> Db:
    """One connection per request; tables are created the first time."""
    global _ready
    if "db" not in g:
        g.db = Db()
        if not _ready:
            with _lock:
                if not _ready:
                    init_schema(g.db)
                    _ready = True
    return g.db


def close_db(_exc=None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()
