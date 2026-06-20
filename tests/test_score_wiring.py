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
    monkeypatch.setattr(mh, "_score", lambda tid, path, session_id=None, store=None, firings=None: {
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
    monkeypatch.setattr(mh, "_score", lambda tid, path, session_id=None, store=None, firings=None: {
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


# --- Opt-in firing observer (statusline ⚑ wiring) --------------------------
#
# Integration tests spy on _notify_observer (patching subprocess.run would mutate
# the shared module object and also catch store_write's git-provenance calls). The
# subprocess mechanics of _notify_observer are unit-tested below, where its only
# subprocess.run call is the observer itself.

def test_observer_invoked_once_per_firing(host_repo, monkeypatch):
    """A real fire → observer called once per fired row (count == firings), each
    with the firing session and the takeaway's one-liner slug."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", host_repo)
    calls = []
    monkeypatch.setattr(mh, "_notify_observer",
                        lambda session, slug: calls.append((session, slug)))

    out = feed(fire_hook, host_repo, rel_path="docs/a.md", monkeypatch=monkeypatch)
    fired = len(json.loads(out)["hookSpecificOutput"]["additionalContext"]
                .splitlines()) - 1  # minus the header line

    assert fired >= 1
    assert len(calls) == fired
    assert all(session == "ws_test" and slug for session, slug in calls)


def test_observer_not_invoked_on_suppress(host_repo, monkeypatch):
    """A suppressed hit is not a firing → observer not called for it."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", host_repo)
    monkeypatch.setattr(mh, "_score", lambda tid, path, session_id=None, store=None, firings=None: {
        "decision": "suppress", "cold_start": False,
        "evidence_count": 5, "ev_score": 0.0,
    })
    calls = []
    monkeypatch.setattr(mh, "_notify_observer",
                        lambda session, slug: calls.append((session, slug)))

    feed(fire_hook, host_repo, rel_path="docs/a.md", monkeypatch=monkeypatch)
    assert calls == []


def test_notify_observer_noop_when_unset(monkeypatch):
    """Default (env var absent): monition ships no observer → no subprocess call."""
    monkeypatch.delenv("MONITION_FIRING_OBSERVER", raising=False)
    ran = []
    monkeypatch.setattr(mh.subprocess, "run", lambda cmd, **kw: ran.append(cmd))

    mh._notify_observer("sess1", "a slug")
    assert ran == []


def test_notify_observer_invocation_contract(monkeypatch):
    """Env var set → `<observer> --session <id> --text <slug>`, prefix shlex-split."""
    monkeypatch.setenv("MONITION_FIRING_OBSERVER", "/usr/bin/true --verbose")
    ran = []
    monkeypatch.setattr(mh.subprocess, "run", lambda cmd, **kw: ran.append((cmd, kw)))

    mh._notify_observer("sess1", "stale store-model claim")
    assert len(ran) == 1
    cmd, kw = ran[0]
    assert cmd == ["/usr/bin/true", "--verbose",
                   "--session", "sess1", "--text", "stale store-model claim"]
    assert kw.get("timeout") == mh.OBSERVER_TIMEOUT_S


def test_notify_observer_error_is_swallowed(monkeypatch):
    """Observer crashes/hangs → error swallowed (fail-open), no exception raised."""
    monkeypatch.setenv("MONITION_FIRING_OBSERVER", "/usr/bin/true")
    monkeypatch.setattr(mh.subprocess, "run",
                        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom")))

    mh._notify_observer("sess1", "a slug")  # must not raise


def test_observer_failure_does_not_suppress_injection(host_repo, monkeypatch):
    """End-to-end through the real _notify_observer: a wedged observer command
    never blocks the firing/injection. Only the observer call raises; git
    provenance (shared subprocess module) is delegated to the real run."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", host_repo)
    monkeypatch.setenv("MONITION_FIRING_OBSERVER", "/usr/bin/observer-xyz")
    real_run = mh.subprocess.run

    def selective_run(cmd, **kw):
        if cmd and cmd[0] == "/usr/bin/observer-xyz":
            raise RuntimeError("observer exploded")
        return real_run(cmd, **kw)

    monkeypatch.setattr(mh.subprocess, "run", selective_run)
    out = feed(fire_hook, host_repo, rel_path="docs/a.md", monkeypatch=monkeypatch)
    assert out != ""  # disclosure still emitted despite observer failure
