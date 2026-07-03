"""Synthetic store fixtures with known ground truth.

Builds SQLite stores by default (zero install). Dolt helpers (`dolt`,
`build_dolt_store`) are available for conformance tests that need the Dolt
backend; they are skipped automatically when dolt is not on PATH.
"""
import os
import shutil
import sqlite3
import subprocess

import pytest

from monition.init_sync import V8_SCHEMA_SQLITE


@pytest.fixture(autouse=True)
def _isolate_state_home(monkeypatch, tmp_path):
    """Every test gets a throwaway XDG_STATE_HOME so the hook state log and
    compaction markers never touch the real ~/.local/state/monition (test
    fixtures were polluting the live hook-errors.log). MONITION_STORE is
    likewise dropped so a dev shell's hub env can't leak in — tests that need
    a store set it explicitly."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg-state"))
    monkeypatch.delenv("MONITION_STORE", raising=False)


# Daemon opt-ins are stripped at IMPORT time, not in the fixture above: with
# MONITION_SQL_SERVER set machine-wide (the 2026-07-02 cutover), every
# Dolt-store test spawns a resident sql-server on its throwaway tmp store and
# leaks it — the exact transient-store littering the opt-in decision exists to
# prevent. A function-scoped autouse delenv does NOT cover session-scoped
# fixtures (canonical_store & co. set up before it runs) — verified 2026-07-02:
# nine leaked servers on deleted pytest dirs. Process-level pop covers every
# fixture scope and every subprocess. Tests that exercise the daemons
# (test_dolt_server.py) setenv explicitly per-test.
os.environ.pop("MONITION_SQL_SERVER", None)
os.environ.pop("MONITION_EMBED_DAEMON", None)

# SQLite schema for test fixtures — same DDL that `monition init` uses.
SCHEMA = V8_SCHEMA_SQLITE

# Ground truth: t1 all-noise, t2 mixed, t3 never fires (general reach — fires in
# every repo), t4 fires unrated, t5 retired, t6 general reach (active, fires).
# Decisions: d1 cold-start (ev_score NULL), d2 suppress (evidence-based, t1),
#            d3 fire (evidence-based, t2 at precision 0.5).
ROWS = """
INSERT INTO takeaways (id, created, kind, trigger_kind, trigger_spec, one_liner, status, reach) VALUES
  (1, '2026-01-01 10:00:00', 'gotcha', 'edit_path', 'docs/*', 'all noise', 'active', 'project'),
  (2, '2026-01-01 10:00:00', 'gotcha', 'edit_path', 'src/*,tools/*', 'mixed', 'active', 'project'),
  (3, '2026-01-01 10:00:00', 'rule', 'edit_path', 'never/*', 'never fires', 'active', 'general'),
  (4, '2026-01-01 10:00:00', 'preference', 'session_start', NULL, 'unrated', 'active', 'project'),
  (5, '2026-01-01 10:00:00', 'gotcha', 'edit_path', 'old/*', 'retired', 'retired', 'project'),
  (6, '2026-01-01 10:00:00', 'rule', 'session_start', NULL, 'mirrored', 'active', 'general'),
  (7, '2026-01-01 10:00:00', 'gotcha', 'on_demand', 'migration, schema', 'on_demand: migration gotcha', 'active', 'project');
INSERT INTO firings (id, takeaway_id, fired_at, session_id, trigger_kind, trigger_context, outcome) VALUES
  (1, 1, '2026-01-02 10:00:00', 's1', 'edit_path', 'docs/a.md', 'noise'),
  (2, 1, '2026-01-03 10:00:00', 's2', 'edit_path', 'docs/b.md', 'noise'),
  (3, 2, '2026-01-02 10:00:00', 's1', 'edit_path', 'src/x.py', 'helpful'),
  (4, 2, '2026-01-03 10:00:00', 's2', 'edit_path', 'tools/y.py', 'noise'),
  (5, 2, '2026-01-04 10:00:00', 's3', 'edit_path', 'src/z.py', NULL),
  (6, 4, '2026-01-02 10:00:00', 's1', 'session_start', NULL, NULL),
  (7, 4, '2026-01-03 10:00:00', 'unknown', 'session_start', NULL, NULL),
  (8, 6, '2026-01-02 10:00:00', 's1', 'session_start', NULL, 'helpful');
INSERT INTO decisions (id, takeaway_id, session_id, decided_at, decision, evidence_count, cold_start, ev_score) VALUES
  (1, 4, 's1', '2026-01-02 10:00:00', 'fire', 0, 1, NULL),
  (2, 1, 's2', '2026-01-03 10:00:00', 'suppress', 2, 0, 0.0000),
  (3, 2, 's3', '2026-01-04 10:00:00', 'fire', 2, 0, 0.5000);
"""


def sqlite_exec(store_path, sql):
    """Execute SQL directly against the SQLite store (for mutation tests)."""
    db = os.path.join(store_path, "store.db")
    with sqlite3.connect(db) as conn:
        conn.executescript(sql)


def build_store(path, sql_parts):
    """Build a SQLite store fixture at `path`."""
    os.makedirs(path, exist_ok=True)
    db = os.path.join(path, "store.db")
    with sqlite3.connect(db) as conn:
        for part in sql_parts:
            conn.executescript(part)
    return path


# ---------------------------------------------------------------------------
# Dolt helpers — for conformance tests only; skip when dolt is unavailable.
# ---------------------------------------------------------------------------

def _dolt_available():
    return (shutil.which("dolt") is not None
            or os.path.exists(os.path.expanduser("~/.local/bin/dolt")))


def dolt(args, cwd):
    """Run a dolt command; asserts success."""
    binary = shutil.which("dolt") or os.path.expanduser("~/.local/bin/dolt")
    out = subprocess.run([binary] + args, cwd=cwd, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return out


def build_dolt_store(path, sql_parts):
    """Build a Dolt store fixture at `path` (requires dolt binary)."""
    os.makedirs(path, exist_ok=True)
    dolt(["init"], path)
    for part in sql_parts:
        dolt(["sql", "-q", part], path)
    return path


# ---------------------------------------------------------------------------
# Primary fixtures (SQLite)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def canonical_store(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("stores") / "canonical")
    return build_store(path, [SCHEMA, ROWS])


@pytest.fixture
def store_copy(canonical_store, tmp_path):
    """A throwaway copy for tests that mutate the schema."""
    dst = str(tmp_path / "store")
    shutil.copytree(canonical_store, dst)
    return dst
