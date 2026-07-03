"""Tests for Store.decisions() read-back and decision_quality metrics."""
import pytest

from monition.store import Store, StoreContractError
from monition.metrics import decision_quality, DecisionQuality
from monition.store_write import WriteStore


def test_decisions_returns_three_rows(canonical_store):
    store = Store(canonical_store)
    decisions = store.decisions()
    assert len(decisions) == 3


def test_decisions_cold_start_has_null_ev_score(canonical_store):
    store = Store(canonical_store)
    decisions = store.decisions()
    cold = [d for d in decisions if d.cold_start]
    assert len(cold) == 1
    assert cold[0].ev_score is None


def test_decisions_evidence_based_have_ev_score(canonical_store):
    store = Store(canonical_store)
    decisions = store.decisions()
    evidence = [d for d in decisions if not d.cold_start]
    assert len(evidence) == 2
    assert all(d.ev_score is not None for d in evidence)


def test_decisions_field_types(canonical_store):
    store = Store(canonical_store)
    d = store.decisions()[0]
    assert isinstance(d.id, int)
    assert isinstance(d.takeaway_id, int)
    assert isinstance(d.evidence_count, int)
    assert isinstance(d.cold_start, bool)
    assert d.decision in ("fire", "suppress")


def test_decisions_cold_start_survives_stringified_scalars(canonical_store, monkeypatch):
    """Dolt's CLI-JSON-through-server shape stringifies every scalar, including
    tinyint booleans (storage_backends._wire_norm_row: "int / Decimal — CLI
    emits these as strings"). bool("0") is True in Python, so an un-cast
    bool(r["cold_start"]) misclassified every decision row as cold-start
    regardless of its real value (the reported bug: `monition report`/`tune`
    permanently showed 100% cold-start against the live Dolt hub).

    Reproduces the shape directly over a real backend's rows rather than
    depending on a live resident dolt sql-server, whose stringification only
    kicks in once it's actually mediating the query — a timing-dependent
    condition unsuited to a deterministic test."""
    store = Store(canonical_store)
    real_execute = store._backend.execute_sql

    def stringify_cold_start(sql):
        rows = real_execute(sql)
        if "FROM decisions" not in sql:
            return rows
        return [{**r, "cold_start": str(r["cold_start"])} for r in rows]

    monkeypatch.setattr(store._backend, "execute_sql", stringify_cold_start)
    decisions = store.decisions()
    # Ground truth (conftest ROWS, in ORDER BY id): d1 cold_start=1, d2/d3 cold_start=0.
    assert [d.cold_start for d in decisions] == [True, False, False]
    assert all(isinstance(d.cold_start, bool) for d in decisions)


def test_decisions_orphan_raises(store_copy):
    ws = WriteStore(store_copy)
    ws._sql(
        "INSERT INTO decisions (takeaway_id, decided_at, decision, evidence_count,"
        " cold_start) VALUES (99, NOW(), 'fire', 0, 1)"
    )
    with pytest.raises(StoreContractError, match="decisions reference missing"):
        Store(store_copy).decisions()


def test_decision_quality_counts(canonical_store):
    decisions = Store(canonical_store).decisions()
    dq = decision_quality(decisions)
    assert dq.total == 3
    assert dq.cold_start_count == 1
    assert dq.evidence_based_count == 2
    assert dq.suppress_count == 1


def test_decision_quality_noise_saved_pct(canonical_store):
    decisions = Store(canonical_store).decisions()
    dq = decision_quality(decisions)
    # 1 suppress out of 3 total = 33.3%
    assert abs(dq.noise_saved_pct - 1 / 3) < 0.001


def test_decision_quality_avg_ev_scores(canonical_store):
    decisions = Store(canonical_store).decisions()
    dq = decision_quality(decisions)
    assert dq.avg_ev_score_suppressed == pytest.approx(0.0)
    assert dq.avg_ev_score_fired == pytest.approx(0.5)


def test_decision_quality_empty():
    dq = decision_quality([])
    assert dq.total == 0
    assert dq.noise_saved_pct == 0.0
    assert not dq.sufficient_data


def test_decision_quality_insufficient_data(canonical_store):
    # 2 evidence-based decisions < 10 threshold
    decisions = Store(canonical_store).decisions()
    dq = decision_quality(decisions)
    assert not dq.sufficient_data
