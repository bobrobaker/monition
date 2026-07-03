"""MONITION_DISABLE — per-invocation opt-out for API-style headless runs.

Two layers, both pinned here: the shell guard in the settings command string
(short-circuits before Python starts) and the Python check in the executors
(covers hosts whose settings predate the guarded-command template).
"""
import io
import json

import pytest

import monition.embed as me
import monition.hooks as hooks
from monition.hooks import (
    fire_hook, guarded_hook_command, prompt_hook, session_brief,
)


@pytest.fixture(autouse=True)
def lexical_only(monkeypatch):
    monkeypatch.setattr(me, "semantic_scores", lambda q, texts: [0.0] * len(texts))


@pytest.fixture
def host_repo(store_copy, tmp_path, monkeypatch):
    import os
    import shutil
    root = tmp_path / "hostrepo"
    os.makedirs(root)
    shutil.move(str(store_copy), str(root / "monition"))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    return str(root)


def test_disable_suppresses_would_fire_prompt(host_repo, monkeypatch, capsys):
    payload = json.dumps({"session_id": "dis1",
                          "prompt": "help me with the database migration"})
    monkeypatch.setenv("MONITION_DISABLE", "1")
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))
    prompt_hook()
    assert capsys.readouterr().out == ""

    # Same payload with the flag unset fires — proving the suppression above
    # was the flag, not a non-matching fixture.
    monkeypatch.delenv("MONITION_DISABLE")
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))
    prompt_hook()
    assert "[t7/f" in capsys.readouterr().out


def test_disable_short_circuits_every_executor(monkeypatch, capsys):
    """Disabled executors return before stdin or the store is touched."""
    opened = []
    monkeypatch.setattr(hooks, "_open_store",
                        lambda: opened.append(1) or (None, None))
    monkeypatch.setenv("MONITION_DISABLE", "1")
    for executor in (fire_hook, session_brief, prompt_hook):
        monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
        executor()
    assert opened == []
    assert capsys.readouterr().out == ""

    # Control: with the flag unset the same payload reaches _open_store.
    monkeypatch.delenv("MONITION_DISABLE")
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    fire_hook()
    assert opened == [1]


def test_guarded_command_carries_shell_guard():
    for sub in ("fire-hook", "session-brief", "prompt-hook"):
        cmd = guarded_hook_command(sub)
        assert cmd.startswith('[ -z "$MONITION_DISABLE" ] || exit 0; ')
