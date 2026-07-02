"""Tests for WriteStore.on_demand_match() — keyword-based on_demand retrieval.

These tests pin the *lexical* contract, so the semantic pass is forced off:
with the embed extra installed, a real model would legitimately add hits.
Hybrid behavior is covered in test_embed.py; the injection cap in
test_injection_cap.py.
"""
import json

import pytest

import monition.embed as me
from monition.store_write import WriteStore


@pytest.fixture(autouse=True)
def lexical_only(monkeypatch):
    monkeypatch.setattr(me, "semantic_scores", lambda q, texts: [0.0] * len(texts))


def _hits(ws, *args, **kwargs):
    return json.loads(ws.on_demand_match(*args, **kwargs))["hits"]


def test_match_returns_keyword_hit(canonical_store):
    ws = WriteStore(canonical_store)
    hits = _hits(ws, "database migration")
    assert any(h["id"] == 7 for h in hits)


def test_match_case_insensitive(canonical_store):
    ws = WriteStore(canonical_store)
    hits = _hits(ws, "MIGRATION path")
    assert any(h["id"] == 7 for h in hits)


def test_match_no_hit(canonical_store):
    ws = WriteStore(canonical_store)
    res = json.loads(ws.on_demand_match("deployment rollback"))
    assert res == {"hits": [], "capped": 0}


def test_match_second_keyword(canonical_store):
    """Matches via the second keyword in a comma-separated spec."""
    ws = WriteStore(canonical_store)
    hits = _hits(ws, "schema change")
    assert any(h["id"] == 7 for h in hits)


def test_match_hit_shape_carries_evidence(canonical_store):
    """v7: hits carry id, one_liner, and the lossless match evidence."""
    ws = WriteStore(canonical_store)
    hits = _hits(ws, "migration")
    assert hits
    h = hits[0]
    assert set(h.keys()) == {"id", "one_liner", "evidence"}
    ev = h["evidence"]
    assert ev["module"] == "lexical"
    assert ev["keyword"] and ev["keyword"].lower() in "migration"
    assert ev["query"] == "migration"  # the full query, never truncated


def test_fire_stores_match_evidence(store_copy):
    """v7: the evidence dict from the matcher lands losslessly in
    firings.match_evidence as JSON. (store_copy: this test writes a firing.)"""
    ws = WriteStore(store_copy)
    h = _hits(ws, "migration")[0]
    ws.fire(str(h["id"]), "on_demand", "s-ev", "migration",
            evidence=h["evidence"])
    firing = ws.firings()[-1]
    assert json.loads(firing.match_evidence) == h["evidence"]


def test_edit_path_match_evidence_names_pattern(canonical_store):
    """v7: an edit_path hit records which glob pattern hit, on which path."""
    ws = WriteStore(canonical_store)
    hits = json.loads(ws.match("src/anything.py"))
    assert hits
    ev = hits[0]["evidence"]
    assert ev["module"] == "glob"
    assert ev["path"] == "src/anything.py"
    assert ev["pattern"] in (hits[0].get("trigger_spec") or "")


def test_match_lexical_hits_never_capped(canonical_store):
    """Lexical hits are exempt from the injection cap by design."""
    ws = WriteStore(canonical_store)
    res = json.loads(ws.on_demand_match("database migration"))
    assert res["capped"] == 0


def test_match_session_dedup(store_copy):
    """Row fired once in a session is excluded from on_demand_match."""
    ws = WriteStore(store_copy)
    ws.fire("7", "on_demand", session="s_dedup", context="migration")
    hits = _hits(ws, "migration", session="s_dedup")
    assert not any(h["id"] == 7 for h in hits)


def test_match_no_session_no_dedup(store_copy):
    """Without a session, fired rows are not excluded."""
    ws = WriteStore(store_copy)
    ws.fire("7", "on_demand", session="s_other", context="migration")
    hits = _hits(ws, "migration", session=None)
    assert any(h["id"] == 7 for h in hits)


def test_match_edit_path_rows_excluded(canonical_store):
    """edit_path and session_start rows do not appear in on_demand results."""
    ws = WriteStore(canonical_store)
    hits = _hits(ws, "all noise")
    assert all(h["id"] == 7 for h in hits) or hits == []
