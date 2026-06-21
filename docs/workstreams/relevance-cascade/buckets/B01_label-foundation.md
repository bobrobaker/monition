# Bucket B01: Label Foundation

Parent: ../workstream.md
State: done
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
- Provenance: `split` by **row-disjoint grouping** (by `takeaway_id`) so no *row* straddles
  train/test — the head embeds prompt⊕row over only ~46 rows, so prompt-grouping alone leaks
  row identity (red-team C1; the prompt key is emitted as `prompt_group` for B02's CV, not as
  the split axis). `label_source` keeps human vs oracle distinguishable; **test is human-only**.
  *(Superseded the original whole-prompt-split call — see the 2026-06-21 rework in Updates.)*
- Validation: conservation tally — every rated firing is in the dataset or in a `skipped`
  count with a reason.

## Tasks

- [ ] Define §1 of the contract concretely (dataset path, file format, the schema above).
- [ ] Build the dataset from the hub: pull rated `on_demand` firings; train on the **full
  prompt** (`situation`, `trigger_context` fallback); assign **row-disjoint** `split`; record
  `label_source=human`. Emit the conservation tally + the per-row-prior baseline check.
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
- **Row-disjoint** grouping is the split axis (red-team C1): the head embeds prompt⊕row over
  ~46 rows, so prompt-grouping leaks row identity (a per-row prior hit AUC 0.77 ≈ the
  headline; under row-disjoint it collapses to 0.50). The spike groups on *prompt* — graduate
  its 120-char `norm_prompt` as the emitted `prompt_group` (for B02 CV), but split on
  `takeaway_id`. Honest evaluation per se is still the principle; the axis changed.
- This bucket produces DATA, not a model. No training here (that's B02).
- Real session prompts → gitignored; never commit the dataset.

## Validation

- Print the conservation tally: `total rated firings = in_dataset + skipped(reason)`.
- Assert: no normalized-prompt appears in both `train` and `test`.
- Assert: `test` rows are all `label_source=human`.

## Done criteria

- [x] Tasks complete; contract §1 defined, §3 decision recorded.
- [x] Validation passes (conservation + no split leakage + human-only test).
- [x] Bucket `Updates` records the final n (train/test), label-source mix, score-logging call.
- [x] Parent workstream progress updated.

## Updates

- 2026-06-21 **Done.** Built `tools/build_relevance_labels.py` (reuses
  `export_records` → `Store`, the approved reader; no direct store access). Output
  `data/relevance-cascade/labels.jsonl` (gitignored).
  - **Final n: 129 firings, all `label_source=human`** — train 91 (40h/51n) / test 38
    (19h/19n, balanced). Up from the spike's n=102 (hub grew). 62 unique-prompt groups
    (44 train / 18 test).
  - Conservation tally clean: `178 rated total = 129 in_dataset + 49 skipped`, all 49
    skipped = `not_on_demand` (session_start 6, edit_path 39, recurrence 4). Validation
    asserts pass: no prompt straddles splits; test is 100% human.
  - **Split = deterministic `sha256(norm_prompt)%5 → test`** — no RNG, reproducible,
    whole-prompt grouping intact (spike's 120-char `norm_prompt` reproduced exactly).
  - **Expansion: human-only, no oracle this bucket** (user-confirmed). Key finding: the
    spike's validated 0.78 grouped-CV AUC was trained on **human labels alone**; the L3
    LLM oracle was only a baseline ceiling ("not required to reproduce the headline
    result" — spike README). Gate is human-only test regardless. If B02 NO-GOs for
    volume, oracle expansion becomes a justified follow-up bucket.
  - **§3 score-logging decided**: log scalar L2′ score + `head_version` per firing (not
    the full embedding — re-embeddable from stored prompt). Wiring deferred to B04.
  - **Schema reconciliation (contract §1)**: collapsed "`label` OR `oracle_relevant`"
    into one `label` column keyed by `label_source` (oracle rows map relevant→helpful).
  - **Handoff to B02**: dataset's rowtext is NOT stored — B02 re-derives it from
    `takeaway_id` (spike used `one_liner` + `trigger_spec`; note `export.py` exposes
    `one_liner` but not `trigger_spec`, so B02 reads the takeaway directly for the spec).
    Feature-parity invariant (train==infer) lives in the workstream.

- 2026-06-21 **Reworked after adversarial red-team (two confirmed blockers in the above).**
  The first pass shipped two defects; both verified against the live hub + runtime code and
  fixed:
  - **C2 — wrong prompt field (parity bug).** The first pass trained on `trigger_context`,
    which for `on_demand` is a **≤200-char preview** (`hooks.py` logs `prompt[:200]`;
    median=max=200, 63% at the cap). At inference the runtime embeds the **full** prompt
    (`on_demand_match(prompt)` → `embed.semantic_scores`). Training on the preview is a
    silent train/infer mismatch. **Fix:** `prompt` = `situation` (= `prompt[:4000]`, the
    full-prompt proxy; present 112/129, only 5 at the cap) with `trigger_context` fallback
    for the 17 older firings. New columns `prompt_source`/`prompt_chars` flag the fallbacks.
  - **C1 — row-identity leakage (gate measured the wrong thing).** The head embeds
    prompt⊕ROW over only 46 distinct rows; the prompt-grouped split put 38/38 test firings'
    rows also in train. A prompt-IGNORING per-row prior scored **AUC 0.773 on that test ≈
    the 0.78 headline** — a useless head would have passed the gate. **Fix:** split is now
    **row-disjoint** (group by `takeaway_id`); the per-row prior collapses to **0.500**
    (asserted ≤0.6 in the builder). Emit `prompt_group` so B02 can do leave-row-out CV.
  - **New numbers:** 129 firings / 46 rows, row-disjoint train 104 (53h/51n) / test 25
    (6h/19n). The honest split is small + imbalanced — exactly why the **gate must be
    leave-row-out CV vs the AUC CI**, not this single split (contract §1 gate caveat,
    new workstream invariants). Conservation still clean (`178 = 129 + 49 not_on_demand`).
  - **Lesson (→ /mine-session, MONITION):** (a) when a head embeds X⊕Y but the holdout
    groups only on X, compute the Y-identity-only baseline on test — if it ≈ the headline,
    the eval proves nothing; (b) before trusting a labels dataset, check which field the
    *runtime* feeds the model — the lossless source was one column over (`situation` vs
    `trigger_context`).
