# monition

The installable module that owns all takeaway machinery: store schema, hook
executors, `init`/`sync`/`migrate`, the reader, metrics, report, and the online EV
scorer that gates fire/suppress decisions (`monition score`, shipped Phase 3). Host projects install Monition once per machine and run
`monition init`; data lives in a **Monition store** (`takeaways`, `firings`, and
`decisions` tables) under the contract in `docs/contracts/takeaway-store.md`. **Backend:
Dolt is our own default** (the v6 hub is a Dolt store, resolved via `MONITION_STORE`);
SQLite (`store.db` at the convention path `<repo-root>/monition/`) stays the recommended
default only for external/standalone hosts that won't install dolt — see
`docs/decisions/2026-06-18-dolt-default-ours-sqlite-external.md`. Detection: `.dolt/` →
Dolt, `store.db` → SQLite. Trigger-as-data
survives: rows own *what fires when*; the module owns *how matching executes*.

Vocabulary: "Monition store" for the per-project instance, "takeaways" (or
"gotchas") for the rows — never "monitions" for rows.

## Map

- `src/monition/` — the module: store reader (the only approved reader of store
  data), metrics, report CLI, lifecycle commands, hook executors, init/sync/migrate.
- `docs/contracts/` — Monition's public contracts: the store-data contracts
  (consumers cite sections, never duplicate them) and the outbound
  `firing-observer` integration contract.
- `docs/road.md` — phase roadmap.
- `tests/` — pytest, including synthetic store fixtures with known ground truth.

## Context hygiene

- **Docs lag code — trust the source, not the prose.** The v6 store model landed
  (general/project scoping via `reach`+`origin_repo`; `mirror` retired; backend
  default is Dolt for us — `docs/decisions/2026-06-18-dolt-default-ours-sqlite-external.md`);
  the per-repo→hub fold (B04) is the one piece still pending CMS's hub path. Treat docs
  as an index to *where* code lives, never as ground truth for *what it does*. Confirm
  any load-bearing claim against the source; when behavior is the question, run a quick
  test or REPL check rather than inferring from a doc.
- Grep for symbols, fields, constants, and call sites before reading any file.
- Structure-scan before any markdown range read: `grep -n "^##" <file>.md` first, then
  bounded reads of only the needed sections. Applies to all docs, not just code.
- Reads over ~150 lines require a stated reason; prefer one complete function/class
  range over multiple partial reads.
- Separate required from conditional reads up front; read only files the change touches.
- Don't re-read what grep or prior output already answered.
- Constrain repo-wide greps to source extensions (e.g. `--include="*.py"`).

## Working here

- Validation: `.venv/bin/pytest` (bare `pytest`/`python -m pytest` aren't on PATH).
  Unset a shell-exported `MONITION_STORE` first (`env -u MONITION_STORE .venv/bin/pytest`)
  — it leaks into the hook tests and causes spurious failures (the hook reads your real
  store, emits nothing → `JSONDecodeError` on empty output). A git worktree has no `.venv`
  (gitignored); run its tests via the parent venv:
  `PYTHONPATH=<worktree>/src .venv/bin/python -m pytest`.
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
  single approved reader in `src/monition/`. Any other code querying the store
  directly (bypassing the reader or WriteStore) is a contract violation.
- **Hooks are blocking, cold subprocesses.** Each `fire-hook`/`session-brief`/
  `prompt-hook` run is a fresh process with no warm state, on the user's critical
  path, under the harness timeout (`UserPromptSubmit` = 30 s). Anything heavy —
  model load, network fetch, downloads — must be pre-staged off the hook path,
  never done lazily inside it.
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
