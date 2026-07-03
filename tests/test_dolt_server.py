"""Resident dolt sql-server lifecycle — the concurrent-write contention fix.

Skipped when dolt is not available. The load-bearing test is
`test_concurrent_writes_no_loss`: without the server, ~8/10 concurrent firings
are bounced with "cannot update manifest: database is read only"; with it, all
land. The rest cover the fail-open lifecycle (disabled = no-op, liveness probe,
stale-info, stop).
"""
import os
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor

import pytest

from monition import dolt_server
from monition.cli import main
from monition.init_sync import V9_SCHEMA
from monition.storage_backends import DoltBackend, _dolt_bin
from monition.store_write import WriteStore

from .conftest import build_dolt_store

pytestmark = pytest.mark.skipif(
    not (shutil.which("dolt") or os.path.exists(os.path.expanduser("~/.local/bin/dolt"))),
    reason="dolt binary not available",
)

_SEED = (
    "INSERT INTO takeaways (id, created, kind, trigger_kind, one_liner, status, reach)"
    " VALUES (1, NOW(), 'gotcha', 'session_start', 'seed', 'active', 'project');"
)


@pytest.fixture
def dolt_store(tmp_path):
    """A throwaway Dolt store seeded with one takeaway (FK target for firings).
    Teardown always stops any sql-server this test left running."""
    path = str(tmp_path / "store")
    build_dolt_store(path, [V9_SCHEMA, _SEED])
    yield path
    dolt_server.stop(path)


@pytest.fixture
def server_on(monkeypatch):
    monkeypatch.setenv("MONITION_SQL_SERVER", "1")


# ---------------------------------------------------------------------------
# Fail-open lifecycle
# ---------------------------------------------------------------------------

def test_disabled_is_noop(dolt_store, monkeypatch):
    """Default (flag unset): ensure_running spawns nothing — behaviour unchanged."""
    monkeypatch.delenv("MONITION_SQL_SERVER", raising=False)
    dolt_server.ensure_running(dolt_store, _dolt_bin())
    assert not dolt_server.running(dolt_store)
    assert not os.path.exists(dolt_server._info_path(dolt_store))


def test_ensure_running_spawns_and_is_detected(dolt_store, server_on):
    dolt_server.ensure_running(dolt_store, _dolt_bin())
    assert dolt_server.running(dolt_store)  # accepting on its port
    info = dolt_server._read_info(dolt_store)
    assert info and dolt_server._pid_alive(info[0]) and dolt_server._port_open(info[1])


def test_ensure_running_idempotent(dolt_store, server_on):
    dolt_server.ensure_running(dolt_store, _dolt_bin())
    first = dolt_server._read_info(dolt_store)
    dolt_server.ensure_running(dolt_store, _dolt_bin())  # second call: no respawn
    assert dolt_server._read_info(dolt_store) == first


def test_stale_info_not_running(dolt_store):
    """A leftover .info file whose PID is dead must read as not-running, so the
    next write either spawns a fresh server or proceeds on the subprocess path."""
    os.makedirs(os.path.join(dolt_store, ".dolt"), exist_ok=True)
    with open(dolt_server._info_path(dolt_store), "w") as f:
        f.write("999999999:3306:deadbeef")  # implausible, dead PID
    assert not dolt_server.running(dolt_store)


def test_stop(dolt_store, server_on):
    dolt_server.ensure_running(dolt_store, _dolt_bin())
    assert dolt_server.running(dolt_store)
    msg = dolt_server.stop(dolt_store)
    assert "stopped sql-server" in msg
    assert not dolt_server.running(dolt_store)


def test_stop_when_none(dolt_store):
    assert dolt_server.stop(dolt_store) == "no running sql-server for this store"


def test_cli_status_and_stop(dolt_store, server_on, capsys):
    assert main(["sql-server-status", "--store", dolt_store]) == 0
    assert "not running" in capsys.readouterr().out
    dolt_server.ensure_running(dolt_store, _dolt_bin())
    assert main(["sql-server-status", "--store", dolt_store]) == 0
    assert "running (pid" in capsys.readouterr().out
    assert main(["sql-server-stop", "--store", dolt_store]) == 0
    assert "stopped sql-server" in capsys.readouterr().out
    assert not dolt_server.running(dolt_store)


# ---------------------------------------------------------------------------
# The contention fix
# ---------------------------------------------------------------------------

def _fire_concurrently(store_path, n=10):
    """Returns the list of error strings (empty == that firing landed)."""
    def fire(i):
        try:
            WriteStore(store_path).fire(1, "session_start", session=f"s{i}",
                                        current_repo=f"/tmp/r{i}")
            return None
        except Exception as e:  # noqa: BLE001 — capture-or-lose, surfaced in assert
            return str(e)[-160:]
    with ThreadPoolExecutor(max_workers=n) as ex:
        return list(ex.map(fire, range(n)))


def test_concurrent_writes_no_loss(dolt_store, server_on):
    """With the server on, every concurrent firing lands — no manifest-lock loss."""
    errs = [e for e in _fire_concurrently(dolt_store, 10) if e]
    assert not errs, f"lost {len(errs)}/10 firings: {errs[:3]}"
    rows = DoltBackend(dolt_store).execute_sql("SELECT COUNT(*) AS c FROM firings")
    assert int(rows[0]["c"]) == 10


def test_concurrent_writes_lossy_without_server(dolt_store, monkeypatch):
    """Pins the premise: without the server, concurrent writes contend and most
    are lost. Guards against a silent regression that makes the fix look free."""
    monkeypatch.delenv("MONITION_SQL_SERVER", raising=False)
    errs = [e for e in _fire_concurrently(dolt_store, 10) if e]
    assert not dolt_server.running(dolt_store)  # nothing spawned
    assert errs  # contention bit at least once


def test_foreign_lock_file_not_treated_as_this_stores_server(tmp_path):
    """A copied/stale .info naming a live pid that serves a DIFFERENT store must
    not resolve — a cp -r'd hub carries the hub's lock, and honoring it routed a
    scratch store's reads AND writes into the real hub via the wire client's
    single-db fallback (found live, B04 smoke 2026-07-03)."""
    store = tmp_path / "scratch-store"
    dolt_dir = store / ".dolt"
    os.makedirs(dolt_dir)
    # our own pid: alive, but its cwd is not the store dir → foreign
    with open(dolt_dir / "sql-server.info", "w") as f:
        f.write(f"{os.getpid()}:3306:deadbeef")
    assert not dolt_server._serves_this_store(os.getpid(), str(store))
    assert dolt_server.address(str(store)) is None
    assert not dolt_server.running(str(store))


def test_own_store_lock_still_resolves(tmp_path, monkeypatch):
    """The ownership check must not break the healthy case: a pid whose cwd IS
    the store dir passes (port probe short-circuits separately)."""
    store = tmp_path / "own-store"
    os.makedirs(store / ".dolt")
    monkeypatch.chdir(store)
    assert dolt_server._serves_this_store(os.getpid(), str(store))
