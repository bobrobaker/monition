"""Hook executors — ported from CMS takeaway_fire.py / takeaway_brief.py.

`fire-hook` (PreToolUse, edit_path), `session-brief` (SessionStart), and
`prompt-hook` (UserPromptSubmit, on_demand) read the hook event JSON on stdin,
match against the host repo's Monition store at the convention path, log
firings, and print an additionalContext injection block. fire-hook and
session-brief are behavior-identical to the CMS originals except the framing
text's command hints, which name the module CLI (`monition show`/`rate`) since
the B06 cutover; prompt-hook is new (no CMS oracle).

Fail-open is two-layered (spec decisions 4 + 14): the executors swallow every
exception internally (absent store, absent dolt → silent return), and the
guarded command string below covers hard crashes — stderr lands in the
per-machine state log, the session is never blocked.
"""
import json
import os
import shlex
import subprocess
import sys

from .score import score as _score
from .store_write import WriteStore

# v5: the firing-grain situational excerpt is capped — a fingerprint of the moment,
# not the full transcript (which the session_id→archive join recovers). Generous
# enough to hold essentially any real prompt or edit excerpt.
SITUATION_CHARS = 4000

# Opt-in firing observer: a hang ceiling, not an expected latency. The session is
# never blocked on the observer (fail-open), so this only bounds a wedged command.
OBSERVER_TIMEOUT_S = 5


def _log_path():
    state = os.environ.get("XDG_STATE_HOME") or os.path.join(
        os.path.expanduser("~"), ".local", "state"
    )
    return os.path.join(state, "monition", "hook-errors.log")


def _log(msg):
    path = _log_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as f:
        f.write(msg + "\n")


def _score_takeaway(takeaway_id, store, session, firings=None):
    """Returns True (fire) or False (suppress). Fail-open on any error.

    Reuses the caller's open `store` so score() skips a redundant per-hit Dolt
    open+schema-validation (~530ms each), and the caller's pre-fetched `firings`
    so the firings table is read once per prompt, not once per hit."""
    try:
        result = _score(takeaway_id, store.path, session_id=session, store=store,
                        firings=firings)
        if result["decision"] == "suppress":
            _log(f"[suppress] t{takeaway_id} session={session}")
            return False
        return True
    except Exception as e:
        _log(f"[score-error] t{takeaway_id}: {e}")
        return True  # fail-open: error is not evidence of noise


def guarded_hook_command(subcommand):
    """The canonical command string `init` writes into settings.json hooks."""
    return (
        "command -v monition >/dev/null 2>&1 || exit 0; "
        'd="${XDG_STATE_HOME:-$HOME/.local/state}/monition"; mkdir -p "$d"; '
        f'monition {subcommand} 2>>"$d/hook-errors.log" || true'
    )


def _repo_root():
    root = os.environ.get("CLAUDE_PROJECT_DIR")
    if root:
        return root
    out = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True,
    )
    return out.stdout.strip() if out.returncode == 0 else None


def _open_store():
    # The store may be a shared hub ($MONITION_STORE) elsewhere; the host repo
    # (root) is always derived from _repo_root(), independent of store location —
    # it is what the reach filter and firing provenance key on.
    root = _repo_root()
    if not root:
        return None, None
    store = os.environ.get("MONITION_STORE") or os.path.join(root, "monition")
    return WriteStore(store), root


def _session_model(data):
    """Best-effort model id at fire time. The hook payload may carry it directly;
    otherwise fall back to the most recent assistant record in the transcript.
    None when neither is available — the column is nullable (missing, not guessed)."""
    m = data.get("model")
    if isinstance(m, dict):
        m = m.get("id") or m.get("display_name")
    if m:
        return str(m)
    tp = data.get("transcript_path")
    if tp and os.path.exists(tp):
        try:
            with open(tp, encoding="utf-8") as f:
                lines = f.readlines()
            for line in reversed(lines):
                line = line.strip()
                if not line:
                    continue
                model = (json.loads(line).get("message") or {}).get("model")
                if model:
                    return str(model)
        except Exception:
            pass
    return None


def _notify_observer(session, slug):
    """Opt-in, decoupled firing observer (one call per fired takeaway, so the
    observer's running count equals the number of firings).

    Monition ships no observer. When (and only when) MONITION_FIRING_OBSERVER names
    a command, it is invoked as `<observer> --session <session_id> --text <slug>`.
    Absent the env var this is a no-op — the convention path of a machine-local
    integration (e.g. the author's Claude Code statusline "⚑" widget) is never
    hard-coded here, keeping monition distributable.

    Fail-open in its own try/except: a bad command, a crash, or a hang (bounded by
    OBSERVER_TIMEOUT_S) is logged and swallowed, never blocking or delaying the
    firing/injection that already happened."""
    observer = os.environ.get("MONITION_FIRING_OBSERVER")
    if not observer:
        return
    try:
        cmd = shlex.split(observer) + ["--session", str(session), "--text", str(slug)]
        subprocess.run(cmd, capture_output=True, timeout=OBSERVER_TIMEOUT_S)
    except Exception as e:
        _log(f"[observer-error] {e}")


def _disclose(store, hits, trigger_kind, session, context=None, model=None,
              situation=None, current_repo=None):
    """Score-gate, log a firing, and format the injection line for each hit."""
    lines = []
    # One firings-table read per prompt, shared across every hit's score() call.
    firings = store.firings() if hits else None
    for h in hits:
        if not _score_takeaway(h["id"], store, session, firings):
            continue
        firing = store.fire(str(h["id"]), trigger_kind, session, context, model,
                            situation, current_repo=current_repo)
        fid = (firing or "").split()[-1] if firing else "?"
        _notify_observer(session, h["one_liner"])
        lines.append(f"[t{h['id']}/f{fid}] {h['one_liner']}")
    return lines


def fire_hook():
    try:
        data = json.load(sys.stdin)
        store, repo = _open_store()
        if store is None:
            return
        ti = data.get("tool_input") or {}
        fp = ti.get("file_path", "") or ""
        if not fp.startswith(repo + os.sep):
            return
        rel = os.path.relpath(fp, repo)
        session = str(data.get("session_id", "unknown"))
        # v5 situational excerpt: what the agent was about to write (Write `content`
        # / Edit `new_string`), capped. None when the tool input carries neither.
        edit = ti.get("content") or ti.get("new_string") or None
        situation = edit[:SITUATION_CHARS] if edit else None

        hits = json.loads(store.match(rel, session, current_repo=repo))
        lines = _disclose(store, hits, "edit_path", session, rel,
                          _session_model(data), situation=situation,
                          current_repo=repo)
        if not lines:
            return

        msg = (
            "Takeaways for this path (full text: monition show <t-id>; "
            "rate: monition rate <f-id> helpful|noise):\n" + "\n".join(lines)
        )
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": msg}}))
    except Exception:
        return  # fail open


def session_brief():
    try:
        data = json.load(sys.stdin)
        store, repo = _open_store()
        if store is None:
            return
        session = str(data.get("session_id", "unknown"))

        rows = json.loads(store.session_start(session, current_repo=repo))
        lines = _disclose(store, rows, "session_start", session,
                          model=_session_model(data), current_repo=repo)
        if not lines:
            return

        msg = (
            "Session-start takeaways (full text: monition show <t-id>; "
            "rate: monition rate <f-id> helpful|noise):\n" + "\n".join(lines)
        )
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": msg}}))
    except Exception:
        return  # fail open


def prompt_hook():
    try:
        data = json.load(sys.stdin)
        store, repo = _open_store()
        if store is None:
            return
        prompt = (data.get("prompt") or "").strip()
        if not prompt:
            return
        session = str(data.get("session_id", "unknown"))

        hits = json.loads(store.on_demand_match(prompt, session, current_repo=repo))
        lines = _disclose(store, hits, "on_demand", session, prompt[:200],
                          _session_model(data), situation=prompt[:SITUATION_CHARS],
                          current_repo=repo)
        if not lines:
            return

        msg = (
            "Takeaways for this prompt (full text: monition show <t-id>; "
            "rate: monition rate <f-id> helpful|noise):\n" + "\n".join(lines)
        )
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": msg}}))
    except Exception:
        return  # fail open
