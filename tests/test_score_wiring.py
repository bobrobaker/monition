"""Score-wiring tests for hook executors (no CMS oracle required).

Tests fire_hook / session_brief directly (not via subprocess) so monkeypatch
works across the score boundary.
"""
import io
import json
import os
import shutil

import pytest

import monition.hooks as mh
from monition.hooks import fire_hook, session_brief


@pytest.fixture
def host_repo(canonical_store, tmp_path):
    root = tmp_path / "hostrepo"
    os.makedirs(root)
    shutil.copytree(canonical_store, root / "monition")
    return str(root)


def feed(hook_fn, repo, rel_path=None, session="ws_test", monkeypatch=None):
    """Call hook_fn with hook JSON on stdin; return captured stdout."""
    data = {"session_id": session}
    if rel_path is not None:
        data["tool_input"] = {"file_path": os.path.join(repo, rel_path)}
    if monkeypatch:
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", repo)
    captured = io.StringIO()
    import sys
    old_stdin, old_stdout = sys.stdin, sys.stdout
    sys.stdin = io.StringIO(json.dumps(data))
    sys.stdout = captured
    try:
        hook_fn()
    finally:
        sys.stdin, sys.stdout = old_stdin, old_stdout
    return captured.getvalue()


def test_fire_hook_cold_start_fires(host_repo, monkeypatch):
    """Default N_COLD_START=3: cold-start → fire (disclosure emitted)."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", host_repo)
    out = feed(fire_hook, host_repo, rel_path="docs/a.md", monkeypatch=monkeypatch)
    assert out != ""
    payload = json.loads(out)
    assert "additionalContext" in payload["hookSpecificOutput"]


def test_fire_hook_suppress_silences_output(host_repo, monkeypatch):
    """score() returns suppress for all hits → no disclosure output."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", host_repo)
    monkeypatch.setattr(mh, "_score", lambda tid, path, session_id=None: {
        "decision": "suppress", "cold_start": False,
        "evidence_count": 5, "ev_score": 0.0,
    })
    out = feed(fire_hook, host_repo, rel_path="docs/a.md", monkeypatch=monkeypatch)
    assert out == ""


def test_fire_hook_score_error_fires_open(host_repo, monkeypatch):
    """score() raises → executor fires as cold-start (fail-open)."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", host_repo)

    def raise_score(*a, **kw):
        raise RuntimeError("scorer exploded")

    monkeypatch.setattr(mh, "_score", raise_score)
    out = feed(fire_hook, host_repo, rel_path="docs/a.md", monkeypatch=monkeypatch)
    assert out != ""  # still fired despite error


def test_session_brief_suppress_silences_output(host_repo, monkeypatch):
    """score() suppresses all session_start rows → no disclosure output."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", host_repo)
    monkeypatch.setattr(mh, "_score", lambda tid, path, session_id=None: {
        "decision": "suppress", "cold_start": False,
        "evidence_count": 5, "ev_score": 0.0,
    })
    out = feed(session_brief, host_repo, monkeypatch=monkeypatch)
    assert out == ""


def test_session_brief_score_error_fires_open(host_repo, monkeypatch):
    """score() raises for session_start → fires as cold-start (fail-open)."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", host_repo)

    def raise_score(*a, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(mh, "_score", raise_score)
    out = feed(session_brief, host_repo, monkeypatch=monkeypatch)
    assert out != ""
