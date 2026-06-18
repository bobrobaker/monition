# Bucket B01: Decisions Readback

Parent: ../workstream.md
State: done
Goal for session: Add `Store.decisions()` and report decision quality vs baseline.
Target duration: 20 min
Context budget: Read parent + this bucket + required touchpoints only.

## Conceptual mapping

All tasks share the `store.py` / `report.py` / `metrics.py` edit surface. The
`decisions` table is already written (Phase 3); this bucket adds the read path and
exposes the data in `monition report`.

## Data contract / provenance

Report first (contract check):
- Which contract section applies? `## decisions — per-field meaning` and
  `### Decision semantics`.
- Producer: `score.py` via `WriteStore.write_decision`. Consumer: `Store.decisions()`
  (new), `monition report` (new section).
- Fields: `id`, `takeaway_id`, `session_id`, `decided_at`, `decision`,
  `evidence_count`, `cold_start`, `ev_score` (nullable — use `.get()`).
- Validation: all decisions rows must reference a known takeaway_id (same orphan
  check pattern as firings).

## Tasks

- [ ] Add `Decision` dataclass to `store.py` (frozen, mirrors contract fields).
- [ ] Add `Store.decisions()` method — reads all rows, returns `list[Decision]`.
- [ ] Add orphan guard (decisions referencing unknown takeaway_id → raise).
- [ ] Add `decision_quality` section to `metrics.py`:
  - cold_start count, evidence_based count, suppress count
  - `improvement_pct`: suppress_count / total_decisions (the noise saved %)
  - baseline comparison: total decisions vs always-fire total
- [ ] Add decision quality block to `report.py` render output (below recommendations).
- [ ] Add tests for `Store.decisions()` to `tests/test_characterization.py` or a
  new `tests/test_decisions.py` — use `canonical_store` fixture, verify row count and
  field types; verify `.get("ev_score")` is None for cold_start rows.

## Required touchpoints

- `src/monition/store.py`  lines 84–100 + 165–205  `Firing` dataclass + `firings()` method
  Pattern to follow for `Decision` dataclass and `decisions()` method.
- `docs/contracts/takeaway-store.md`  `grep -n "^## decisions"` then bounded read of that section
  Field names, types, nullable columns, and semantics before writing code.
- `src/monition/metrics.py`  full file
  Where to add the decision quality function(s); existing audit() pattern to follow.
- `src/monition/report.py`  full file
  Where to add the decision quality render block.

## Conditional touchpoints

- `tests/conftest.py`  `grep -n "decisions\|SCHEMA\|canonical"`
  Read only if the canonical_store fixture needs decisions rows for test coverage —
  check whether the fixture already has decisions rows from Phase 3 before adding.
- `src/monition/store_write.py`  `grep -n "write_decision"`
  Read only if Decision field names are unclear from the contract.

## Do-not-read / avoid

- `src/monition/score.py` — decisions are written there; no edits here.
- `src/monition/hooks.py` — no changes this bucket.

## Design direction

- `Decision` dataclass: `id: int`, `takeaway_id: int`, `session_id: Optional[str]`,
  `decided_at: datetime`, `decision: str`, `evidence_count: int`,
  `cold_start: bool`, `ev_score: Optional[float]`.
  `cold_start` stored as `tinyint(1)` in Dolt — convert via `bool(r["cold_start"])`.
- `decisions()` query: `SELECT id, takeaway_id, session_id, decided_at, decision,
  evidence_count, cold_start, ev_score FROM decisions ORDER BY id`.
  Use `r.get("ev_score")` — NULL when cold_start=True; Dolt omits the key entirely.
- Orphan guard pattern mirrors firings orphan check: warn vs raise — match whichever
  pattern firings uses (check before deciding).
- `improvement_pct` = suppress_count / max(1, total_decisions) — the fraction of
  decision events where Monition avoided a noisy firing. The always-fire baseline
  would have fired all of them.
- Report block label: `"Decision quality (Phase 3+)"` — keep it clearly optional/
  new so it doesn't confuse users with sparse data (add "(N=X decisions)" inline).
- If decisions table has zero rows, print nothing for the decision quality block.

## Validation

- `pytest tests/` — all existing tests green; new decisions tests pass.
- `pytest -k decisions` — focused run on new tests.
- `python tools/lint.py` — no ERRORs.
- Expected: `Store.decisions()` returns a list of `Decision`; report renders without
  errors on both a store with and without decisions rows.

## Done criteria

- [ ] Tasks complete.
- [ ] Validation passes.
- [ ] Bucket `Updates` section records discoveries/gotchas/handoff.
- [ ] Parent workstream progress updated; B02 state → `next`.

## Updates

- [2026-06-12] Created. Handoff: none yet. Gotchas: none yet.
- [2026-06-12] Done. 54 passed, 35 skipped, lint clean.
  Added `Decision` dataclass and `Store.decisions()` to `store.py`. Added
  `decision_quality()` + `DecisionQuality` dataclass to `metrics.py`. Added
  decision quality block to `report.py` render (shown only when decisions > 0).
  Updated contract: removed "Write-only (Phase 3)" bullet → "Read-back (Phase 4)".
  Added 3 decisions rows to conftest ROWS (d1 cold-start, d2 suppress, d3 fire).
  Gotcha: conftest decisions rows triggered `len(rows) == 1` failures in
  test_score.py queries by takeaway_id — fixed by adding session_id filter.
  Handoff for B02: `decision_quality()` accepts `List[Decision]` and returns
  `DecisionQuality`; `sufficient_data` gate is evidence_based_count >= 10.
