# Bucket B01: Label Foundation

Parent: ../workstream.md
State: next
Goal for session: Build the (prompt,row)→label dataset + leakage-free split.
Target duration: 30 min
Context budget: Read parent + this bucket + required touchpoints only.

## Conceptual mapping

- One mental model: *assemble trustworthy training data*. The spike trained on 102 firings
  and overfit (train AUC 1.00); this bucket expands and structures the labels so B02 can
  train + gate on something real. Edit surface: a data-prep script + the contract.

## Data contract / provenance

Owns §1 of `docs/contracts/relevance-cascade.md` (read it in full — you are defining it).

- Inputs: hub `firings` ⋈ `takeaways` — rated `on_demand` firings with `trigger_context`.
- Outputs: a label dataset (gitignored data dir) per §1 — fields `takeaway_id`, `prompt`,
  `label`/`oracle_relevant`, `label_source`, `split`.
- Provenance: `split` by **whole-prompt grouping** (normalized prompt, 120-char key) so no
  prompt straddles train/test. `label_source` keeps human vs oracle labels distinguishable;
  **test split is human-labeled only**.
- Validation: conservation tally — every rated firing is in the dataset or in a `skipped`
  count with a reason.

## Tasks

- [ ] Define §1 of the contract concretely (dataset path, file format, the schema above).
- [ ] Build the dataset from the hub: pull rated `on_demand` firings; assign whole-prompt
  `split`; record `label_source=human`. Emit the conservation tally.
- [ ] Expand labels toward n that supports 384-dim features: (a) rate more of the ~434
  unrated firings via the evidence-gated rating path, and/or (b) offline-oracle generation
  over additional (prompt,row) pairs — tag these `label_source=oracle`, keep them OUT of the
  test split.
- [ ] **Decide the score-logging question** (contract §3): log nothing / scalar score /
  full embedding for future training. Record the decision + rationale in the contract.
  (Wiring, if any, is B04 — decide here, do not wire.)

## Required touchpoints

- `docs/contracts/relevance-cascade.md`  full file  — you define §1, decide §3.
- `src/monition/export.py`  `grep -n "def \|unrated\|--session\|rating_priority"`  — the
  existing unrated-firing export + rating-priority order to drive label expansion; reuse it.
- `spike/relevance-cascade:spike/embed_classifier.py`  lines building `prompts/rowtexts/y`
  + `norm_prompt`/grouped CV — the exact prompt-normalization + grouping to reproduce.

## Conditional touchpoints

- `src/monition/store.py` / `store_write.py`  `grep -n "def firings"`  — read only if you
  need the firings reader/field set beyond what `export.py` exposes.
- the mine-session rating discipline (CMS-owned) — read only if expanding via human rating
  rather than the oracle.

## Design direction

- **Do not mix label sources in the test set.** Human labels are ground truth; oracle
  labels are a training-volume aid. The gate (B02) is measured on human-only test.
- Whole-prompt grouping is non-negotiable — the spike showed standard CV (0.81) vs grouped
  (0.78) differ; only grouped is honest. Reuse the spike's 120-char normalized key exactly.
- This bucket produces DATA, not a model. No training here (that's B02).
- Real session prompts → gitignored; never commit the dataset.

## Validation

- Print the conservation tally: `total rated firings = in_dataset + skipped(reason)`.
- Assert: no normalized-prompt appears in both `train` and `test`.
- Assert: `test` rows are all `label_source=human`.

## Done criteria

- [ ] Tasks complete; contract §1 defined, §3 decision recorded.
- [ ] Validation passes (conservation + no split leakage + human-only test).
- [ ] Bucket `Updates` records the final n (train/test), label-source mix, score-logging call.
- [ ] Parent workstream progress updated.

## Updates

- 2026-06-21 Created. Handoff: none yet. Gotchas: none yet.
