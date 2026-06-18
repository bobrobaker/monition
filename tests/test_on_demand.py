"""Tests for WriteStore.on_demand_match() — keyword-based on_demand retrieval.

These tests pin the *lexical* contract, so the semantic pass is forced off:
with the embed extra installed, a real model would legitimately add hits.
Hybrid behavior is covered in test_embed.py.
"""
import json

import pytest

import monition.embed as me
from monition.store_write import WriteStore


@pytest.fixture(autouse=True)
def lexical_only(monkeypatch):
    monkeypatch.setattr(me, "semantic_scores", lambda q, texts: [0.0] * len(texts))


def test_match_returns_keyword_hit(canonical_store):
    ws = WriteStore(canonical_store)
    hits = json.loads(ws.on_demand_match("database migration"))
    assert any(h["id"] == 7 for h in hits)


def test_match_case_insensitive(canonical_store):
    ws = WriteStore(canonical_store)
    hits = json.loads(ws.on_demand_match("MIGRATION path"))
    assert any(h["id"] == 7 for h in hits)


def test_match_no_hit(canonical_store):
    ws = WriteStore(canonical_store)
    hits = json.loads(ws.on_demand_match("deployment rollback"))
    assert hits == []


def test_match_second_keyword(canonical_store):
    """Matches via the second keyword in a comma-separated spec."""
    ws = WriteStore(canonical_store)
    hits = json.loads(ws.on_demand_match("schema change"))
    assert any(h["id"] == 7 for h in hits)


def test_match_returns_id_and_one_liner_only(canonical_store):
    ws = WriteStore(canonical_store)
    hits = json.loads(ws.on_demand_match("migration"))
    assert hits
    h = hits[0]
    assert set(h.keys()) == {"id", "one_liner"}


def test_match_session_dedup(store_copy):
    """Row fired once in a session is excluded from on_demand_match."""
    ws = WriteStore(store_copy)
    ws.fire("7", "on_demand", session="s_dedup", context="migration")
    hits = json.loads(ws.on_demand_match("migration", session="s_dedup"))
    assert not any(h["id"] == 7 for h in hits)


def test_match_no_session_no_dedup(store_copy):
    """Without a session, fired rows are not excluded."""
    ws = WriteStore(store_copy)
    ws.fire("7", "on_demand", session="s_other", context="migration")
    hits = json.loads(ws.on_demand_match("migration", session=None))
    assert any(h["id"] == 7 for h in hits)


def test_match_edit_path_rows_excluded(canonical_store):
    """edit_path and session_start rows do not appear in on_demand results."""
    ws = WriteStore(canonical_store)
    hits = json.loads(ws.on_demand_match("all noise"))
    assert all(h["id"] == 7 for h in hits) or hits == []
