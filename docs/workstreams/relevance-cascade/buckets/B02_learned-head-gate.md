# Bucket B02: Learned Head + GO/NO-GO Gate

Parent: ../workstream.md
State: later
Goal for session: Train L2′, measure at scale on human test, gate, serialize.
Target duration: 35 min
Context budget: Read parent + this bucket + required touchpoints only.

## Conceptual mapping

- One mental model: *the learned relevance head as a measured, serialized artifact*.
  Graduates the spike's `embed_classifier.py` methodology into a repeatable trainer/eval and
  applies the **usefulness gate**. If the gate fails, the workstream pauses (B03+ do not run).

## Data contract / provenance

Owns §2 of `docs/contracts/relevance-cascade.md` (read §1 + §2). Consumes B01's dataset.

- Inputs: B01 label dataset (verify field names against a real sample — `label_source`,
  `split`, `prompt`, `takeaway_id`).
- Outputs: a serialized head artifact per §2 — weights + feature spec + `version` +
  `embed.MODEL_NAME` + train/test AUC. **Resolve and record the artifact format + on-disk
  location in §2** (open decision).
- Provenance: feature = L2-normalized prompt⊕row embeddings from `embed._embed_raw` — MUST
  match B03's inference path (cross-bucket invariant: train/infer feature parity).
- Validation: grouped held-out AUC on the **human-only** test split.

Report first (contract check): which §2 fields does this define? what consumer (B03 runtime)
loads the artifact? what would break parity? how is parity validated?

## Tasks

- [ ] Graduate the embedding-head trainer/eval into a repeatable module (candidate:
  `src/monition/relevance/` or extend the eval substrate). Train on B01 train split.
- [ ] Also graduate `layer_eval` (the calibration-invariant "add-a-layer" harness, incl.
  rank-normalized Spearman + conditional-lift) — it is the durable tool, used here and later.
- [ ] Measure on the human-only test split: grouped AUC + a precision/recall curve. Report
  the train/test gap (overfit check).
- [ ] **Apply the GO/NO-GO gate**: define the usefulness bar with the user up front (e.g.
  test AUC ≥ a threshold AND a usable operating point exists). Record PASS/FAIL explicitly.
- [ ] On PASS: serialize the production head artifact (§2). On FAIL: stop, write the
  finding to the decision doc, set workstream `Blocked`.

## Required touchpoints

- `docs/contracts/relevance-cascade.md`  §1–§2  — dataset in, artifact out.
- `spike/relevance-cascade:spike/embed_classifier.py`  full — the trainer + grouped CV +
  product/PCA features to graduate (do not blindly copy: it has a fixed l2/iters, n=102).
- `spike/relevance-cascade:spike/layer_eval.py`  full — the harness to graduate.
- `src/monition/embed.py`  `grep -n "_embed_raw\|MODEL_NAME\|_weights_dir\|SIM_THRESHOLD"`
  — vector API, model id, managed cache dir (artifact-location candidate).

## Do-not-read / avoid

- `src/monition/score.py` — the Gate is out of scope; this head is a Filter, not the Gate.

## Design direction

- The gate is the point of this bucket. Do not skip to serializing a head that hasn't
  cleared the bar on **human** test labels — oracle labels can inflate apparent AUC.
- Pick the simplest head that wins (logistic-on-product was as good as PCA+MLP in the spike).
  Heavy regularization; report train AUC to expose overfit.
- Operating-point *selection* (the threshold) is B05; here, only confirm a usable point
  EXISTS on the PR curve. Serialize the head, not a threshold.

## Validation

- Grouped (whole-prompt) test AUC printed, with train AUC and the gap.
- Artifact round-trips: load it back, reproduce identical scores on a sample.
- Loading refuses if stored model id ≠ live `embed.MODEL_NAME`.

## Done criteria

- [ ] Gate decision recorded (PASS/FAIL) with the bar stated.
- [ ] On PASS: artifact serialized + §2 finalized + round-trip validated.
- [ ] `layer_eval` + trainer graduated and runnable.
- [ ] Bucket `Updates` records test AUC, gap, operating-point existence, artifact path.
- [ ] Parent progress updated (or `Blocked` set on FAIL).

## Updates

- 2026-06-21 Created. Handoff: none yet. Gotchas: none yet.
