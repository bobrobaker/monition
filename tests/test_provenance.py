"""v4 fire-time provenance capture on `firings`.

The columns are impossible to backfill, so the contract is: every fire captures
what it can (git state from the store's host repo, model from the caller, the
monition version), and anything unavailable stays honestly NULL — a fire is
never blocked by provenance capture.
"""
import json
import subprocess

from monition.hooks import _session_model
from monition.store import Store
from monition.store_write import WriteStore

from .conftest import build_store, SCHEMA, ROWS


def _git(args, cwd):
    subprocess.run(["git"] + args, cwd=cwd, check=True,
                   capture_output=True, text=True)


def _fired(store_path, session):
    return next(f for f in Store(store_path).firings() if f.session_id == session)


def test_fire_captures_model_and_version(store_copy):
    # store_copy's parent is a tmp dir, not a git repo -> git state not captured,
    # but the fire still lands and the caller-supplied model is recorded.
    WriteStore(store_copy).fire("1", "edit_path", "sess-y", "src/b.py",
                                model="claude-test-model")
    f = _fired(store_copy, "sess-y")
    assert f.model == "claude-test-model"
    assert f.monition_version is None or isinstance(f.monition_version, str)
    assert f.git_sha is None or len(f.git_sha) == 40  # shape, env-independent


def test_fire_without_model_is_null(store_copy):
    WriteStore(store_copy).fire("1", "session_start", "sess-z")
    f = _fired(store_copy, "sess-z")
    assert f.model is None  # missing data, never guessed


def test_fire_captures_git_provenance(tmp_path):
    repo = tmp_path / "host"
    repo.mkdir()
    _git(["init"], str(repo))
    _git(["config", "user.email", "t@example.com"], str(repo))
    _git(["config", "user.name", "t"], str(repo))
    (repo / "README.md").write_text("hi\n")
    _git(["add", "-A"], str(repo))
    _git(["commit", "-m", "init"], str(repo))
    head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()

    store = str(repo / "monition")
    build_store(store, [SCHEMA, ROWS])  # the new monition/ dir leaves the repo dirty
    WriteStore(store).fire("1", "edit_path", "sess-x", "src/a.py",
                           model="claude-opus-4-8")

    f = _fired(store, "sess-x")
    assert f.git_sha == head
    assert f.git_dirty is True
    assert f.model == "claude-opus-4-8"


def test_session_model_from_payload_string():
    assert _session_model({"model": "claude-opus-4-8"}) == "claude-opus-4-8"


def test_session_model_from_payload_dict():
    assert _session_model({"model": {"id": "claude-x", "display_name": "X"}}) == "claude-x"


def test_session_model_from_transcript(tmp_path):
    tp = tmp_path / "transcript.jsonl"
    tp.write_text(
        json.dumps({"type": "user", "message": {"content": "hi"}}) + "\n"
        + json.dumps({"type": "assistant", "message": {"model": "claude-from-tx"}}) + "\n"
    )
    assert _session_model({"transcript_path": str(tp)}) == "claude-from-tx"


def test_session_model_absent_is_none(tmp_path):
    assert _session_model({}) is None
    assert _session_model({"transcript_path": str(tmp_path / "missing.jsonl")}) is None
