"""Reader contract validation — docs/contracts/takeaway-store.md checklist."""
import pytest

from monition.store import Store, StoreContractError
from tests.conftest import sqlite_exec


def test_reads_canonical_store(canonical_store):
    s = Store(canonical_store)
    takeaways = s.takeaways()
    firings = s.firings()
    assert len(takeaways) == 7
    assert len(firings) == 8
    assert takeaways[0].one_liner == "all noise"
    assert firings[4].outcome is None  # NULL stays None, not "noise"


def test_rejects_non_monition_directory(tmp_path):
    with pytest.raises(StoreContractError, match="not a Monition store"):
        Store(str(tmp_path))


def test_rejects_missing_table(store_copy):
    sqlite_exec(store_copy, "DROP TABLE firings")
    with pytest.raises(StoreContractError, match="missing required table"):
        Store(store_copy)


def test_rejects_missing_column(store_copy):
    sqlite_exec(store_copy, "ALTER TABLE takeaways DROP COLUMN one_liner")
    with pytest.raises(StoreContractError, match="missing required column"):
        Store(store_copy)


@pytest.mark.skip(reason="Dolt-only: enum domains are not in SQLite type strings; "
                          "enforced via CHECK constraints at write time")
def test_rejects_changed_enum_domain(store_copy):
    pass


def test_tolerates_additive_column(store_copy):
    sqlite_exec(store_copy, "ALTER TABLE takeaways ADD COLUMN confidence REAL")
    assert len(Store(store_copy).takeaways()) == 7


def test_rejects_orphan_firing(store_copy):
    sqlite_exec(store_copy,
                "INSERT INTO firings (takeaway_id, fired_at) "
                "VALUES (999, datetime('now'))")
    with pytest.raises(StoreContractError, match="missing takeaways"):
        Store(store_copy).firings()


def test_firing_eligibility(canonical_store):
    from monition.store import FIRING_ELIGIBLE
    assert FIRING_ELIGIBLE == ("active",)
    by_id = {t.id: t for t in Store(canonical_store).takeaways()}
    assert by_id[3].firing_eligible  # mirror candidate: candidacy never mutes
    assert by_id[6].firing_eligible  # mirrored: same
    assert not by_id[5].firing_eligible  # retired


@pytest.mark.skip(reason="Dolt-only: v1 dialect detection uses MySQL DESCRIBE type "
                          "strings; SQLite stores are always created at v5")
def test_rejects_v1_dialect_with_migrate_message(store_copy):
    pass
