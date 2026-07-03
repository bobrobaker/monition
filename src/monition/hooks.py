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

MONITION_DISABLE (any non-empty value) opts a single invocation out of all
three executors — see _disabled().
"""
import json
import os
import shlex
import subprocess
import sys

from . import session_state, trace
from .score import score as _score
from .store_write import WriteStore

# v5: the firing-grain situational excerpt is capped — a fingerprint of the moment,
# not the full transcript (which the session_id→archive join recovers). Generous
# enough to hold essentially any real prompt or edit excerpt.
SITUATION_CHARS = 4000

# (The opt-in firing observer is fire-and-forget — see _notify_observer.)


def _log_path():
    state = os.environ.get("XDG_STATE_HOME") or os.path.join(
        os.path.expanduser("~"), ".local", "state"
    )
    return os.path.join(state, "monition", "hook-errors.log")


# The state log is append-per-event with no reader-driven bound, so the writer
# owns rotation: current + one .1 generation ≈ 2×MAX on disk, worst case.
LOG_MAX_BYTES = 5 * 1024 * 1024


def _log(msg):
    path = _log_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        if os.path.getsize(path) > LOG_MAX_BYTES:
            os.replace(path, path + ".1")
    except OSError:
        pass
    with open(path, "a") as f:
        f.write(msg + "\n")


def _score_takeaway(takeaway_id, store, session, firings=None):
    """Score one takeaway and return its decision dict, WITHOUT writing the decision
    row (the caller batches a whole prompt's decision writes into one INSERT).
    Returns None on error — fail-open: the caller fires and writes no decision row,
    matching the pre-batch behavior where a score() exception persisted nothing.

    Reuses the caller's open `store` so score() skips a redundant per-hit Dolt
    open+schema-validation (~530ms each), and the caller's pre-fetched `firings`
    so the firings table is read once per prompt, not once per hit."""
    try:
        return _score(takeaway_id, store.path, session_id=session, store=store,
                      firings=firings, defer_write=True)
    except Exception as e:
        _log(f"[score-error] t{takeaway_id}: {e}")
        return None  # fail-open: error is not evidence of noise


# Harness-generated prompts arrive through the same UserPromptSubmit event as
# a human-typed prompt but were never typed by anyone — a subagent's
# completion notice, most visibly. These match stored takeaways just as
# readily as real questions, so on a broad session they saturate the
# injection cap turn after turn and — worse — get batch-rated "noise" by
# whoever is clearing the cap, corrupting the eval substrate for whichever
# rows happened to co-fire in that batch (t91-t98, see
# docs/decisions/2026-07-02-boilerplate-prompt-gate.md).
#
# Deliberately narrow and evidenced, not a generic "looks systemy" heuristic:
# a prefix match only, checked against the live hub store's `firings.situation`
# for on_demand rows. `<task-notification>` is the one shape with real volume
# (837 of 5,878 on_demand firings, ~14%, all sharing this exact opening tag —
# Task-tool completion notices). Other candidate shapes considered and
# rejected for lack of a repeatable evidenced prefix: a `<command-name>/clear
# </command-name>`-bearing "Summarise the session transcript..." dump appeared
# under only 2 distinct sessions (6 firings) with no stable opening prefix,
# and no other tag (`<local-command-*>`, `<bash-*>`, `<monitor-*>`, `Caveat:`,
# "This session is being continued") appears at all in the hub. Add a prefix
# here only once it clears the same bar: a real, repeatable opening string in
# `firings.situation`/`trigger_context`, not a guess.
#
# A prefix check, not a substring/contains check: a human prompt that merely
# *mentions* a task-notification example mid-text is real user content, not
# boilerplate, and must still be matched.
#
# B04: the prefix tuple's source of truth moved to the cascade skeleton
# (relevance/cascade.py BOILERPLATE_PREFIXES — the gate resident); this
# delegation keeps the pre-match position and the evidence bar above. Lazy
# import: only prompt_hook pays it, never fire-hook/session-brief.
def _is_boilerplate(prompt):
    from .relevance.cascade import BOILERPLATE_PREFIXES
    return prompt.startswith(BOILERPLATE_PREFIXES)


def _disabled():
    """Explicit per-invocation opt-out: any non-empty MONITION_DISABLE suppresses
    matching, injection, AND firing capture — meant for API-style headless runs
    (`MONITION_DISABLE=1 claude -p ...`) where hook latency and firing-log noise
    are unwanted. The guarded command short-circuits in the shell before Python
    starts; this check covers hosts whose settings predate that template. Scoped
    to the hook executors only — the CLI and reader ignore it."""
    return bool(os.environ.get("MONITION_DISABLE"))


def guarded_hook_command(subcommand):
    """The canonical command string `init` writes into settings.json hooks."""
    return (
        '[ -z "$MONITION_DISABLE" ] || exit 0; '
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

    Fail-open in its own try/except: a bad command or a crash is logged and
    swallowed. Fire-and-forget (Phase 8): the hook never waits on the observer —
    a wedged observer costs the session nothing, and the hook process exits
    right after, reparenting the child to init for reaping."""
    observer = os.environ.get("MONITION_FIRING_OBSERVER")
    if not observer:
        return
    try:
        cmd = shlex.split(observer) + ["--session", str(session), "--text", str(slug)]
        subprocess.Popen(cmd, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        _log(f"[observer-error] {e}")


def _disclose(store, hits, trigger_kind, session, context=None, model=None,
              situation=None, current_repo=None, scores=None, head_version=None):
    """Score-gate, log a firing, and format the injection line for each hit.

    `scores`: {takeaway_id: P(helpful)} from the cascade head, logged onto each
    firing (v9, contract relevance-cascade.md §3); None off the passive path."""
    lines = []
    # One firings-table read per prompt, shared across every hit's score() call.
    firings = store.firings() if hits else None
    decisions = []  # batched to one INSERT after the loop (lever 3)
    to_fire = []
    for h in hits:
        result = _score_takeaway(h["id"], store, session, firings)
        if result is not None:
            decisions.append((h["id"], session, result["decision"],
                              result["evidence_count"], result["cold_start"],
                              result["ev_score"]))
            if result["decision"] == "suppress":
                # No log line: the decision row (decision + cold_start +
                # evidence_count) already records this; routine suppressions
                # were drowning real errors in hook-errors.log.
                continue
        # result is None → fail-open fire (no decision row); else decision == 'fire'
        to_fire.append(h)
    # One INSERT + one read-back for the whole prompt (Phase 8 — fire() costs
    # 3 subprocesses per hit). Fail-open: any batch problem falls back to the
    # slow-but-proven per-hit path; firings are never dropped silently.
    fids = None
    score_of = (scores or {}).get
    if to_fire:
        try:
            fids = store.fire_batch(
                [(str(h["id"]), h.get("evidence"), score_of(h["id"]))
                 for h in to_fire],
                trigger_kind, session, context, model, situation,
                current_repo=current_repo, head_version=head_version)
        except Exception as e:
            _log(f"[fire-batch-error] falling back to per-hit fire: {e}")
    for i, h in enumerate(to_fire):
        if fids is None:
            firing = store.fire(str(h["id"]), trigger_kind, session, context,
                                model, situation, current_repo=current_repo,
                                evidence=h.get("evidence"),
                                relevance_score=score_of(h["id"]),
                                head_version=(head_version
                                              if score_of(h["id"]) is not None
                                              else None))
            fid = (firing or "").split()[-1] if firing else "?"
        else:
            fid = fids[i]
        _notify_observer(session, h["one_liner"])
        lines.append(f"[t{h['id']}/f{fid}] {h['one_liner']}")
    if decisions:
        # Fail-open: the audit/EV-history write must never lose the disclosure.
        try:
            store.write_decisions(decisions)
        except Exception as e:
            _log(f"[decision-write-error] {e}")
    return lines


def fire_hook():
    if _disabled():
        return
    try:
        trace.mark("start")
        data = json.load(sys.stdin)
        trace.mark("stdin_parsed")
        store, repo = _open_store()
        trace.mark("store_opened")
        if store is None:
            return
        ti = data.get("tool_input") or {}
        tool = str(data.get("tool_name") or "")
        fp = ti.get("file_path", "") or ""
        session = str(data.get("session_id", "unknown"))
        model = _session_model(data)
        lines = []

        # edit_path flow: only for file-bearing tools writing under the repo
        if fp.startswith(repo + os.sep):
            rel = os.path.relpath(fp, repo)
            # v5 situational excerpt: what the agent was about to write (Write
            # `content` / Edit `new_string`), capped. None when neither.
            edit = ti.get("content") or ti.get("new_string") or None
            situation = edit[:SITUATION_CHARS] if edit else None
            hits = json.loads(store.match(rel, session, current_repo=repo))
            trace.mark("matched")
            lines += _disclose(store, hits, "edit_path", session, rel,
                               model, situation=situation, current_repo=repo)

        # tool_call flow (v8): execution-moment rows matching this tool call.
        # One _disclose per flow (never per hit — a firings read per hit is
        # the O(N) hook-path antipattern). context/situation are previews of
        # the shared tool call; each hit's exact matched text is lossless in
        # its match_evidence.
        if tool:
            tc_hits = json.loads(store.match_tool_call(
                tool, ti, session, current_repo=repo))
            trace.mark("tool_matched")
            if tc_hits:
                matched = tc_hits[0]["evidence"].get("matched") or ""
                lines += _disclose(
                    store, tc_hits, "tool_call", session,
                    f"{tool}: {matched}"[:200], model,
                    situation=matched[:SITUATION_CHARS] or None,
                    current_repo=repo)

        trace.mark("disclosed")
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
    finally:
        trace.report("fire-hook")


def session_brief():
    if _disabled():
        return
    try:
        trace.mark("start")
        data = json.load(sys.stdin)
        trace.mark("stdin_parsed")
        store, repo = _open_store()
        trace.mark("store_opened")
        if store is None:
            return
        session = str(data.get("session_id", "unknown"))

        # Compaction wipes injected firing text from the context window while
        # the per-session dedup would still block a re-fire. Record a marker
        # (the store's current max firing id) so dedup only counts firings
        # after it — the rows re-arm, including for this very brief.
        if data.get("source") == "compact":
            try:
                row = store._sql("SELECT MAX(id) AS id FROM firings")
                max_id = (row[0].get("id") if row else None) or 0
                session_state.record_compaction(session, max_id)
            except Exception as e:
                _log(f"[compaction-marker-error] session={session}: {e}")

        rows = json.loads(store.session_start(session, current_repo=repo))
        trace.mark("matched")
        lines = _disclose(store, rows, "session_start", session,
                          model=_session_model(data), current_repo=repo)
        trace.mark("disclosed")
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
    finally:
        trace.report("session-brief")


def prompt_hook():
    if _disabled():
        return
    try:
        trace.mark("start")
        data = json.load(sys.stdin)
        trace.mark("stdin_parsed")
        store, repo = _open_store()
        trace.mark("store_opened")
        if store is None:
            return
        prompt = (data.get("prompt") or "").strip()
        if not prompt:
            return
        session = str(data.get("session_id", "unknown"))
        if _is_boilerplate(prompt):
            # No matching, no firings — a harness-generated notice is not a
            # user turn to score takeaways against. Quiet but observable:
            # same log, same file as the [capped] line above.
            _log(f"[boilerplate] skipped harness-generated prompt"
                 f" session={session}")
            return

        # --- relevance cascade (B04): transforms gate the MATCHER input; the
        # head scores the ORIGINAL prompt (train/infer parity — the head was
        # trained on unsanitized `situation` texts, so pipeline purity loses to
        # parity here). Passive path only; pulls (mcp, cli query) stay ungated.
        # Kill switch: MONITION_CASCADE_DISABLE=1 → exactly today's behavior.
        # Every failure falls open to the ungated path.
        casc = None
        if not os.environ.get("MONITION_CASCADE_DISABLE"):
            try:
                from .relevance import cascade as casc
            except Exception as e:
                _log(f"[cascade-error] import: {e}")
        match_input = prompt
        if casc is not None:
            try:
                match_input = casc.SpanSanitizer().apply(prompt) or prompt
            except Exception as e:
                _log(f"[cascade-error] sanitizer: {e}")
                match_input = prompt

        res = json.loads(store.on_demand_match(match_input, session,
                                               current_repo=repo))
        hits, capped = res["hits"], res["capped"]
        trace.mark("matched")
        if capped:
            # never a silent truncation: note the cap in the state log too
            _log(f"[capped] {capped} semantic hit(s) over the injection cap"
                 f" session={session}")

        scores, head_version = None, None
        if casc is not None and hits:
            try:
                if os.path.exists(casc.default_artifact_path()):
                    from . import embed as _embed_mod
                    scorer = casc.L2HeadScorer(embed_fn=_embed_mod._embed)
                    scored = casc.run_scorers(prompt[:SITUATION_CHARS], hits,
                                              [scorer])
                    for tag, detail in scored["trace"]:
                        if tag.startswith("error:"):
                            _log(f"[cascade-error] {tag} {detail}"
                                 f" session={session} (scorer abstained,"
                                 f" candidates fail open)")
                    fired_ids = casc.commit_suppress_only(scored["belief"])
                    kept = [h for h in hits if h["id"] in fired_ids]
                    if len(kept) < len(hits):
                        # name the suppressed rows + their scores: suppression
                        # writes no firing row, so this line is the only
                        # dogfood/audit trail (B05)
                        gone = ", ".join(
                            f"t{h['id']}@{scorer.last_probs.get(h['id'], -1):.4f}"
                            for h in hits if h["id"] not in fired_ids)
                        _log(f"[cascade] suppressed {len(hits) - len(kept)}"
                             f" of {len(hits)} candidate(s): {gone}"
                             f" session={session}")
                    hits = kept
                    scores = scorer.last_probs
                    head_version = f"head-v{scorer.head.version}"
                    trace.mark("cascaded")
                # no artifact staged (external host) → quietly ungated
            except Exception as e:
                _log(f"[cascade-error] scoring, fell open ungated: {e}")

        lines = _disclose(store, hits, "on_demand", session, prompt[:200],
                          _session_model(data), situation=prompt[:SITUATION_CHARS],
                          current_repo=repo, scores=scores,
                          head_version=head_version)
        trace.mark("disclosed")
        if not lines:
            return

        msg = (
            "Takeaways for this prompt (full text: monition show <t-id>; "
            "rate: monition rate <f-id> helpful|noise):\n" + "\n".join(lines)
        )
        if capped:
            msg += (f"\n(+{capped} more suppressed by cap — "
                    f"monition query \"...\" shows all)")
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": msg}}))
    except Exception:
        return  # fail open
    finally:
        trace.report("prompt-hook")
