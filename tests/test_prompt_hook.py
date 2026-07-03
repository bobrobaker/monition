"""UserPromptSubmit executor — on_demand disclosure driven by the user prompt.

No CMS oracle exists for this executor (it's new in Phase 4), so these tests
pin behavior directly: in-process calls with stdin/stdout patched, the
semantic pass forced off so only the lexical contract is exercised.
"""
import io
import json

import pytest

import monition.embed as me
from monition.hooks import _log_path, prompt_hook


@pytest.fixture(autouse=True)
def lexical_only(monkeypatch):
    monkeypatch.setattr(me, "semantic_scores", lambda q, texts: [0.0] * len(texts))


@pytest.fixture
def host_repo(store_copy, tmp_path, monkeypatch):
    """Repo layout the executor sees: store at <root>/monition/."""
    import os
    import shutil
    root = tmp_path / "hostrepo"
    os.makedirs(root)
    shutil.move(str(store_copy), str(root / "monition"))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    return str(root)


def run_hook(monkeypatch, capsys, prompt, session="ps1"):
    payload = {"session_id": session}
    if prompt is not None:
        payload["prompt"] = prompt
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    prompt_hook()
    return capsys.readouterr().out


def test_prompt_hit_injects_context(host_repo, monkeypatch, capsys):
    out = run_hook(monkeypatch, capsys, "help me with the database migration")
    payload = json.loads(out)
    hso = payload["hookSpecificOutput"]
    assert hso["hookEventName"] == "UserPromptSubmit"
    assert "[t7/f" in hso["additionalContext"]
    assert "monition show" in hso["additionalContext"]


def test_prompt_no_hit_silent(host_repo, monkeypatch, capsys):
    assert run_hook(monkeypatch, capsys, "deployment rollback") == ""


def test_prompt_dedups_within_session(host_repo, monkeypatch, capsys):
    first = run_hook(monkeypatch, capsys, "migration plan", session="dd1")
    second = run_hook(monkeypatch, capsys, "migration again", session="dd1")
    assert "[t7/f" in first
    assert second == ""


def test_empty_prompt_silent(host_repo, monkeypatch, capsys):
    assert run_hook(monkeypatch, capsys, "   ") == ""
    assert run_hook(monkeypatch, capsys, None) == ""


def test_no_store_silent(tmp_path, monkeypatch, capsys):
    import os
    root = tmp_path / "bare"
    os.makedirs(root)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    assert run_hook(monkeypatch, capsys, "migration") == ""


def test_garbage_stdin_fails_open(host_repo, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    prompt_hook()
    assert capsys.readouterr().out == ""


def test_firing_logged_with_prompt_context(host_repo, monkeypatch, capsys):
    import os
    from monition.store_write import WriteStore
    run_hook(monkeypatch, capsys, "schema migration question", session="ctx1")
    ws = WriteStore(os.path.join(host_repo, "monition"))
    rows = ws._sql(
        "SELECT trigger_kind, trigger_context FROM firings"
        " WHERE session_id = 'ctx1'"
    )
    assert rows and rows[0]["trigger_kind"] == "on_demand"
    assert rows[0]["trigger_context"] == "schema migration question"


# ---- harness-boilerplate gate (task-notification and lookalikes) ----------


def test_task_notification_skipped_no_firing(host_repo, monkeypatch, capsys):
    import os
    from monition.store_write import WriteStore
    # Carries "migration" so it would hit t7 if matching ran at all — proves
    # the empty output is the gate, not a lexical miss.
    notification = (
        "<task-notification>\n"
        "<task-id>abc123</task-id>\n"
        "<summary>Agent \"migration\" finished</summary>\n"
        "</task-notification>"
    )
    out = run_hook(monkeypatch, capsys, notification, session="boiler1")
    assert out == ""
    ws = WriteStore(os.path.join(host_repo, "monition"))
    rows = ws._sql("SELECT id FROM firings WHERE session_id = 'boiler1'")
    assert rows == []


def test_task_notification_logs_boilerplate_skip(host_repo, monkeypatch, capsys):
    run_hook(monkeypatch, capsys, "<task-notification>\n<task-id>x</task-id>",
              session="boiler2")
    with open(_log_path()) as f:
        log = f.read()
    assert "[boilerplate] skipped harness-generated prompt session=boiler2" in log


def test_leading_whitespace_before_task_notification_still_skipped(
        host_repo, monkeypatch, capsys):
    # prompt_hook strips the prompt before the gate check runs.
    out = run_hook(monkeypatch, capsys,
                    "  \n<task-notification>\n<task-id>y</task-id>",
                    session="boiler3")
    assert out == ""


def test_human_prompt_mentioning_task_notification_still_matches(
        host_repo, monkeypatch, capsys):
    # A prompt that merely *contains* the tag mid-text is real user content —
    # only a leading match counts as boilerplate.
    out = run_hook(
        monkeypatch, capsys,
        "I saw a <task-notification> in the log about the migration issue",
        session="boiler4")
    assert "[t7/f" in out
