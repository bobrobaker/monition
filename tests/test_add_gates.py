"""Birth gates on `monition add`: the one-liner length cap and the
active-duplicate check. (The suppressed-row resurrection gate stays in
test_resurrection.py — the two candidate sets are disjoint.)

Fixture notes: t2 ("mixed") is active with a latest decision of "fire"; t4
("unrated") is active and never scored; t5 ("retired") is retired; t1 ("all
noise") is the only suppressed row.
"""
import pytest

import monition.embed as me
from monition.cli import main
from monition.store_write import ONE_LINER_MAX_CHARS, WriteStore


@pytest.fixture(autouse=True)
def exact_only(monkeypatch):
    """Default embeddings off: the duplicate gate fails open to exact-match
    (and find_resurrection to Jaccard, which nothing here comes near)."""
    def boom(q, texts):
        raise RuntimeError("embed extra not installed")
    monkeypatch.setattr(me, "semantic_scores", boom)


def _add(store, one_liner, *extra):
    return main(["add", "--kind", "gotcha", "--trigger-kind", "edit_path",
                 "--one-liner", one_liner, "--store", store, *extra])


# ---- active-duplicate gate --------------------------------------------------


def test_exact_duplicate_of_active_row_refused(store_copy, capsys):
    assert _add(store_copy, "mixed") == 3
    out = capsys.readouterr().out
    assert "DUPLICATE" in out and "t2" in out
    assert "log-recurrence" in out and "--force" in out


def test_force_overrides_duplicate_gate(store_copy, capsys):
    assert _add(store_copy, "mixed", "--force") == 0
    assert "added takeaway" in capsys.readouterr().out


def test_distinct_lesson_inserts_normally(store_copy, capsys):
    assert _add(store_copy, "a wholly distinct new lesson") == 0
    assert "added takeaway" in capsys.readouterr().out


def test_embedding_near_duplicate_refused(store_copy, monkeypatch, capsys):
    """Cosine >= DUPLICATE_COSINE against an active row refuses the add.
    Scores are keyed to t4 ("unrated", active, never scored) so the
    resurrection gate — which only sees suppressed rows — stays quiet."""
    monkeypatch.setattr(
        me, "semantic_scores",
        lambda q, texts: [0.95 if t == "unrated" else 0.0 for t in texts])
    assert _add(store_copy, "differently worded but same lesson") == 3
    out = capsys.readouterr().out
    assert "DUPLICATE" in out and "t4" in out and "0.95" in out


def test_below_duplicate_cosine_inserts(store_copy, monkeypatch, capsys):
    """SIM_THRESHOLD-grade similarity (same topic) is not duplicate-grade."""
    monkeypatch.setattr(
        me, "semantic_scores",
        lambda q, texts: [0.7 if t == "unrated" else 0.0 for t in texts])
    assert _add(store_copy, "same topic, genuinely different lesson") == 0


def test_retired_rows_are_not_duplicate_candidates(store_copy, capsys):
    assert _add(store_copy, "retired") == 0  # t5's one_liner, but t5 is retired


def test_suppressed_rows_route_to_resurrection_not_duplicate(store_copy,
                                                             capsys):
    """An exact match to the suppressed t1 hits the resurrection gate (its
    consent flow revives/merges); the duplicate gate never sees it."""
    ws = WriteStore(store_copy)
    assert ws.find_active_duplicate("all noise") == []


# ---- one-liner length cap ---------------------------------------------------


def test_over_length_one_liner_refused_naming_the_cap(store_copy, capsys):
    long = "x" * (ONE_LINER_MAX_CHARS + 1)
    assert _add(store_copy, long) == 2
    err = capsys.readouterr().err
    assert str(ONE_LINER_MAX_CHARS) in err
    assert "injected" in err  # the why, not just the number


def test_at_length_one_liner_passes(store_copy, capsys):
    assert _add(store_copy, "y" * ONE_LINER_MAX_CHARS) == 0


def test_force_overrides_length_cap(store_copy, capsys):
    long = "z" * (ONE_LINER_MAX_CHARS + 1)
    assert _add(store_copy, long, "--force") == 0
    assert "added takeaway" in capsys.readouterr().out
