"""Dolt backend conformance — proves the seam holds.

These tests run the same read/write operations as the main suite but against a
Dolt store, verifying that DoltBackend is substitutable for SqliteBackend.
Skipped when dolt is not available.
"""
import os
import shutil

import pytest

from monition.store import Store, StoreContractError
from monition.store_write import WriteStore

from .conftest import ROWS, build_dolt_store, dolt

pytestmark = pytest.mark.skipif(
    not (shutil.which("dolt") or os.path.exists(os.path.expanduser("~/.local/bin/dolt"))),
    reason="dolt binary not available",
)

# Use V6_SCHEMA (MySQL DDL) for Dolt fixture
from monition.init_sync import V6_SCHEMA as DOLT_SCHEMA


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
