# Bucket B01: Governed-docs realignment

Parent: ../workstream.md
State: done
Goal for session: Monition-side governed docs match the accepted spec.
Target duration: 20 min
Context budget: Read parent + this bucket + required touchpoints only.

## Conceptual mapping

- One mental model (the spec's decisions), three doc surfaces in this repo.
  Doing them together prevents a half-reversed scope confusing later buckets.

## Tasks

- [ ] `CLAUDE.md`: rewrite the scope paragraph — Monition is the installable
      module owning all takeaway machinery (schema, executors, init/sync/
      migrate, reader, metrics, report; score in Phase 3); drop "consumer,
      never a co-owner" and "trigger layer stays store-side"; repeal the
      Phase-1 "store access is read-only" working rule (writes flow through
      module commands only); add the vocabulary line (Monition store /
      takeaways).
- [ ] `docs/road.md`: rewrite Phase 2 as moduleization + CMS cutover
      (deliverable/design/validation/exit from spec §Decisions, §Cutover
      checklist, §Success criteria); move online scoring to Phase 3 (add
      `decisions` table, cold-start threshold); tuning/retrieval becomes
      Phase 4 (+ MCP on-demand noted as candidate); mark Phase 2 as the
      ongoing phase.
- [ ] `docs/contracts/takeaway-store.md`: retitle for Monition stores; update
      preamble + producers/consumers table (producers become module commands;
      the module is no longer "consumer-only"); terminology sweep ("Monition
      store"); keep v2 fingerprint semantics, field tables, near-misses, and
      validation requirements unchanged.
- [ ] Grep-sweep repo docs for stale phrases: "consumer of the store",
      "store-side", "takeaway store" (where it means the instance), "read-only
      in Phase 1".

## Required touchpoints

- `docs/specs/2026-06-11-module-realignment.md`  (full read)  the source of every edit
- `CLAUDE.md`  (full read — it is short)  scope paragraph + working rules
- `docs/road.md`  grep -n "^##\|^###" then bounded reads of Phases 2–3  rewrite surface
- `docs/contracts/takeaway-store.md`  lines 1–38  preamble, producers table, versioning — the only contract region this bucket may edit

## Do-not-read / avoid

- `src/monition/`, `tests/` — no code changes in this bucket; behavior is
  untouched by doc edits.
- Contract sections below line 38 — field semantics are correct and out of
  scope here.

## Design direction

- Report first (contract check): this bucket touches only the contract's
  preamble/producer table; field semantics, coordinate systems, and validation
  requirements must survive verbatim. Validation = post-edit diff shows no
  changes below the Versioning section.
- The spec is authoritative; where road.md's old Phase 2 text conflicts, the
  spec wins. Keep road.md's Phase 1 status block (exited 2026-06-11) intact.
- Keep contract version at v2 — ownership reframing is not a schema change.

## Validation

- `python3 tools/lint.py` (or commit dry-run) — no ERRORs.
- `grep -rn "never a co-owner\|store-side\|read-only" CLAUDE.md docs/road.md docs/contracts/takeaway-store.md` — remaining hits are deliberate (e.g. history notes), each justified in Updates.
- Expected: docs read coherently in the new vocabulary; contract diff below the
  Versioning section is empty.

## Done criteria

- [x] Tasks complete.
- [x] Validation passes.
- [x] Bucket `Updates` section records discoveries/gotchas/handoff.
- [x] Parent workstream progress updated.

## Updates

- [2026-06-11 19:55] Created. Handoff: none yet. Gotchas: none yet.
- [2026-06-11] Done. All four tasks complete: CLAUDE.md scope/Map/working-rules
  rewritten (vocabulary line added; read-only rule replaced with
  writes-through-module-commands + no-real-CMS-writes-before-B06); road.md design
  positions reworked (consumer/co-owner and hook-seam bullets replaced by
  one-owner, trigger-as-data, fail-open-absent-and-broken), Phase 2 rewritten as
  moduleization + CMS cutover and marked ongoing, scoring moved to Phase 3
  (decisions table, cold-start N~3), tuning/retrieval to Phase 4 (+ MCP
  candidate); contract retitled "Monition store (v2)", preamble reframed as
  code↔data boundary spec, producer table now names module commands with a
  transition note (CMS takeaway*.py remain live producers until B06 — the
  characterization oracle).
  Validation: `tools/lint.py` exit 0; stale-phrase grep clean except one
  deliberate hit — road.md:84 "read-only" inside the preserved Phase 1 history
  block. Contract diff below the Versioning section is empty; the one Versioning
  edit swaps "store-side migration" for "`monition migrate` is the repair path"
  (semantics unchanged, per spec decision 9).
  Gotcha for B02: ported lifecycle command names are not yet fixed — the contract
  table deliberately says "module lifecycle commands" generically (only
  `monition dump`/`migrate` are named in the spec); B02 should settle subcommand
  names and may tighten the table then (preamble-only edit, still allowed? No —
  B05 is the only other contract-editing bucket per invariants; if B02's names
  diverge from the generic wording, fold the table tweak into B05 or get an
  invariant amendment).
