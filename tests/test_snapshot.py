"""`monition snapshot` — dirty-tree capture to a namespaced side ref.

Pins the spec's success criteria (decision 4/5): a side-ref commit captures the
dirty tree (tracked + untracked, ignored excluded) WITHOUT mutating working tree /
HEAD / branches / tags; idempotent per `<id>`; firing provenance stamped into the
commit message via the approved store reader.
"""
import os
import subprocess

import pytest

from monition.snapshot import REF_NAMESPACE, SnapshotError, _build_message, capture

from .conftest import SCHEMA, build_store


def _git(repo, *args):
    out = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return out.stdout


@pytest.fixture
def repo(tmp_path):
    """A host repo with a committed base plus a dirty working tree: one modified
    tracked file and one untracked file."""
    r = str(tmp_path / "host")
    os.makedirs(r)
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "t@t")
    _git(r, "config", "user.name", "t")
    with open(os.path.join(r, "tracked.txt"), "w") as f:
        f.write("original\n")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "init")
    with open(os.path.join(r, "tracked.txt"), "w") as f:
        f.write("modified\n")
    with open(os.path.join(r, "untracked.txt"), "w") as f:
        f.write("new file\n")
    return r


def _state(repo):
    return {
        "head": _git(repo, "rev-parse", "HEAD").strip(),
        "branches": _git(repo, "branch", "--format=%(refname)").strip(),
        "tags": _git(repo, "tag").strip(),
        "status": _git(repo, "status", "--porcelain").strip(),
    }


def test_capture_records_side_ref_without_mutating(repo):
    before = _state(repo)
    result = capture(repo, issue="disclosure mis-fires on docs")

    assert result["ref"] == f"{REF_NAMESPACE}/disclosure-mis-fires-on-docs"
    assert _state(repo) == before  # working tree / HEAD / branches / tags untouched

    # the ref resolves to the captured commit, parented on the prior HEAD
    assert _git(repo, "rev-parse", result["ref"] + "^{commit}").strip() == result["commit"]
    assert result["base"] == before["head"]
    assert _git(repo, "rev-parse", result["commit"] + "^").strip() == before["head"]


def test_capture_includes_tracked_changes_and_untracked(repo):
    result = capture(repo, issue="x")
    tree = _git(repo, "ls-tree", "-r", "--name-only", result["ref"]).split()
    assert "tracked.txt" in tree and "untracked.txt" in tree
    # the dirty (uncommitted) content is what gets captured, not the committed base
    assert _git(repo, "show", result["ref"] + ":tracked.txt") == "modified\n"
    assert _git(repo, "show", result["ref"] + ":untracked.txt") == "new file\n"


def test_ignored_files_excluded(repo):
    with open(os.path.join(repo, ".gitignore"), "w") as f:
        f.write("secret/\n")
    os.makedirs(os.path.join(repo, "secret"))
    with open(os.path.join(repo, "secret", "key.txt"), "w") as f:
        f.write("nope\n")
    result = capture(repo, issue="x")
    tree = _git(repo, "ls-tree", "-r", "--name-only", result["ref"]).split()
    assert "secret/key.txt" not in tree
    assert ".gitignore" in tree  # the ignore file itself is untracked, not ignored


def test_idempotent_per_id(repo):
    capture(repo, issue="same issue")
    with open(os.path.join(repo, "untracked.txt"), "w") as f:
        f.write("changed again\n")
    capture(repo, issue="same issue")
    refs = _git(repo, "for-each-ref", REF_NAMESPACE).strip().splitlines()
    assert len(refs) == 1  # re-flagging overwrites the single ref, no pile-up


def test_no_head_repo(tmp_path):
    r = str(tmp_path / "fresh")
    os.makedirs(r)
    _git(r, "init", "-q")
    with open(os.path.join(r, "wip.txt"), "w") as f:
        f.write("work in progress\n")
    result = capture(r, issue="x")
    assert result["base"] is None  # parentless capture on an unborn HEAD
    tree = _git(r, "ls-tree", "-r", "--name-only", result["ref"]).split()
    assert "wip.txt" in tree


def test_build_message_stamps_firing_provenance():
    msg = _build_message("firing-7", "base40", firing_id="7",
                         git_sha="a" * 40, situation="the disclosure\n  mis-fired on docs")
    assert "firing: f7" in msg
    assert "base-firing-sha: " + "a" * 40 in msg
    assert "forked-from: base40" in msg
    assert "situation: the disclosure mis-fired on docs" in msg  # collapsed fingerprint


def test_capture_with_firing_reads_provenance_via_store(repo, tmp_path):
    rows = (
        "INSERT INTO takeaways (id, created, kind, trigger_kind, one_liner) VALUES "
        "(1, '2026-01-01 10:00:00', 'gotcha', 'edit_path', 'x');\n"
        "INSERT INTO firings (id, takeaway_id, fired_at, git_sha, situation) VALUES "
        f"(7, 1, '2026-02-01 10:00:00', '{'a' * 40}', 'mis-fired on docs edits');"
    )
    store = build_store(str(tmp_path / "store"), [SCHEMA, rows])
    result = capture(repo, firing_id="7", store_path=store)

    assert result["id"] == "firing-7"
    assert result["firing_id"] == "f7"
    body = _git(repo, "log", "-1", "--format=%B", result["ref"])
    assert "firing: f7" in body
    assert "a" * 40 in body
    assert "mis-fired on docs edits" in body


def test_firing_not_in_store_raises(repo, tmp_path):
    store = build_store(str(tmp_path / "store"), [SCHEMA])
    with pytest.raises(SnapshotError):
        capture(repo, firing_id="99", store_path=store)
