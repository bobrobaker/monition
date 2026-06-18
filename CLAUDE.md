# monition

The installable module that owns all takeaway machinery: store schema, hook
executors, `init`/`sync`/`migrate`, the reader, metrics, report, and the online EV
scorer that gates fire/suppress decisions (`monition score`, shipped Phase 3). Host projects install Monition once per machine and run
`monition init`; data stays per-project in a **Monition store** (a Dolt instance at
the convention path `<repo-root>/monition/`; `takeaways` + `firings` tables) under
the contract in `docs/contracts/takeaway-store.md`. Trigger-as-data survives: rows
own *what fires when*; the module owns *how matching executes*.

Vocabulary: "Monition store" for the per-project instance, "takeaways" (or
"gotchas") for the rows — never "monitions" for rows.

## Map

- `src/monition/` — the module: store reader (the only approved reader of store
  data), metrics, report CLI; lifecycle commands, hook executors, and
  init/sync/migrate land across Phase 2.
- `docs/contracts/` — the Monition-store data contract; consumers cite sections,
  never duplicate them.
- `docs/road.md` — phase roadmap.
- `tests/` — pytest, including synthetic store fixtures with known ground truth.

## Context hygiene

- Grep for symbols, fields, constants, and call sites before reading any file.
- Structure-scan before any markdown range read: `grep -n "^##" <file>.md` first, then
  bounded reads of only the needed sections. Applies to all docs, not just code.
- Reads over ~150 lines require a stated reason; prefer one complete function/class
  range over multiple partial reads.
- Separate required from conditional reads up front; read only files the change touches.
- Don't re-read what grep or prior output already answered.
- Constrain repo-wide greps to source extensions (e.g. `--include="*.py"`).

## Working here

- Validation: `.venv/bin/pytest` (bare `pytest`/`python -m pytest` aren't on PATH)
- Pre-commit linter: ERROR blocks, WARN advises (`tools/lint.py`). Arm once on a fresh
  clone: `git config core.hooksPath .githooks`.
- **Never codify silently.** Rule and convention changes are proposed and accepted
  before writing — use `/codify`.
- **Non-trivial design decisions get a design review** — the question, options,
  and *why the rejected ones lost*. Project-internal calls land in
  `docs/decisions/YYYY-MM-DD-slug.md`; cross-project calls in the cross-project decision
  store. `road.md §2` stays the compressed verdict that links back.
- Wrapping up mid-task: `/handoff` writes a decision-ready handoff to `handoffs/`.
- Store writes flow only through module commands; all store reads go through the
  single approved reader in `src/monition/`. Any other code issuing `dolt sql`
  against a Monition store is a contract violation. Nothing writes to the real CMS
  store before the cutover bucket (B06).
- **The eval substrate is monition's; the tier-3 evaluator is not.** Monition owns
  and *exposes* the row-coupled eval substrate (firings/ratings + fire-time
  provenance) and the ΔP(fail) graduation-seam currency, via the `export-firings`
  read-verb. It does **not** build the tier-3 governance-module evaluator (scoring
  CLAUDE.md lines, prompts, skills by named-failure-mode rate) — that is CMS's
  shipped discipline, consuming the read-verb. A monition session asked to "improve
  evals" stops at the substrate. (Confer 2026-06-12, user-ratified; detail in
  `docs/road.md`.)
- **Deployment is CMS's; the machinery is monition's.** A monition session asked to
  *deploy* or *dogfood* the context-management system into a host project hands to
  CMS — CMS owns instantiation (tier-0 payload, session-archive wiring, mining
  discipline, lesson-routing). Monition *exposes* the machinery (`init`/`sync`/`migrate`,
  the store contract) but does not orchestrate the deployment. (Parallel to the
  eval-substrate seam above.)

## Dispatch

- The roadmap is `docs/road.md`; work descends roadmap → workstream → bucket
  (`docs/workstreams/`). Find the active workstream with
  `grep -r "^Progress:" docs/workstreams/ --include=workstream.md`.
- `/dispatch` turns a phase discussion into a workstream + buckets, or executes the
  next bucket per the workstream's execution protocol.
