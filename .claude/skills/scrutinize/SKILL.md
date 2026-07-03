---
name: scrutinize
description: Deep pass on one artifact — verify load-bearing claims structurally, surface angles a default answer would prune, red-team from a fresh-context subagent. Use when the user invokes /scrutinize [target], or says "go over this thoroughly", "go deep on X", "pressure-test this", or "what aren't you telling me". Also covers an architecture-width / AI-executor pain audit when the target is a codebase or design — "width scan", "architecture-width scan", "coupling audit", "maintainability/architecture-debt audit". Proposes moves but does not auto-edit.
---

# scrutinize

A deliberate deep pass on **one** artifact, doing three things a normal answer doesn't:
read it thoroughly (not skim-to-summary), surface the high-value angles a brief answer
would prune, and red-team it from a *fresh context window* so the critique isn't anchored
to how the artifact was framed in this thread. Output is a tight report — propose moves,
don't edit unless asked. The full pass is the **non-default** path: a thin target trips the
early-bail in step 1 rather than drawing the ceremony.

## Resolving the target

Resolve "the thing called on" in order: (1) an explicit argument — a path, a name, or
quoted text → that; (2) else the artifact in focus — the file/doc/output just discussed,
or your last substantive answer; (3) if still ambiguous, ask one line and stop. Don't
thoroughly scrutinize the wrong thing.

## Procedure

1. **Thorough pass, then triage.** Read the whole target *and its immediate context* — for
   a file, what it imports and what cites it; for a doc, the full text and what it
   references. Produce the load-bearing read: what it actually claims, its gaps, internal
   tensions, and what it depends on. For each load-bearing claim — especially any
   "shared / reused / same-as / subset / core" claim — **verify it against its referent
   structurally** (the code / call graph), not nominally; a matching name or comment is not
   verification. Mark a claim you can't substantiate **UNVERIFIED**, and rank
   UNVERIFIED/FALSE findings *above* "concerns" — a clean confident falsehood triggers no
   worry, so the operation is *verify*, not worry. This is the distilled understanding, not
   a recap.

   **Then decide whether the rest fires.** Thinness is the *absence of a load-bearing claim,
   dependency, or tension* — **not** short length: a one-line entry asserting something
   consequential earns the full pass; a long rambling target with nothing to dig into bails.
   If it's thin, **bail early**: give the short answer, skip the pruned-3 and the subagent,
   and say you skipped them and why. Don't manufacture depth a thin target doesn't have.

2. **Surface the pruned 3.** Up to 3 angles a brief default answer would leave out — *not* a
   claimed audit of suppressed reasoning (you don't have reliable access to what you
   "considered and discarded," so don't present these as recovered secrets). They're the
   high-value points a normal-length reply prunes for brevity, low confidence, or
   tangentiality. For each: **the angle**, **why a default answer omits it**, and **why it
   might matter anyway**. Don't pad to three — two good ones beat three manufactured. Rank by
   expected value to the user, not by your confidence.

3. **Fresh-context adversarial pass** (only if step 1's triage said the target is worth it).
   Spawn ONE fresh subagent (the Agent tool, general-purpose) whose prompt contains *only*
   the serialized target plus the red-team question — no inherited framing, no "I think this
   is good / done." Fresh context buys *less anchoring to this thread*, not true
   independence: it's the same model with the same priors, so it catches framing effects,
   not blind spots you share with yourself. Ask it briefly for: the weakest claim, the
   load-bearing unstated assumption, where it breaks (or the strongest counter-case), and the
   one thing that would change the conclusion. Keep it scope-boxed — one agent. Treat its
   output as **fallible**: it can confidently surface a wrong "weakest claim," so the next
   step judges it, doesn't defer to it.

4. **Reconcile and report.** Tight output:
   - **Deep read** — gaps/tensions and any UNVERIFIED/FALSE findings, not a recap.
   - **Pruned** — the up-to-3 angles.
   - **Adversary** — its findings, then your judgement: which land, which don't, why.
   - **So what** — optional, ≤3 bullets: the concrete moves (edit, add a link, open a
     question). Propose; don't auto-write unless asked.

## Optional angle: architecture width (AI-executor lens)

When the target is a codebase, module boundary, or design (not a doc/claim), one of the
pruned-3 angles (step 2) can be this lens instead of a generic one: *"for the next likely
change, what must an executor read, infer, edit, and validate to avoid breaking hidden
invariants?"* Walk one or two concrete next-change scenarios (add a feature/concept, change
one policy/rule, add one variant) and flag which pain category bites: discovery (hard to
find the owner/source-of-truth), ownership (unclear who owns a rule/identity), context
(one change needs broad simultaneous reads), coordination (synchronized cross-subsystem
edits), contracts (stringly protocols standing in for typed ones), invariants (rules living
away from the edit surface), validation (only broad runs catch local mistakes), or review
(large diffs mixing unrelated concepts). Report it as one pruned angle with a one-line
target shape, not a separate hotspot backlog — if the finding is big enough to warrant a
prioritized backlog across many files, say so and hand it off as a follow-up scope rather
than inflating this report.

## Calibration

The failure mode to watch is a run that only ever confirms its own success. Whether it's
working is judged by the user — not by you, since you ran it and would just confirm
yourself:

- **Pruned hit-rate** — were the angles non-obvious *and* true *and* useful, or padding?
- **Adversary additivity** — did the fresh-context agent surface something the user hadn't
  already seen, or just echo the deep read? An echo means framing is leaking into its prompt.
- **Action conversion** — did the scrutiny change the artifact, or just generate text? Lots
  of text, no change → theater.
- **Cost proportion** — one quick subagent, one tight report, and thin targets bailing early.
  If trivial targets keep drawing the full ceremony, the triage gate isn't biting.
