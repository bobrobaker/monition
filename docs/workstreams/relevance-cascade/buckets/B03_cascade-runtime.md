# Bucket B03: Cascade Runtime

Parent: ../workstream.md
State: later
Goal for session: Port Layer + orchestrator + L0 + L2′ layer to src, standalone.
Target duration: 30 min
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

- [ ] Create the runtime module: the `Layer` interface (`evaluate(context, candidates) →
  {id:(category,certainty)}`, `ABSTAIN` first-class) + the cost-ordered, certainty-gated
  orchestrator (knobs `TARGET_CERTAINTY`, `TIME_BUDGET`; cheapest-first on the unsettled
  residual; pre-emptive budget check; fail-closed-on-firing at commit).
- [ ] Implement `L0` admissibility (regex non-prompt / `<task-notification>`) and `L2′`
  (loads the B02 head, scores candidates). `L1` lexical optional — the spike showed it
  redundant; include only if `layer_eval` still rates it KEEP.
- [ ] **Confirm the real UserPromptSubmit hook window** before fixing `TIME_BUDGET`
  (assumed 30 s). Source it from the hook config, not folklore.
- [ ] Unit tests: orchestrator stops at certainty / at budget; pre-emptive budget never
  starts an unaffordable layer; fail-closed (unsettled → not fired) on the passive path;
  L2′ refuses a head whose model id ≠ live `embed.MODEL_NAME`.

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

- [ ] Runtime module + L0 + L2′ implemented, no hooks imported.
- [ ] Hook-window value confirmed + recorded.
- [ ] Tests pass (control flow, fail-closed, feature parity, model-id guard).
- [ ] Bucket `Updates` records the module path + the confirmed hook window.
- [ ] Parent progress updated.

## Updates

- 2026-06-21 Created. Handoff: none yet. Gotchas: none yet.
