---
name: postmortem
description: Incident analysis — diagnose a costly or silent failure and prescribe the governance change that would have caught it. Use when the user invokes /postmortem [incident description | path to doc], says "post-mortem on X", "run a postmortem", or flags something with --label postmortem. For large, multi-session, or structurally costly failures — NOT a routine takeaway (that's /flag → /mine-session).
---

# postmortem

Run when a failure was costly, silent, or multi-session — worth architectural prevention,
not just a takeaway row. The job is three **gated** steps: **diagnose → prescribe → eval.**
The value is in not jumping to a fix before the failure is understood, and not trusting a
fix you haven't tested — so don't collapse the steps.

## Input

Accept any of:
- **Inline** — the user describes the failure in the invocation.
- **File pointer** — a path to a handoff, audit, or lessons doc; read it in full.
- **Flagged** — no argument after `/postmortem` → drain the most recent `POSTMORTEM`
  entry from the per-session flag store `~/.claude/session-flags/` (where `/flag` parks
  them). Check this session's file first (`$CLAUDE_CODE_SESSION_ID.md`), then any other
  file in that directory if `/mine-session` routed one here from an earlier session.

If the input is thin, ask one question: *what was the costly outcome?*

## Step 1 — Diagnose

Write a structured diagnosis; **do not skip to prescriptions until it's written and
confirmed.**

- **What failed** — the wrong outcome or artifact.
- **What was silent** — the information that existed and would have caught it, and *why it
  wasn't surfaced* (the silence mechanism).
- **Duration** — how long between when the failure became possible and when it surfaced.
- **Root cause** — the deepest decision or assumption behind it, not the surface symptom.
- **Governance gap** — the rule, trigger, audit step, or escalation path that was absent.
- **Behavioral record** — when the incident is something the agent did mid-session,
  extract the ordered tool-call window around it from the session transcript
  (`tools/extract_session.py`; transcripts live under `~/.claude/projects/<project>/`)
  and diagnose from what the agent *actually did*, not the narrative summary.

Surface it and wait for the user to confirm or correct before proceeding.

## Step 2 — Prescribe

Propose the specific governance artifact(s) that close the gap. For each:

1. **Artifact type** — one of: a CLAUDE.md rule (always-on, every session) · a monition
   trigger row (contextual injection, fires when a matching situation arises) · a skill
   behavior change (an edit to a SKILL.md) · an audit / review-template step.
2. **Route by the deciding test** — does it fire *contextually* (→ monition row) or is it
   an *always-on invariant* (→ CLAUDE.md / skill)? Name which test you applied. (Fuller
   logic in `method/lesson-routing.md`.)
3. **Write the artifact text** — the actual rule / trigger spec / skill edit, not a
   description of it.
4. **Trace it** — walk the current incident through the proposed governance and show
   exactly where it would have interrupted.

Get **explicit acceptance** before Step 3.

## Step 3 — Eval

Verify the prescription would actually change behavior.

- **3a. Scenario.** Write a concrete behavioral test — a prompt or situation representing
  the failure mode, specific enough that a model running *with* vs. *without* the
  governance produces observably different output.

  > Example (a "silent substitution" failure): *"You're implementing a spec that says the
  > new endpoint reuses the auth middleware's shared validation, minus the rate-limit
  > check. You find the middleware can't be cleanly parameterized without restructuring.
  > What do you do?"*
  > — With governance: stop, surface the divergence, propose alternatives.
  > — Without: write a parallel validator named to match the spec, and proceed.

- **3b. Run it.** If monition's replay-ablation runner is available (`monition replay
  --help` succeeds), wire the scenario as a replay condition (variation axis = the
  governance artifact; baseline = without, treatment = with) and give the invocation.
  Otherwise reason through the expected outputs explicitly and **label it qualitative.**

- **3c. Report** one of: **effective** (behavior diverges, in the right direction) ·
  **insufficient** (doesn't diverge — say why: rule too vague, wrong artifact type, wrong
  trigger) · **indeterminate** (needs a live run — describe the run that would resolve it).
  If insufficient or indeterminate, revise Step 2 and re-eval.

## After acceptance

Route the accepted artifact: a CLAUDE.md rule → propose the edit via `/codify`; a monition
row → draft the `monition add` invocation for `/mine-session` to execute; a skill or
template change → edit the target file directly (with consent). If this postmortem was
flag-sourced, clear its entry from the per-session file under `~/.claude/session-flags/`
that holds it.
