# Bucket B04: Batch-dump attribution

Parent: ../workstream.md
State: later
Goal for session: Shared-cause noise batches attribute to breadth, not rows.
Target duration: 30 min
Context budget: Read parent + this bucket + required touchpoints only.

## Conceptual mapping

- One analytical concept: a batch of noise ratings sharing (session, prompt
  moment) is evidence about the prompt × breadth interaction, not N independent
  row defects. Edit surface is read-side only (metrics/export), feeding B06.

## Data contract / provenance

- Inputs: firings grouped by (session_id, fired_at proximity / same
  trigger_context) — verify the grouping key against real bulk-rated batches in
  the hub (the 06-20 audit found one meta-prompt lighting 19 rows).
- Outputs: a batch-attribution annotation on export/metrics records (e.g.
  `batch_size` / `shared_cause` fields — additive, no schema_version bump), so
  B06's proposal logic can discount shared-cause noise for per-row decisions.
- Validation: on the hub snapshot, known bulk-rated batches (one citation, many
  rows) are detected; individually-rated firings are not flagged.

## Tasks

- [ ] Detect shared-cause batches from firing data (same session + same prompt
      moment; the injection already caps batches at 5+lexical, so bound is known).
- [ ] Expose the annotation in `export_records` (additive keys) and the
      per-row audit metrics (a noise count split: individual vs batch).
- [ ] Report surface: per-row noise line distinguishes "N noise (M in batch
      dumps)" so a human reading recommendations sees the shared cause.

## Required touchpoints

- `src/monition/metrics.py  grep -n "def audit\|noise"  per-row aggregates`
- `src/monition/export.py  grep -n "_record\|rating_priority"  export record + additive-keys precedent`
- `docs/decisions/2026-06-18-noise-targets-the-filter-not-the-gate.md  §both cautions`
  The attribution rule this implements.

## Conditional touchpoints

- `src/monition/score.py  grep -n "evidence_count"  scorer evidence`
  Read only if choosing to discount batch noise in the suppress gate itself —
  default is NO (pre-Phase-7 stance: the Gate consuming them stays accepted;
  this bucket only *annotates* for B06 and humans).

## Design direction

- Read-side only; no store writes, no rating rewrites — the labels are honest
  data (those firings WERE dilution), attribution changes their *weight* in
  proposals, not their existence.
- Snapshot the hub to a scratch store for development; never sample live.

## Validation

- Full suite green + a fixture with one 6-row batch and two individual ratings
  asserts the exact split.
- Expected: `monition report` on the scratch snapshot shows batch-split noise
  counts for known dump sessions.

## Done criteria

- [ ] Tasks complete.
- [ ] Validation passes.
- [ ] Bucket `Updates` section records discoveries/gotchas/handoff.
- [ ] Parent workstream progress updated.

## Updates

- [2026-07-01 20:11] Created. Handoff: none yet. Gotchas: none yet.
