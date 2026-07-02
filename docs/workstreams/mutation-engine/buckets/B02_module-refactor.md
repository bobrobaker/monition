# Bucket B02: Module refactor, behavior-locked

Parent: ../workstream.md
State: done
Goal for session: Matchers behind the Module seam; matching behavior unchanged.
Target duration: 45 min
Context budget: Read parent + this bucket + required touchpoints only.

## Conceptual mapping

- Pure structural refactor of the three matchers onto B01's representation:
  one edit surface (store_write matchers + a new module module), one mental
  model (each kind = one module answering "fires on this moment?").

## Data contract / provenance

- Inputs: B01's contract §Trigger modules (required touchpoint, not duplicated
  here).
- Outputs: none persisted — no schema writes in this bucket.
- Validation: characterization parity (below).

## Tasks

- [x] Step 0 inspection gate: read the actual matcher implementations before
      writing any module code (multi-variant rule).
- [x] Characterization tests FIRST, exact-value level: for a fixture store,
      assert the full hit sets (ids AND evidence dicts) of `match()`,
      `on_demand_match()` (lexical-forced and with a stubbed semantic scorer),
      and `session_start()` — exact sets, not spot checks.
- [x] Extract modules per B01's design; matchers delegate; hit dicts (incl.
      `evidence`) byte-identical.
- [x] The injection cap, reach filter, `_not_yet_fired` dedup, and EV-scorer
      call sites stay OUTSIDE modules — a module answers matching only.

## Required touchpoints

- `docs/contracts/takeaway-store.md  grep -n "Trigger modules"  B01's new section`
- `src/monition/store_write.py  grep -n "def match\|def on_demand_match\|def session_start\|_cap_hits\|lex_kw"  matchers + cap`
- `tests/test_on_demand.py  grep -n "def test"  existing lexical contract tests`
  Existing pins; extend, don't weaken.

## Conditional touchpoints

- `src/monition/hooks.py  grep -n "_disclose"  executor`
  Read only if hit-dict shape must change (it should not).

## Design direction

- Behavior-preserving is the named invariant: any diff in hit sets or evidence
  dicts is a bug in this bucket, not a design opportunity.
- Assess-path == eval-path starts here: modules are importable units B03/B06
  call directly — never re-implemented for offline use.
- Fail-open posture preserved: absent embeddings degrade to lexical-only inside
  the semantic module, exactly as today.

## Validation

- `env -u MONITION_STORE .venv/bin/pytest` — full suite green; new
  characterization tests pass before AND after the extraction (run them against
  the pre-refactor code first to prove they lock, then refactor).
- Expected: zero behavioral diff; hook latency unchanged (no new store opens or
  per-hit reads).

## Done criteria

- [x] Tasks complete.
- [x] Validation passes.
- [x] Bucket `Updates` section records discoveries/gotchas/handoff.
- [x] Parent workstream progress updated.

## Updates

- [2026-07-01 20:11] Created. Handoff: none yet. Gotchas: none yet.
- [2026-07-02] Done. `src/monition/modules.py` created (`glob_match`,
  `lexical_match`, `semantic_rank`); the three matchers delegate; hit dicts
  byte-identical (locked by `tests/test_module_parity.py`, 8 exact-value
  tests, green against pre-refactor code first, then post). Full suite
  285 passed / 2 skipped (pre-existing dolt-conformance skips).
  Discoveries: `metrics.spec_matches` was a live re-implementation of glob
  matching ("reproduce exactly" by copy) — folded onto `modules.glob_match`
  in this bucket, the first assess-path==eval-path enforcement. Gotchas:
  `semantic_rank` is batch-shaped (one embed call per query, never per row —
  hook cold-path); `trace.mark("match:semantic_done")` moved inside the
  module to preserve trace parity (marks only when scoring succeeded);
  `session_start` delegates to nothing by design — the `always` module has no
  per-row check, the select-all IS the module (documented in modules.py
  docstring; no ceremonial call fabricated). Handoff to B03: per-row θ filter
  goes inside `semantic_rank` (read `sem_threshold` off the row dict, NULL →
  global) — the one edit surface the seam was built for; B03 also ships the
  atomic v8 migration per B01's contract paragraph.
