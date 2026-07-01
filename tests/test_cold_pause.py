"""Cold-pause: unrated rows must not fire forever.

The plain cold-start rule (evidence < N_COLD_START -> fire) let a never-rated
row fire unboundedly. A row with N_UNRATED_PAUSE+ lifetime firings and ZERO
ratings is suppressed (reason "cold-pause") until any rating arrives. Pausing
does not starve the rating path: ratings arrive at mine time via
`export-firings` over the firings already logged, and `--order-by priority`
ranks a cold-paused row at the head of the worklist.
"""
import io
import json
import os
import shutil

import pytest

import monition.embed as me
import monition.score as sc
from monition.export import export_records
from monition.hooks import prompt_hook
from monition.score import score
from monition.store import Store
from monition.store_write import WriteStore


@pytest.fixture(autouse=True)
def isolated_state(monkeypatch, tmp_path_factory):
    monkeypatch.setenv(
        "XDG_STATE_HOME", str(tmp_path_factory.mktemp("state")))


@pytest.fixture(autouse=True)
def lexical_only(monkeypatch):
    monkeypatch.setattr(me, "semantic_scores",
                        lambda q, texts: [0.0] * len(texts))


def _seed_unrated_row(ws, n_firings, spec="coldpause"):
    tid = int(ws.add("gotcha", "on_demand", f"never rated {spec} row",
                     spec).split()[-1])
    for i in range(n_firings):
        ws.fire(str(tid), "on_demand", session=f"cp{i}")
    return tid


def test_cold_pause_at_threshold(store_copy):
    ws = WriteStore(store_copy)
    tid = _seed_unrated_row(ws, sc.N_UNRATED_PAUSE)
    result = score(tid, store_copy)
    assert result["decision"] == "suppress"
    assert result["reason"] == "cold-pause"
    assert result["cold_start"] is True
    assert result["evidence_count"] == 0
    assert result["ev_score"] is None


def test_below_threshold_still_fires(store_copy):
    ws = WriteStore(store_copy)
    tid = _seed_unrated_row(ws, sc.N_UNRATED_PAUSE - 1)
    result = score(tid, store_copy)
    assert result["decision"] == "fire"
    assert result["reason"] is None


def test_any_rating_lifts_the_pause(store_copy):
    """One rating — even 'noise' — moves the row back to plain cold start."""
    ws = WriteStore(store_copy)
    tid = _seed_unrated_row(ws, sc.N_UNRATED_PAUSE)
    fid = next(f.id for f in ws.firings() if f.takeaway_id == tid)
    ws.rate(str(fid), "noise")
    result = score(tid, store_copy)
    assert result["decision"] == "fire"
    assert result["cold_start"] is True
    assert result["evidence_count"] == 1


def test_cold_pause_decision_row_signature(store_copy):
    """The stored row is suppress + cold_start=1 + evidence 0 — a combination
    no other scoring path writes, so it stays queryable without widening the
    decision enum."""
    ws = WriteStore(store_copy)
    tid = _seed_unrated_row(ws, sc.N_UNRATED_PAUSE)
    score(tid, store_copy, session_id="s_pause")
    rows = ws._sql(f"SELECT * FROM decisions WHERE takeaway_id = {tid}"
                   " AND session_id = 's_pause'")
    assert len(rows) == 1
    assert rows[0]["decision"] == "suppress"
    assert rows[0]["cold_start"] == 1
    assert rows[0]["evidence_count"] == 0


def test_prompt_hook_suppresses_cold_paused_row(store_copy, tmp_path,
                                                monkeypatch, capsys):
    """End to end: the disclosure path skips a cold-paused row."""
    root = tmp_path / "hostrepo"
    os.makedirs(root)
    shutil.move(str(store_copy), str(root / "monition"))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    ws = WriteStore(os.path.join(str(root), "monition"))
    _seed_unrated_row(ws, sc.N_UNRATED_PAUSE)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(
        {"session_id": "cp_hook", "prompt": "tell me about coldpause"})))
    prompt_hook()
    assert capsys.readouterr().out == ""  # matched, scored, cold-paused


def test_priority_worklist_surfaces_cold_paused_row(store_copy):
    """`export-firings --order-by priority` ranks the paused row first:
    rated_count 0 -> boundary closeness 1.0 x the highest traffic in the
    store, so its already-logged firings get rated next."""
    ws = WriteStore(store_copy)
    tid = _seed_unrated_row(ws, sc.N_UNRATED_PAUSE)
    records = export_records(Store(store_copy), order_by="priority")
    assert records[0]["takeaway_id"] == tid
    assert records[0]["rating_priority"] == float(sc.N_UNRATED_PAUSE)
