# Output Template

Use this exact structure. Omit a section only if it is genuinely empty (no concerns in
that class).

---

```markdown
Proceed or pause: [proceed / pause / stop-and-ask-user]

Decision summary:
- [1-3 bullets explaining the verdict]

Must fix before implementation (A):
1. [title]
   Category: [concern lens]
   Evidence: [specific file/line/field, or "needs targeted read: X because Y"]
   Why it matters: [concrete failure mode if ignored]
   Recommended action: [specific, bounded]
   Owner/timing: [who, when]

Fix before closing this bucket (B):
1. ...

Park on the tech-debt shelf / later (C):
1. ...

Accept / ignore (D):
1. ...

Tech-debt shelf candidates:
- [Suggested `docs/debt.md` entry for C-level concerns worth saving]
  (format: one-line locus — file/symbol — plus the deferred action, enough to act cold)

Process-lesson candidates:
- [Only if a repeated workflow or context-management failure appeared. Route a routine
  one to /flag; a costly, multi-session one to /postmortem.]

Questions for user:
- [Only questions that materially change implementation or phase scope]

Copy-paste patch:
```text
[Concise instructions pasteable into the active session, if useful.
Omit this block if no patch is warranted.]
```
```

---

## Section guidance

### Proceed or pause
- **proceed**: All A-class concerns are resolved or absent; B-class are minor and actionable.
- **pause**: One or more A-class concerns require a user decision or spec update before
  writing code.
- **stop-and-ask-user**: The scope itself is unclear; surfacing concerns requires user
  input first.

### Decision summary
Three bullets max. State the one most important reason for the verdict and any conditions
that would flip it.

### Must fix / Fix before closing / Park on shelf / Accept
Each item gets all five fields. If evidence is in an unread file, write
`Evidence: needs targeted read: [file/symbol] because [reason]` — do not guess.

### Tech-debt shelf candidates
Only for C-class concerns worth preserving. Give a suggested `docs/debt.md` entry —
locus plus the deferred action, enough to act on cold. Do not append to the shelf
automatically.

### Process-lesson candidates
Only if this session revealed a repeated workflow pattern, context-management failure, or
process gap. Route routine ones to `/flag`, costly/multi-session ones to `/postmortem` —
do not write a full report here.

### Questions for user
Only questions that change implementation or phase scope. Skip clarifying questions that
can be resolved by reading the spec.

### Copy-paste patch
Omit unless there is a concrete, bounded instruction to paste back. Do not include large
code blocks — just targeted text the user can drop into their active session.
