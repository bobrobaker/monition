"""Tests for monition tune: threshold recommendation and CLI."""
import pytest

from monition.metrics import decision_quality, tune_recommendation, DecisionQuality
from monition.report import render_tune
from monition.store import Store


def _make_decision(id_, tid, decision, evidence_count, cold_start, ev_score=None):
    from monition.store import Decision
    from datetime import datetime
    return Decision(
        id=id_, takeaway_id=tid, session_id="s",
        decided_at=datetime(2026, 1, 1), decision=decision,
        evidence_count=evidence_count, cold_start=cold_start, ev_score=ev_score,
    )


def test_tune_recommendation_no_decisions():
    dq = decision_quality([])
    rec = tune_recommendation(dq)
    assert "no decisions" in rec


def test_tune_recommendation_insufficient_data():
    decisions = [_make_decision(i, 1, "fire", 3, False, 0.8) for i in range(5)]
    dq = decision_quality(decisions)
    rec = tune_recommendation(dq)
    assert "insufficient" in rec
    assert "5" in rec


def test_tune_recommendation_no_suppressions():
    decisions = [_make_decision(i, 1, "fire", 5, False, 0.8) for i in range(15)]
    dq = decision_quality(decisions)
    assert dq.suppress_count == 0
    rec = tune_recommendation(dq)
    assert "no suppressions" in rec or "N_COLD_START" in rec


def test_tune_recommendation_well_calibrated():
    fires = [_make_decision(i, 1, "fire", 5, False, 0.8) for i in range(8)]
    suppresses = [_make_decision(10 + i, 2, "suppress", 5, False, 0.45) for i in range(7)]
    dq = decision_quality(fires + suppresses)
    assert dq.sufficient_data
    rec = tune_recommendation(dq, ev_threshold=0.5)
    assert "threshold" in rec.lower() or "well" in rec.lower() or "suppressed" in rec


def test_render_tune_no_decisions(canonical_store):
    # canonical_store has 3 decisions — just verify render completes without error
    store = Store(canonical_store)
    output = render_tune(store)
    assert "monition tune" in output
    assert "Decisions:" in output
    assert "Noise saved" in output
    assert "Recommendation:" in output


def test_render_tune_shows_counts(canonical_store):
    store = Store(canonical_store)
    output = render_tune(store)
    assert "3 total" in output
    assert "1 cold-start" in output
    assert "2 evidence-based" in output
    assert "1 suppressed" in output
