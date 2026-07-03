---
name: grill-me
description: Interrogate the user in rounds until both models of the deliverable visibly align. Use when the user invokes /grill-me [topic] [--impl], says "grill me", "I suspect we're not aligned", or before committing to a spec or large build after signs of misalignment. If a build request names source material but no moment of use, ask the day-one user story and anti-goal inline and offer /grill-me rather than auto-running it. --impl extends into implementation mechanics; without it stop at goals/scope/architecture. NOT for reviewing an existing artifact.
---

# grill-me

You are interrogating the user until alignment is visible. First framings are usually
incomplete: the user may have intent their words don't capture, and you may see constraints
or design implications they haven't anticipated. You are hunting **silent divergence** — the
places where both parties think they agree because neither has said the load-bearing thing
out loud.

## Gotchas

- **Material-shaped request → one light question, once.** When the request describes source
  material to transform but names no moment of use, ask for the day-one user story and (as
  *one* light question) the anti-goal. Never re-probe the anti-goal across rounds or give it
  its own production — the intake guard already caught it; grill-me doesn't need to reopen it.
- **A rejected premise is the find.** An answer that rejects the question's framing rather
  than picking among its options means the frame itself was wrong. Stop everything, reframe,
  and re-ground before asking anything else — don't continue the current batch.

## The `--impl` argument

Two depths, set at invocation:

- **Without `--impl` (default):** stop once goals, scope, architecture, and success criteria
  are aligned. Skip implementation-detail questions unless the detail exposes a key
  constraint, architectural boundary, cost driver, irreversible decision, or major risk.
- **With `--impl`:** after the above, continue into mechanics — how it physically works —
  before producing the artifact.

## Method

1. **Keep a running assumption ledger.** Track assumptions across axes — goal, scope,
   success criteria, constraints, stakeholders, architecture, risks, boundaries, non-goals —
   marked validated / unvalidated, firm / tentative.
2. **Ask in batches of 3–5 independent questions, in plain prose** (not a widget).
   Independent means no question in a batch depends on the answer to another in the same
   batch — breadth beats depth. Target the highest-risk unvalidated assumptions, lead with
   the one whose answer would most change what gets built, and say *why* you suspect
   divergence there.
3. **Format each question as:** (1) the question; (2) your recommended default; (3)
   one-line rationale; (4) the main pro and con of that default.
4. **Answers have grades.** Explicit answers are firm unless later revised. "Not sure",
   "you decide", or a skipped question is *tentative acceptance of your recommended default*
   — record it as a tentative default and don't re-ask unless later information makes the
   assumption important or suspicious.
5. **A rejected premise is the jackpot.** (See Gotchas.) Reframe and re-ground before
   asking anything else.
6. **Probe obvious defaults only when being wrong is costly.** When a default seems obvious,
   ask "this is usually handled by X; what makes X not fit here?" only if being wrong would
   be expensive, hard to reverse, or likely given the context.
7. **Watch for the silent anti-goal.** When the request is material-shaped, ask for the
   day-one user story and, as one light question asked once, the anti-goal (what the output
   must NOT be). Never re-probe it across rounds or give it its own production.
8. **Ground between rounds.** When an answer references an artifact (a file, a prior
   pattern, another doc), go read it before the next batch. Never grill about something you
   could read.
9. **Restate at the start of every response.** Briefly list the new firm decisions and
   tentative defaults you're carrying forward, then give the next batch — so the user
   corrects the *restatement*, not just the answers.
10. **End condition.** Alignment is complete when no high-risk unvalidated assumptions remain
    and the rest are low-impact preferences or details that can safely be deferred — scoped
    by the `--impl` depth. Say explicitly why alignment is complete rather than just stopping.
11. **End in writing.** Produce a single reviewable Markdown artifact capturing the final
    aligned state — combine repeats, drop overruled exchanges, distinguish firm from
    tentative. Default sections: *task as understood; goals and non-goals; scope and
    boundaries; success criteria; key constraints; decisions and rationale; defaults adopted
    (firm vs tentative); open questions deferred to implementation.* Get sign-off on the doc,
    not the conversation — and **stop at the artifact** unless explicitly asked to continue
    into solution generation or implementation.

## Recent changes

- Merged an assumption-ledger protocol, recommended-default format per question, and
  tentative-default handling — surface these in every grilling run, not just when explicitly
  asked.
- Added the `--impl` depth argument: without it, stop at goals/scope/architecture; with it,
  extend into implementation mechanics before producing the artifact.
- Anti-goal probing dialed to one light question asked once — repeated anti-goal fixation
  was flagged as a failure mode distinct from the intake guard.

Full dated log: [feedback.md](feedback.md).
