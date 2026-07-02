# Bucket B01: Module representation design

Parent: ../workstream.md
State: next
Goal for session: Trigger-module spec designed, contracted, design-reviewed.
Target duration: 45 min
Context budget: Read parent + this bucket + required touchpoints only.

## Conceptual mapping

- One design pass settles every representation question the later buckets
  consume: how a module is spelled on the row, where per-row parameters (B03's
  threshold) live, how a new kind (B05's tool_call) enters the enum, and what a
  mutation's provenance record looks like (B06). Splitting these produces four
  incompatible half-designs.

## Data contract / provenance

- Inputs: `takeaways.trigger_kind` + `trigger_spec` — current coordinate
  systems per contract §`trigger_spec` coordinate systems.
- Outputs: a contract section (new §Trigger modules in
  `docs/contracts/takeaway-store.md`) defining: module spelling on the row,
  per-row parameter storage, provenance record for mutations, and the
  compatibility rule (existing rows valid unmodified).
- Provenance: mutation records must capture (row id, field, old value, new
  value, when, proposal source) — enough for `replay` to run the counterfactual.
  Decide storage: a `mutations` table vs Dolt commit history vs both — note
  SQLite hosts have no Dolt history, so Dolt-history-only under-serves the
  contract's backend-agnostic stance.
- Validation: contract §Versioning gets a v8 paragraph ONLY if a schema touch
  is chosen; a design that rides existing columns (e.g. JSON in trigger_spec
  for new-kind rows) must say so explicitly and defend it.

## Tasks

- [ ] Design the module representation: keep `trigger_kind`/`trigger_spec` as
      the storage (modules are an interpretation layer), or introduce a JSON
      module spec — decide with reasons, favoring zero migration for the 151
      live rows.
- [ ] Decide where B03's per-row semantic threshold lives (row data, not module
      constant; NULL = global default `SIM_THRESHOLD`).
- [ ] Decide the mutation-provenance representation (B06 consumes; replay must
      be able to reconstruct old spec).
- [ ] Decide how `tool_call` (B05) enters `trigger_kind` (enum widening = v8 +
      migrate rung + reader fingerprint update — check the ladder gotcha).
- [ ] Write the contract section(s); write the design-review decision doc
      (options, why rejected ones lost, supersession audit, contract section
      cited) per CLAUDE.md §Working here.

## Required touchpoints

- `docs/contracts/takeaway-store.md  grep -n "^##\|^###"  §trigger_spec coordinate systems, §Versioning`
  The coordinate systems the modules must reproduce exactly; the versioning
  discipline a schema touch must follow.
- `src/monition/store_write.py  grep -n "def match\|def on_demand_match\|def session_start\|SIM_THRESHOLD"  the three matchers`
  What the module seam must wrap without behavior change.
- `docs/decisions/2026-07-01-row-lifecycle-pr-framing-and-mutation-track.md  §Decision`
  The determinism ladder and black-box framing this design implements.
- `docs/decisions/2026-06-21-no-store-mutation-primitive-isolate-instead.md  §Options B`
  The narrow-mutator pattern mutation-apply verbs must follow.

## Conditional touchpoints

- `src/monition/store.py  grep -n "_detect_stale_schema\|_REQUIRED"  fingerprint validator`
  Read only if the design chooses a schema touch (v8) — the ladder ordering and
  per-indicator table guards are both load-bearing (t71 + this session's flag).
- `src/monition/init_sync.py  grep -n "V7_SCHEMA\|_V7_STEPS"  DDL chain`
  Same trigger: only for a v8 schema touch.

## Design direction

- Report first (contract check): which contract section applies, what
  producer/consumer boundary this touches, what could break, what validation
  proves preservation.
- Bias: modules as an interpretation layer over existing columns; new columns
  only where a value must be queried or mutated independently (the per-row
  threshold probably qualifies; a JSON blob hiding it does not serve `tune`).
- Composition ("layered combinations" in the road) must be *representable* but
  not *implemented* — say how the spelling extends, build nothing.
- The multi-variant rule applies workstream-wide: variant kind is an explicit
  field, never inferred; record it in the contract section.

## Validation

- Contract section drafted; decision doc written with supersession audit
  (grep decisions/ + road.md §2); user has accepted the design (consent gate —
  do not proceed to B02 on an unreviewed design).
- Expected: zero code changes in this bucket.

## Done criteria

- [ ] Tasks complete.
- [ ] Validation passes.
- [ ] Bucket `Updates` section records discoveries/gotchas/handoff.
- [ ] Parent workstream progress updated.

## Updates

- [2026-07-01 20:11] Created. Handoff: none yet. Gotchas: none yet.
