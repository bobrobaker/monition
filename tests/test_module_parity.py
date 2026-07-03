"""Characterization parity for the B02 module refactor (bucket B02, Phase 7).

Exact-value locks on the three matchers' full output — ids AND evidence dicts,
whole lists, not spot checks — written against the pre-refactor matchers and
required to stay green, unchanged, after the modules.py extraction. Any diff
here is a bug in the refactor, not a design opportunity (workstream invariant:
behavior-preserving until consented).
"""
import json

import pytest

import monition.embed as me
from monition.store_write import WriteStore


def test_match_exact_hit_list(canonical_store):
    ws = WriteStore(canonical_store)
    assert json.loads(ws.match("src/x.py")) == [
        {
            "id": 2,
            "one_liner": "mixed",
            "trigger_spec": "src/*,tools/*",
            "evidence": {"module": "glob", "pattern": "src/*", "path": "src/x.py"},
        }
    ]


def test_match_second_pattern_exact(canonical_store):
    """Hit via the second comma-separated pattern names *that* pattern."""
    ws = WriteStore(canonical_store)
    assert json.loads(ws.match("tools/y.py")) == [
        {
            "id": 2,
            "one_liner": "mixed",
            "trigger_spec": "src/*,tools/*",
            "evidence": {"module": "glob", "pattern": "tools/*", "path": "tools/y.py"},
        }
    ]


def test_match_miss_is_empty(canonical_store):
    ws = WriteStore(canonical_store)
    assert json.loads(ws.match("elsewhere/z.py")) == []


def test_on_demand_lexical_exact(canonical_store, monkeypatch):
    monkeypatch.setattr(me, "semantic_scores", lambda q, t: [0.0] * len(t))
    ws = WriteStore(canonical_store)
    assert json.loads(ws.on_demand_match("migration path")) == {
        "hits": [
            {
                "id": 7,
                "one_liner": "on_demand: migration gotcha",
                "trigger_spec": "migration, schema",
                "evidence": {
                    "module": "lexical",
                    "keyword": "migration",
                    "query": "migration path",
                },
            }
        ],
        "capped": 0,
    }


def test_on_demand_semantic_exact(canonical_store, monkeypatch):
    """No lexical hit; stubbed scorer puts t7 above threshold — exact semantic
    hit dict including the 4-decimal score rounding."""
    monkeypatch.setattr(me, "semantic_scores", lambda q, t: [0.87654321] * len(t))
    ws = WriteStore(canonical_store)
    assert json.loads(ws.on_demand_match("deployment rollback")) == {
        "hits": [
            {
                "id": 7,
                "one_liner": "on_demand: migration gotcha",
                "trigger_spec": "migration, schema",
                "evidence": {
                    "module": "semantic",
                    "score": 0.8765,
                    "query": "deployment rollback",
                },
            }
        ],
        "capped": 0,
    }


def test_on_demand_semantic_below_threshold_exact(canonical_store, monkeypatch):
    """Stubbed score below SIM_THRESHOLD (0.6) yields exactly nothing."""
    monkeypatch.setattr(me, "semantic_scores", lambda q, t: [0.59] * len(t))
    ws = WriteStore(canonical_store)
    assert json.loads(ws.on_demand_match("deployment rollback")) == {
        "hits": [],
        "capped": 0,
    }


def test_on_demand_broken_embeddings_fail_open_exact(canonical_store, monkeypatch):
    """A raising scorer degrades to lexical-only — exactly today's fail-open."""
    def boom(q, t):
        raise RuntimeError("no model")
    monkeypatch.setattr(me, "semantic_scores", boom)
    ws = WriteStore(canonical_store)
    assert json.loads(ws.on_demand_match("migration path")) == {
        "hits": [
            {
                "id": 7,
                "one_liner": "on_demand: migration gotcha",
                "trigger_spec": "migration, schema",
                "evidence": {
                    "module": "lexical",
                    "keyword": "migration",
                    "query": "migration path",
                },
            }
        ],
        "capped": 0,
    }


def test_session_start_exact(canonical_store):
    """Exact list; session_start hits carry NO evidence key (the `always`
    module has nothing to record) — that absence is locked here."""
    ws = WriteStore(canonical_store)
    assert json.loads(ws.session_start()) == [
        {"id": 4, "one_liner": "unrated"},
        {"id": 6, "one_liner": "mirrored"},
    ]
