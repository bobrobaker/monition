"""Lever-3 audit tests: batched decision writes must be byte-equivalent to the
old per-hit inline writes, and the batch write must stay fail-open."""
import io
import json
import os
import shutil
import sqlite3

import pytest

import monition.embed as me
import monition.hooks as mh
from monition.store_write import WriteStore

from .conftest import SCHEMA, build_store


def _decisions(store_path):
    db = os.path.join(store_path, "store.db")
    with sqlite3.connect(db) as c:
        c.row_factory = sqlite3.Row
        return [dict(r) for r in c.execute(
            "SELECT takeaway_id, session_id, decision, evidence_count, cold_start,"
            " ev_score FROM decisions ORDER BY takeaway_id, session_id, id"
        )]


# --- Unit: write_decisions(batch) == repeated write_decision, incl. NULL ev_score ---

def test_batch_matches_per_row(tmp_path):
    rows = [
        (1, "s", "fire", 0, True, None),       # cold-start: NULL ev_score
        (2, "s", "suppress", 4, False, 0.25),  # evidence suppress
        (3, "s", "fire", 4, False, 0.75),      # evidence fire
    ]
    per = build_store(str(tmp_path / "per"), [SCHEMA])
    bat = build_store(str(tmp_path / "bat"), [SCHEMA])
    ws_per, ws_bat = WriteStore(per), WriteStore(bat)
    for r in rows:
        ws_per.write_decision(*r)
    ws_bat.write_decisions(rows)
    assert _decisions(per) == _decisions(bat)
    assert _decisions(bat)[0]["ev_score"] is None          # NULL preserved
    assert _decisions(bat)[1]["ev_score"] == pytest.approx(0.25)


def test_write_decisions_empty_is_noop(tmp_path):
    s = build_store(str(tmp_path / "s"), [SCHEMA])
    WriteStore(s).write_decisions([])
    assert _decisions(s) == []


# --- Integration: a multi-hit prompt writes a decision row per scored hit ---
# (fire AND suppress), firings only for fired hits.

ROWS = """
INSERT INTO takeaways (id, created, kind, trigger_kind, trigger_spec, one_liner, status, reach) VALUES
  (40,'2026-01-01 10:00:00','gotcha','on_demand','alpha','fire-cold','active','general'),
  (41,'2026-01-01 10:00:00','gotcha','on_demand','beta', 'suppress', 'active','general'),
  (42,'2026-01-01 10:00:00','gotcha','on_demand','gamma','fire-evid','active','general');
INSERT INTO firings (takeaway_id, fired_at, session_id, trigger_kind, outcome) VALUES
  (41,'2026-01-02 10:00:00','ev','on_demand','noise'),
  (41,'2026-01-02 10:00:01','ev','on_demand','noise'),
  (41,'2026-01-02 10:00:02','ev','on_demand','noise'),
  (42,'2026-01-02 10:00:00','ev','on_demand','helpful'),
  (42,'2026-01-02 10:00:01','ev','on_demand','helpful'),
  (42,'2026-01-02 10:00:02','ev','on_demand','helpful');
"""


@pytest.fixture
def host_repo(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    store = build_store(str(repo / "store"), [SCHEMA, ROWS])
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    monkeypatch.setenv("MONITION_STORE", store)
    monkeypatch.setattr(me, "semantic_scores", lambda q, texts: [0.0] * len(texts))
    return str(repo), store


def _feed(fn, data):
    import sys
    cap = io.StringIO()
    oi, oo = sys.stdin, sys.stdout
    sys.stdin, sys.stdout = io.StringIO(json.dumps(data)), cap
    try:
        fn()
    finally:
        sys.stdin, sys.stdout = oi, oo
    return cap.getvalue()


def test_disclose_batches_fire_and_suppress(host_repo):
    _repo, store = host_repo
    out = _feed(mh.prompt_hook, {"session_id": "p1", "prompt": "alpha beta gamma"})
    # injection carries only the two fired takeaways
    ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert "[t40/" in ctx and "[t42/" in ctx and "[t41/" not in ctx
    # a decision row exists for EVERY scored hit — including the suppressed one
    decs = {d["takeaway_id"]: d["decision"] for d in _decisions(store)}
    assert decs == {40: "fire", 41: "suppress", 42: "fire"}
    # firings only for the fired hits
    with sqlite3.connect(os.path.join(store, "store.db")) as c:
        fired = {r[0] for r in c.execute(
            "SELECT takeaway_id FROM firings WHERE session_id='p1'")}
    assert fired == {40, 42}


def test_batch_write_failure_is_fail_open(host_repo, monkeypatch):
    """If the batched decision write throws, the disclosure must STILL be emitted."""
    _repo, store = host_repo

    def boom(self, rows):
        raise RuntimeError("simulated dolt write failure")

    monkeypatch.setattr(WriteStore, "write_decisions", boom)
    out = _feed(mh.prompt_hook, {"session_id": "p2", "prompt": "alpha beta gamma"})
    assert out.strip(), "disclosure was lost when the decision write failed"
    ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert "[t40/" in ctx and "[t42/" in ctx
