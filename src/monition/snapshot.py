"""`monition snapshot` — capture a replay-ablation environment snapshot.

Records the host repo's full dirty tree (tracked + untracked; ignored files
excluded) as a throwaway commit under `refs/monition/snapshots/<id>` — a durable,
namespaced side ref that pollutes no branch or tag (spec decision 4). Capture is
stash-create-style: a tree is built from a temp index and a commit object written,
touching neither the working tree, HEAD, branches, nor tags. When an originating
firing is named, its `git_sha` (the base it forked from) and `situation`
fingerprint are stamped into the commit message, linking snapshot<->firing — the
firing's recorded provenance is only the *locator*, the snapshot itself is the
*reconstruction*.

Idempotent per `<id>`: re-flagging the same issue overwrites the single ref rather
than piling up redundant ones (spec decision 5). Deciding to flag stays a judgment
act (human or in-session LLM); the capture is automatic and complete in one call.

Store reads (the `--firing` provenance lookup) go through the single approved
reader (`store.Store`); this module issues no `dolt sql` of its own.

Known v1 limit (open question in the spec): submodules are captured as gitlink
pointers only, not their working-tree contents.

Spec: `docs/specs/2026-06-14-replay-ablation-runner.md`.
"""
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone

REF_NAMESPACE = "refs/monition/snapshots"


class SnapshotError(Exception):
    """A snapshot capture could not complete; the host repo is left untouched."""


def _git(repo_root, args, env=None, check=True):
    out = subprocess.run(["git", "-C", repo_root, *args],
                         capture_output=True, text=True, env=env)
    if check and out.returncode != 0:
        raise SnapshotError(f"git {' '.join(args)} failed: {out.stderr.strip()}")
    return out


def _slugify(text):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:48] or "issue"


def _fid(firing_id):
    """Normalize a firing id given as `3` or `f3` to the integer 3."""
    return int(str(firing_id).lstrip("tf"))


def derive_id(issue=None, firing_id=None):
    """The `<id>` that names the side ref. Firing- and issue-derived ids are
    stable (so re-flagging the same thing overwrites one ref); a bare call gets a
    fresh timestamped id."""
    if firing_id is not None:
        return f"firing-{_fid(firing_id)}"
    if issue:
        return _slugify(issue)
    return "snap-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _firing_provenance(store_path, firing_id):
    """(git_sha, situation) for the originating firing, via the approved reader."""
    from .store import Store
    fid = _fid(firing_id)
    for f in Store(store_path).firings():
        if f.id == fid:
            return f.git_sha, f.situation
    raise SnapshotError(f"no firing f{fid} in store {store_path}")


def _build_message(snap_id, base, firing_id, git_sha, situation):
    lines = [
        f"monition snapshot {snap_id}",
        "",
        "Captured dirty tree (tracked + untracked) for replay-ablation.",
        "",
    ]
    if firing_id is not None:
        lines.append(f"firing: f{_fid(firing_id)}")
    if git_sha:
        lines.append(f"base-firing-sha: {git_sha}")
    if base:
        lines.append(f"forked-from: {base}")
    if situation:
        # fingerprint only: collapse to one bounded line so the message stays a
        # locator, not a second copy of the reconstruction
        lines.append("situation: " + " ".join(situation.split())[:200])
    return "\n".join(lines) + "\n"


def capture(repo_root, *, issue=None, firing_id=None, store_path=None):
    """Capture the host repo's dirty tree to `refs/monition/snapshots/<id>`.

    Returns a dict (id, ref, commit, base, firing_id). Never mutates the working
    tree, HEAD, branches, or tags: the tree is built from a throwaway temp index
    and only the side ref is written.
    """
    repo_root = os.path.abspath(repo_root)
    head = _git(repo_root, ["rev-parse", "--verify", "-q", "HEAD"], check=False)
    base = head.stdout.strip() or None

    git_sha = situation = None
    if firing_id is not None:
        if not store_path:
            raise SnapshotError("--firing needs a store: pass --store or run inside a repo")
        git_sha, situation = _firing_provenance(store_path, firing_id)

    snap_id = derive_id(issue, firing_id)

    # Build the tree from a temp index so the real index/working tree are untouched.
    # An empty index + `add -A` stages the entire working tree (tracked + untracked,
    # honoring .gitignore) — that captured set is exactly "the dirty tree".
    tmpdir = tempfile.mkdtemp(prefix="monition-snap-")
    try:
        env = {**os.environ, "GIT_INDEX_FILE": os.path.join(tmpdir, "index")}
        _git(repo_root, ["add", "-A"], env=env)
        tree = _git(repo_root, ["write-tree"], env=env).stdout.strip()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    msg = _build_message(snap_id, base, firing_id, git_sha, situation)
    commit_args = ["commit-tree", tree, "-m", msg]
    if base:
        commit_args += ["-p", base]
    commit = _git(repo_root, commit_args).stdout.strip()

    ref = f"{REF_NAMESPACE}/{snap_id}"
    _git(repo_root, ["update-ref", ref, commit])  # idempotent per <id>: one ref
    return {
        "id": snap_id,
        "ref": ref,
        "commit": commit,
        "base": base,
        "firing_id": None if firing_id is None else f"f{_fid(firing_id)}",
    }
