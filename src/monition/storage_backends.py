"""Storage-backend seam: SqliteBackend (default) and DoltBackend (optional).

Backend detection via open_backend(path):
  .dolt/ present  → DoltBackend (requires dolt binary)
  store.db present → SqliteBackend (stdlib sqlite3, zero install)

New stores via `monition init` default to SQLite.
The seam sits *under* Store/WriteStore; they remain the single approved
reader/writer.
"""
import datetime
import json
import os
import re
import shutil
import sqlite3
import subprocess

from . import dolt_server

try:                     # optional `[wire]` extra — MySQL wire protocol to the
    import pymysql       # resident sql-server (~1-5ms/query vs ~160ms/CLI spawn,
except ImportError:      # decision 2026-07-02-wire-client-extra). Absent → the
    pymysql = None       # CLI path below, byte-for-byte unchanged.

# Transport-level MySQL errnos: can't connect / server gone / lost connection.
# These fall back to the CLI; every other MySQL error is a QUERY error and must
# raise StorageBackendError exactly like the CLI path would.
_WIRE_TRANSPORT_ERRNOS = {2003, 2006, 2013}


class StorageBackendError(Exception):
    """Raised by a backend when a SQL operation fails; Store re-raises as
    StoreContractError so callers never need to import this directly."""


def _dolt_bin():
    found = shutil.which("dolt")
    if found:
        return found
    fallback = os.path.expanduser("~/.local/bin/dolt")
    return fallback if os.path.exists(fallback) else None


class SqliteBackend:
    """SQLite storage backend — stdlib sqlite3, zero install."""

    name = "sqlite"

    def __init__(self, db_path):
        self.db_path = db_path  # full path to store.db

    @staticmethod
    def _adapt(sql):
        return sql.replace("NOW()", "datetime('now')")

    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def quote(s):
        """SQL string literal in the SQLite dialect: quote-doubling only —
        backslashes are LITERAL characters here (unlike MySQL), so they must
        not be escaped or the stored value gains spurious backslashes."""
        return "'" + str(s).replace("'", "''") + "'"

    def execute_sql(self, sql):
        sql = self._adapt(sql)
        conn = self._conn()
        try:
            cur = conn.execute(sql)
            conn.commit()
            if cur.description:
                return [dict(r) for r in cur.fetchall()]
            return []
        except sqlite3.Error as e:
            conn.rollback()
            raise StorageBackendError(str(e)) from e
        finally:
            conn.close()

    def describe(self, table):
        """Returns [{Field, Type}] for each column; [] when table is missing."""
        conn = self._conn()
        try:
            cur = conn.execute(f"PRAGMA table_info('{table}')")
            rows = cur.fetchall()
        finally:
            conn.close()
        return [{"Field": r["name"], "Type": r["type"]} for r in rows]

    def describe_all(self, tables):
        """{table: [{Field, Type}]} for every table — the schema-fingerprint
        projection only (unlike Dolt's raw describe, no Null/Key/Extra).
        In-process and cheap here; exists for signature parity with
        DoltBackend's one-subprocess version."""
        return {t: self.describe(t) for t in tables}

    def dump(self, store_dir):
        target = os.path.join(store_dir, "dump.sql")
        with sqlite3.connect(self.db_path) as conn:
            lines = list(conn.iterdump())
        with open(target, "w") as f:
            f.write("\n".join(lines) + "\n")
        return target

    def init(self, schema):
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(schema)

    def snapshot(self, message):
        """SQLite has no internal commit. Write dump.sql; git handles history."""
        store_dir = os.path.dirname(self.db_path)
        dump = self.dump(store_dir)
        return f"wrote {os.path.basename(dump)} — `git add monition/dump.sql && git commit` to checkpoint"


class DoltBackend:
    """Dolt storage backend. Queries ride the MySQL wire protocol to the
    resident sql-server when the `[wire]` extra is installed and a server is
    accepting (~1ms/query); otherwise — and as the fail-open fallback — each
    query shells out to the dolt binary (~160ms/spawn)."""

    name = "dolt"

    def __init__(self, path):
        self._path = path  # store directory (contains .dolt/)
        self._wire_conn = None   # lazy, one per backend instance — no pooling
        self._wire_dead = False  # set on unrecoverable open failure (auth, no db)

    def _run(self, args, check=True):
        out = subprocess.run(
            [_dolt_bin()] + args, cwd=self._path, capture_output=True, text=True,
        )
        if check and out.returncode != 0:
            raise StorageBackendError(out.stderr.strip() or out.stdout.strip())
        return out

    @staticmethod
    def quote(s):
        """SQL string literal in the MySQL/Dolt dialect: backslash is an
        escape character in string literals, so double it; quotes via
        doubling (valid MySQL, and avoids the \\' form SQLite can't parse)."""
        return "'" + str(s).replace("\\", "\\\\").replace("'", "''") + "'"

    def execute_sql(self, sql):
        # Opt-in (MONITION_SQL_SERVER): ensure a resident sql-server owns the store
        # so concurrent writes serialize through it instead of contending on the
        # manifest lock. Fail-open and a no-op when disabled — the `dolt sql -q`
        # below auto-routes through any running server, so this needs no client.
        dolt_server.ensure_running(self._path, _dolt_bin())
        if pymysql is not None and not self._wire_dead:
            rows = self._wire_execute(sql)
            if rows is not None:
                return rows
        out = subprocess.run(
            [_dolt_bin(), "sql", "-q", sql, "-r", "json"],
            cwd=self._path, capture_output=True, text=True,
        )
        if out.returncode != 0:
            raise StorageBackendError(out.stderr.strip() or out.stdout.strip())
        text = out.stdout.strip()
        return json.loads(text).get("rows", []) if text else []

    # --- wire transport (optional [wire] extra) -----------------------------
    # Same SQL, same single write path — only how bytes reach the resident
    # sql-server changes (decision 2026-07-02-wire-client-extra). Fail-open
    # chain: transport problem → CLI subprocess; query error → StorageBackendError
    # identical to the CLI path (a bad query must fail, not silently re-run).

    def _wire_execute(self, sql):
        """Rows via the resident server's wire protocol, or None → caller uses
        the CLI. Never raises for transport reasons; raises StorageBackendError
        for query errors."""
        try:
            conn = self._wire_conn or self._wire_open()
        except Exception:
            self._wire_dead = True   # auth/db-resolution failure — stop trying
            return None
        if conn is None:             # no accepting server right now — retry later
            return None
        try:
            with conn.cursor(pymysql.cursors.DictCursor) as cur:
                cur.execute(sql)
                rows = cur.fetchall() if cur.description else []
            return [self._wire_norm_row(r) for r in rows]
        except pymysql.MySQLError as e:
            errno_ = e.args[0] if e.args and isinstance(e.args[0], int) else None
            if errno_ in _WIRE_TRANSPORT_ERRNOS:
                try:
                    conn.close()
                except Exception:
                    pass
                self._wire_conn = None   # next call reconnects (or CLI-falls-back)
                return None
            raise StorageBackendError(str(e)) from e

    def _wire_open(self):
        """Connect to the accepting server, resolve the store's database, cache
        the connection. None when no server is accepting (not an error — the
        CLI path handles this call). Raises on auth/db-resolution failure, which
        _wire_execute converts into a permanent per-process opt-out."""
        addr = dolt_server.address(self._path)
        if addr is None:
            return None
        conn = pymysql.connect(
            host=addr[0], port=addr[1], user="root", password="",
            connect_timeout=0.5, autocommit=True,
        )
        with conn.cursor() as cur:
            cur.execute("SHOW DATABASES")
            names = [r[0] for r in cur.fetchall()]
        system = {"information_schema", "mysql", "performance_schema", "sys"}
        candidates = [n for n in names if n not in system]
        # dolt names the db after the store dir (unsupported chars → _).
        want = re.sub(r"[^A-Za-z0-9_$]", "_",
                      os.path.basename(os.path.abspath(self._path)))
        db = want if want in candidates else (
            candidates[0] if len(candidates) == 1 else None)
        if db is None:
            conn.close()
            raise StorageBackendError(
                f"wire: cannot resolve store db among {candidates}")
        conn.select_db(db)
        self._wire_conn = conn
        return conn

    @staticmethod
    def _wire_norm_row(row):
        """CLI-JSON parity: dolt `-r json` THROUGH THE SERVER stringifies every
        value and omits NULL keys (verified live 2026-07-02; serverless direct
        access emits native JSON numbers instead — consumers tolerate both,
        via int(...)/row.get). Wire only ever runs where a server is accepting,
        so mirror the through-server shape exactly."""
        out = {}
        for k, v in row.items():
            if v is None:
                continue
            if isinstance(v, datetime.datetime):
                out[k] = v.strftime("%Y-%m-%d %H:%M:%S")
            elif isinstance(v, datetime.date):
                out[k] = v.strftime("%Y-%m-%d")
            elif isinstance(v, bytes):
                out[k] = v.decode("utf-8", "replace")
            elif isinstance(v, str):
                out[k] = v
            else:
                out[k] = str(v)   # int / Decimal — CLI emits these as strings
        return out

    def describe(self, table):
        """Returns [{Field, Type}] for each column; [] when table is missing.
        Routed through execute_sql so it rides the wire when available; the
        ensure_running gate there also keeps a describe from racing a concurrent
        server spawn into a false "table missing"."""
        try:
            return self.execute_sql(f"DESCRIBE `{table}`")
        except StorageBackendError:
            return []

    def describe_all(self, tables):
        """Every table's columns in ONE subprocess: {table: [{Field, Type}]} —
        the schema-fingerprint projection only, NOT describe()'s full rows
        (no Null/Key/Extra). Schema validation used to pay one DESCRIBE spawn
        per table per store open (~160ms each × 10 — the dominant hook-latency
        cost, Phase 8); information_schema answers them all in a single
        invocation. Any error or unrecognizable result shape falls back to
        per-table describe so validation outcomes stay identical to the
        one-table-at-a-time path."""
        if not tables:
            return {}
        names = ", ".join(self.quote(t) for t in tables)
        sql = (
            "SELECT table_name AS Tbl, column_name AS Field, column_type AS Type "
            "FROM information_schema.columns "
            f"WHERE table_schema = DATABASE() AND table_name IN ({names}) "
            "ORDER BY table_name, ordinal_position"
        )
        try:
            rows = self.execute_sql(sql)
        except StorageBackendError:
            return {t: self.describe(t) for t in tables}
        out = {t: [] for t in tables}
        matched = False
        for r in rows:
            # Key case is the engine's choice for aliases — normalize.
            rk = {(k or "").lower(): v for k, v in r.items()}
            t = rk.get("tbl")
            if t in out:
                matched = True
                out[t].append({"Field": rk.get("field"), "Type": rk.get("type")})
        if rows and not matched:
            # Result shape not what we expect (alias handling changed?) —
            # trust the per-table path over guessing.
            return {t: self.describe(t) for t in tables}
        return out

    def dump(self, store_dir):
        self._run(["dump", "-f"])
        legacy = os.path.join(store_dir, "doltdump.sql")
        target = os.path.join(store_dir, "dump.sql")
        if os.path.exists(legacy):
            os.replace(legacy, target)
        return target

    def init(self, schema):
        """Run `dolt init` then apply the schema DDL."""
        out = subprocess.run(
            [_dolt_bin(), "init"], cwd=self._path, capture_output=True, text=True,
        )
        if out.returncode != 0:
            raise StorageBackendError(f"dolt init failed: {out.stderr.strip()}")
        out = subprocess.run(
            [_dolt_bin(), "sql", "-q", schema], cwd=self._path,
            capture_output=True, text=True,
        )
        if out.returncode != 0:
            raise StorageBackendError(f"store DDL failed: {out.stderr.strip()}")

    def snapshot(self, message):
        self._run(["add", "-A"])
        out = self._run(["commit", "-m", message], check=False)
        return (out.stdout or out.stderr).strip().splitlines()[0]


def open_backend(path):
    """Detect which backend serves the store at `path` and return it.

    Detection order:
      1. .dolt/ directory → DoltBackend (requires dolt binary on PATH)
      2. store.db file    → SqliteBackend
    """
    if os.path.isdir(os.path.join(path, ".dolt")):
        if _dolt_bin() is None:
            raise StorageBackendError(
                "dolt binary not found on PATH or ~/.local/bin"
            )
        return DoltBackend(path)
    db = os.path.join(path, "store.db")
    if os.path.exists(db):
        return SqliteBackend(db)
    raise StorageBackendError(
        f"{path} is not a Monition store "
        "(no .dolt/ directory and no store.db — "
        "run `monition init` to create one)"
    )
