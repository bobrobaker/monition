# Bucket B03: Per-row semantic threshold

Parent: ../workstream.md
State: later
Goal for session: `tune` becomes a gated per-row threshold actuator.
Target duration: 45 min
Context budget: Read parent + this bucket + required touchpoints only.

## Conceptual mapping

- One concept (the semantic module's threshold becomes row data, moved by that
  row's own ratings) across a small edit surface: the threshold storage (per
  B01), the semantic module read path, and the `tune` verb.

## Data contract / provenance

- Inputs: rated firings per row (67 rows have ≥3 ratings at workstream
  creation); `match_evidence` semantic scores — the score production matched at
  (verify field shape against a real firing row at implementation time).
- Outputs: per-row threshold value at B01's decided location; a decision-doc'd
  objective (recall at precision floor).
- Provenance: every threshold change is a consented row edit with old value
  recorded (B01's provenance representation).
- Validation: pre-registered gate (below) — registered BEFORE measuring.

## Tasks

- [ ] Pre-register the gate in this file's Updates before computing anything:
      metric (e.g. replay-simulated noise reduction at no helpful-firing loss,
      vs the global SIM_THRESHOLD baseline), the row set (rows with ≥3 ratings
      and semantic traffic), and the pass bar.
- [ ] Implement per-row threshold read in the semantic module (NULL = global
      default; no behavior change for untouched rows).
- [ ] `tune` computes proposed per-row thresholds from that row's rated firings
      + match_evidence scores; PRINTS proposals with evidence; applies only via
      an explicit consented flag (narrow verb, old value recorded).
- [ ] Run the gate via `replay` on a scratch snapshot; report pass/fail
      honestly — a NO-GO parks the actuator (advisory mode stays), it does not
      lower the bar.

## Required touchpoints

- `docs/contracts/takeaway-store.md  grep -n "Trigger modules"  threshold storage per B01`
- `src/monition/score.py  grep -n "EV_THRESHOLD\|N_COLD_START\|def score"  the gate this must not entangle`
  Threshold tunes the Filter (matching), not the Gate (suppression) — keep the
  seam clean per 2026-06-18-noise-targets-the-filter-not-the-gate.
- `src/monition/report.py  grep -n "render_tune"  current advisory output`
- `src/monition/cli.py  grep -n "\"tune\""  verb wiring`

## Conditional touchpoints

- `src/monition/replay.py  grep -n "def "  replay surface`
  Read when wiring the gate measurement.

## Design direction

- One interpretable parameter per row, moved by that row's own ratings — this
  is the deliberately-different middle path the B02 NO-GO left open; do NOT
  introduce features, embeddings-of-ratings, or any trained component here.
- Rows below 3 ratings are untouchable (cold-start rules unchanged).
- Scratch-store discipline for all measurement (snapshot + MONITION_STORE).

## Validation

- Full suite green; gate result recorded in Updates with the pre-registered
  bar quoted verbatim next to the measured number.
- Expected: untouched rows behaviorally identical; tune-applied rows change
  only via consent.

## Done criteria

- [ ] Tasks complete.
- [ ] Validation passes (or NO-GO honestly recorded and actuator parked).
- [ ] Bucket `Updates` section records discoveries/gotchas/handoff.
- [ ] Parent workstream progress updated.

## Updates

- [2026-07-01 20:11] Created. Handoff: none yet. Gotchas: none yet.
