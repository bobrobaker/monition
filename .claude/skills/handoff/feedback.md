# handoff — feedback log

Dated provenance of how the handoff protocol evolved: what was ambiguous or misapplied,
and the correction. Consult when **revising** a rule. The distilled, firing form lives in
`SKILL.md` (`## Gotchas` and the body) — this is the audit trail, not loaded on every run.

*(No misfires recorded yet — add dated entries as the protocol is exercised.)*

## 2026-07-02 — envelope-not-backlog resolution added

An audit found the consume-then-delete lifecycle falsified in practice (1 deletion ever;
8/16 handoffs sat `status: open`, oldest 16d). Root cause: un-started work had no
routing rule, so envelopes accreted as a de-facto backlog. Added the fourth resolution
(route work into the target repo's road/debt with context, then delete the envelope);
housekeep probe C now cites this skill's menu instead of restating it.
