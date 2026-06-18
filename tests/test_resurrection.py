"""Phase 4 — suppression resurrection.

`monition add` runs the similarity matcher against currently-suppressed rows
before inserting; a near-match is the harvested natural counterfactual that the
suppression was wrong. 'Suppressed' is computed (latest `decisions` row =
suppress), not a takeaway status. These tests pin detection (embedding + lexical
fail-open), the suppressed-only candidate filter, the three consent-gate
resolutions, and the CLI detect-and-refuse (exit 3).
"""
import monition.embed as me
from monition.cli import main
from monition.score import score
from monition.store_write import WriteStore


def _add_suppressed(ws, one_liner, full_content=None):
    """Insert a takeaway and mark its latest decision 'suppress'."""
    tid = int(ws.add("gotcha", "edit_path", one_liner, "x/*", full_content).split()[-1])
    ws.write_decision(tid, "s", "suppress", 4, False, 0.25)
    return tid


# --- detection (embedding path) -------------------------------------------

def test_embedding_detects_near_match(store_copy, monkeypatch):
    ws = WriteStore(store_copy)
    tid = _add_suppressed(ws, "dolt migration needs an explicit schema bump")
    monkeypatch.setattr(me, "semantic_scores",
                        lambda q, texts: [0.95 if "migration" in t else 0.0 for t in texts])
    matches = ws.find_resurrection("remember to bump schema on dolt migration")
    assert [m["id"] for m in matches] == [tid]
    m = matches[0]
    assert m["evidence_count"] == 4 and m["ev_score"] == 0.25 and m["similarity"] == 0.95


def test_embedding_below_threshold_no_match(store_copy, monkeypatch):
    ws = WriteStore(store_copy)
    _add_suppressed(ws, "dolt migration needs an explicit schema bump")
    monkeypatch.setattr(me, "semantic_scores", lambda q, texts: [0.1] * len(texts))
    assert ws.find_resurrection("unrelated lesson about retry backoff") == []


# --- detection (lexical fail-open) ----------------------------------------

def test_lexical_fallback_when_embed_unavailable(store_copy, monkeypatch):
    ws = WriteStore(store_copy)
    tid = _add_suppressed(ws, "dolt migration needs an explicit schema bump")

    def boom(q, texts):
        raise RuntimeError("no embed extra installed")

    monkeypatch.setattr(me, "semantic_scores", boom)
    # near-duplicate wording -> high Jaccard over content tokens
    hits = ws.find_resurrection("explicit schema bump needed for dolt migration")
    assert tid in [m["id"] for m in hits]
    # disjoint wording -> no match
    assert ws.find_resurrection("retry backoff on flaky network calls") == []


# --- candidate filter ------------------------------------------------------

def test_only_suppressed_rows_are_candidates(store_copy, monkeypatch):
    """A near-match to a row the scorer is FIRING is not a resurrection."""
    ws = WriteStore(store_copy)
    tid = int(ws.add("gotcha", "edit_path", "fires fine lesson", "y/*").split()[-1])
    ws.write_decision(tid, "s", "fire", 4, False, 0.9)
    monkeypatch.setattr(me, "semantic_scores", lambda q, texts: [0.99] * len(texts))
    assert tid not in [m["id"] for m in ws.find_resurrection("fires fine lesson")]


def test_no_decisions_means_no_resurrection(store_copy, monkeypatch):
    """Rows never scored have no suppress decision and are never candidates."""
    ws = WriteStore(store_copy)
    monkeypatch.setattr(me, "semantic_scores", lambda q, texts: [0.99] * len(texts))
    tid = int(ws.add("gotcha", "edit_path", "never scored", "n/*").split()[-1])
    assert tid not in [m["id"] for m in ws.find_resurrection("never scored")]


# --- consent-gate resolutions ---------------------------------------------

def test_resolve_new_creates_row(store_copy):
    ws = WriteStore(store_copy)
    before = len(ws.takeaways())
    msg = ws.resolve_add("new", "gotcha", "edit_path", "brand new", "z/*")
    assert "added takeaway" in msg
    assert len(ws.takeaways()) == before + 1


def test_resolve_log_helpful_revives(store_copy):
    ws = WriteStore(store_copy)
    tid = _add_suppressed(ws, "lesson to revive")
    msg = ws.resolve_add(f"log-helpful:t{tid}", "gotcha", "edit_path",
                         "lesson to revive", "z/*")
    assert f"revived takeaway t{tid}" in msg
    fs = [f for f in ws.firings() if f.takeaway_id == tid]
    assert any(f.outcome == "helpful" and f.trigger_kind == "resurrection" for f in fs)


def test_log_helpful_lifts_score_above_threshold(store_copy):
    """The revive is real: re-scoring after log-helpful flips suppress -> fire."""
    ws = WriteStore(store_copy)
    tid = int(ws.add("gotcha", "edit_path", "borderline lesson", "b/*").split()[-1])
    for ctx, outcome in [("a", "helpful"), ("b", "noise"), ("c", "noise")]:
        fid = int(ws.fire(tid, "edit_path", context=ctx).split()[-1])
        ws.rate(fid, outcome)
    assert score(tid, store_copy)["decision"] == "suppress"   # 1/3 = 0.33
    ws.log_helpful_equivalent(tid, context="re-learned")      # -> 2/4 = 0.5
    assert score(tid, store_copy)["decision"] == "fire"


def test_resolve_merge_folds_content_no_duplicate(store_copy):
    ws = WriteStore(store_copy)
    tid = _add_suppressed(ws, "merge target", "original body")
    before = len(ws.takeaways())
    msg = ws.resolve_add(f"merge:t{tid}", "gotcha", "edit_path",
                         "the re-learned wording", "z/*", "extra detail")
    assert f"merged into takeaway t{tid}" in msg
    assert len(ws.takeaways()) == before          # no duplicate row
    body = next(t.full_content for t in ws.takeaways() if t.id == tid)
    assert "re-learned wording" in body and "original body" in body


def test_resolve_missing_target_is_rejected(store_copy):
    import pytest
    from monition.store import StoreContractError
    ws = WriteStore(store_copy)
    with pytest.raises(StoreContractError):
        ws.resolve_add("merge", "gotcha", "edit_path", "x", "z/*")


# --- CLI detect-and-refuse -------------------------------------------------

def test_cli_add_refuses_on_resurrection(store_copy, monkeypatch, capsys):
    monkeypatch.setattr(me, "semantic_scores", lambda q, texts: [0.99] * len(texts))
    code = main(["add", "--kind", "gotcha", "--trigger-kind", "edit_path",
                 "--one-liner", "all noise again", "--store", store_copy])
    assert code == 3
    out = capsys.readouterr().out
    assert "RESURRECTION" in out and "--resolve" in out


def test_cli_add_resolve_new_succeeds(store_copy, monkeypatch, capsys):
    monkeypatch.setattr(me, "semantic_scores", lambda q, texts: [0.99] * len(texts))
    code = main(["add", "--kind", "gotcha", "--trigger-kind", "edit_path",
                 "--one-liner", "all noise again", "--resolve", "new",
                 "--store", store_copy])
    assert code == 0
    assert "added takeaway" in capsys.readouterr().out


def test_cli_add_no_match_inserts_normally(store_copy, monkeypatch, capsys):
    monkeypatch.setattr(me, "semantic_scores", lambda q, texts: [0.0] * len(texts))
    code = main(["add", "--kind", "gotcha", "--trigger-kind", "edit_path",
                 "--one-liner", "wholly unrelated new lesson", "--store", store_copy])
    assert code == 0
    assert "added takeaway" in capsys.readouterr().out
