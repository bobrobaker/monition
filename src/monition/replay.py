"""`monition replay` — the per-condition replay-ablation runner.

Given a captured snapshot ref and a YAML conditions-manifest, the runner
materializes a discardable worktree per condition off the snapshot, injects that
condition's context fragments (everything not listed is withheld), runs the task
on a real interactive Claude agent via a pluggable backend, and records a
structured per-condition artifact: the worktree diff + the outcome-check verdict +
the agent's advisory report. It computes **no score** (G2) — a tier-2 caller reads
the cross-condition difference directly; a tier-3 caller (CMS) feeds the artifacts
to its rubric.

Per-condition isolation is mandatory (spec decision 8): each condition gets its own
worktree on its own branch forked from the snapshot, auto-cleaned after harvest, so
one run cannot mutate the host repo or another condition's state. To keep the
harvested diff the *agent's* work alone, the materialized env + injected context are
frozen as a pre-agent base commit; the diff is taken from there.

Format split mirrors the repo: YAML manifest in, JSONL summary out (like
`export-firings`). Bulky diffs/logs stay in per-condition directories; the
top-level `summary.jsonl` stays thin and version-stamped (additive-column
discipline). Spec: `docs/specs/2026-06-14-replay-ablation-runner.md`.
"""
import json
import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

from .backends import BackendError, get_backend

REPLAY_SCHEMA_VERSION = 1
DEFAULT_CONDITION_CAP = 8          # spec decision 7 (overridable)
DEFAULT_RUN_TIMEOUT = 1800.0       # per-run wall-clock bound, seconds
MAX_PARALLEL = 4                   # ceiling on --parallel N (subscription caps)
POLL_INTERVAL = 2.0                # seconds between completion polls

# git worktree add/remove are not concurrency-safe (they lock $GIT_DIR/worktrees);
# serialize just those quick ops so --parallel keeps the agent runs concurrent
# without racing the worktree table.
_WORKTREE_LOCK = threading.Lock()

REPORT_NAME = "report.txt"
DIFF_NAME = "diff.patch"
VERDICT_NAME = "verdict.json"
PROMPT_NAME = "prompt.txt"
LOG_NAME = "agent.log"

WORKER_PROTOCOL = """\
[monition replay worker protocol]
You are an isolated worker in a throwaway git worktree on branch `{branch}`, forked
from a captured environment snapshot. Do the task below, then:
  1. Commit your work to this branch (`git commit`), honoring any pre-commit hooks.
     The branch is the authoritative record of your work; uncommitted changes are
     not harvested.
  2. Write a short report of what you did to exactly this path:
       {report_path}
  3. End your final message with a line beginning `STATUS:` (e.g. `STATUS: done`).
Do not push and do not touch any path outside this worktree except the report path.

[task]
{task}
"""


class ReplayError(Exception):
    """A replay could not run; the host repo is left uncorrupted."""


@dataclass
class Condition:
    id: str
    include: List[str]
    check: Optional[str]


@dataclass
class Manifest:
    task: str
    model: str
    fragments: dict
    conditions: List[Condition]
    setup: Optional[str] = None


@dataclass
class RunSpec:
    condition_id: str
    worktree: Optional[str]
    branch: str
    base_commit: str          # the pre-agent base (set after env/context freeze)
    model: str
    prompt: str
    prompt_path: str
    report_path: str
    check: Optional[str]
    timeout: float
    include: List[str] = field(default_factory=list)
    log_path: Optional[str] = None


# --------------------------------------------------------------------------- #
# manifest
# --------------------------------------------------------------------------- #

_ID_OK = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")


def _safe_id(cid):
    if not cid or any(c not in _ID_OK for c in cid):
        raise ReplayError(
            f"condition id '{cid}' must be non-empty and use only "
            "[A-Za-z0-9._-] (it names a branch and a directory)")
    return cid


def _parse_fragments(raw):
    if not isinstance(raw, dict):
        raise ReplayError("manifest: `fragments` must be a mapping of id -> {path, content}")
    out = {}
    for fid, body in raw.items():
        if not isinstance(body, dict) or "path" not in body or "content" not in body:
            raise ReplayError(f"manifest: fragment '{fid}' needs `path` and `content`")
        mode = body.get("mode", "append")
        if mode not in ("append", "write"):
            raise ReplayError(f"manifest: fragment '{fid}' mode must be 'append' or 'write'")
        out[str(fid)] = {"path": str(body["path"]),
                         "content": str(body["content"]), "mode": mode}
    return out


def _parse_conditions(raw, fragments):
    if not isinstance(raw, list) or not raw:
        raise ReplayError("manifest: `conditions` must be a non-empty list")
    seen, out = set(), []
    for i, c in enumerate(raw):
        if not isinstance(c, dict) or "id" not in c:
            raise ReplayError(f"manifest: condition #{i} needs an `id`")
        cid = _safe_id(str(c["id"]))
        if cid in seen:
            raise ReplayError(f"manifest: duplicate condition id '{cid}'")
        seen.add(cid)
        include = c.get("include") or []
        if not isinstance(include, list):
            raise ReplayError(f"manifest: condition '{cid}' `include` must be a list")
        unknown = [f for f in include if str(f) not in fragments]
        if unknown:
            raise ReplayError(
                f"manifest: condition '{cid}' includes unknown fragment(s): "
                + ", ".join(unknown))
        out.append(Condition(id=cid, include=[str(f) for f in include],
                              check=c.get("check")))
    return out


def load_manifest(path):
    """Parse the YAML conditions-manifest. Lazy-imports PyYAML so only `replay`
    pays for it (parallel to how mcp/embed are optional)."""
    try:
        import yaml
    except ImportError:
        raise ReplayError("`monition replay` needs PyYAML: pip install pyyaml")
    try:
        with open(path) as f:
            raw = yaml.safe_load(f)
    except FileNotFoundError:
        raise ReplayError(f"manifest not found: {path}")
    except yaml.YAMLError as e:
        raise ReplayError(f"manifest is not valid YAML: {e}")
    if not isinstance(raw, dict):
        raise ReplayError("manifest must be a YAML mapping")
    task, model = raw.get("task"), raw.get("model")
    if not task or not str(task).strip():
        raise ReplayError("manifest: `task` is required")
    if not model:
        raise ReplayError("manifest: `model` is required (the pin for cross-condition comparability)")
    fragments = _parse_fragments(raw.get("fragments") or {})
    conditions = _parse_conditions(raw.get("conditions") or [], fragments)
    return Manifest(task=str(task), model=str(model), fragments=fragments,
                    conditions=conditions, setup=raw.get("setup"))


# --------------------------------------------------------------------------- #
# git helpers
# --------------------------------------------------------------------------- #

def _git(cwd, args, env=None, check=True):
    out = subprocess.run(["git", "-C", cwd, *args],
                         capture_output=True, text=True, env=env)
    if check and out.returncode != 0:
        raise ReplayError(f"git {' '.join(args)} failed: {out.stderr.strip()}")
    return out


def _resolve_ref(repo_root, ref):
    out = _git(repo_root, ["rev-parse", "--verify", "-q", f"{ref}^{{commit}}"], check=False)
    sha = out.stdout.strip()
    if not sha:
        raise ReplayError(f"snapshot ref not found: {ref} (did you run `monition snapshot`?)")
    return sha


def _git_root_or_die(repo_root):
    if repo_root:
        return os.path.abspath(repo_root)
    out = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                         capture_output=True, text=True)
    if out.returncode != 0:
        raise ReplayError("not in a git repo: run `monition replay` from the host repo")
    return out.stdout.strip()


def _utc_stamp():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# per-condition lifecycle
# --------------------------------------------------------------------------- #

def _build_prompt(task, branch, report_path):
    return WORKER_PROTOCOL.format(branch=branch, report_path=report_path, task=task)


def _build_spec(cond, manifest, snapshot_commit, run_id, out_dir, wt_root, timeout):
    cdir = os.path.join(out_dir, cond.id)
    worktree = None if wt_root is None else os.path.join(wt_root, cond.id)
    branch = f"monition/replay/{run_id}/{cond.id}"
    report_path = os.path.join(cdir, REPORT_NAME)
    prompt_path = os.path.join(cdir, PROMPT_NAME)
    log_path = os.path.join(cdir, LOG_NAME)
    return RunSpec(
        condition_id=cond.id, worktree=worktree, branch=branch,
        base_commit=snapshot_commit, model=manifest.model,
        prompt=_build_prompt(manifest.task, branch, report_path),
        prompt_path=prompt_path, report_path=report_path,
        check=cond.check, timeout=timeout, include=list(cond.include),
        log_path=log_path)


def _inject_fragments(manifest, spec):
    """Write each included fragment into the worktree (everything else withheld).
    `append` (default) adds to any existing file; `write` overwrites it."""
    wt = os.path.realpath(spec.worktree)
    for fid in spec.include:
        frag = manifest.fragments[fid]
        target = os.path.realpath(os.path.join(spec.worktree, frag["path"]))
        if target != wt and not target.startswith(wt + os.sep):
            raise ReplayError(
                f"fragment '{fid}' path escapes the worktree: {frag['path']}")
        os.makedirs(os.path.dirname(target) or wt, exist_ok=True)
        content = frag["content"]
        if frag["mode"] == "write":
            with open(target, "w") as f:
                f.write(content)
        else:
            existing = ""
            if os.path.exists(target):
                with open(target) as f:
                    existing = f.read()
            sep = "" if (not existing or existing.endswith("\n")) else "\n"
            tail = "" if content.endswith("\n") else "\n"
            with open(target, "a") as f:
                f.write(sep + content + tail)


def _freeze_base(spec):
    """Commit the materialized env + injected context as the pre-agent base, so the
    harvested diff is the agent's work alone. Returns the frozen HEAD sha."""
    st = subprocess.run(["git", "-C", spec.worktree, "status", "--porcelain"],
                        capture_output=True, text=True)
    if st.stdout.strip():
        _git(spec.worktree, ["add", "-A"])
        _git(spec.worktree, ["-c", "user.email=monition@local",
                             "-c", "user.name=monition", "commit", "--no-verify",
                             "-q", "-m",
                             f"monition replay: materialize condition {spec.condition_id}"])
    return _git(spec.worktree, ["rev-parse", "HEAD"]).stdout.strip()


def _await_completion(backend, spec):
    deadline = time.monotonic() + spec.timeout
    while True:
        done = backend.is_done(spec)
        if done:
            return done
        if time.monotonic() >= deadline:
            return None
        time.sleep(POLL_INTERVAL)


def _run_check(spec):
    out = subprocess.run(spec.check, shell=True, cwd=spec.worktree,
                         capture_output=True, text=True)
    return {"command": spec.check, "exit_code": out.returncode,
            "passed": out.returncode == 0,
            "stdout": out.stdout[-4000:], "stderr": out.stderr[-4000:]}


def _sweep_run(repo_root, wt_root, run_id):
    """Best-effort removal of a whole run's worktrees + branches. The per-condition
    `finally` handles the normal/timeout/error paths; this exists for the signal
    path, where a hard kill bypasses `finally` and would otherwise orphan them
    (found in live validation 2026-06-14). Sweeping by `wt_root` + `run_id` prefix
    cleans every condition regardless of which were mid-flight."""
    if wt_root:
        shutil.rmtree(wt_root, ignore_errors=True)
    subprocess.run(["git", "-C", repo_root, "worktree", "prune"],
                   capture_output=True, text=True)
    out = subprocess.run(["git", "-C", repo_root, "branch", "--list",
                          f"monition/replay/{run_id}/*"], capture_output=True, text=True)
    for b in out.stdout.split():
        subprocess.run(["git", "-C", repo_root, "branch", "-D", b],
                       capture_output=True, text=True)


def _cleanup(repo_root, spec):
    if not spec.worktree:
        return
    with _WORKTREE_LOCK:
        subprocess.run(["git", "-C", repo_root, "worktree", "remove", "--force", spec.worktree],
                       capture_output=True, text=True)
        subprocess.run(["git", "-C", repo_root, "branch", "-D", spec.branch],
                       capture_output=True, text=True)


def _run_condition(repo_root, snapshot_commit, snapshot_ref, manifest, spec,
                   backend, out_dir):
    cdir = os.path.dirname(spec.report_path)
    os.makedirs(cdir, exist_ok=True)
    started = _utc_now()
    status, completed_by, error, verdict = "error", None, None, None
    head_commit = snapshot_commit
    diff = ""
    try:
        with _WORKTREE_LOCK:
            _git(repo_root, ["worktree", "add", "--quiet", "-b", spec.branch,
                             spec.worktree, snapshot_commit])
        if manifest.setup:
            subprocess.run(manifest.setup, shell=True, cwd=spec.worktree,
                           capture_output=True, text=True)
        _inject_fragments(manifest, spec)
        spec.base_commit = _freeze_base(spec)   # pre-agent base for diff + is_done

        backend.spawn(spec)
        completed_by = _await_completion(backend, spec)
        status = "completed" if completed_by else "timeout"

        head_commit = _git(spec.worktree, ["rev-parse", "HEAD"]).stdout.strip()
        diff = _git(repo_root, ["diff", spec.base_commit, head_commit]).stdout
        if spec.check:
            verdict = _run_check(spec)
    except Exception as e:  # never let one condition corrupt the host or the run
        error = str(e)
        status = "error"
    finally:
        try:
            backend.teardown(spec)
        except Exception:
            pass
        _cleanup(repo_root, spec)

    diff_path = os.path.join(cdir, DIFF_NAME)
    with open(diff_path, "w") as f:
        f.write(diff)
    if verdict is not None:
        with open(os.path.join(cdir, VERDICT_NAME), "w") as f:
            json.dump(verdict, f, indent=2)

    return {
        "schema_version": REPLAY_SCHEMA_VERSION,
        "condition_id": spec.condition_id,
        "snapshot_ref": snapshot_ref,
        "base_commit": spec.base_commit,
        "branch": spec.branch,
        "head_commit": head_commit,
        "model": spec.model,
        "included_fragments": spec.include,
        "status": status,                 # completed | timeout | error
        "completed_by": completed_by,     # branch | report | None
        "diff_path": os.path.relpath(diff_path, out_dir),
        "report_path": (os.path.relpath(spec.report_path, out_dir)
                        if os.path.exists(spec.report_path) else None),
        "log_path": (os.path.relpath(spec.log_path, out_dir)
                     if spec.log_path and os.path.exists(spec.log_path) else None),
        "verdict": verdict,               # {command, exit_code, passed, ...} | None
        "error": error,
        "started_at": started,
        "ended_at": _utc_now(),
        # no score: the runner stops at artifacts (G2)
    }


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #

def _dry_run_report(snapshot_ref, snapshot_commit, manifest, specs, out_dir, parallel):
    return {
        "dry_run": True,
        "snapshot_ref": snapshot_ref,
        "base_commit": snapshot_commit,
        "out_dir": out_dir,
        "model": manifest.model,
        "parallel": parallel,
        "conditions": [
            {"condition_id": s.condition_id, "branch": s.branch,
             "included_fragments": s.include, "check": s.check}
            for s in specs
        ],
    }


def run_replay(snapshot_ref, manifest_path, *, out_dir=None, parallel=1,
               dry_run=False, backend=None, backend_name="tmux", repo_root=None,
               max_conditions=DEFAULT_CONDITION_CAP, timeout=DEFAULT_RUN_TIMEOUT):
    """Vary the manifest's conditions over the snapshot and emit per-condition
    artifacts. `backend` (an instance) overrides `backend_name` lookup — the test
    seam. Returns a dict; for `dry_run`, a plan with no side effects on git."""
    repo_root = _git_root_or_die(repo_root)
    manifest = load_manifest(manifest_path)
    n = len(manifest.conditions)
    if n > max_conditions:
        raise ReplayError(
            f"{n} conditions exceeds the cap of {max_conditions}; raise "
            "--max-conditions to override (the cap bounds subscription burn)")
    snapshot_commit = _resolve_ref(repo_root, snapshot_ref)
    run_id = _utc_stamp()
    out_dir = os.path.abspath(out_dir or os.path.join(repo_root, "monition-replay", run_id))
    parallel = max(1, min(parallel, MAX_PARALLEL, n))

    wt_root = None if dry_run else tempfile.mkdtemp(prefix="monition-replay-")
    specs = [_build_spec(c, manifest, snapshot_commit, run_id, out_dir, wt_root, timeout)
             for c in manifest.conditions]

    if dry_run:
        return _dry_run_report(snapshot_ref, snapshot_commit, manifest, specs, out_dir, parallel)

    if backend is None:
        backend = get_backend(backend_name)
    backend.preflight()  # fail clearly before any worktree is created
    os.makedirs(out_dir, exist_ok=True)

    def work(spec):
        return _run_condition(repo_root, snapshot_commit, snapshot_ref,
                              manifest, spec, backend, out_dir)

    # Harden against a hard kill: SIGINT/SIGTERM bypasses the per-condition `finally`,
    # so sweep this run's worktrees+branches before re-raising the default action.
    prev_handlers = {}

    def _on_signal(signum, _frame):
        _sweep_run(repo_root, wt_root, run_id)
        signal.signal(signum, signal.SIG_DFL)
        os.kill(os.getpid(), signum)
    for _sig in (signal.SIGINT, signal.SIGTERM):
        try:
            prev_handlers[_sig] = signal.signal(_sig, _on_signal)
        except ValueError:
            pass  # not the main thread (e.g. a worker/test caller) — skip handlers
    try:
        if parallel == 1:
            records = [work(s) for s in specs]
        else:
            with ThreadPoolExecutor(max_workers=parallel) as ex:
                records = list(ex.map(work, specs))
    finally:
        shutil.rmtree(wt_root, ignore_errors=True)
        for _sig, _h in prev_handlers.items():
            signal.signal(_sig, _h)

    summary_path = os.path.join(out_dir, "summary.jsonl")
    with open(summary_path, "w") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return {"out_dir": out_dir, "summary": summary_path, "snapshot_ref": snapshot_ref,
            "base_commit": snapshot_commit, "records": records}
