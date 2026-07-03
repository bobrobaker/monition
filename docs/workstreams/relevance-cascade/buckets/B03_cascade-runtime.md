# Bucket B03: Cascade Runtime

Parent: ../workstream.md
State: done
Goal for session: Typed skeleton (gate/transform/scorer) + residents, standalone.
Target duration: one session
Context budget: Read parent + this bucket + required touchpoints only.

## Conceptual mapping

- One mental model: *the runtime engine, no hooks yet*. Graduate the spike's `cascade.py`
  into `src/monition/` as a standalone, unit-tested module. No `hooks.py` edits here —
  integration is B04. Edit surface: new module(s) + tests only.

## Data contract / provenance

Consumes §2 (the head artifact) — read it to know the load format + feature spec.

- Inputs: the B02 head artifact (verify the on-disk format against the real file).
- Provenance: the `L2′` layer's feature construction MUST byte-for-byte match B02's training
  features (train/infer parity invariant). Build the SAME prompt⊕row embedding the trainer
  used; if B02 graduated a shared `features()` helper, call it — do not re-implement.

## Tasks

*(Reconciled 2026-07-03 to the typed-skeleton amendment — workstream Updates 2026-07-02/03.
The skeleton has three typed stages, not a flat scorer stack: prompt-level **gates**
(pre-match, one verdict skips everything), match-input **transforms** (rewrite the text
the matcher sees), pair-level **scorers** (per-candidate category/certainty). Residents
per B06: boilerplate gate, span-sanitization transform, L2′ head scorer. Metamatch is
OUT (B06 verdict); L1 lexical stays out (spike redundancy, nothing in B06 revived it).)*

- [ ] Create the runtime module with the three typed stages: `Gate` (prompt → skip-all
  verdict or pass, runs before any matching), `Transform` (prompt → rewritten match
  input), `Scorer` (the old `Layer`: `evaluate(context, candidates) →
  {id:(category,certainty)}`, `ABSTAIN` first-class) + the cost-ordered,
  certainty-gated orchestrator over scorers (knobs `TARGET_CERTAINTY`, `TIME_BUDGET`;
  cheapest-first on the unsettled residual; pre-emptive budget check;
  fail-closed-on-firing at commit).
- [ ] Gate resident: **boilerplate prefix gate** — move the source of truth
  (`_BOILERPLATE_PREFIXES` + prefix test) into the skeleton, preserving its pre-match
  semantics (`2026-07-02-boilerplate-prompt-gate.md`: "prefix skip, not a
  candidate-level filter"). NO hooks.py edits here — hooks.py keeps its copy until B04
  rewires it to import from the skeleton; record the temporary duplication as an
  explicit B04 task.
- [ ] Transform resident: **span sanitization** — strip quoted row/machinery spans the
  matcher must not treat as work context (`[tNNN/fNNNN]` ids, `monition show/rate/query`
  output shapes, the hook's own injected-context block). Deterministic, unit-tested;
  wire/measure decision belongs to B04/B05.
- [ ] Scorer resident: `L2′` head — loads the B06-accepted artifact
  (`~/.cache/monition/relevance/head-v1.json`), scores candidates through the SAME
  feature path as training (`relevance.head.build_features` — do not re-implement).
- [ ] **Confirm the real UserPromptSubmit hook window** before fixing `TIME_BUDGET`
  (assumed 30 s). Source it from the hook config/harness docs, not folklore.
- [ ] Unit tests: gate short-circuits before transforms/scorers; transforms compose in
  order; orchestrator stops at certainty / at budget; pre-emptive budget never starts
  an unaffordable scorer; fail-closed (unsettled → not fired) on the passive path; L2′
  refuses a head whose model id ≠ live `embed.MODEL_NAME`.

## Required touchpoints

- `spike/relevance-cascade:spike/cascade.py`  full — the structure to graduate.
- `docs/contracts/relevance-cascade.md`  §2  — head load format + feature parity.
- `src/monition/embed.py`  `grep -n "_embed_raw\|MODEL_NAME"`  — inference embeddings.
- existing module style: `src/monition/score.py` full (small) — match the project's module
  shape (single responsibility, fail-open imports).

## Conditional touchpoints

- `src/monition/store_write.py`  `grep -n "def on_demand_match"`  (≈:202) — read only to
  align the candidate-row shape the orchestrator expects with what the matcher will pass in
  B04; do NOT edit it here.

## Do-not-read / avoid

- `src/monition/hooks.py` — integration is B04. Building the runtime against hooks now
  couples two mental models and two edit surfaces.

## Design direction

- Standalone + unit-testable is the whole point: the orchestrator takes `(context,
  candidates, layers)` and returns fired ids — it must not import hooks or read a store.
- Keep `TIME_BUDGET` and `TARGET_CERTAINTY` as named constants/config, not magic numbers.
- Fail-open for *availability* (a layer error must not crash the hook — caught, treated as
  ABSTAIN) but fail-closed for *firing* (unsettled at budget → don't fire). These coexist.

## Validation

- `pytest` the new module: all orchestrator-control + L0 + L2′-load tests pass.
- A smoke run: feed a known meta prompt + a technical row → cascade drops it; feed a matching
  pair → fires. (Uses the B02 artifact.)

## Done criteria

- [x] Runtime module + residents implemented, no hooks imported.
- [x] Hook-window value confirmed + recorded.
- [x] Tests pass (control flow, fail-closed, feature parity, model-id guard).
- [x] Bucket `Updates` records the module path + the confirmed hook window.
- [x] Parent progress updated.

## Updates

- 2026-06-21 Created. Handoff: none yet. Gotchas: none yet.
- 2026-07-03 Reconciled to the typed-skeleton amendment (Tasks note above): three stage
  kinds (gate/transform/scorer), residents from B06 — boilerplate gate, span-sanitizer
  transform, L2′ head scorer; metamatch OUT, L1 lexical stays out.
- 2026-07-03 **Done.** Module: `src/monition/relevance/cascade.py`; tests:
  `tests/test_cascade.py` (14, all pass). **Hook window confirmed: 30s** for
  UserPromptSubmit command hooks (code.claude.com/docs/en/hooks.md — reduced from the
  600s other events get; neither settings.json overrides it), so `HOOK_WINDOW_S=30`,
  `TIME_BUDGET_MS=3000`. Smoke vs the real artifact: boilerplate prompt gated (zero
  scoring); work prompt fired both candidates under `commit_suppress_only`; a
  row-quoting prompt's match input sanitized down to the bare human question.
  **Handoff to B04:** (1) rewire `hooks.py` to import `BOILERPLATE_PREFIXES`/gate from
  the skeleton — until then a drift-guard test (`test_boilerplate_constant_matches_
  hooks_until_b04`) pins the two copies equal; (2) wire the WARM embed path into
  `L2HeadScorer(embed_fn=...)` — the smoke's first evaluate cost 872ms, almost all
  cold fastembed load, vs the 40ms warm estimate; (3) commit polarity: both policies
  shipped, `commit_suppress_only` is the default matching the user-accepted operating
  point (suppress P(helpful) < 0.014); `commit_fail_closed` retained for a future
  strong scorer — B05 measures and finalizes; (4) `OP_SUPPRESS_THRESHOLD=0.014` is a
  provenance-commented constant, B05 finalizes.
