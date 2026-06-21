# Bucket B05: Operating Point + Rollout

Parent: ../workstream.md
State: later
Goal for session: Pick the firing threshold, measure noise reduction, dogfood, ship.
Target duration: 25 min
Context budget: Read parent + this bucket + required touchpoints only.

## Conceptual mapping

- One mental model: *turn the wired cascade into a tuned, observed, shipped filter*. The
  head exists (B02), it is wired (B04); this picks the operating point and proves the win on
  held-out data before turning it on broadly.

## Data contract / provenance

- Inputs: the B02 head + the B01 human-only test split + live firings post-integration.
- Provenance: the operating point is a property of the head VERSION; record it alongside the
  head version so a retrain re-selects it. Do not bake a magic threshold into code.

## Tasks

- [ ] From B02's precision/recall curve, pick the **operating point** with the user: choose
  the helpful-loss / noise-blocked trade explicitly (passive = precise-leaning). Record the
  chosen `fire_floor`/`TARGET_CERTAINTY` + the expected blocked-noise / lost-helpful at it.
- [ ] Measure the realized effect on the held-out human test set: noise blocked, helpful
  kept — vs the current always-fire baseline. State it as a number, not a vibe.
- [ ] Dogfood: run live for a session bracket; spot-rate a sample of newly-suppressed and
  still-firing rows to confirm the live behavior matches the offline estimate.
- [ ] Decide rollout scope: this hub vs forks. Note that standalone forks without the head
  artifact must degrade to current behavior (fail-open) — confirm that path.
- [ ] Backlink the workstream result into `road.md §2` (durable position) and mark the
  decision doc implemented.

## Required touchpoints

- B02 head artifact + its recorded PR curve — `grep "## Updates" B02_learned-head-gate.md,
  then read from that offset` for the curve + artifact path.
- `docs/contracts/relevance-cascade.md`  §2  — operating point ↔ head version coupling.
- `src/monition/report.py` / `metrics.py`  `grep -n "def audit\|def tune\|noise"` — reuse
  the existing measurement surface to report blocked/kept rather than hand-rolling.

## Conditional touchpoints

- `docs/road.md`  §2 + `### Next` — read only when backlinking the result at the end.

## Design direction

- The operating point is a USER trade, not a default — surface the PR curve and the
  helpful-loss at each candidate point; let them pick. 0.78 AUC is not a clean separator, so
  some helpful loss is unavoidable; name it.
- Measure on the human test split, not oracle labels.
- Fork-safety: no head artifact → fail-open to today's matcher. A fork must never break
  because the learned head is absent.

## Validation

- Realized blocked-noise / lost-helpful on the human test split, vs baseline, printed.
- Dogfood sample rated; live ≈ offline estimate (within reason — note if not).
- A standalone-fork path (no artifact) verified to fall back to current behavior.

## Done criteria

- [ ] Operating point chosen + recorded with the head version.
- [ ] Realized effect measured on human test + dogfood, reported as numbers.
- [ ] Fork fail-open verified.
- [ ] Decision doc marked implemented; `road.md §2` backlinked.
- [ ] Bucket `Updates` records the shipped operating point + measured win.
- [ ] Parent progress updated → workstream complete.

## Updates

- 2026-06-21 Created. Handoff: none yet. Gotchas: none yet.
