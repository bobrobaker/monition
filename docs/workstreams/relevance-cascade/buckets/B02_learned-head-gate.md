# Bucket B02: Learned Head + GO/NO-GO Gate

Parent: ../workstream.md
State: done (NO-GO — gate failed, workstream paused)
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

- [x] Graduate the embedding-head trainer/eval into a repeatable module
  (`src/monition/relevance/head.py` + `tools/train_relevance_head.py`).
- [x] Also graduate `layer_eval` → `src/monition/relevance/eval.py` (LORO CV, cluster-bootstrap
  CI, per-row-prior leak check, suppression curve).
- [x] Measure with **leave-row-out CV** + suppression curve. Reported train AUC (1.000),
  gap (0.33), and the 95% CI.
- [x] **Apply the GO/NO-GO gate**: bar set with the user up front (95% CI lower bound > 0.60).
  Result: **FAIL** — best CI LB 0.582 < 0.60.
- [x] On FAIL: stopped, wrote `docs/decisions/2026-06-21-relevance-cascade-b02-no-go.md`,
  paused the workstream. (No artifact serialized — PASS branch N/A.)

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

- [x] Gate decision recorded (NO-GO) with the bar stated (95% CI LB > 0.60).
- [~] On PASS: artifact serialized + §2 finalized + round-trip validated. **N/A — FAIL.**
  (§2 marked deferred; serializer + round-trip + model-id refusal are implemented in
  `head.py`, just not run for production weights.)
- [x] `layer_eval` + trainer graduated and runnable.
- [x] Bucket `Updates` records test AUC, gap, operating-point existence (no artifact path — NO-GO).
- [x] Parent progress updated (workstream paused).

## Updates

- 2026-06-21 Created. Handoff: none yet. Gotchas: none yet.
- 2026-06-21 **DONE — NO-GO.** Built `src/monition/relevance/{head.py,eval.py}` (graduated the
  spike's logistic-on-product head + leave-row-out CV + cluster-bootstrap CI + per-row-prior
  leak check + suppression curve) and `tools/train_relevance_head.py` (the trainer + gate).
  - **Bar (set with user up front):** 95% CI lower bound of LORO-CV AUC > 0.60.
  - **Result:** logistic-on-product LORO-CV **0.669**, CI [0.551, 0.778]; train AUC 1.000
    (gap 0.33 = overfit at low L2, but the CV ceiling does not move). Variant sweep: concat
    0.628, PCA20 0.638, PCA40 **0.676 CI [0.582, 0.762]** (best), cosine-alone 0.441. L2 sweep
    {2…800}: point estimate plateaus ~0.667, only falls with more reg. **No head clears 0.60**
    — best CI LB anywhere is 0.582.
  - **Operating point:** at ≥90% helpful retention, suppresses only ~20% of noise (54%→~50%).
  - **Verdict:** volume wall (46 rows → wide CI), not a model bug. No artifact serialized
    (§2 artifact-format decision is moot under NO-GO; the head.py serializer + model-id
    refusal are written and unit-exercisable, just not run for production weights).
  - per-row-prior leak check = 0.060 (LOO train-mean shrinkage artifact, well under the 0.6
    leak ceiling; LORO is row-disjoint by construction so no leak inflates the CV).
  - **Handoff to a revisit:** re-open the spike's two false premises (leak-inflated 0.78;
    metamatch negative measured on the same leaky n=102 fixture). Decision doc:
    `docs/decisions/2026-06-21-relevance-cascade-b02-no-go.md`.
