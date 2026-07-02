"""B03: per-row semantic threshold — module read path, the narrow
set_threshold verb (mutations provenance), and the calibrate proposal/gate
math, all with a stubbed embedding scorer keyed on the query string."""
import json

import pytest

import monition.embed as me
from monition.calibrate import apply as cal_apply, gate, propose
from monition.store import Store, StoreContractError
from monition.store_write import WriteStore

from .conftest import sqlite_exec

# Situations avoid the t7 keywords ('migration', 'schema') so the lexical
# module never claims them; scores are deterministic per situation text.
SCORES = {
    "helpful high": 0.80,
    "helpful low": 0.72,
    "noise mid": 0.65,
    "noise low": 0.61,
    "noise high": 0.90,
    "holdout noise": 0.65,
}


@pytest.fixture(autouse=True)
def stub_scores(monkeypatch):
    monkeypatch.setattr(
        me, "semantic_scores",
        lambda q, texts: [SCORES.get(q, 0.0)] * len(texts))


def _seed_rated_history(store):
    """Five rated situation-bearing on_demand firings for t7, time-ordered so
    the 70% split puts the first four in calibration."""
    rows = [
        ("2026-01-02 10:00:00", "helpful", "helpful high"),
        ("2026-01-03 10:00:00", "helpful", "helpful low"),
        ("2026-01-04 10:00:00", "noise", "noise mid"),
        ("2026-01-05 10:00:00", "noise", "noise low"),
        ("2026-01-06 10:00:00", "noise", "holdout noise"),
    ]
    values = ",".join(
        f"(7, '{at}', 's_cal', 'on_demand', '{out}', '{sit}')"
        for at, out, sit in rows)
    sqlite_exec(store, (
        "INSERT INTO firings (takeaway_id, fired_at, session_id,"
        f" trigger_kind, outcome, situation) VALUES {values};"))


def test_semantic_rank_respects_per_row_threshold(store_copy):
    ws = WriteStore(store_copy)
    hits = json.loads(ws.on_demand_match("noise high"))["hits"]
    assert [h["id"] for h in hits] == [7]  # 0.90 >= global 0.6

    ws.set_threshold(7, 0.95)
    hits = json.loads(ws.on_demand_match("noise high"))["hits"]
    assert hits == []  # 0.90 < per-row 0.95

    ws.set_threshold(7, None)
    hits = json.loads(ws.on_demand_match("noise high"))["hits"]
    assert [h["id"] for h in hits] == [7]  # cleared -> global again


def test_set_threshold_writes_mutation_provenance(store_copy):
    ws = WriteStore(store_copy)
    msg = ws.set_threshold("t7", 0.75, source="test-run")
    assert "mutation logged" in msg
    assert {t.id: t for t in ws.takeaways()}[7].sem_threshold == 0.75

    ws.set_threshold(7, 0.8)
    ws.set_threshold(7, None)
    muts = ws.mutations()
    assert [m.verb for m in muts] == ["tune", "tune", "tune"]
    assert [json.loads(m.changes)["sem_threshold"] for m in muts] == [
        {"old": None, "new": 0.75},
        {"old": 0.75, "new": 0.8},
        {"old": 0.8, "new": None},
    ]
    assert muts[0].source == "test-run"
    assert all(m.takeaway_id == 7 for m in muts)


def test_set_threshold_guards(store_copy):
    ws = WriteStore(store_copy)
    with pytest.raises(StoreContractError, match=r"\[0,1\]"):
        ws.set_threshold(7, 1.5)
    with pytest.raises(StoreContractError, match="on_demand semantic module"):
        ws.set_threshold(1, 0.7)  # t1 is edit_path
    with pytest.raises(StoreContractError, match="no takeaway"):
        ws.set_threshold(999, 0.7)
    assert ws.mutations() == []  # refused writes leave no provenance


def test_propose_math(store_copy):
    _seed_rated_history(store_copy)
    props = propose(Store(store_copy))
    assert len(props) == 1
    p = props[0]
    assert p["takeaway_id"] == 7
    # theta = max(0.6, min helpful 0.72); suppresses 0.65, 0.65, 0.61 — not 0.90
    assert p["proposed"] == 0.72
    assert p["current"] == 0.6
    assert p["n_semantic"] == 5 and p["n_lexical"] == 0
    assert p["n_helpful_semantic"] == 2 and p["n_noise_semantic"] == 3
    assert p["noise_suppressed"] == 3
    assert p["min_helpful_score"] == 0.72


def test_propose_skips_below_rating_floor(store_copy):
    sqlite_exec(store_copy, (
        "INSERT INTO firings (takeaway_id, fired_at, session_id,"
        " trigger_kind, outcome, situation) VALUES"
        " (7, '2026-01-02 10:00:00', 's', 'on_demand', 'noise', 'noise mid'),"
        " (7, '2026-01-03 10:00:00', 's', 'on_demand', 'helpful', 'helpful high');"))
    assert propose(Store(store_copy)) == []  # 2 < MIN_RATINGS


def test_gate_math(store_copy):
    _seed_rated_history(store_copy)
    g = gate(Store(store_copy))
    assert g["rows_proposed"] == 1
    row = g["per_row"][0]
    # cal = first 4 (theta from helpful 0.80/0.72 -> 0.72, suppresses 2);
    # holdout = 1 noise at 0.65: baseline fires it, theta suppresses it.
    assert row["theta"] == 0.72 and row["cal_n"] == 4 and row["eval_n"] == 1
    assert g["holdout_noise"] == 1 and g["noise_suppressed"] == 1
    assert g["holdout_helpful"] == 0 and g["helpful_lost"] == 0
    assert g["noise_reduction"] == 1.0
    assert g["pass"] is True


def test_apply_is_recomputed_and_actuates(store_copy):
    _seed_rated_history(store_copy)
    ws = WriteStore(store_copy)
    msg = cal_apply(ws, 7)
    assert "0.72" in msg
    assert {t.id: t for t in ws.takeaways()}[7].sem_threshold == 0.72
    muts = ws.mutations()
    assert len(muts) == 1 and muts[0].verb == "tune"
    assert "calibrate:" in muts[0].source
    # production actuation: the 0.65-scoring situation no longer fires
    hits = json.loads(ws.on_demand_match("noise mid"))["hits"]
    assert hits == []
    hits = json.loads(ws.on_demand_match("helpful high"))["hits"]
    assert [h["id"] for h in hits] == [7]


def test_apply_without_proposal_refuses(store_copy):
    ws = WriteStore(store_copy)
    with pytest.raises(StoreContractError, match="no current calibrate proposal"):
        cal_apply(ws, 7)
    assert ws.mutations() == []
