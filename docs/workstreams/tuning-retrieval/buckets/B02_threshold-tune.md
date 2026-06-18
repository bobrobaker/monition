# Bucket B02: Threshold Tune

Parent: ../workstream.md
State: done
Goal for session: `monition tune` — measure improvement vs always-fire, recommend thresholds.
Target duration: 25 min
Context budget: Read parent + this bucket + required touchpoints only.

## Conceptual mapping

All tasks share the `cli.py` / `score.py` / `metrics.py` edit surface. B01 provided
`Store.decisions()` and the decision quality metrics; this bucket surfaces them as a
CLI command and adds threshold recommendation logic.

## Tasks

- [ ] Add `tune(store_path)` function to `metrics.py`:
  - Reads `store.decisions()` + `store.firings()`.
  - Sufficient-data gate: if evidence-based decisions < 10, return a warning
    struct with `sufficient_data=False` and counts.
  - Compute: `suppress_count`, `fire_count`, `cold_start_count`,
    `noise_saved_pct` (suppress_count / total_decisions),
    `avg_ev_score_at_suppress` (mean ev_score for decision='suppress'),
    `avg_ev_score_at_fire` (mean ev_score for evidence-based fire decisions).
  - Threshold recommendation: if `avg_ev_score_at_suppress` is near current
    `EV_THRESHOLD`, emit a note suggesting the threshold is well-calibrated;
    if `suppress_count == 0`, suggest lowering N_COLD_START; no arithmetic
    auto-tune — just descriptive recommendation strings.
- [ ] Add `monition tune [--store PATH]` subcommand to `cli.py`:
  - Calls `tune(path)`, prints structured text output (not JSON — human-readable).
  - Non-zero exit only on store access errors; insufficient data → exit 0 + warning.
- [ ] Add tests to `tests/test_tune.py`:
  - `test_tune_insufficient_data`: < 10 evidence-based decisions → warning, exit 0.
  - `test_tune_shows_improvement`: fixture with ≥ 10 decisions including suppress rows
    → output contains `suppress_count` and `noise_saved_pct` > 0.
  - `test_tune_no_decisions`: empty decisions table → prints nothing meaningful, exit 0.

## Required touchpoints

- `src/monition/metrics.py`  full file
  Where `tune()` lives; existing `audit()` pattern to follow.
- `src/monition/score.py`  `grep -n "N_COLD_START\|EV_THRESHOLD"`
  Current threshold values — reference them in the recommendation text.
- `src/monition/cli.py`  `grep -n "def \|subparsers\|add_parser\|args.cmd"`
  CLI dispatch pattern to follow for the new `tune` subcommand.
- `grep -n "^## Updates" docs/workstreams/tuning-retrieval/buckets/B01_decisions-readback.md`
  then bounded read from that offset — B01 handoff notes.

## Conditional touchpoints

- `src/monition/store.py`  `grep -n "def decisions"`
  Read only if Decision field names or return type are unclear from B01's handoff.
- `tests/conftest.py`  `grep -n "decisions"`
  Read only if the canonical_store fixture needs additional decisions rows for test
  coverage — check row counts before adding fixture data.

## Do-not-read / avoid

- `src/monition/score.py` body — `tune()` reads constants but doesn't modify them.
- `src/monition/hooks.py` — no changes this bucket.

## Design direction

- `tune()` returns a dict (or dataclass) rather than printing directly — `cli.py`
  handles rendering. This keeps `metrics.py` testable without subprocess.
- Threshold recommendation strings are qualitative: "EV_THRESHOLD appears well-placed
  (mean suppress ev_score: 0.XX)" — never a computed replacement value. The human
  reviews and edits `score.py` manually.
- `noise_saved_pct` is the primary exit-criterion metric: the measurable improvement
  over always-fire baseline (where it would be 0% savings).
- Sufficient-data gate of 10 is soft: the gate only suppresses the recommendation
  section, not the basic counts display.
- Output format (human-readable, not JSON):
  ```
  monition tune — <store_path>
  Decisions: N total (X cold-start, Y evidence-based, Z suppressed)
  Noise saved vs always-fire: N.N% (Z suppressed of Y evidence-based)
  Recommendation: <qualitative string>
  ```

## Validation

- `pytest tests/test_tune.py` — new tests pass.
- `pytest` — full suite green.
- `python tools/lint.py` — no ERRORs.
- Expected: `monition tune <store>` runs against the canonical fixture, prints counts,
  exits 0 even when no decisions rows exist.

## Done criteria

- [ ] Tasks complete.
- [ ] Validation passes.
- [ ] Bucket `Updates` section records discoveries/gotchas/handoff.
- [ ] Parent workstream progress updated; B03 state → `next`.
- [ ] `docs/road.md` Phase 4 exit criterion ("measurable improvement vs always-fire")
  noted as satisfied in the phase status.

## Updates

- [2026-06-12] Created. Handoff: none yet. Gotchas: none yet.
- [2026-06-12] Done. 60 passed, 35 skipped, lint clean.
  Added `tune_recommendation(dq, n_cold_start, ev_threshold)` to `metrics.py`.
  Added `render_tune(store)` to `report.py`. Added `monition tune [--store]`
  to CLI. Qualitative recommendations only — no auto-patching of score.py.
  Phase 4 exit criterion met: `noise_saved_pct` measures improvement vs baseline.
