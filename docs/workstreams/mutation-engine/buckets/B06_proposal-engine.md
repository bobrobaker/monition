# Bucket B06: Proposal engine

Parent: ../workstream.md
State: later
Goal for session: Audit-cadence read proposes consented row mutations.
Target duration: 60 min
Context budget: Read parent + this bucket + required touchpoints only.

## Conceptual mapping

- The verbs that close the lifecycle: one read-side engine walking per-row
  evidence (ratings with B04 attribution, violations, match_evidence) and
  emitting typed proposals — tighten / broaden / migrate-down-ladder / merge /
  graduate / stale — each rendered with its evidence for the mine-session
  consent gate.

## Data contract / provenance

- Inputs: `export-firings` records (incl. `match_evidence`, batch annotations),
  `violations` rows, row specs. Verify all field names against real records —
  not this spec.
- Outputs: proposals are a READ (rendered text/JSON), not store rows, unless
  B01 decided a persisted proposal record; applies happen only through the
  narrow consented verbs with old-spec provenance.
- Validation: replay counterfactual per applied mutation (did the tightened
  spec keep helpful firings and drop noise?).

## Tasks

- [ ] **Signal gate first** (parent §Bucket Index): report FN/evidence volume;
      if still thin, stop and surface — do not build on 3-row data.
- [ ] Proposal rules, deterministic and evidence-cited: tighten (noise
      concentrated off-pattern in match_evidence), broaden (violations name
      sessions whose text the trigger missed), migrate (every helpful semantic
      hit's evidence contains a stable literal → keyword/tool_call candidate),
      merge (active near-duplicates), graduate (fires ~every session,
      consistently helpful → propose always-on surface + retire here), stale
      (referent paths/commands vanished from origin repo).
- [ ] Judge module candidates with the `layer_eval` rank-normalized
      conditional-lift discipline (spike artifact — reuse, don't rebuild).
- [ ] Surface: a verb (`monition propose` or report section) consumed at
      mine-time/audit cadence; graduation proposals name the target always-on
      surface but do NOT write it (that's the human's/CMS's move).
- [ ] Apply path: narrow verbs only, old spec recorded, one row at a time.

## Required touchpoints

- `docs/contracts/takeaway-store.md  grep -n "Trigger modules\|Violation"  spec + FN semantics`
- `src/monition/export.py  grep -n "_record"  the evidence record shape`
- `docs/workstreams/relevance-cascade/  grep -rn "layer_eval\|ABSTAIN" --include=*.md`
  Where the judging discipline lives; read the harness pointer, not the spike.
- `src/monition/store_write.py  grep -n "def set_signature\|def retire"  narrow-verb pattern for apply verbs`

## Conditional touchpoints

- `docs/decisions/2026-06-18-noise-targets-the-filter-not-the-gate.md`
  Read if any proposal pushes toward suppression — Filter-first ordering.

## Design direction

- Deterministic rules over evidence; no learned scorer (a learned ranker later
  owes a pre-registered gate and is out of this bucket's scope).
- Every proposal line cites its evidence (firing ids / violation ids /
  match_evidence excerpts) — a human must be able to verify in seconds.
- Batch-attributed noise (B04) discounts toward breadth-layer framing before
  any per-row tighten/suppress proposal.
- Assess-path == eval-path: candidate triggers are evaluated by running the
  REAL modules over stored match_evidence/transcripts, never a re-implementation.

## Validation

- Full suite green; on a hub snapshot, the engine reproduces at least one
  known-good proposal per class where data exists (e.g. merge: a known clone
  pair; broaden: t28's violation) and proposes nothing where evidence is thin.
- Expected: exit-gate path live — one consented mutation applied on the hub +
  replay counterfactual measured (injected-volume reduction at equal-or-better
  helpful rate).

## Done criteria

- [ ] Tasks complete.
- [ ] Validation passes.
- [ ] Bucket `Updates` section records discoveries/gotchas/handoff.
- [ ] Parent workstream progress updated (workstream complete if exit gate met).

## Updates

- [2026-07-01 20:11] Created. Handoff: none yet. Gotchas: none yet.
