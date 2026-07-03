---
name: update-roadmap
description: Govern the upkeep of docs/road.md — add a phase, update a phase's status/exit, or capture a forward-scoped item into the future phase it belongs to. Keeps phases at refinement-conversation altitude (forward-looking, not pre-implemented); confirms before editing.
---

# update-roadmap

Keep `docs/road.md` current and useful. The roadmap does two jobs, and upkeep serves
both:

1. **It catches forward scope.** Smaller items realized mid-work that belong to a *later*
   phase get lost unless they're parked where the plan will surface them. The roadmap is
   that park — not the tech-debt shelf (which is for mundane code cleanup), and not a
   session note (which evaporates).
2. **It gives the next session forward-looking structure to build toward.** A phase states
   *enough* direction to start a refinement conversation and no more. Upkeep preserves
   that altitude — concrete enough to aim at, not so detailed it pre-implements.

Never edits the file without explicit user confirmation.

## Roadmap location

Always `docs/road.md` relative to the project root. Do not guess or derive another path.

## Step 1 — Orient

Run:
```
grep -n "^##\|^###\|Ongoing phase" docs/road.md
```
Then read only the sections needed to understand:
- the current active phase (look for `<----- Ongoing phase ----->`);
- the phase your item belongs to, if it's a forward-scope capture;
- the surrounding phase entries, so a new entry matches their format and ordering.

Do not cat the full file. Read only targeted ranges.

## Step 2 — Classify

Determine which case applies. If unclear, ask before proceeding.

| Case | Meaning | Where it goes |
|---|---|---|
| **New phase** | A high-level deliverable not yet in `## 2. Phase roadmap` | A new `### Phase N` section under `## 2` |
| **Phase update** | An existing phase's status, exit criteria, or design changed | Edit that phase's entry in `## 2` |
| **Forward-scope capture** | A smaller item realized mid-work that belongs to a *later* phase | Add it to that phase's `Design:` or `Surfaces:` so it's carried forward |

**Routing a realized item — make this call before drafting:**
- Part of an **existing future phase's deliverable** → fold into that phase (forward-scope capture).
- A **deliverable in its own right**, not covered by any phase → new phase.
- **Mundane code cleanup** in a file you touched → not the roadmap; it belongs on the
  tech-debt shelf (`docs/debt.md`). Say so and stop — don't force it into a phase.

When in doubt between these, ask the user.

## Step 3 — Clarify

Only ask what's genuinely ambiguous — not what's already clear from context (recent
conversation, an existing workstream doc, git log).

Required to draft any phase entry:
- **Name** — short, human-readable.
- **Deliverable** — one sentence: the outcome.
- **Surfaces** — key files/modules touched.
- **Status** — one of `not started` / `active` / `blocked` / `complete`.
- **Exit** — the criterion that closes the phase.

For a **forward-scope capture**, you mainly need: which phase it belongs to, and the one
line that states the item at that phase's altitude (a direction, not an implementation).

**Verify cited references before drafting.** If the entry cites a workstream, confirm the
path exists (`ls docs/workstreams/<slug>/`) and the bucket range is real. Do not carry a
path or bucket range forward from an older entry without checking — slugs get renamed and
workstreams archived, leaving dangling references. Flag any dangling reference to the user
instead of carrying it forward.

## Step 4 — Draft

Draft the exact text, following the template already in `docs/road.md` (the `### Phase N`
shape under `## 2`). Match the surrounding entries' fields and depth. A new phase entry:

```
### Phase N — [Name]

**Status:** [status].

**Deliverable:** [one-sentence outcome].

**Surfaces:** [key files/modules].

**Design:**

- [Durable design decision — direction, not implementation.]

**File/doc changes:** [list]

**Validation:** [validation approach]

**Estimate:** [token range].

**Exit:** [exit criterion].

---
```

A forward-scope capture is usually a single bullet added under an existing phase's
`Design:` or `Surfaces:` — keep it to the altitude of the phase it joins.

Show the draft before touching the file.

## Step 5 — Confirm

Before any edit, show the user:

**Hierarchy context** (always):
- **Active phase** — which `### Phase N` carries the `<----- Ongoing phase ----->` marker.
- **Inserting/editing** — the section and phase the change lands in (e.g. "new `### Phase 4`
  under `## 2`, after Phase 3" or "into Phase 3's `Design:` list").
- **Before / after** — the immediately preceding and following entries and their status.

Present it as a small scannable block:
```
Active phase:   Phase 2 — [name]
Change:         new ### Phase 4 under ## 2
Before:         Phase 3 — [name] [status]
After:          (end of ## 2)
```

**Proposed text** — the exact insertion/edit, in a code block.

Then ask: "Does this look right? I'll update `docs/road.md` once you confirm." Do not edit
until the user confirms.

## Step 6 — Edit

Use the Edit tool with `old_string` anchored to a unique nearby line. Never Write the whole
file. After editing, run:
```
grep -n "^##\|^###\|Ongoing phase" docs/road.md
```
to confirm the insertion landed where intended.

## What NOT to do

- Do not cat the full `docs/road.md` — use targeted reads only.
- Do not edit without confirmation.
- Do not invent a workstream path or slug — confirm from context or ask.
- **Do not let a phase drift below refinement altitude** — implementation detail belongs in
  a workstream/bucket, not the roadmap. A phase entry states direction; it does not
  pre-implement.
- Do not put mundane code-debt in the roadmap — that's the tech-debt shelf's job.
