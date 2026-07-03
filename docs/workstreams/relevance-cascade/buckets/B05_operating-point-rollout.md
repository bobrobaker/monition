# Bucket B05: Operating Point + Rollout

Parent: ../workstream.md
State: done
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

- [x] Operating point chosen + recorded with the head version.
- [x] Realized effect measured on human test + dogfood, reported as numbers.
- [x] Fork fail-open verified.
- [x] Decision doc marked implemented; `road.md §2` backlinked.
- [x] Bucket `Updates` records the shipped operating point + measured win.
- [x] Parent progress updated → workstream complete.

## Updates

- 2026-06-21 Created. Handoff: none yet. Gotchas: none yet.
- 2026-07-03 **Done — workstream complete.** Operating point chosen by the user from
  the honest LORO curve: **suppress_threshold 0.0139** (expected 23% noise blocked /
  10% helpful lost; adjacent candidates 0.0043 = 14%/5% and 0.0410 = 30%/15% were
  declined — "doesn't distinguish that much, keep as is"). Stored **inside the head
  artifact** (`operating_point` field, head.py serializer extended; scorer resolution:
  explicit arg → artifact → module fallback constant — no magic threshold in code).
  Realized effect: all-rated LORO 23%/10% (by construction); **held-out human test
  split (n=87): 17% noise blocked / 0% helpful lost** — 0% is small-sample-favorable
  (28 helpful ⇒ ~4% quantization), the calibrated expectation stays 23%/10%. Dogfood
  (first live day): 5 real suppression events across 3 sessions; **live suppression
  ran ~32% of candidates vs ~17% expected** — small n (19) on a meta-heavy day;
  suppression log lines now carry row ids + scores (`t<id>@<p>`) so the follow-up can
  rate them; **re-measure checkpoint proposed to the user** (t216-style self-retiring
  row; rating two evidenced firings f6529/f6446 helpful also proposed — the permission
  layer correctly declined unrequested substrate writes mid-bucket). Fork fail-open:
  pinned by `test_no_artifact_fires_ungated_null_score` (no artifact → today's
  behavior, NULL scores). Backlinks: road.md §2 durable position added; Phase 5
  status COMPLETE; `### Next` updated; `2026-06-18-noise-targets-the-filter` marked
  IMPLEMENTED. **Follow-on captured (road.md §2, not scheduled): per-row suppress
  thresholds** — user's design instinct, the suppression-side analog of
  `sem_threshold`, feasible once per-row score+rating volume accumulates.
