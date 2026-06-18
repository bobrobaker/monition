# Bucket B02: Scorer

Parent: ../workstream.md
State: done
Goal for session: Build `score()`, log to decisions, wire `monition score` CLI.
Target duration: 30 min
Context budget: Read parent + this bucket + required touchpoints only.

## Conceptual mapping

All tasks share the score.py surface: the scoring function, the decisions write,
and the CLI command that exposes it. Tests live close to the logic. The executor
wiring is excluded (B03) because it touches a different file and mental model.

## Data contract / provenance

Report first (contract check):
- Which contract section applies? `## decisions — per-field meaning` (added in B01).
- Producer/consumer: `score()` writes decisions rows; no Phase 3 consumer reads them.
- Fields: `takeaway_id`, `session_id`, `decided_at`, `decision`, `evidence_count`,
  `cold_start`, `ev_score` — verify exact column names against the B01 contract edit
  before writing insert logic.
- Validation: every `score()` call produces exactly one decisions row; `ev_score` is
  NULL iff `cold_start=True`.

## Tasks

- [ ] Create `src/monition/score.py`:
  - Module constants: `N_COLD_START = 3`, `EV_THRESHOLD = 0.5`
  - `score(takeaway_id: int, store_path: Path, session_id: str | None = None) -> dict`
    Returns `{"decision": "fire"|"suppress", "cold_start": bool, "evidence_count": int, "ev_score": float|None}`
  - Logic: open `WriteStore(store_path)`; get rated firings for takeaway_id;
    if evidence_count < N_COLD_START → cold-start fire; else precision = helpful/total_rated;
    decision = "fire" if precision >= EV_THRESHOLD else "suppress"; write decisions row; return dict.
  - Add `write_decision` method to `WriteStore` in `store_write.py`.
- [ ] Register `monition score <takeaway_id>` in `cli.py`: print JSON result to stdout.
- [ ] Tests in `tests/test_score.py`:
  - Cold-start path: < N_COLD_START rated firings → decision="fire", cold_start=True.
  - Fire path: sufficient evidence, precision >= threshold → decision="fire".
  - Suppress path: sufficient evidence, precision < threshold → decision="suppress".
  - decisions row written with correct fields for each path.

## Required touchpoints

- `src/monition/store.py`  lines 76–84  `Firing` dataclass
  Field names and types; `outcome` is None (unrated), `'helpful'`, or `'noise'`.
- `src/monition/store.py`  lines 168–188  `Store.firings()`
  The approved read path; returns all firings — filter by takeaway_id + outcome != None in scorer.
- `src/monition/store_write.py`  lines 50–148  `WriteStore`
  Pattern for adding a write method (see `fire()`, `rate()`); `_dolt()` is the raw runner.
- `src/monition/cli.py`  lines 38–end  command registration
  Pattern for adding a new subcommand.
- `grep "## Updates" buckets/B01_contract-v3.md`, then read from that offset
  B01 handoff: confirm exact column names decided during B01 before writing insert.

## Conditional touchpoints

- `src/monition/metrics.py`  full file
  Read only if unclear how to aggregate firings by takeaway — it may have a pattern worth reusing.

## Do-not-read / avoid

- `src/monition/hooks.py` — executor wiring is B03; don't touch it here.
- `src/monition/init_sync.py` — schema already handled in B01.

## Design direction

- `score()` takes a `Path` and opens its own `WriteStore` — it is a standalone function,
  not a method on an existing class. Executors in B03 call it with the resolved store path.
- Filter rated firings: `[f for f in store.firings() if f.takeaway_id == takeaway_id and f.outcome is not None]`
- `evidence_count` = len of rated firings for this takeaway (not total firings).
- `helpful_count` = len of those where `f.outcome == "helpful"`.
- `ev_score` = `helpful_count / evidence_count` when not cold-start; `None` otherwise.
- `write_decision` on `WriteStore`: INSERT into decisions, then `dolt add decisions` +
  commit via `self.commit(...)`. Pattern: match `fire()` which does the same for firings.
- `monition score` CLI: accepts `takeaway_id` as int arg, resolves store path via
  `resolve_store_path()`, calls `score()`, prints `json.dumps(result, indent=2)`.
- Keep `ev_score` as Python `float | None`; the decisions row stores it as decimal(5,4)
  (Dolt handles the precision; no rounding needed before insert).

## Validation

- `pytest tests/test_score.py` — new tests pass.
- `pytest` — full suite green, no regressions.
- Lint: `python tools/lint.py` — no ERRORs.
- Expected: all three decision paths covered; decisions rows in fixture store confirmed
  with `SELECT * FROM decisions` via a test helper or direct dolt call.

## Done criteria

- [ ] Tasks complete.
- [ ] Validation passes.
- [ ] Bucket `Updates` section records discoveries/gotchas/handoff.
- [ ] Parent workstream progress updated; B03 set to `next`.

## Updates

- [2026-06-12 00:00] Created. Handoff: none yet. Gotchas: none yet.
- [2026-06-12] Done. 39 passed, 35 skipped, lint clean.
  Gotchas:
  - Dolt omits NULL columns from JSON output entirely (KeyError, not None). Used `.get("ev_score")`
    in the cold-start test. This pattern is relevant anywhere a nullable column is tested from
    raw `_sql()` results.
  - No fixture takeaway has >= 3 rated firings, so evidence-based tests monkeypatch N_COLD_START.
  Handoff for B03: `score(takeaway_id, store_path, session_id)` in `monition.score`. Returns
  `{"decision": "fire"|"suppress", "cold_start": bool, "evidence_count": int, "ev_score": float|None}`.
  Any exception from `score()` must be caught in the executor and treated as fire (fail-open).
