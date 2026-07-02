# Trigger-module representation: interpretation layer, columns for parameters, event-grain provenance

Status: accepted (user, 2026-07-02 — B01 consent gate cleared)
Contract sections: `takeaway-store.md` §Trigger modules (new), §Versioning (v8
planned paragraph), §takeaways per-field meaning (`sem_threshold`),
§mutations per-field meaning (new)

## Question

Phase 7 makes triggers swappable modules that a consent-gated engine mutates.
One design pass must settle: (1) how a module is spelled on the row, (2) where
per-row parameters (B03's semantic threshold) live, (3) what a mutation's
provenance record is, and (4) how a new kind (B05's `tool_call`) enters the
enum — under zero migration for the 151 live rows and the constraints of
`2026-07-01-row-lifecycle-pr-framing-and-mutation-track.md`.

## Decision

1. **Modules are an interpretation layer** over `trigger_kind` / `trigger_spec` /
   per-row parameter columns. The kind→module-composition mapping is a closed
   function recorded in contract §Trigger modules (`edit_path`→`glob`,
   `session_start`→`always`, `on_demand`→`lexical` OR `semantic` — naming the
   composition `on_demand_match` already executes). Module identity is never
   stored redundantly and never inferred from spec shape. Zero migration; every
   existing row valid unmodified.
2. **Per-row parameters are columns.** `sem_threshold` (decimal, nullable,
   NULL = global `SIM_THRESHOLD`) joins `takeaways` at v8; read only by the
   semantic pass and reporting, written only by B03's narrow `tune` verb.
3. **Mutation provenance is a `mutations` table**, event-grain: explicit `verb`
   (open documented vocabulary), `changes` JSON `{field: {old, new}}` capturing
   old values before the write, `source` pointer. Backend-agnostic contract
   record; Dolt history is auxiliary audit only.
4. **`tool_call` enters by enum widening at v8**, and v8 ships as **one atomic
   migration at B03** (first schema consumer) carrying all three pieces —
   threshold column, enum widening, mutations table — so the version-ladder
   detector gets exactly one v8 rung (the v7 atomicity lesson). Post-v7 kinds
   spell `trigger_spec` as JSON; the three v7 microformats are frozen.

Composition ("layered combinations") is representable — a future composite kind
is a new enum value whose JSON spec is a module-descriptor tree — and explicitly
not implemented ahead of a consuming proposal.

## Options considered and why the rejected ones lost

- **Spelling — A (chosen): interpretation layer over existing columns.**
  Preserves trigger-as-data (road.md §2), costs zero migration, and every later
  bucket's need (threshold, tool_call, provenance) is served by additive pieces.
- **Spelling — B: a JSON module descriptor replacing `trigger_kind`/`trigger_spec`.**
  Rejected: rewrites 151 rows and every consumer (matchers, report, export,
  CMS-side tooling) to buy generality only a composition engine would use — and
  building for composition ahead of a consuming proposal is a named non-goal.
- **Spelling — C: a normalized `modules` table (row → N module rows).**
  Rejected: adds a join on the hook path (hooks are cold, blocking subprocesses)
  for a mapping that is a fixed function of `trigger_kind`; normalization earns
  nothing until rows carry variable module sets, which none do.
- **Threshold — in `trigger_spec` (JSON or microformat extension).** Rejected:
  `tune` becomes a string-rewriter, aggregation requires parsing a dialect, and
  it mixes user-authored trigger data with an engine-calibrated parameter —
  different provenance, different mutators (the bucket's own bias: a JSON blob
  hiding the threshold does not serve `tune`).
- **Threshold — module constant.** Rejected outright: B03's whole point is
  per-row calibration; a constant is what exists today (`SIM_THRESHOLD`).
- **Provenance — Dolt commit history only.** Rejected: SQLite hosts have no
  history (under-serves the contract's backend-agnostic stance), and mining
  commits interleave — recovering per-row field diffs from commit archaeology is
  not a query interface for `replay`.
- **Provenance — per-field mutation rows** (the bucket's sketch tuple).
  Rejected in favor of event-grain: a kind migration atomically changes
  `trigger_kind` + `trigger_spec`; two rows need a grouping id to stay one
  counterfactual unit — an extra column to reassemble what one `changes` JSON
  records natively.
- **Provenance — both table and Dolt history as contract records.** Rejected:
  two sources of truth; the table is the record, history is free audit on Dolt.
- **`tool_call` — piecemeal schema bumps (v8a threshold at B03, v8b enum at B05,
  v8c table at B06).** Rejected: three fingerprint updates, three ladder rungs,
  and ambiguous version detection between them — v7 already taught that partial
  migration makes the ladder ambiguous (hence its per-indicator table guards).
- **`tool_call` — reuse `on_demand` with a JSON spec instead of widening.**
  Rejected: `trigger_kind` is the executor binding (which hook event fires it);
  a PreToolUse module under `on_demand` would be dispatched by the wrong
  executor, and variant kind must be an explicit field, never inferred from
  spec shape (the multi-variant rule).

## Supersession audit

Grepped `docs/decisions/` + `road.md` §2 (2026-07-01):

- `2026-06-21-no-store-mutation-primitive-isolate-instead.md` — **affirmed**:
  mutation-apply verbs follow its Options-B narrow-mutator pattern; no generic
  setter, no purge. One side-remark in its Option B rationale ("per-row
  `trigger_spec` editing demoted to a ~2-case cleanup tool") was already
  superseded by the mutation-track framing decision (2026-07-01), which makes
  trigger mutation first-class; the narrow-verb *pattern* it argued for is
  exactly what this design adopts.
- `2026-07-01-row-lifecycle-pr-framing-and-mutation-track.md` — **implemented
  by this design** (black-box module, determinism ladder, mutation = consented
  row edit with provenance); its binding constraints are restated, not changed.
- `2026-06-18-noise-targets-the-filter-not-the-gate.md` — untouched; batch
  attribution (B04) consumes it.
- `2026-06-21-relevance-cascade-b02-no-go.md` — not reopened: `sem_threshold`
  is one interpretable per-row scalar moved by that row's own ratings, no
  learned component.
- road.md §2 **Trigger-as-data** — affirmed and cited in the contract section:
  rows keep owning *what fires when*; the module layer is *how matching
  executes*.
- No decision doc is superseded outright; nothing marked.

## Consequences

- v8 is designed now, implemented at B03 as one atomic migration; contract
  §Versioning carries the v8 paragraph explicitly marked planned (docs lead
  code here by design — the paragraph is the spec B03 builds to; v7 stays
  current until it ships).
- B02 (module seam refactor) is behavior-preserving and schema-free: it wraps
  the three matchers behind the module interpretation with parity tests, no v8
  dependency.
- The reader fingerprint (`store.py:_REQUIRED` `trigger_kind` enum regex) and
  `_detect_stale_schema` gain their v8 rung in the same release as the
  migration, with per-indicator table guards for `mutations`.
- Replay's reconstruction contract starts at v8: pre-v8 trigger edits are
  unrecorded and unreconstructable; stated in §mutations semantics.
