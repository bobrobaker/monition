"""Storage-backend seam: SqliteBackend (default) and DoltBackend (optional).

Backend detection via open_backend(path):
  .dolt/ present  → DoltBackend (requires dolt binary)
  store.db present → SqliteBackend (stdlib sqlite3, zero install)

New stores via `monition init` default to SQLite.
The seam sits *under* Store/WriteStore; they remain the single approved
reader/writer.
"""
import json
import os
import shutil
import sqlite3
import subprocess


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
    """Dolt storage backend — shells out to the dolt binary."""

    name = "dolt"

    def __init__(self, path):
        self._path = path  # store directory (contains .dolt/)

    def _run(self, args, check=True):
        out = subprocess.run(
            [_dolt_bin()] + args, cwd=self._path, capture_output=True, text=True,
        )
        if check and out.returncode != 0:
            raise StorageBackendError(out.stderr.strip() or out.stdout.strip())
        return out

    def execute_sql(self, sql):
        out = subprocess.run(
            [_dolt_bin(), "sql", "-q", sql, "-r", "json"],
            cwd=self._path, capture_output=True, text=True,
        )
        if out.returncode != 0:
            raise StorageBackendError(out.stderr.strip() or out.stdout.strip())
        text = out.stdout.strip()
        return json.loads(text).get("rows", []) if text else []

    def describe(self, table):
        """Returns [{Field, Type}] for each column; [] when table is missing."""
        out = subprocess.run(
            [_dolt_bin(), "sql", "-q", f"DESCRIBE `{table}`", "-r", "json"],
            cwd=self._path, capture_output=True, text=True,
        )
        if out.returncode != 0:
            return []
        text = out.stdout.strip()
        return json.loads(text).get("rows", []) if text else []

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
