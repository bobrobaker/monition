# Bucket B02: Module refactor, behavior-locked

Parent: ../workstream.md
State: later
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

- [ ] Step 0 inspection gate: read the actual matcher implementations before
      writing any module code (multi-variant rule).
- [ ] Characterization tests FIRST, exact-value level: for a fixture store,
      assert the full hit sets (ids AND evidence dicts) of `match()`,
      `on_demand_match()` (lexical-forced and with a stubbed semantic scorer),
      and `session_start()` — exact sets, not spot checks.
- [ ] Extract modules per B01's design; matchers delegate; hit dicts (incl.
      `evidence`) byte-identical.
- [ ] The injection cap, reach filter, `_not_yet_fired` dedup, and EV-scorer
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

- [ ] Tasks complete.
- [ ] Validation passes.
- [ ] Bucket `Updates` section records discoveries/gotchas/handoff.
- [ ] Parent workstream progress updated.

## Updates

- [2026-07-01 20:11] Created. Handoff: none yet. Gotchas: none yet.
