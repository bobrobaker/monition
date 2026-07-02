# Workstream: Mutation Engine (Phase 7)

Progress: B01–B05 done (2026-07-02). B06/proposal-engine stays signal-gated — check FN volume + match_evidence accumulation (workstream signal gate) before activating.
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
| B01 | done | buckets/B01_module-representation.md | Module spec design + contract section + design review | — |
| B02 | done | buckets/B02_module-refactor.md | Matchers behind Module seam, behavior-locked | B01 |
| B03 | done | buckets/B03_per-row-threshold.md | `tune` becomes per-row actuator (gated) — NO-GO, apply parked; v8 shipped | B02 |
| B04 | done | buckets/B04_batch-attribution.md | Shared-cause noise batches attribute to breadth layer | — |
| B05 | done | buckets/B05_tool-call-module.md | PreToolUse tool-call module + executor | B02 |
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
- [2026-07-01] B01 design drafted (docs only, zero code) — awaiting user
  acceptance before B02. Cross-bucket decision with sequencing impact: **v8 is
  one atomic migration landing at B03** (sem_threshold + `tool_call` enum
  widening + `mutations` table together), so B05 and B06 consume v8 without
  further schema touches and B02 stays schema-free. Contract now carries a
  planned-v8 paragraph as B03's binding spec.
- [2026-07-02] B01 accepted; B02 done same day (modules.py seam, parity-locked,
  suite green). Cross-bucket discovery: `metrics.spec_matches` was a live glob
  re-implementation — folded onto `modules.glob_match`; when touching other
  offline consumers, grep for further matcher copies before writing new ones
  (assess-path == eval-path is now enforceable by import, not by prose).
- [2026-07-02] B03 done: v8 shipped (atomic — sem_threshold + tool_call enum +
  mutations table; SQLite = takeaways rebuild, CHECKs can't be ALTERed), verb
  surface split user-ratified (`calibrate` = Filter, `tune` stays Gate), and
  the pre-registered gate returned **NO-GO** (75% holdout noise reduction but
  helpful_lost=1 vs a zero bar) — apply parked, proposals advisory. Cross-
  bucket consequences: B05 gets its enum value for free; B06 gets `mutations`
  + a worked example of the pre-registered-gate discipline and the margin-less
  threshold-rule failure mode. OPERATIONAL: hub must be migrated to v8 by the
  user (editable install → hooks fail open until then).
- [2026-07-02] Hub migrated to v8 (user-ran); hooks verified healthy. B04 done
  same day: batch attribution is read-side live — hub measurement: 80% of
  rated noise (103/129) is batch-borne, so B06's per-row proposals MUST
  consume `batch_size`/`noise_batch` or they will over-punish rows for
  prompt-layer noise. The signal-gate arithmetic on B06 should also count
  batch-discounted noise, not raw noise.
- [2026-07-02] B05 done: tool_call module live end-to-end — t91 consented
  down the ladder (`migrate_kind` provenance) and fired live (f4459) the
  same session. Cross-bucket lessons for B06: (a) substring needles match
  MENTIONS as well as acts (f4459 fired on a heredoc containing "git push");
  proposals should consider anchored needles. (b) Pre-existing dialect
  quoting bug found+fixed at the backend seam (backend.quote) — SQLite
  hosts corrupted values containing backslashes/apostrophes; apostrophe
  prompts broke firing INSERTs silently. (c) `_merge_hook_entries` staleness
  now keys on matcher too — matcher-only changes propagate via sync.
  Workstream state: only B06 remains, behind its signal gate.
