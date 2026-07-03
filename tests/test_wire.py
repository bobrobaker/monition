"""Wire-protocol transport (`[wire]` extra) — decision 2026-07-02-wire-client-extra.

The wire client is a TRANSPORT inside DoltBackend, not a second path: identical
SQL, results normalized to the dolt CLI's JSON shape (every value a string, NULL
keys omitted). Load-bearing tests: CLI-parity on real rows, the fail-open chain
(no server → CLI, server dies → CLI), and query errors raising StorageBackendError
identically on both transports. Skipped without dolt or pymysql.
"""
import os
import shutil

import pytest

from monition import dolt_server
from monition.init_sync import V8_SCHEMA
from monition.storage_backends import DoltBackend, StorageBackendError, pymysql

from .conftest import build_dolt_store

pytestmark = [
    pytest.mark.skipif(
        not (shutil.which("dolt") or os.path.exists(os.path.expanduser("~/.local/bin/dolt"))),
        reason="dolt binary not available",
    ),
    pytest.mark.skipif(pymysql is None, reason="pymysql ([wire] extra) not installed"),
]

_SEED = (
    "INSERT INTO takeaways (id, created, kind, trigger_kind, one_liner, status, reach)"
    " VALUES (1, NOW(), 'gotcha', 'session_start', 'seed one', 'active', 'project'),"
    "        (2, NOW(), 'rule', 'on_demand', 'seed two', 'active', 'general');"
)


@pytest.fixture
def dolt_store(tmp_path):
    path = str(tmp_path / "store")
    build_dolt_store(path, [V8_SCHEMA, _SEED])
    yield path
    dolt_server.stop(path)


@pytest.fixture
def server_on(monkeypatch):
    monkeypatch.setenv("MONITION_SQL_SERVER", "1")


def _wire_backend(path):
    """Backend that has actually established a wire connection."""
    b = DoltBackend(path)
    b.execute_sql("SELECT 1")  # ensure_running + wire connect
    assert b._wire_conn is not None, "wire connection did not establish"
    return b


def test_wire_used_and_cli_parity(dolt_store, server_on):
    """Same rows through wire and CLI — values, NULL-key omission, ordering."""
    wire = _wire_backend(dolt_store)
    cli = DoltBackend(dolt_store)
    cli._wire_dead = True  # force the subprocess path
    for q in (
        "SELECT * FROM takeaways ORDER BY id",
        "DESCRIBE `takeaways`",
        "SELECT COUNT(*) AS n FROM takeaways",
        "SELECT id, trigger_spec FROM takeaways ORDER BY id",  # trigger_spec NULL
    ):
        assert wire.execute_sql(q) == cli.execute_sql(q), q
    # NULL keys are omitted, not None-valued (the CLI-JSON contract).
    row = wire.execute_sql("SELECT id, trigger_spec FROM takeaways WHERE id = 1")[0]
    assert "trigger_spec" not in row


def test_wire_write_visible_to_cli(dolt_store, server_on):
    """A write through the wire lands in the store (autocommit) — same single
    write path, visible to a CLI-transport read."""
    wire = _wire_backend(dolt_store)
    wire.execute_sql(
        "INSERT INTO firings (takeaway_id, fired_at, session_id, trigger_kind)"
        " VALUES (1, NOW(), 'wire-test', 'on_demand')")
    cli = DoltBackend(dolt_store)
    cli._wire_dead = True
    rows = cli.execute_sql("SELECT session_id FROM firings")
    assert rows == [{"session_id": "wire-test"}]


def test_no_server_falls_back_to_cli(dolt_store, monkeypatch):
    """Flag off, no server anywhere → wire opts out silently, CLI serves.
    Serverless CLI JSON emits native numbers (unlike through-server, which
    stringifies) — assert semantically, as every consumer does."""
    monkeypatch.delenv("MONITION_SQL_SERVER", raising=False)
    b = DoltBackend(dolt_store)
    rows = b.execute_sql("SELECT COUNT(*) AS n FROM takeaways")
    assert len(rows) == 1 and int(rows[0]["n"]) == 2
    assert b._wire_conn is None


def test_server_killed_midway_falls_back(dolt_store, server_on, monkeypatch):
    """The exit-criterion chain: established wire connection, server dies, next
    query still succeeds (CLI), no exception escapes."""
    b = _wire_backend(dolt_store)
    dolt_server.stop(dolt_store)
    # Disable respawn so the fallback (not a fresh server) is what's proven.
    monkeypatch.delenv("MONITION_SQL_SERVER", raising=False)
    rows = b.execute_sql("SELECT COUNT(*) AS n FROM takeaways")
    assert len(rows) == 1 and int(rows[0]["n"]) == 2  # serverless CLI: numbers


def test_query_error_raises_identically(dolt_store, server_on):
    """A bad query is a QUERY error on both transports — StorageBackendError,
    never a silent CLI re-run of the same bad SQL."""
    wire = _wire_backend(dolt_store)
    cli = DoltBackend(dolt_store)
    cli._wire_dead = True
    for backend in (wire, cli):
        with pytest.raises(StorageBackendError):
            backend.execute_sql("SELECT nope FROM no_such_table")
    # describe() maps the missing-table error to [] on both transports.
    assert wire.describe("no_such_table") == []
    assert cli.describe("no_such_table") == []
