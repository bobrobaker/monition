"""Injection cap for on_demand disclosure.

Unbounded semantic matching injected 41-75 rows (~6k tokens) on broad prompts.
The cap: lexical hits (user-designed deterministic triggers) are ALWAYS kept;
semantic-only hits are capped to the top SEMANTIC_TOP_K by cosine, then
INJECTION_CHAR_BUDGET drops the lowest-scoring semantic hits first. Dropping
is never silent — `on_demand_match` reports a `capped` count and both
executors (prompt-hook, MCP match_gotchas) render a "+N suppressed" trailer.
"""
import io
import json
import os
import shutil

import pytest

import monition.embed as me
import monition.store_write as sw
from monition.hooks import prompt_hook
from monition.mcp_server import match_gotchas_impl
from monition.store_write import WriteStore, _cap_hits


@pytest.fixture(autouse=True)
def isolated_state(monkeypatch, tmp_path_factory):
    """Keep hook state-log writes out of the real XDG state dir."""
    monkeypatch.setenv(
        "XDG_STATE_HOME", str(tmp_path_factory.mktemp("state")))


def _mk(n, prefix="row"):
    return [{"id": i, "one_liner": f"{prefix} {i}"} for i in range(n)]


# ---- _cap_hits unit ---------------------------------------------------------


def test_top_k_keeps_highest_scoring_prefix():
    """`semantic` arrives score-desc; the cap keeps exactly the top K."""
    semantic = _mk(sw.SEMANTIC_TOP_K + 5)
    kept, capped = _cap_hits([], semantic)
    assert kept == semantic[:sw.SEMANTIC_TOP_K]
    assert capped == 5


def test_lexical_never_dropped_even_over_budget(monkeypatch):
    monkeypatch.setattr(sw, "INJECTION_CHAR_BUDGET", 10)  # tiny
    lexical = _mk(20, "lexical")  # far over the budget on their own
    kept, capped = _cap_hits(lexical, _mk(3, "semantic"))
    assert kept == lexical          # every lexical hit survives
    assert capped == 3              # every semantic hit dropped


def test_char_budget_drops_lowest_scoring_semantic_first(monkeypatch):
    lexical = _mk(2, "lexical")
    semantic = _mk(4, "semantic")
    budget = (sum(len(h["one_liner"]) for h in lexical)
              + sum(len(h["one_liner"]) for h in semantic[:2]))
    monkeypatch.setattr(sw, "INJECTION_CHAR_BUDGET", budget)
    kept, capped = _cap_hits(lexical, semantic)
    assert kept == lexical + semantic[:2]  # tail (lowest scores) went first
    assert capped == 2


def test_no_hits_no_cap():
    assert _cap_hits([], []) == ([], 0)


# ---- store-level on_demand_match -------------------------------------------


def _seed_semantic_rows(ws, n):
    """n on_demand rows whose keywords never match the test queries; the fake
    scorer below scores 'sem row i' at 0.6 + i/100 (higher i = higher score)."""
    for i in range(n):
        ws.add("gotcha", "on_demand", f"sem row {i:02d}", f"kw{i}")


def _fake_scores(q, texts):
    return [0.6 + int(t.split()[2]) / 100 if t.startswith("sem row") else 0.0
            for t in texts]


def test_on_demand_caps_to_top_k_by_score(store_copy, monkeypatch):
    ws = WriteStore(store_copy)
    _seed_semantic_rows(ws, sw.SEMANTIC_TOP_K + 3)
    monkeypatch.setattr(me, "semantic_scores", _fake_scores)
    res = json.loads(ws.on_demand_match("zzz unrelated"))
    liners = [h["one_liner"] for h in res["hits"]]
    # highest-scoring rows survive, ordered score-desc
    expect = [f"sem row {i:02d}"
              for i in range(sw.SEMANTIC_TOP_K + 2, 2, -1)]
    assert liners == expect
    assert res["capped"] == 3


def test_on_demand_lexical_kept_alongside_capped_semantic(store_copy, monkeypatch):
    ws = WriteStore(store_copy)
    _seed_semantic_rows(ws, sw.SEMANTIC_TOP_K + 2)
    monkeypatch.setattr(me, "semantic_scores", _fake_scores)
    res = json.loads(ws.on_demand_match("about the migration"))
    assert res["hits"][0]["id"] == 7  # lexical hit on "migration" leads
    assert res["capped"] == 2
    assert len(res["hits"]) == 1 + sw.SEMANTIC_TOP_K


def test_on_demand_cap_false_returns_everything(store_copy, monkeypatch):
    """`monition query`'s escape hatch: cap=False returns the full set."""
    ws = WriteStore(store_copy)
    n = sw.SEMANTIC_TOP_K + 4
    _seed_semantic_rows(ws, n)
    monkeypatch.setattr(me, "semantic_scores", _fake_scores)
    res = json.loads(ws.on_demand_match("zzz unrelated", cap=False))
    assert len(res["hits"]) == n
    assert res["capped"] == 0


# ---- executor trailers ------------------------------------------------------


@pytest.fixture
def host_repo(store_copy, tmp_path, monkeypatch):
    root = tmp_path / "hostrepo"
    os.makedirs(root)
    shutil.move(str(store_copy), str(root / "monition"))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    return str(root)


def test_prompt_hook_renders_cap_trailer(host_repo, monkeypatch, capsys):
    ws = WriteStore(os.path.join(host_repo, "monition"))
    _seed_semantic_rows(ws, sw.SEMANTIC_TOP_K + 3)
    monkeypatch.setattr(me, "semantic_scores", _fake_scores)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(
        {"session_id": "cap1", "prompt": "zzz unrelated"})))
    prompt_hook()
    ctx = json.loads(capsys.readouterr().out)["hookSpecificOutput"][
        "additionalContext"]
    assert "(+3 more suppressed by cap" in ctx
    assert ctx.count("[t") == sw.SEMANTIC_TOP_K  # only the kept hits injected


def test_prompt_hook_no_trailer_when_nothing_capped(host_repo, monkeypatch,
                                                    capsys):
    monkeypatch.setattr(me, "semantic_scores",
                        lambda q, texts: [0.0] * len(texts))
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(
        {"session_id": "cap2", "prompt": "database migration"})))
    prompt_hook()
    ctx = json.loads(capsys.readouterr().out)["hookSpecificOutput"][
        "additionalContext"]
    assert "suppressed by cap" not in ctx


def test_mcp_match_gotchas_capped_with_trailer(store_copy, monkeypatch):
    ws = WriteStore(store_copy)
    _seed_semantic_rows(ws, sw.SEMANTIC_TOP_K + 2)
    monkeypatch.setattr(me, "semantic_scores", _fake_scores)
    out = match_gotchas_impl("zzz unrelated", store_path=store_copy)
    assert "(+2 more suppressed by cap" in out
    assert out.count("[t") == sw.SEMANTIC_TOP_K
