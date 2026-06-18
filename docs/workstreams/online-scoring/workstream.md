# Workstream: Online Scoring (Phase 3)

Progress: all done (B01–B03 complete, 2026-06-12)
Blocked: none

## Objective

Wire every fire decision through a `monition score` call that logs its reasoning to
a new `decisions` Dolt table (schema v3). Cold-start: always fire when a takeaway
has fewer than N rated firings. Suppression only happens with positive proof of noise
(precision below threshold on sufficient evidence). Fail-open on scorer errors.

## Execution Protocol (do not change)

1. Read this workstream first. For B01, read the full file. For B02+, do NOT use `cat` — run `grep -n "^##" workstream.md` first to get section line anchors, then use bounded reads for only: Objective, Execution Protocol, Bucket Index, and Cross-Bucket Invariants — skip Deferred/Non-Goals, Estimate, and any lower boilerplate sections.
2. Use `Progress` and `Bucket Index` to select the active bucket; if none is active, select the next bucket.
2a. If the index references a bucket file that does not exist yet, read `## Bucket template` in the generator prompt before creating it.
3. Open only the selected bucket file. If its `State` is not `active`, update it to `active` before reading touchpoints.
4. Read only that bucket's required touchpoints before reporting.
5. Report first: selected bucket, required touchpoints read, current behavior, proposed edits, validation plan, and extra touchpoints if needed.
6. Only edit after the plan is clear.
7. Run the bucket's validation.
8. Update the bucket file's `Updates` section with completed tasks, discoveries, gotchas, test results, and handoff notes.
9. Update this workstream's `Progress`, `Bucket Index`, and `Updates` only for progress, sequencing changes, cross-bucket discoveries, and cross-bucket gotchas. Also update the next bucket file's `State` from `later` to `next`. Use the Read tool (not Bash `cat`) to open workstream.md before editing it — Edit requires a prior Read call.
10. Keep only one bucket active at a time unless the user explicitly authorizes parallel execution.

## Bucket Index

| B | State | File | Goal | Depends |
|---|---|---|---|---|
| B01 | done | buckets/B01_contract-v3.md | Contract v3: `decisions` table + schema migration | — |
| B02 | done | buckets/B02_scorer.md | `score()` function, decisions writes, `monition score` CLI | B01 |
| B03 | done | buckets/B03_executor-wiring.md | Wire hook executors through `score()` | B02 |

States: `next`, `active`, `blocked`, `done`, `deferred`, `later`.

## Cross-Bucket Invariants

- Data contract: `docs/contracts/takeaway-store.md` — B01 adds the `decisions`
  section and v3 versioning note; B02/B03 read only the decisions section before
  touching decisions fields. Nothing else edits the contract this workstream.
- Fail-open: `score()` errors (any exception) → treat as cold-start fire. Never
  raise from inside an executor; log to hook-errors.log and proceed.
- Constants: `N_COLD_START = 3` and `EV_THRESHOLD = 0.5` live in `score.py` as
  module-level exports. Tests may monkeypatch them; no bucket may hardcode 3 or 0.5.
- decisions writes go through a `WriteStore` method — never raw `dolt sql` directly.
- The scorer reads rated firings only via `Store.firings()` — the approved reader.
  It must not issue its own `dolt sql` queries against `firings`.
- `decisions` table is write-only for Phase 3 (no read-back in report/metrics).
  The approved reader (`Store`) gains a `decisions()` method only when Phase 4 needs it.

## Deferred / Non-Goals

- Tuning `N_COLD_START` or `EV_THRESHOLD` — Phase 4.
- `decisions` read-back in `monition report` or `metrics.py` — Phase 4.
- MCP on-demand query surface — Phase 4.
- Multi-machine / config-based store path — deferred globally.
- `monition doctor` — deferred.

## Global Implementation Notes

- v3 migration: `monition migrate` currently handles only v1→v2. B01 extends it to
  detect v2 (decisions table absent) and add the decisions table — two separate
  migration paths in the same command.
- Validator upgrade: `_REQUIRED` in `store.py` gains a `decisions` entry in B01;
  the error message for a missing decisions table must name `monition migrate` as the
  repair path, matching the v1→v2 pattern.
- `score.py` imports `Store` for reads and `WriteStore` for writes; it is the only
  new source file in this workstream.
- `monition score <takeaway_id>` outputs JSON to stdout; executors call `score()`
  directly (never shell out).
- `ev_score` is NULL in decisions rows when `cold_start=1`.

## Updates

- [2026-06-12] Initial plan created. Phase 2 complete (B01–B06 done 2026-06-11). Next: B01/contract-v3.
- [2026-06-12] B01 done. V2_SCHEMA kept as a named constant (takeaways + firings, no decisions) so V1 test
  fixtures stay decisions-free; V3_SCHEMA = V2_SCHEMA + _DECISIONS_DDL. v1→v2 migration now also creates
  decisions table (result is v3). 33 passed, lint clean. Next: B02/scorer.
- [2026-06-12] B02 done. score.py + write_decision + CLI + 6 tests. Dolt omits NULL columns from JSON
  entirely — use .get() for nullable columns in _sql() results. 39 passed, lint clean. Next: B03/executor-wiring.
- [2026-06-12] B03 done. Executor wiring + 5 wiring tests. 44 passed, lint clean. Phase 3 complete.
