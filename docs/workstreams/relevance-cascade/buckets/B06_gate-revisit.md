# Bucket B06: Gate revisit — metamatch re-test + head re-score at 4.6× data

Parent: ../workstream.md
State: done
Goal for session: honest per-layer GO/NO-GO on today's corpus.
Target duration: one session
Context budget: Read parent + this bucket + required touchpoints only.

## Conceptual mapping

- Both re-tests (metamatch, head) consume the same rebuilt label dataset and the same
  LORO-CV gate harness; running them together amortizes the dataset rebuild and makes
  the redundancy comparison (does metamatch add lift *over* the head, or vice versa)
  free. This bucket executes the NO-GO doc's revisit note: both spike premises —
  the leak-inflated 0.78 AND the buried metamatch negative — were measured on the same
  leaky n=102 fixture, so both need honest re-measurement before B03 knows its residents.

## Data contract / provenance

- Inputs: hub firings, **read-only**, via `monition export-firings --rated-only`
  (the approved reader) — rated `on_demand` firings only (the cascade gates the passive
  path only). Corpus at bucket creation: 594 rated on_demand / 137 distinct rows /
  337 noise + 257 helpful; 577 carry `situation` (verify at implementation time).
- Inputs: metaness labels for rows and prompts — produced by an **offline LLM oracle
  pass** (per-item `meta` bool + `confidence`), schema per the spike's
  `metaness_out.json`. The oracle labels data; it never ships.
- Outputs: rebuilt label dataset (`data/relevance-cascade/`, gitignored — contains real
  session prompts); per-layer gate verdicts recorded in this bucket's Updates + the
  workstream; if a head variant clears, a serialized head per contract §2.
- Provenance: dataset rows keep `takeaway_id` + firing id; the split is **row-disjoint**
  (hold out whole `takeaway_id`s). Builder asserts the per-row-prior AUC ≤ 0.6 on test
  (C1 invariant).
- Validation: conservation vs the export count; class balance reported per split;
  parity invariant checked (see Design direction).

## Tasks

- [ ] Rebuild the label dataset at today's volume with B01's corrected tooling
  (`tools/build_relevance_labels.py`), preserving row-disjoint split + parity + per-row-prior
  assertion. Record n / rows / balance.
- [ ] Offline oracle pass: metaness labels (`meta`, `confidence`) for all dataset rows and
  prompts, spike schema.
- [ ] Metamatch signal (`+confidence-product` on agree / `−` on disagree, per the spike's
  `run_eval_metamatch.py`), evaluated with the `layer_eval` discipline — marginal AUC,
  Spearman redundancy vs cosine and vs the head, CV conditional lift — under **leave-row-out
  CV vs the AUC confidence interval** (the corrected B02 gate, bar: 95% CI LB > 0.60).
- [ ] Re-score the B02 head variants (logistic-on-product, PCA40) on the new dataset, same
  gate, same bar.
- [ ] Runtime-estimability check for metamatch: prompt-side metaness must be computable on
  the hook path with **no inline LLM** (candidate: embedding-centroid or lexical estimator,
  trained/validated against the oracle labels). Metamatch is GO only if the *runtime
  estimator* preserves the separation the oracle-labeled signal shows — an oracle-only GO
  is a NO-GO for integration.
- [ ] Record per-layer verdicts in Updates; append a dated **Update** to
  `docs/decisions/2026-06-21-relevance-cascade-b02-no-go.md` with the honest re-test
  results (it currently carries the revisit as an open question); hand the cleared-resident
  list to B03.

## Required touchpoints

- `../workstream.md  Cross-Bucket Invariants`  gate methodology, parity, row-disjoint eval.
- `docs/contracts/relevance-cascade.md  §1, §2`  dataset + head-artifact contract.
- `docs/decisions/2026-06-21-relevance-cascade-b02-no-go.md  ## Revisit note`  the two
  premises this bucket re-opens.
- `tools/build_relevance_labels.py  (whole file)`  the corrected dataset builder to re-run.
- `spike branch spike/relevance-cascade — spike/run_eval_metamatch.py, spike/layer_eval.py`
  metamatch construction + the layer-worthiness engine (methodology to graduate, not code
  to copy).

## Conditional touchpoints

- `src/monition/relevance/  (B02 head + eval code)`  read when re-scoring the head — reuse,
  don't rewrite.
- `src/monition/embed.py  _embed_raw, MODEL_NAME`  read if the runtime-estimability check
  builds an embedding-based metaness estimator.

## Do-not-read / avoid

- `spike README "Regenerating fixtures" SQL`  it selects `trigger_context` (the ≤200-char
  preview) — the exact C2 train/infer parity bug B01's red-team fixed. Fixtures come from
  B01's tooling, never from these commands.

## Design direction

- The gate is unchanged from the corrected B02 form: leave-row-out CV, 95% CI lower bound
  must clear 0.60 against the ~0.5 row-disjoint baseline. Per-layer verdicts — metamatch
  and the head are judged independently; either, both, or neither may clear.
- Parity invariant (workstream): the prompt half is `situation` at train /
  `prompt[:SITUATION_CHARS]` at infer; the row half is `f"{one_liner} {trigger_spec}"`.
  Verify against a live sample before training — a field/truncation mismatch silently
  destroys the AUC.
- Metamatch is a ~1-parameter signal: expect a tight CI. If it clears, it enters B03 as a
  scorer layer whose row-side metaness is precomputed offline and prompt-side comes from
  the validated runtime estimator.
- All instrumentation writes go to scratch stores or gitignored files; the hub is
  read-only for this bucket.
- Rank-normalize before any signal comparison or combination (layer_eval already does) —
  raw-confidence combiners grade calibration, not information.

## Validation

- Dataset builder assertions pass: row-disjoint split, per-row-prior AUC ≤ 0.6 on test,
  conservation vs export count.
- `layer_eval`-style report produced for metamatch + head variants with LORO AUC + CI.
- Expected: a recorded GO/NO-GO per layer — the bucket is done when the verdicts are
  written down, whichever way they fall.

## Done criteria

- [ ] Tasks complete.
- [ ] Validation passes.
- [ ] Bucket `Updates` section records verdicts/discoveries/gotchas/handoff.
- [ ] Parent workstream progress updated; NO-GO decision doc carries the re-test Update.

## Updates

- [2026-07-02] Created (revisit dispatch — session re-opened the workstream after finding
  the metamatch negative was buried on the leaky fixture and the corpus grew 129→594
  rated on_demand / 46→137 rows). Handoff: none yet. Gotchas: none yet.
- [2026-07-03] Dataset rebuilt: 594 records / 137 rows, conservation exact (674 = 594 +
  80 not_on_demand), 577/594 prompts from `situation`, per-row-prior 0.500 on the static
  split. **Gotcha — memory:** embedding 577 near-512-token prompts at fastembed's default
  batch 256 allocates multi-GB attention buffers (June's ≤200-char previews masked this);
  first trainer run destabilized the machine (WSL, 8GB). Fixes shipped: `_embed_raw`
  batch_size=16 (`embed.py`); daemon RSS self-ceiling `DAEMON_RSS_MAX_MB=600` (the warm
  daemon had arena-bloated 106MB→1.8GB, ONNX arenas never shrink — killed, respawns
  capped); B06 embeddings precomputed once to `data/relevance-cascade/embed_cache.jsonl`
  via `tools/embed_relevance_cache.py` (deduped 1188→476 texts, chunked, resumable),
  consumed by `train_relevance_head.py --embed-cache` through a new `embed_fn` injection
  on `build_features` (value-identical; parity preserved). Downstream evals are now
  model-free numpy.
- [2026-07-03] **Head re-score at 4.6× data: FAIL, by a hair — and the volume-wall story
  is now answered.** LORO-CV AUC 0.657, 95% CI [0.598, 0.715] vs bar CI-LB > 0.60 (June:
  0.669, CI [0.551, 0.778]). The CI tightened ~2.6× around an unchanged ~0.66 point
  estimate: more data did not reveal a better head, it revealed the head is *genuinely*
  ~0.66. A usable operating point now exists (23% noise suppressed @ 10% helpful loss,
  threshold 0.014) — June had none. Verdict: NO-GO on the pre-set bar (0.598 ≤ 0.60;
  the bar exists to resist exactly this rationalization), but the finding shifts from
  "unvalidatable" to "validated-marginal". Note: the printed per-row-prior 0.191 is a
  benign LOO artifact (each held-out row scored by the leave-it-out global mean
  anti-correlates with its own labels — `eval.py:52`); leak would read HIGH, not low.
  Next: metamatch oracle pass (awaiting rubric/model sign-off), then its gate run.
- [2026-07-03] **User decision — bar amended post-hoc, head ACCEPTED for integration.**
  The owner of the 0.60 bar (set 2026-06-21 pre-numbers) reviewed the honest result
  (CI-LB 0.598, tight CI around 0.66, usable operating point 23% noise @ 10% helpful
  loss) and accepted the validated-marginal head for the B03 scorer slot, eyes open on
  the 10% helpful collateral. Recorded as an explicit amendment, not a gate pass — the
  trainer still reports FAIL against the original bar. Serialization deferred until the
  metamatch verdict decides whether the scorer slot ships head-only or head+metamatch;
  the serializer change (trainer writes only on PASS today) lands with that decision.
- [2026-07-03] **Metamatch verdict: the buried negative was TRUE — honest re-test FAILS
  decisively.** Oracle pass: haiku, 16 batches, 398 items (261 prompts / 137 rows; 122
  meta prompts, 50 meta rows; rubric = "operating the machinery vs engineering it";
  10-lowest-confidence + 5-high spot-check passed human review — low-conf items were
  genuinely ambiguous stubs like "check"/"do it"). Result: metamatch AUC **0.552**, CI
  [0.502, 0.601] — FAIL vs 0.60 CI-LB bar. P(noise|mismatch)=0.62 vs P(noise|match)=0.52
  (the spike's 70/45, faded). Decorrelated from the head (Spearman +0.05) but adds NO
  conditional lift: rank-combined head+metamatch LORO AUC 0.645 vs head-alone 0.657
  (−0.012), combo CI-LB 0.584. So the June "cheap proxy doesn't separate" negative was
  right despite its leaky fixture. Runtime-estimability task MOOT. Evaluator graduated:
  `tools/eval_metamatch.py`; oracle labels: `data/relevance-cascade/metaness_out.json`.
- [2026-07-03] **B06 closed.** Scorer slot ships **head-only** (user acceptance,
  2026-07-03). Artifact serialized with the new explicit override
  (`train_relevance_head.py --write --accept-marginal`, gate verdict still prints FAIL)
  to `~/.cache/monition/relevance/head-v1.json` (contract §2's candidate location — near
  the managed weights cache, NOT in-repo; B03/B04 finalize). Round-trip AUC exact +
  model-id refusal verified. Validation: full suite 341 passed / 1 pre-existing failure
  (`test_generated_matches_cms_regen`, METHOD_LESSON_ROUTING stale vs CMS — predates
  this bucket, lives in the mutation-engine-touched `init_sync.py` path, surfaced to
  user). Handoff to B03: residents = boilerplate gate (refactor in, pre-match position),
  span-sanitization transform (candidate, decided at B03), head scorer (artifact above,
  operating point threshold≈0.014 → 23% noise @ 10% helpful loss, B05 finalizes);
  metamatch is OUT.
