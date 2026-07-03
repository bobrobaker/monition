---
name: concern-review
description: Surface and triage architecture, implementation, contract, testing, evaluation, and handoff concerns after a bucket/session or before implementation. Use when asked for top concerns, questions, risks, a proceed/pause judgment, or a bucket debrief review. NOT a refactor or audit, and NOT a postmortem on a failure that already happened.
---

# concern-review

Surface and triage concerns after a bucket/session or before implementation. The job is
not to list everything that could go wrong — it is to **classify each concern by timing
and actionability** so the session knows what blocks now and what can be parked.

## This is not

- A refactor, audit, or implementation skill — it surfaces and routes, never edits.
- A postmortem (that analyzes a failure that *already* happened; this runs *before* one).
- The tech-debt shelf itself — non-blocking concerns are *routed* to it, not filed here.

## Relationship to siblings

- **Tech-debt shelf (`docs/debt.md`):** a concern that is real but non-blocking goes
  under `Tech-debt shelf candidates` with suggested entry wording. Do not append to the
  shelf automatically — surface the candidate and let the user (or the capture act) file it.
- **/postmortem and /flag:** concern-review asks "Can we proceed, and what risks should
  be routed?" If a *repeated process or workflow* failure surfaces (not a code concern),
  add a `Process-lesson candidates` section — route a routine one to `/flag` and a costly,
  multi-session one to `/postmortem`.

## Core behavior

1. Use currently loaded context first.
2. Read the active workstream, active bucket, relevant contract/spec sections, changed
   files, and relevant tests if available.
3. Inspect a file only when you have a specific reason; do not broad-scan the repo.
4. If a targeted read is needed, say: "Needs targeted read: [file/symbol] because [reason]."
5. Do not edit code or docs.
6. Do not file tech-debt entries or open tasks automatically unless explicitly asked.
7. Output concern triage per the required format in `references/output-template.md`.

## File-intake priority

1. Active workstream / active bucket doc
2. Relevant contract / spec sections
3. Changed files and directly named files
4. Relevant tests
5. Grep or section reads before full-file reads

## Triage classes (summary)

See `references/concern-taxonomy.md` for full definitions and examples.

| Class | Meaning |
|-------|---------|
| A | Block before implementation — spec/API/contract too ambiguous to proceed |
| B | Fix before closing this bucket — small local issue correctable now |
| C | Park on the tech-debt shelf / later phase — real but belongs to a later phase |
| D | Accept / ignore — speculative, already mitigated, or not phase-relevant |

**Key rule**: Do not treat "real concern" as "must fix now." Classify by timing and
actionability.

## Concern lenses (summary)

See `references/concern-taxonomy.md` for full definitions and examples. Apply all that
are relevant:

1. Contract mismatch
2. Evaluator / scorer validity
3. Misleading-success states
4. API seam / handoff ownership
5. Test truthfulness
6. State / cache / isolation
7. Scope / phase correctness
8. Metric validity
9. Artifact freshness / reproducibility
10. User-decision dependency
11. Review-loop stop condition
12. Unverified hypothesis

## Output

Follow the format in `references/output-template.md` exactly.
