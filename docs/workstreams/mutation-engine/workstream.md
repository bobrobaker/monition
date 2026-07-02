# Workstream: Mutation Engine (Phase 7)

Progress: B01/module-representation-design next
Blocked: none

## Objective

Rows improve instead of only firing or dying: triggers become swappable modules,
and a consent-gated engine proposes per-row mutations (tighten / broaden /
migrate down the determinism ladder / merge / graduate / stale) from FP
(ratings), FN (violations), and `match_evidence`. Buckets are ordered by
data-readiness: representation and ratings-backed work first; the proposal
engine last, after live signal has accumulated. Frame:
`docs/decisions/2026-07-01-row-lifecycle-pr-framing-and-mutation-track.md`
(binding constraints in its Decision + Consequences sections).

## Execution Protocol (do not change)

1. Read this workstream first. For B01, read the full file. For B02+, do NOT use `cat` — run `grep -n "^##" workstream.md` first to get section line anchors, then use bounded reads for only: Objective, Execution Protocol, Bucket Index, and Cross-Bucket Invariants — skip Deferred/Non-Goals, Estimate, and any lower boilerplate sections.
2. Use `Progress` and `Bucket Index` to select the active bucket; if none is active, select the next bucket.
2a. If the index references a bucket file that does not exist yet, read `## Bucket template` in the generator prompt before creating it.
3. Open only the selected bucket file. If its `State` is not `active`, update it to `active` before reading touchpoints.
4. Read only that bucket's required touchpoints before reporting.
5. Report first: selected bucket, required touchpoints read, current behavior, proposed edits, validation plan, and extra touchpoints if needed.
6. Only edit after the plan is clear.
7. Run the bucket's validation.
8. Update the bucket file's `Updates` section with completed tasks, discoveries, gotchas, test results, and handoff notes.
9. Update this workstream's `Progress`, `Bucket Index`, and `Updates` only for progress, sequencing changes, cross-bucket discoveries, and cross-bucket gotchas. Also update the next bucket file's `State` from `later` to `next`. Use the Read tool (not Bash `cat`) to open workstream.md before editing it — Edit requires a prior Read call.
10. Keep only one bucket active at a time unless the user explicitly authorizes parallel execution.

## Bucket Index

| B | State | File | Goal | Depends |
|---|---|---|---|---|
| B01 | next | buckets/B01_module-representation.md | Module spec design + contract section + design review | — |
| B02 | later | buckets/B02_module-refactor.md | Matchers behind Module seam, behavior-locked | B01 |
| B03 | later | buckets/B03_per-row-threshold.md | `tune` becomes per-row actuator (gated) | B02 |
| B04 | later | buckets/B04_batch-attribution.md | Shared-cause noise batches attribute to breadth layer | — |
| B05 | later | buckets/B05_tool-call-module.md | PreToolUse tool-call module + executor | B02 |
| B06 | later | buckets/B06_proposal-engine.md | Audit-cadence proposal read + consent-gated apply + provenance | B02, B04 |

States: `next`, `active`, `blocked`, `done`, `deferred`, `later`.

**Signal gate on B06:** before activating B06, check live FN/evidence volume
(`monition report` FN section; firings with `match_evidence`). If violations
still sit at ~1 organic exemplar or match_evidence < ~500 firings, prefer
running B04/B05 first or pausing — the engine must not ship proposals trained
on days of data (the sequencing constraint that gated this whole phase).

## Cross-Bucket Invariants

- Data/model contract: preserve `docs/contracts/takeaway-store.md`; buckets that
  touch row fields, firings, or any new persisted artifact must read the
  relevant section before editing, and contract-section-first for any schema touch.
- **Assess-path == eval-path** (named invariant): the code path used to decide a
  module candidate matches (in proposals, calibration, or replay) must be the
  same path production matching executes — never a re-implementation.
- **Mutation = consented row edit with provenance**: old spec recorded before
  any change; no auto-apply anywhere; writes only via narrow WriteStore verbs
  (no generic setter — decision 2026-06-21).
- **Behavior-preserving until consented**: the module refactor changes zero
  matching behavior; parity/characterization tests lock current semantics first.
- **No learned component without a B02-grade pre-registered gate** (framing
  decision; the relevance-cascade NO-GO is not reopened).
- Hooks stay cold, blocking subprocesses: nothing added to the hook path may
  load models, re-open stores per hit, or add O(N) reads (the 865→8 ms lesson).
- Violations/FN events never enter precision denominators, disclosure dedup, or
  scorer evidence (v7 contract §Violation semantics).

## Deferred / Non-Goals

- Tier-3 evaluator (scoring CLAUDE.md/prompts/skills) — CMS's; monition stops
  at the substrate.
- Deployment/dogfooding orchestration — CMS's.
- Re-opening the global learned relevance head (B02 NO-GO stands).
- Layered/composed multi-module triggers beyond what a proposal actually needs
  — representation must allow composition (B01), but do not build a composition
  engine ahead of a consuming proposal.
- `state probe` module kind — listed on the ladder, no consuming row class yet.

## Global Implementation Notes

- Data-readiness snapshot at creation (2026-07-01): 348 ratings (8.0%), 67 rows
  with ≥3 ratings, 0 rows ≥5 noise ratings, 13 violations across 3 rows (1
  clean organic exemplar: t28), 46 firings with match_evidence. FP-side work is
  data-ready; FN/evidence-side work is not yet.
- The spike's durable artifacts (Layer+ABSTAIN concept, cost-ordered cascade
  orchestrator, `layer_eval` rank-normalized conditional-lift harness) live in
  the paused relevance-cascade workstream — B06 judges module candidates with
  that discipline; do not rebuild it blind.
- Store is a shared live hub under an editable install — suite green before
  stepping away; synthetic writes only to scratch stores (verification IS
  instrumentation — this includes piping test JSON into hooks).
- Exit gate (road.md §Phase 7): one full lifecycle observed live on the hub +
  measured injected-volume reduction at equal-or-better helpful rate vs
  pre-mutation baseline.

## Updates

- [2026-07-01 20:11] Initial plan created (Phase 6 closed same day; exit gate
  met via seed signatures + backfill sweep). Next: B01/module-representation-design.
