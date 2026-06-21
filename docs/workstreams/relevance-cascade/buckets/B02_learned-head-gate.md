# Bucket B02: Learned Head + GO/NO-GO Gate

Parent: ../workstream.md
State: next
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
  `split`, `prompt`, `prompt_source`, `prompt_group`, `takeaway_id`). `prompt` is the
  **full** prompt (B01 fixed a parity bug where it was the ≤200 `trigger_context` preview);
  `split` is **row-disjoint** (group by `takeaway_id`), NOT prompt-grouped.
- Outputs: a serialized head artifact per §2 — weights + feature spec + `version` +
  `embed.MODEL_NAME` + train/test AUC. **Resolve and record the artifact format + on-disk
  location in §2** (open decision).
- Provenance: feature = L2-normalized prompt⊕row embeddings from `embed._embed_raw`. Parity
  is about the input STRING (contract §2): prompt = full prompt; row =
  `f"{one_liner} {trigger_spec}"` re-derived from `takeaway_id` (read the takeaway — export
  lacks `trigger_spec`). MUST match B03/B04's inference path.
- Validation: **leave-row-out CV AUC** on human labels vs the AUC confidence interval and
  the ~0.5 row-disjoint baseline — NOT a single-split point estimate (see C1/M1 below).

Report first (contract check): which §2 fields does this define? what consumer (B03 runtime)
loads the artifact? what would break parity? how is parity validated?

## Tasks

- [ ] Graduate the embedding-head trainer/eval into a repeatable module (candidate:
  `src/monition/relevance/` or extend the eval substrate). Train on B01 train split.
- [ ] Also graduate `layer_eval` (the calibration-invariant "add-a-layer" harness, incl.
  rank-normalized Spearman + conditional-lift) — it is the durable tool, used here and later.
- [ ] Measure with **leave-row-out CV** (every `takeaway_id` held out once → all 129 firings
  get an unseen-row prediction; baseline ~0.5) + a precision/recall curve. Report the
  train/test gap (overfit check) AND the AUC confidence interval (n is small).
- [ ] **Apply the GO/NO-GO gate**: define the usefulness bar with the user up front. The bar
  is on the **CI lower bound clearing the ~0.5 row-disjoint baseline** (a point estimate at
  this n is uninformative — see C1/M1) AND a usable operating point exists. Record PASS/FAIL.
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
  cleared the bar on **human** labels — oracle labels can inflate apparent AUC.
- **C1 (B01 red-team): row-disjoint eval is mandatory.** The head embeds prompt⊕row over
  ~46 rows; a prompt-grouped split lets a prompt-ignoring per-row prior hit AUC ~0.77 ≈ the
  headline — proving nothing. Hold out whole rows; the per-row baseline is ~0.5. The spike's
  `embed_classifier.py` groups on *prompt* — graduate its mechanics but switch the group key
  to `takeaway_id` (do not blindly copy).
- **M1 (B01 red-team): n is tiny, so report the CI.** At ~46 rows the held-out positives are
  few (AUC SE ≈ 0.08–0.13); a single point estimate can't distinguish 0.78 from chance. Gate
  on the CI lower bound, and prefer leave-row-out CV over any single split.
- Pick the simplest head that wins (logistic-on-product was as good as PCA+MLP in the spike).
  Heavy regularization; report train AUC to expose overfit.
- Operating-point *selection* (the threshold) is B05; here, only confirm a usable point
  EXISTS on the PR curve. Serialize the head, not a threshold.

## Validation

- Leave-row-out CV AUC printed, with train AUC, the gap, and the CI.
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
