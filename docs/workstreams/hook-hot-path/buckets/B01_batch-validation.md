# Bucket B01: Batch schema validation into one invocation

Parent: ../workstream.md
State: done
Goal for session: store open = ≤2 dolt spawns, not 10.
Target duration: 30 min
Context budget: Read parent + this bucket + required touchpoints only.

## Conceptual mapping

- All 10 per-open spawns come from one call chain: `Store.__init__` →
  `_detect_stale_schema` + `_validate_schema`, each issuing per-table
  `backend.describe()` calls; `describe` is one `dolt sql -q` subprocess each.
  One mental model (schema introspection), one edit surface
  (`store.py` + `storage_backends.py`).
- Also creates the bench harness this workstream's validation lives on — needed
  here first to prove the win.

## Tasks

- [ ] Add `describe_all(tables)` to both backends: SQLite loops its existing
      per-table path (in-process, cheap); Dolt issues ONE
      `information_schema.columns` query (`SELECT table_name, column_name AS
      Field, column_type AS Type FROM information_schema.columns WHERE
      table_name IN (...)`) and groups rows per table. Missing table = absent
      key (≙ today's empty describe).
- [ ] Rewrite `_detect_stale_schema` + `_validate_schema` to consume one shared
      `describe_all` result (fetched once in `Store.__init__`), preserving the
      exact error messages and raise conditions.
- [ ] Instrument-count spawns before/after (wrap `subprocess.run` as in the
      2026-07-02 probe): assert open ≤2 spawns.
- [ ] Add `tools/hook_bench.py`: copy `$MONITION_STORE` → tmp scratch, pipe N
      synthetic prompt/tool events through `monition prompt-hook`/`fire-hook`
      with `MONITION_TRACE`, print per-phase medians, delete scratch (and stop
      any sql-server it spawned: `monition sql-server-stop --store <scratch>`
      or kill by `/proc/<pid>/cwd`). Never touches the hub.
- [ ] Record fresh warm numbers in `## Updates` (baseline is in parent Global
      Implementation Notes).

## Required touchpoints

- `src/monition/store.py  238–345  Store.__init__/_detect_stale_schema/_validate_schema`
  The whole call chain being restructured; `_REQUIRED`/`_REQUIRED_SQLITE` at 25.
- `src/monition/storage_backends.py  33–99  SqliteBackend (describe at 72)`
  Pattern to mirror; keep its per-table path as the loop body.
- `src/monition/storage_backends.py  101–181  DoltBackend (describe at 139, execute_sql at 124)`
  Where the single information_schema query lands; note `ensure_running` gating.
- `tests/  grep -n "StoreContractError\|_validate_schema\|describe" tests/*.py`
  Tests asserting validation raises/messages — must stay green unmodified.

## Conditional touchpoints

- `src/monition/migrate.py  grep -n "describe"`
  Read only if migrate shares the describe path and would double-fetch.

## Do-not-read / avoid

- `src/monition/embed.py`, `src/monition/modules.py`
  Matching is ms-scale; nothing here changes it.
- `src/monition/dolt_server.py`
  B03's surface. `ensure_running` behavior is correct as-is for this bucket.

## Design direction

- One `information_schema.columns` statement replaces N describes; the ladder
  checks in `_detect_stale_schema` then run over the in-memory dict — pure
  restructure, zero behavior change. Named invariant: **same inputs → same
  StoreContractError (or none) as today**, byte-identical messages.
- Dolt JSON omits NULL columns entirely: `row.get()`, never `row[]`.
- `information_schema.columns` column names differ from `describe` output
  (`COLUMN_NAME`/`COLUMN_TYPE` vs `Field`/`Type`) — alias in SQL so downstream
  dict-building code is unchanged. Verify actual JSON keys against the live
  server before wiring (dolt may case-fold).
- Keep `describe(table)` public and working (other callers may exist — grep
  first); `describe_all` is additive.

## Validation

- `env -u MONITION_STORE .venv/bin/pytest -x -q` — full suite green.
- Spawn-count probe: WriteStore open ≤2 subprocess calls (was 10).
- `tools/hook_bench.py` on a hub scratch copy: fire-hook store_opened ≤ ~350ms
  (was 1.1–1.3s).

## Done criteria

- [ ] Tasks complete.
- [ ] Validation passes.
- [ ] Bucket `Updates` section records discoveries/gotchas/handoff.
- [ ] Parent workstream progress updated.

## Updates

- [2026-07-02 16:25] Created. Handoff: none yet. Gotchas: none yet.
- [2026-07-02 17:00] DONE. `describe_all` added to both backends (Dolt: one
  `information_schema.columns` query aliased to Field/Type, ordered by
  ordinal_position, `table_schema = DATABASE()`, case-normalized keys, fallback
  to per-table describe on error/odd shape); `_validate_schema` fetches once and
  threads the dict through `_detect_stale_schema` (now takes `cols_by_table`).
  **Store open: 1027ms/10 spawns → 152ms/1 spawn.** Bench (tools/hook_bench.py,
  hub-sized scratch, warm): fire-hook median 404ms (was 1.3–1.6s), prompt-hook
  1546ms (was 2.8–3.4s); store_opened ~130ms both. Full suite green
  (315 passed); suite runtime itself dropped 199s → 76s. Gotchas: (1) Dolt raw
  describe rows carry Null/Key/Extra — describe_all returns the Field/Type
  projection only (documented); (2) daemon env-strip for tests must live at
  conftest IMPORT time — a function-scoped autouse delenv runs AFTER
  session-scoped fixtures, which leaked 9 sql-servers before the fix. Handoff:
  disclosed phase (763ms median, B02) is now the biggest prompt-hook chunk;
  remaining per-query spawns ~130-150ms each are B03's target.
