---
name: dispatch
description: Run the dispatch path — turn a roadmap phase discussion into a workstream + bucket files, or execute the next bucket of an existing workstream. Use when the user invokes /dispatch, says "start the next phase" / "generate buckets" / "run the next bucket". NOT for one-off tasks that fit a single session — just do those.
---

# dispatch

1. **Resolve the target by slug, then kind-check.** A "build X" / "next bucket of
   X" reference resolves to a **slug** — the stable content-name (e.g.
   `export-firings`), never a bare number: `Phase 2` / `P2` / `B0N` are display
   ordering, and the same number names different work across schemes (monition
   `road.md` Phase N vs the cross-project P-series vs buckets). If a bare number
   maps to more than one candidate across `road.md` + `docs/workstreams/` + the
   cross-project roadmap + open handoffs, it is
   **ambiguous — surface the candidates and ask, never guess.** Then gate before
   loading anything heavy: run
   `grep -r "^Progress:" docs/workstreams/ --include=workstream.md` (cheap). If an
   active workstream has buckets left and the user wants execution, follow that
   workstream's own Execution Protocol and stop — do **not** read the generator
   prompt (~4k tokens you don't need).
2. **Size gate:** if the phase likely fits one session, do not generate a
   workstream — execute it directly against the `docs/road.md` phase's Design and
   Validation sections (report-first, then build). **Reconcile before building:**
   roadmap/candidate prose is deliberately informal (road.md §1), so grep the
   fields/states/symbols it names and confirm they exist as described — if the
   framing doesn't survive contact with the schema/contract (e.g. a "suppressed
   row" with no such status), surface the mismatch and resolve it with the user
   before writing code. Buckets package context across sessions; below that
   threshold they are ceremony.
3. **To create a new workstream** (phase exceeds a session): read
   `docs/prompts/workstream_bucket_generator.md` in full, hold the phase discussion
   (input: the relevant `docs/road.md` phase + anything the user pastes), then
   generate the parent + bucket files per the prompt, reporting files created /
   assumptions / compression rationale / risks.
4. After any path, if the run surfaced a reusable generation or execution lesson,
   propose a dated entry for the prompt's Updates section — never codify silently.
