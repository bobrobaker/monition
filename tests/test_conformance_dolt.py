"""Dolt backend conformance — proves the seam holds.

These tests run the same read/write operations as the main suite but against a
Dolt store, verifying that DoltBackend is substitutable for SqliteBackend.
Skipped when dolt is not available.
"""
import os
import shutil

import pytest

from monition import dolt_server
from monition.store import Store, StoreContractError
from monition.store_write import WriteStore

from .conftest import ROWS, build_dolt_store, dolt

pytestmark = pytest.mark.skipif(
    not (shutil.which("dolt") or os.path.exists(os.path.expanduser("~/.local/bin/dolt"))),
    reason="dolt binary not available",
)

# Use V9_SCHEMA (MySQL DDL) for Dolt fixture
from monition.init_sync import V9_SCHEMA as DOLT_SCHEMA


@pytest.fixture(scope="module")
def dolt_canonical(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("dolt_stores") / "canonical")
    return build_dolt_store(path, [DOLT_SCHEMA, ROWS])


@pytest.fixture
def dolt_copy(dolt_canonical, tmp_path):
    dst = str(tmp_path / "dolt_copy")
    shutil.copytree(dolt_canonical, dst)
    return dst


# --- Read contract ---

def test_dolt_reads_canonical(dolt_canonical):
    s = Store(dolt_canonical)
    takeaways = s.takeaways()
    firings = s.firings()
    decisions = s.decisions()
    assert len(takeaways) == 7
    assert len(firings) == 8
    assert len(decisions) == 3
    assert takeaways[0].one_liner == "all noise"
    assert firings[4].outcome is None


def test_dolt_field_types_and_values(dolt_canonical):
    """Value- and type-level assertions, not just row counts — the gap this
    bug class shipped through (`monition report`/`tune` misread every
    cold_start/git_dirty row against the live hub while every test here still
    passed, because nothing checked further than `len(...)`). Ground truth
    from conftest.ROWS: d1 cold-start (evidence_count 0, ev_score None), d2
    suppress (evidence_count 2, ev_score 0.0), d3 fire (evidence_count 2,
    ev_score 0.5)."""
    s = Store(dolt_canonical)
    takeaways = s.takeaways()
    firings = s.firings()
    decisions = {d.id: d for d in s.decisions()}

    assert all(isinstance(t.id, int) for t in takeaways)
    assert all(isinstance(f.id, int) and isinstance(f.takeaway_id, int)
               for f in firings)
    assert firings[2].takeaway_id == 2  # f3 in conftest.ROWS: takeaway_id 2

    d1, d2, d3 = decisions[1], decisions[2], decisions[3]
    assert (d1.cold_start, d1.ev_score, d1.evidence_count) == (True, None, 0)
    assert (d2.cold_start, d2.ev_score, d2.evidence_count) == (False, 0.0, 2)
    assert (d3.cold_start, d3.ev_score, d3.evidence_count) == (False, 0.5, 2)
    for d in decisions.values():
        assert isinstance(d.id, int) and isinstance(d.takeaway_id, int)
        assert isinstance(d.evidence_count, int)
        assert isinstance(d.cold_start, bool)
        assert d.ev_score is None or isinstance(d.ev_score, float)


def test_dolt_stringified_scalars_survive_across_all_readers(dolt_copy, monkeypatch):
    """Sibling of test_decisions.py's cold_start test and test_export_firings.py's
    git_dirty test, run here against a real DoltBackend and widened to every
    numeric field the store.py readers cast: id/takeaway_id (all readers),
    evidence_count, cold_start, ev_score, git_dirty. Reproduces the documented
    Dolt-CLI-JSON-through-server shape (storage_backends.DoltBackend.
    _wire_norm_row: every scalar stringified, NULLs omitted) deterministically,
    without depending on a live resident sql-server, whose stringification only
    kicks in once it is actually mediating the query (see
    test_dolt_live_sql_server_shape_casts_correctly below for that transport)."""
    # conftest.ROWS leaves every firing's git_dirty NULL; seed one with a real
    # (non-NULL) value so the git_dirty cast has ground truth to check here too.
    dolt(["sql", "-q",
          "INSERT INTO firings (takeaway_id, fired_at, session_id, trigger_kind,"
          " git_dirty) VALUES (1, NOW(), 'conf-gd', 'edit_path', 0)"],
         dolt_copy)

    store = Store(dolt_copy)
    real_execute = store._backend.execute_sql
    numeric_cols = {"id", "takeaway_id", "evidence_count", "cold_start",
                    "ev_score", "git_dirty"}

    def stringify_all(sql):
        rows = real_execute(sql)
        return [
            {k: (str(v) if k in numeric_cols and v is not None else v)
             for k, v in r.items()}
            for r in rows
        ]

    monkeypatch.setattr(store._backend, "execute_sql", stringify_all)

    takeaways = store.takeaways()
    firings = store.firings()
    decisions = store.decisions()

    assert all(isinstance(t.id, int) for t in takeaways)
    assert all(isinstance(f.id, int) and isinstance(f.takeaway_id, int)
               for f in firings)
    seeded = next(f for f in firings if f.session_id == "conf-gd")
    assert seeded.git_dirty is False  # bool("0") would misreport True

    assert all(
        isinstance(d.id, int) and isinstance(d.takeaway_id, int)
        and isinstance(d.evidence_count, int) and isinstance(d.cold_start, bool)
        for d in decisions
    )
    cold = next(d for d in decisions if d.cold_start)
    assert cold.ev_score is None
    warm = [d for d in decisions if not d.cold_start]
    assert warm and all(isinstance(d.ev_score, float) for d in warm)


def test_dolt_live_sql_server_shape_casts_correctly(tmp_path, monkeypatch):
    """True-transport version of the two tests above: a real resident `dolt
    sql-server` (opt-in via MONITION_SQL_SERVER, gated off by default —
    conftest.py pops the env var at process level) mediates every query
    end-to-end, which is where the documented stringify-every-scalar shape
    actually originates (storage_backends.DoltBackend._wire_norm_row). The
    monkeypatch tests above simulate that shape deterministically; this one
    proves the real server produces it and Store still reads correctly.
    A scratch store, explicitly torn down — never the shared dolt_canonical/
    dolt_copy fixtures, so the resident server this test spawns can't leak
    into any other test."""
    path = str(tmp_path / "live_server_store")
    build_dolt_store(path, [DOLT_SCHEMA, ROWS])
    monkeypatch.setenv("MONITION_SQL_SERVER", "1")
    try:
        store = Store(path)
        takeaways = store.takeaways()
        firings = store.firings()
        decisions = {d.id: d for d in store.decisions()}

        assert dolt_server.running(path)  # actually mediated, not CLI-direct
        assert all(isinstance(t.id, int) for t in takeaways)
        assert all(isinstance(f.id, int) and isinstance(f.takeaway_id, int)
                   for f in firings)
        d1, d2, d3 = decisions[1], decisions[2], decisions[3]
        assert (d1.cold_start, d1.ev_score, d1.evidence_count) == (True, None, 0)
        assert (d2.cold_start, d2.ev_score, d2.evidence_count) == (False, 0.0, 2)
        assert (d3.cold_start, d3.ev_score, d3.evidence_count) == (False, 0.5, 2)
        assert all(isinstance(d.evidence_count, int) for d in decisions.values())
    finally:
        dolt_server.stop(path)


def test_dolt_rejects_missing_table(dolt_copy):
    dolt(["sql", "-q", "DROP TABLE firings"], dolt_copy)
    with pytest.raises(StoreContractError, match="missing required table"):
        Store(dolt_copy)


def test_dolt_rejects_missing_column(dolt_copy):
    dolt(["sql", "-q", "ALTER TABLE takeaways DROP COLUMN one_liner"], dolt_copy)
    with pytest.raises(StoreContractError, match="missing required column"):
        Store(dolt_copy)


def test_dolt_rejects_changed_enum_domain(dolt_copy):
    dolt(["sql", "-q",
          "ALTER TABLE firings MODIFY outcome enum('helpful','noise','meh')"],
         dolt_copy)
    with pytest.raises(StoreContractError, match="contract requires"):
        Store(dolt_copy)


# --- Write + read-back contract ---

def test_dolt_add_fire_rate_round_trip(dolt_copy):
    ws = WriteStore(dolt_copy)
    msg = ws.add("gotcha", "edit_path", "dolt seam test", "new/*",
                 full_content="why", source="conformance")
    assert "added takeaway" in msg
    tid = int(msg.split()[-1])

    fire_msg = ws.fire(tid, "edit_path", session="conf-s1", context="new/x.py")
    assert "firing" in fire_msg
    fid = int(fire_msg.split()[-1])

    ws.rate(fid, "helpful")

    s = Store(dolt_copy)
    t = next(t for t in s.takeaways() if t.id == tid)
    assert t.one_liner == "dolt seam test"
    f = next(f for f in s.firings() if f.id == fid)
    assert f.outcome == "helpful"


def test_dolt_roundtrips_backslashes_and_quotes(dolt_copy):
    """The MySQL dialect needs backslash escaping where SQLite must not have
    it (backend.quote seam) — same round-trip both conformance suites run."""
    ws = WriteStore(dolt_copy)
    gnarly = "it's a \\\"quoted\\\" backslash-y 'context'"
    ws.fire("7", "on_demand", session="conf-q1", context=gnarly,
            situation=gnarly)
    f = next(x for x in Store(dolt_copy).firings() if x.session_id == "conf-q1")
    assert f.trigger_context == gnarly
    assert f.situation == gnarly


# --- dump ---

def test_dolt_dump_writes_sql(dolt_copy, tmp_path):
    ws = WriteStore(dolt_copy)
    result = ws.dump()
    assert "dump.sql" in result
    assert os.path.exists(os.path.join(dolt_copy, "dump.sql"))


# --- snapshot ---

def test_dolt_snapshot(dolt_copy):
    ws = WriteStore(dolt_copy)
    ws.add("rule", "session_start", "a snapshot test row")
    msg = ws.commit("conformance snapshot")
    assert msg  # dolt returns "commit <sha>" or similar
