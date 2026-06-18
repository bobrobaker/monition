"""`monition replay` — the per-condition replay-ablation runner.

Pins the spec's success criteria: per-condition worktrees off the snapshot,
fragment injection (with/without), branch-authoritative completion, per-condition
dirs + `summary.jsonl` carrying diff + outcome-check verdict, NO score, mandatory
isolation/teardown, and the guards (condition cap, timeout, --dry-run). The loop is
driven by `StubBackend` so the suite never spawns a real agent (spec: tests must not
burn the subscription).
"""
import json
import os
import subprocess

import pytest

from monition import backends
from monition.backends import StubBackend
from monition.replay import ReplayError, load_manifest, run_replay
from monition.snapshot import capture


def _git(repo, *args):
    out = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return out.stdout


@pytest.fixture
def repo(tmp_path):
    r = str(tmp_path / "host")
    os.makedirs(r)
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "t@t")
    _git(r, "config", "user.name", "t")
    with open(os.path.join(r, "tracked.txt"), "w") as f:
        f.write("original\n")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "init")
    # leave a dirty working tree, the realistic snapshot case
    with open(os.path.join(r, "tracked.txt"), "w") as f:
        f.write("work in progress\n")
    return r


@pytest.fixture
def snapshot_ref(repo):
    return capture(repo, issue="bug")["ref"]


MANIFEST = """\
task: |
  Fix the failing case.
model: claude-opus-4-8
fragments:
  ctx:
    path: CLAUDE.md
    content: "INJECTED-MARKER: prefer X over Y"
conditions:
  - id: with-ctx
    include: [ctx]
    check: "test -f agent_output.txt"
  - id: without-ctx
    include: []
    check: "test -f does_not_exist"
"""


@pytest.fixture
def manifest_path(tmp_path):
    p = tmp_path / "manifest.yaml"
    p.write_text(MANIFEST)
    return str(p)


def make_worker(record_calls=None):
    """A stub agent: notes whether context was injected, does a unit of work, and
    commits it to its branch (so the branch-authoritative loop sees completion)."""
    def worker(spec):
        if record_calls is not None:
            record_calls.append(spec.condition_id)
        wt = spec.worktree
        claude_md = os.path.join(wt, "CLAUDE.md")
        injected = os.path.exists(claude_md) and "INJECTED-MARKER" in open(claude_md).read()
        with open(os.path.join(wt, "agent_output.txt"), "w") as f:
            f.write(f"work by {spec.condition_id}\n")
        subprocess.run(["git", "-C", wt, "add", "-A"], check=True, capture_output=True)
        subprocess.run(["git", "-C", wt, "commit", "-q", "-m", "agent work"],
                       check=True, capture_output=True)
        os.makedirs(os.path.dirname(spec.report_path), exist_ok=True)
        with open(spec.report_path, "w") as f:
            f.write(f"injected={injected}\nSTATUS: done\n")
    return worker


def _records_by_id(result):
    return {r["condition_id"]: r for r in result["records"]}


def test_replay_loop_emits_artifacts(repo, snapshot_ref, manifest_path, tmp_path):
    out = str(tmp_path / "out")
    result = run_replay(snapshot_ref, manifest_path, out_dir=out,
                        backend=StubBackend(make_worker()), repo_root=repo)

    # summary.jsonl: one thin record per condition
    summary_text = open(os.path.join(out, "summary.jsonl")).read()
    lines = summary_text.strip().splitlines()
    assert len(lines) == 2
    recs = _records_by_id(result)

    with_ctx, without = recs["with-ctx"], recs["without-ctx"]
    assert with_ctx["status"] == "completed" and with_ctx["completed_by"] == "branch"
    assert with_ctx["included_fragments"] == ["ctx"]
    assert without["included_fragments"] == []

    # outcome-check verdicts: exit-code authoritative
    assert with_ctx["verdict"]["passed"] is True
    assert without["verdict"]["passed"] is False

    # the runner computes NO score (G2)
    assert "score" not in summary_text
    for r in result["records"]:
        assert "score" not in r and "score" not in r["verdict"]


def test_fragment_injection_is_with_or_without(repo, snapshot_ref, manifest_path, tmp_path):
    out = str(tmp_path / "out")
    run_replay(snapshot_ref, manifest_path, out_dir=out,
               backend=StubBackend(make_worker()), repo_root=repo)
    with_report = open(os.path.join(out, "with-ctx", "report.txt")).read()
    without_report = open(os.path.join(out, "without-ctx", "report.txt")).read()
    assert "injected=True" in with_report
    assert "injected=False" in without_report


def test_diff_is_agent_work_only_injection_frozen_in_base(repo, snapshot_ref,
                                                          manifest_path, tmp_path):
    out = str(tmp_path / "out")
    run_replay(snapshot_ref, manifest_path, out_dir=out,
               backend=StubBackend(make_worker()), repo_root=repo)
    diff = open(os.path.join(out, "with-ctx", "diff.patch")).read()
    assert "agent_output.txt" in diff          # the agent's committed work
    assert "INJECTED-MARKER" not in diff        # injected context is in the base, not the diff


def test_isolation_and_teardown(repo, snapshot_ref, manifest_path, tmp_path):
    before_status = _git(repo, "status", "--porcelain")
    before_worktrees = _git(repo, "worktree", "list")
    run_replay(snapshot_ref, manifest_path, out_dir=str(tmp_path / "out"),
               backend=StubBackend(make_worker()), repo_root=repo)

    # host working tree untouched; worktrees + condition branches all torn down
    assert _git(repo, "status", "--porcelain") == before_status
    assert _git(repo, "worktree", "list") == before_worktrees
    assert "monition/replay/" not in _git(repo, "branch", "-a")


def test_condition_cap_blocks_before_spawn(repo, snapshot_ref, tmp_path):
    big = tmp_path / "big.yaml"
    big.write_text(
        "task: t\nmodel: m\nconditions:\n"
        + "".join(f"  - id: c{i}\n    check: 'true'\n" for i in range(3)))
    calls = []
    with pytest.raises(ReplayError, match="exceeds the cap"):
        run_replay(snapshot_ref, str(big), out_dir=str(tmp_path / "out"),
                   backend=StubBackend(make_worker(calls)), repo_root=repo,
                   max_conditions=2)
    assert calls == []  # never spawned


def test_dry_run_lists_without_spawning(repo, snapshot_ref, manifest_path, tmp_path):
    out = tmp_path / "out"
    calls = []
    result = run_replay(snapshot_ref, manifest_path, out_dir=str(out), dry_run=True,
                        backend=StubBackend(make_worker(calls)), repo_root=repo)
    assert result["dry_run"] is True
    assert {c["condition_id"] for c in result["conditions"]} == {"with-ctx", "without-ctx"}
    assert calls == []                       # no agent spawned
    assert not os.path.exists(out / "summary.jsonl")  # no artifacts written
    assert "monition/replay/" not in _git(repo, "branch", "-a")  # no worktree/branch


def test_timeout_when_branch_never_advances(repo, snapshot_ref, manifest_path, tmp_path):
    def idle_worker(spec):
        pass  # does no work, makes no commit, writes no report
    result = run_replay(snapshot_ref, manifest_path, out_dir=str(tmp_path / "out"),
                        backend=StubBackend(idle_worker), repo_root=repo, timeout=0.01)
    for r in result["records"]:
        assert r["status"] == "timeout"
        assert r["completed_by"] is None


def test_second_backend_registers_without_touching_core(repo, snapshot_ref,
                                                        manifest_path, tmp_path):
    backends.register_backend("spy-stub", lambda: StubBackend(make_worker()))
    result = run_replay(snapshot_ref, manifest_path, out_dir=str(tmp_path / "out"),
                        backend_name="spy-stub", repo_root=repo)
    assert len(result["records"]) == 2


def test_parallel_runs_all_conditions(repo, snapshot_ref, manifest_path, tmp_path):
    result = run_replay(snapshot_ref, manifest_path, out_dir=str(tmp_path / "out"),
                        backend=StubBackend(make_worker()), repo_root=repo, parallel=2)
    assert {r["condition_id"] for r in result["records"]} == {"with-ctx", "without-ctx"}
    assert all(r["status"] == "completed" for r in result["records"])


# --- manifest validation -------------------------------------------------- #

def test_tmux_backend_command_is_autonomous_and_logged():
    """The live-path command (not run in tests) pins the model, bypasses claude's
    permission gates so it runs unattended, stays off `-p`, and tees output to the
    condition log. Guards the fix found in live validation (2026-06-14)."""
    from monition.backends import TmuxBackend
    from monition.replay import RunSpec
    spec = RunSpec(condition_id="c", worktree="/wt", branch="b", base_commit="x",
                   model="claude-haiku-4-5-20251001", prompt="p",
                   prompt_path="/out/c/prompt.txt", report_path="/out/c/report.txt",
                   check=None, timeout=1.0, log_path="/out/c/agent.log")
    cmd = TmuxBackend()._shell_cmd(spec)
    assert "--model claude-haiku-4-5-20251001" in cmd
    assert "--dangerously-skip-permissions" in cmd
    assert " -- " in cmd  # end-of-options: a prompt starting with --- is positional
    assert " -p" not in cmd and "--print" not in cmd
    assert "/out/c/agent.log" in cmd and "2>&1" in cmd
    # opt-out leaves the gates in place
    assert "--dangerously-skip-permissions" not in TmuxBackend(skip_permissions=False)._shell_cmd(spec)


def test_manifest_requires_model(tmp_path):
    p = tmp_path / "m.yaml"
    p.write_text("task: t\nconditions:\n  - id: a\n")
    with pytest.raises(ReplayError, match="model"):
        load_manifest(str(p))


def test_manifest_rejects_unknown_fragment(tmp_path):
    p = tmp_path / "m.yaml"
    p.write_text("task: t\nmodel: m\nconditions:\n  - id: a\n    include: [ghost]\n")
    with pytest.raises(ReplayError, match="unknown fragment"):
        load_manifest(str(p))


def test_manifest_rejects_duplicate_condition_id(tmp_path):
    p = tmp_path / "m.yaml"
    p.write_text("task: t\nmodel: m\nconditions:\n  - id: a\n  - id: a\n")
    with pytest.raises(ReplayError, match="duplicate"):
        load_manifest(str(p))
