"""Execution-backend seam for the replay-ablation runner (spec decision 6).

The runner core (`replay.py`) owns the wide, generic part: worktree lifecycle,
fragment injection, branch-authoritative completion detection, diff harvest,
outcome-check, and teardown. A *backend* owns only the narrow act the core can't
do generically — launching a real agent inside a condition's worktree and tearing
its session down. Keeping the seam this small is the point: a matured
GUI or hosted-agent backend can be registered later without reworking the
core.

Backends:
- `TmuxBackend` (default, name "tmux"): a real interactive `claude` — never
  `claude -p` — in a detached tmux session inside the worktree, model pinned, on
  the subscription billing bucket (spec decision 2). Prereq-checked; the live path
  is exercised by hand, while the runner loop is covered in tests by `StubBackend`
  so the suite never spawns a real agent or burns the subscription.
- `StubBackend`: drives a caller-supplied `worker(spec)` synchronously in place of
  a real agent — the test seam proving the loop is backend-agnostic.

Completion is branch-authoritative (spec decision 3): `is_done` defaults to "a new
commit on the condition branch => done; else a stable non-empty report file =>
done". The branch is authoritative, the report advisory. The default lives on the
base class so every backend inherits it; a future backend that knows its own
completion signal may override it.
"""
import os
import shlex
import shutil
import subprocess


class BackendError(Exception):
    """A backend could not start (missing prereq) or failed to spawn."""


def _head(worktree):
    out = subprocess.run(["git", "-C", worktree, "rev-parse", "HEAD"],
                         capture_output=True, text=True)
    return out.stdout.strip() if out.returncode == 0 else None


def _report_ready(path):
    try:
        return os.path.getsize(path) > 0
    except OSError:
        return False


class Backend:
    """Base backend. Subclasses must implement `spawn`; the rest have defaults."""

    name = "base"

    def preflight(self):
        """Raise BackendError if prerequisites are missing. Default: no-op."""

    def spawn(self, spec):
        raise NotImplementedError

    def is_done(self, spec):
        """Branch-authoritative completion. Returns 'branch', 'report', or None."""
        if _head(spec.worktree) != spec.base_commit:
            return "branch"
        if _report_ready(spec.report_path):
            return "report"
        return None

    def teardown(self, spec):
        """Release the agent session. Default: no-op."""


class TmuxBackend(Backend):
    """Interactive `claude` (no `-p`) in a detached tmux session per condition."""

    name = "tmux"

    def __init__(self, skip_permissions=True):
        self._sessions = {}
        # An unattended agent in a fresh worktree hits claude's workspace-trust
        # dialog and per-tool approval prompts with no one to answer, so it blocks at
        # the gate and never does the task (found in live validation 2026-06-14).
        # Bypassing them is what makes the runner autonomous; it is safe *here*
        # precisely because each condition runs in a disposable, isolated worktree off
        # the snapshot, auto-torn-down (spec decision 8) — the sandbox the "dangerous"
        # flag's warning assumes is missing. Opt out with skip_permissions=False.
        self.skip_permissions = skip_permissions

    def preflight(self):
        for tool in ("tmux", "claude"):
            if shutil.which(tool) is None:
                raise BackendError(
                    f"backend 'tmux' needs `{tool}` on PATH; not found. monition "
                    "replay never falls back to `claude -p` — that draws the metered "
                    "programmatic credit bucket, not the subscription (spec decision 2)."
                )

    def _session(self, spec):
        return f"monition-replay-{spec.condition_id}"

    def _shell_cmd(self, spec):
        """The shell command tmux execs. Seeds the prompt from a file so the
        multi-line worker protocol survives the tmux/shell arg boundary; pins the
        model for cross-condition comparability; stays interactive (no -p) on the
        subscription bucket; bypasses permission gates so the agent runs unattended;
        tees output to the condition log so a stuck agent leaves a trace instead of
        dying silently with the pane."""
        perms = "--dangerously-skip-permissions " if self.skip_permissions else ""
        # `--` ends option parsing so a prompt that begins with `-`/`---` (the worker
        # protocol header) is taken as the positional prompt, not an unknown flag
        # (found in live validation 2026-06-14).
        cmd = (f"claude --model {shlex.quote(spec.model)} {perms}-- "
               f'"$(cat {shlex.quote(spec.prompt_path)})"')
        if spec.log_path:
            cmd += f" > {shlex.quote(spec.log_path)} 2>&1"
        return cmd

    def spawn(self, spec):
        for p in (spec.prompt_path, spec.log_path):
            if p:
                os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(spec.prompt_path, "w") as f:
            f.write(spec.prompt)
        session = self._session(spec)
        cmd = ["tmux", "new-session", "-d", "-s", session,
               "-c", spec.worktree, "sh", "-c", self._shell_cmd(spec)]
        out = subprocess.run(cmd, capture_output=True, text=True)
        if out.returncode != 0:
            raise BackendError(f"tmux spawn failed: {out.stderr.strip()}")
        self._sessions[spec.condition_id] = session

    def teardown(self, spec):
        session = self._sessions.pop(spec.condition_id, self._session(spec))
        subprocess.run(["tmux", "kill-session", "-t", session],
                       capture_output=True, text=True)


class StubBackend(Backend):
    """Test seam: runs `worker(spec)` synchronously in place of a real agent, so by
    the time the core polls `is_done` the simulated work is already on the branch."""

    name = "stub"

    def __init__(self, worker):
        self._worker = worker

    def spawn(self, spec):
        self._worker(spec)


_REGISTRY = {"tmux": TmuxBackend}


def register_backend(name, factory):
    """Register a backend factory under `name` (callable() -> Backend)."""
    _REGISTRY[name] = factory


def get_backend(name):
    try:
        return _REGISTRY[name]()
    except KeyError:
        known = ", ".join(sorted(_REGISTRY))
        raise BackendError(f"unknown backend '{name}'; known: {known}")
