"""v5 firing-grain `situation` capture.

The executors record a short decision-context excerpt at fire time — the
un-truncated user prompt for `on_demand`, the edited content for `edit_path`,
NULL when there is none. This is the firing-grain context the session-archive
join on `session_id` recovers only at session grain (confer 2026-06-14,
`eval-engine-seam-and-archive-durability`), so it is captured at the source.

Drives the executors in-process (stdin patched) and asserts the persisted row.
"""
import io
import json
import os
import shutil

import pytest

import monition.embed as me
from monition.hooks import fire_hook, prompt_hook
from monition.store import Store
from monition.store_write import WriteStore


@pytest.fixture(autouse=True)
def lexical_only(monkeypatch):
    # force the semantic pass off so on_demand matching is lexical-only
    monkeypatch.setattr(me, "semantic_scores", lambda q, texts: [0.0] * len(texts))


@pytest.fixture
def host_repo(store_copy, tmp_path, monkeypatch):
    """Repo layout the executors see: store at <root>/monition/."""
    root = tmp_path / "hostrepo"
    os.makedirs(root)
    shutil.move(str(store_copy), str(root / "monition"))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    return str(root)


def _rows(host_repo, session):
    ws = WriteStore(os.path.join(host_repo, "monition"))
    return ws._sql(
        "SELECT trigger_context, situation FROM firings"
        f" WHERE session_id = '{session}'"
    )


def _run(monkeypatch, executor, payload):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    executor()


def test_fire_persists_situation(store_copy):
    # the raw writer round-trips the column (no score gate, no executor)
    WriteStore(store_copy).fire("1", "edit_path", "us1", "docs/a.md",
                                situation="about to write: def f(): ...")
    f = next(x for x in Store(store_copy).firings() if x.session_id == "us1")
    assert f.situation == "about to write: def f(): ..."
    assert f.trigger_context == "docs/a.md"  # the match stays distinct from the excerpt


def test_prompt_hook_situation_is_untruncated_prompt(host_repo, monkeypatch):
    # longer than the 200-char trigger_context preview, so truncation is visible
    long_prompt = "schema migration " + "x" * 400
    _run(monkeypatch, prompt_hook, {"session_id": "ps_sit", "prompt": long_prompt})

    rows = _rows(host_repo, "ps_sit")
    assert rows
    assert len(rows[0]["trigger_context"]) == 200   # preview is truncated
    assert rows[0]["situation"] == long_prompt       # full prompt captured


def test_fire_hook_situation_is_edit_excerpt(host_repo, monkeypatch):
    content = "def migrate():\n    pass  # the edit the agent was about to make"
    _run(monkeypatch, fire_hook, {
        "session_id": "fh_sit",
        "tool_input": {"file_path": os.path.join(host_repo, "docs/a.md"),
                       "content": content},
    })

    rows = _rows(host_repo, "fh_sit")
    assert rows
    assert rows[0]["trigger_context"] == "docs/a.md"  # the match (path)
    assert rows[0]["situation"] == content            # the edit excerpt


def test_fire_hook_situation_null_without_edit_content(host_repo, monkeypatch):
    # a tool_input carrying neither `content` nor `new_string` leaves it honestly NULL.
    # Asserted through the approved reader, which maps a missing/NULL column to None.
    _run(monkeypatch, fire_hook, {
        "session_id": "fh_none",
        "tool_input": {"file_path": os.path.join(host_repo, "docs/a.md")},
    })

    store = Store(os.path.join(host_repo, "monition"))
    f = next(x for x in store.firings() if x.session_id == "fh_none")
    assert f.situation is None
