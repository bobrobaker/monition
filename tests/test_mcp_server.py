"""MCP tool handler — direct function tests, no `mcp` package required.

`match_gotchas_impl` is the explicit-pull surface: no EV-scorer suppression
(Claude asked), but every disclosure still logs a firing so ratings work.
Lexical-only here, same as test_on_demand.py.
"""
import pytest

import monition.embed as me
from monition.mcp_server import match_gotchas_impl
from monition.store_write import WriteStore


@pytest.fixture(autouse=True)
def lexical_only(monkeypatch):
    monkeypatch.setattr(me, "semantic_scores", lambda q, texts: [0.0] * len(texts))


def test_hit_returns_lines_and_logs_firing(store_copy):
    out = match_gotchas_impl("database migration", store_path=store_copy)
    assert "[t7/f" in out
    assert "monition rate" in out
    rows = WriteStore(store_copy)._sql(
        "SELECT trigger_kind, trigger_context FROM firings WHERE takeaway_id = 7"
    )
    assert any(r["trigger_kind"] == "on_demand"
               and r["trigger_context"] == "database migration" for r in rows)


def test_no_hit(store_copy):
    assert match_gotchas_impl("deployment rollback",
                              store_path=store_copy) == "No matching gotchas."


def test_repeat_query_not_suppressed(store_copy):
    """Explicit pulls have no per-session dedup: same query fires again."""
    first = match_gotchas_impl("migration", store_path=store_copy)
    second = match_gotchas_impl("migration", store_path=store_copy)
    assert "[t7/f" in first and "[t7/f" in second


def test_broken_store_fails_open(tmp_path):
    out = match_gotchas_impl("migration", store_path=str(tmp_path / "nope"))
    assert out.startswith("Gotcha lookup unavailable:") or "No Monition store" in out


def test_no_store_resolvable(monkeypatch):
    monkeypatch.setattr("monition.mcp_server.resolve_store_path", lambda: None)
    assert "No Monition store" in match_gotchas_impl("migration")
