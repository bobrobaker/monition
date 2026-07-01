"""Tests for the optional embedding layer and the hybrid on_demand pass.

No fastembed required: embed.py internals are tested by faking `_embed_raw`;
the hybrid logic in on_demand_match by faking `semantic_scores`. One real-model
integration test runs only when fastembed is installed.
"""
import importlib.util
import json

import pytest

import monition.embed as me
from monition.embed import cosine, embed_texts, semantic_scores
from monition.store_write import WriteStore


# ---- pure functions ---------------------------------------------------------


def test_cosine_identity():
    assert cosine([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)


def test_cosine_orthogonal():
    assert cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_zero_vector():
    assert cosine([0.0, 0.0], [1.0, 1.0]) == 0.0


# ---- cache-through ----------------------------------------------------------


@pytest.fixture
def fake_backend(monkeypatch, tmp_path):
    """Deterministic vectors + isolated cache; returns the call counter."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    calls = []

    def raw(texts):
        calls.append(list(texts))
        # one-hot-ish: vector derived from text length so distinct texts differ
        return [[float(len(t)), 1.0] for t in texts]

    monkeypatch.setattr(me, "_embed_raw", raw)
    return calls


def test_embed_texts_caches(fake_backend):
    embed_texts(["alpha", "beta"])
    assert len(fake_backend) == 1
    embed_texts(["alpha", "beta"])  # second call: all cached
    assert len(fake_backend) == 1
    embed_texts(["alpha", "gamma"])  # only the miss goes to the backend
    assert fake_backend[1] == ["gamma"]


def test_semantic_scores_self_similarity(fake_backend):
    scores = semantic_scores("alpha", ["alpha", "completely different words"])
    assert scores[0] == pytest.approx(1.0)  # identical text → identical vector


# ---- hybrid on_demand pass --------------------------------------------------


def _hits(ws, *args, **kwargs):
    return json.loads(ws.on_demand_match(*args, **kwargs))["hits"]


def test_hybrid_semantic_hit(canonical_store, monkeypatch):
    """Query with no keyword overlap still hits t7 via embeddings."""
    monkeypatch.setattr(me, "semantic_scores", lambda q, texts: [0.9] * len(texts))
    ws = WriteStore(canonical_store)
    hits = _hits(ws, "deployment rollback")
    assert any(h["id"] == 7 for h in hits)


def test_hybrid_threshold_excludes_low_similarity(canonical_store, monkeypatch):
    monkeypatch.setattr(me, "semantic_scores", lambda q, texts: [0.3] * len(texts))
    ws = WriteStore(canonical_store)
    hits = _hits(ws, "deployment rollback")
    assert hits == []


def test_hybrid_lexical_hits_rank_first(store_copy, monkeypatch):
    """A lexical hit precedes a higher-similarity semantic-only hit."""
    ws = WriteStore(store_copy)
    ws.add("gotcha", "on_demand", "semantic only row", "kubernetes", None, None,
           None)
    monkeypatch.setattr(me, "semantic_scores", lambda q, texts: [0.95] * len(texts))
    hits = _hits(ws, "migration plan")
    assert hits[0]["id"] == 7  # lexical hit on "migration"
    assert any(h["one_liner"] == "semantic only row" for h in hits[1:])


def test_hybrid_fail_open_equals_lexical(canonical_store, monkeypatch):
    """Embedding errors degrade to exactly the lexical-only result."""
    def boom(q, texts):
        raise RuntimeError("model download failed")

    monkeypatch.setattr(me, "semantic_scores", boom)
    ws = WriteStore(canonical_store)
    assert _hits(ws, "deployment rollback") == []
    hits = _hits(ws, "migration plan")
    assert [h["id"] for h in hits] == [7]


def test_hybrid_semantic_hits_deduped(store_copy, monkeypatch):
    """Per-session dedup applies to semantic hits too."""
    monkeypatch.setattr(me, "semantic_scores", lambda q, texts: [0.9] * len(texts))
    ws = WriteStore(store_copy)
    ws.fire("7", "on_demand", session="s_sem", context="deployment rollback")
    hits = _hits(ws, "deployment rollback", session="s_sem")
    assert not any(h["id"] == 7 for h in hits)


# ---- real model (optional) --------------------------------------------------


@pytest.mark.skipif(importlib.util.find_spec("fastembed") is None,
                    reason="fastembed not installed (monition[embed] extra)")
def test_real_model_semantic_neighbors(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    scores = semantic_scores(
        "database schema migration",
        ["altering tables and migrating data", "baking sourdough bread"],
    )
    assert scores[0] > scores[1]
