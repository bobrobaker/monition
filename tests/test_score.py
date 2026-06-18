"""Tests for monition.score.

Fixture ground truth (from conftest.py):
  t1: 2 rated firings — both noise      (ev=0.0 with 2 evidence)
  t2: 2 rated (1 helpful, 1 noise) + 1 unrated
  t3: 0 firings
  t4: 2 unrated firings                  (0 rated → cold start)
  t6: 1 rated firing — helpful           (ev=1.0 with 1 evidence)

Cold-start tests use the default N_COLD_START=3 (all fixture takeaways qualify).
Evidence-based tests monkeypatch N_COLD_START to trigger evidence paths.
"""
import monition.score as sc
from monition.score import score
from monition.store_write import WriteStore


def test_score_cold_start_no_rated(store_copy):
    """t4 has 0 rated firings → cold-start fire."""
    result = score(4, store_copy, session_id="s_test")
    assert result["decision"] == "fire"
    assert result["cold_start"] is True
    assert result["evidence_count"] == 0
    assert result["ev_score"] is None


def test_score_cold_start_some_rated(store_copy):
    """t1 has 2 rated firings but < N_COLD_START=3 → cold-start fire."""
    result = score(1, store_copy)
    assert result["decision"] == "fire"
    assert result["cold_start"] is True
    assert result["evidence_count"] == 2
    assert result["ev_score"] is None


def test_score_suppress_on_low_precision(store_copy, monkeypatch):
    """t1: all-noise evidence, N_COLD_START=2 → evidence-based suppress."""
    monkeypatch.setattr(sc, "N_COLD_START", 2)
    result = score(1, store_copy)
    assert result["decision"] == "suppress"
    assert result["cold_start"] is False
    assert result["evidence_count"] == 2
    assert result["ev_score"] == 0.0


def test_score_fire_on_high_precision(store_copy, monkeypatch):
    """t6: 1 helpful firing, N_COLD_START=1 → evidence-based fire."""
    monkeypatch.setattr(sc, "N_COLD_START", 1)
    result = score(6, store_copy)
    assert result["decision"] == "fire"
    assert result["cold_start"] is False
    assert result["evidence_count"] == 1
    assert result["ev_score"] == 1.0


def test_score_writes_decision_row(store_copy, monkeypatch):
    """Each score() call produces exactly one decisions row with correct fields."""
    monkeypatch.setattr(sc, "N_COLD_START", 2)
    score(1, store_copy, session_id="s_audit")  # t1: suppress
    ws = WriteStore(store_copy)
    rows = ws._sql("SELECT * FROM decisions WHERE takeaway_id = 1 AND session_id = 's_audit'")
    assert len(rows) == 1
    r = rows[0]
    assert r["decision"] == "suppress"
    assert r["cold_start"] == 0
    assert r["evidence_count"] == 2
    assert r["session_id"] == "s_audit"
    assert r["ev_score"] is not None


def test_score_cold_start_row_has_null_ev(store_copy):
    """Cold-start decision rows have NULL ev_score."""
    score(4, store_copy, session_id="s_cold")
    ws = WriteStore(store_copy)
    rows = ws._sql("SELECT * FROM decisions WHERE takeaway_id = 4 AND session_id = 's_cold'")
    assert len(rows) == 1
    assert rows[0]["cold_start"] == 1
    assert rows[0].get("ev_score") is None  # Dolt omits NULL columns from JSON
