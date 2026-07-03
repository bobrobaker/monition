---
name: dispatch
description: Run the dispatch path — turn a roadmap phase discussion into a workstream + bucket files, or execute the next bucket of an existing workstream. Use when the user invokes /dispatch, says "start the next phase" / "generate buckets" / "run the next bucket". NOT for one-off tasks that fit a single session — just do those.
---

# dispatch

1. **Kind-check first — gate before you load anything heavy.** Run
   `grep -r "^Progress:" docs/workstreams/ --include=workstream.md` (cheap). If an
   active workstream has buckets left and the user wants execution, follow that
   workstream's own Execution Protocol and stop — do **not** read the generator
   prompt (~4k tokens you don't need). Resolve "build X" by **slug** (the work's
   content-name) across the roadmap, workstreams, and open handoffs — numbers are
   display order only, and a bare number more than one scheme defines is ambiguous,
   so ask rather than guess.
2. **Size gate:** if the phase likely fits one session, do not generate a
   workstream — execute it directly against the `docs/road.md` phase's Design and
   Validation sections (report-first, then build). Buckets package context across
   sessions; below that threshold they are ceremony. Before building, reconcile the
   phase's informal vocabulary against the actual schema or code — if the framing
   names something the data model lacks (a status that isn't a status), surface the
   mismatch first rather than silently translating it. Before report-first, if
   `docs/debt.md` exists, grep it for the files this phase touches; surface any hits
   with a fold-in / sibling / parked call (fold in only within budget).
3. **To create a new workstream** (phase exceeds a session): read the generator
   prompt in full — `docs/prompts/workstream_bucket_generator.md` (in CMS itself,
   where it is the shipped template: `starter/prompts/workstream_bucket_generator.md`)
   — then hold the phase discussion
   (input: the relevant `docs/road.md` phase + anything the user pastes), then
   generate the parent + bucket files per the prompt, reporting files created /
   assumptions / compression rationale / risks.
4. After any path, if the run surfaced a reusable generation or execution lesson,
   propose a dated entry for the prompt's Updates section — never codify silently.
5. **Delegated runs — capture at the seam the workers can't.** If this run dispatched
   buckets to stateless workers that were then torn down, their bucket/workstream
   `Updates` survived but their lessons and an archive entry did not. Before closing the
   run, do the two end-of-session passes they couldn't: one `/mine-session` over the
   worker results in your window plus the accumulated bucket Updates (run-level, through
   the normal consent gate — not one pass per worker), and one `/wrap-session` for the
   run with workers as sub-sections.
