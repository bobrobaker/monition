# Workstream: Hook hot-path — per-invocation store cost

Progress: COMPLETE (2026-07-02, B01–B04 same day). Exit met: warm prompt-hook 431ms / fire-hook 52ms (baseline 2.8–3.4s / 1.3–1.6s).
Blocked: none

## Objective

Cut warm hook latency from prompt-hook ~2.8–3.4s / fire-hook ~1.3–1.6s to ≤0.5s /
≤0.3s by eliminating per-store-interaction subprocess spawns (~160ms each; ~90% of
hook time), without abandoning the cold-subprocess fail-open model. Road.md Phase 8;
evidence measured 2026-07-02 (see Global Implementation Notes).

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
| B01 | done | buckets/B01_batch-validation.md | 1 spawn for schema validation + bench harness | — |
| B02 | done | buckets/B02_batch-writes.md | 1 write spawn per prompt; non-blocking observer | B01 |
| B03 | done | buckets/B03_wire-client.md | optional wire-protocol client, fail-open to CLI | B01 |
| B04 | done | buckets/B04_exit-eval.md | before/after trace vs baseline; exit check | B02, B03 |

States: `next`, `active`, `blocked`, `done`, `deferred`, `later`.

## Cross-Bucket Invariants

- **Fail-open is absolute**: every new path (batched validation, batched writes,
  wire client) degrades to the current per-call CLI behavior on any error; a hook
  must never block or crash the session.
- **Single write path preserved**: all store writes stay inside
  `WriteStore`/`storage_backends`; the wire client is a transport inside
  `DoltBackend`, never a second write path (contract:
  `docs/contracts/takeaway-store.md`).
- **Validation semantics unchanged**: same `StoreContractError` raises on
  missing/stale schema; the version-ladder messages of `_detect_stale_schema`
  stay intact (tests assert them).
- **Injected firing ids stay truthful**: the `[tX/fY]` line must name the firing
  row actually written — the `rate` verb keys on it. Any batched INSERT must
  recover real per-row ids, not assume them.
- **Bench writes never touch the hub**: all measurement runs against a scratch
  copy of the hub (`cp -r`), discarded after. Piping fabricated prompts into an
  executor IS instrumentation.
- **SQLite backend behavior unchanged** — it is in-process and already cheap;
  batching/wire work is Dolt-only, but every change must keep the SQLite tests
  green.

## Deferred / Non-Goals

- **Resident hook daemon** (true 10s-of-ms): out of scope — abandons the
  cold-subprocess model. Revisit only if B01–B03 measure insufficient vs targets.
- Matching/embed pipeline: already ms-scale (cosine ~14ms); do not touch.
- Python interpreter startup (~130ms): accepted floor for this phase.
- dolt binary startup itself: not ours to fix; we reduce invocation *count*.

## Global Implementation Notes

- **Baseline (2026-07-02, hub-sized scratch store, sql-server + embed daemon on,
  observer unset)**: prompt-hook 2.8–3.4s (store_opened 1.2–1.4s, match:sql ~125ms,
  embed:cache_loaded ~100ms, cosine ~14ms, matched-tail ~250ms, disclosed
  1.2–1.6s); fire-hook 1.3–1.6s (store_opened 1.1–1.3s, tool_matched ~240–320ms).
- Probes: `dolt sql -q "select 1"` = ~160ms flat (pure client spawn; query ~0);
  4 describes in ONE invocation = 159ms ≈ 1 describe; python spawn+imports
  (MONITION_DISABLE hook) = ~130ms, invisible to MONITION_TRACE.
- WriteStore open = 10 dolt subprocess calls (counted via subprocess.run wrap):
  `_detect_stale_schema` describes + per-table `describe` loop in
  `_validate_schema` (+ backend detection).
- Trace tooling exists: `MONITION_TRACE=<path>` per-hook JSONL
  (`src/monition/trace.py`); marks already placed in hooks.py.
- Dolt JSON gotcha (generator log 2026-06-12): NULL columns are omitted from JSON
  output — use `row.get("col")`, never `row["col"]`, on nullable reads.

## Updates

- [2026-07-02 16:25] Initial plan created from road.md Phase 8. Next: B01/batch-validation.
- [2026-07-02 17:00] B01 done: store open 1027ms/10 spawns → 152ms/1. Warm bench
  now fire-hook 404ms / prompt-hook 1546ms. Cross-bucket discovery: test
  hermeticity env-strips must be at conftest IMPORT time (session-scoped
  fixtures set up before function-scoped autouse fixtures — leaked sql-servers
  otherwise). tools/hook_bench.py is the standard measurement (warm-up event +
  medians + scratch/server teardown). Next: B02/batch-writes.
- [2026-07-02 17:20] B02 done: fire_batch + fire-and-forget observer; id-truth
  verified 5/5 on scratch. Cross-bucket discoveries: (1) bench prompt fires few
  hits after session dedup — per-hit wins under-show in medians; assess batch
  levers with the multi-hit id-truth run, not the bench alone; (2) `disclosed`
  contains a FULL firings-table read (~6k rows) — candidate narrowing
  (`WHERE takeaway_id IN`) noted in B03/B04. Next: B03/wire-client — design
  review to be proposed before implementation.
- [2026-07-02 17:55] B03+B04 done — workstream COMPLETE. Wire transport
  (pymysql `[wire]` extra, decision 2026-07-02-wire-client-extra): 0.9ms/query
  vs 151.7ms CLI spawn. Exit met: prompt-hook 431ms / fire-hook 52ms warm
  medians. Cross-cutting gotcha: dolt CLI `-r json` value shapes differ
  serverless (native numbers) vs through-server (all strings) — consumers
  tolerate both; wire mirrors through-server. Deferred follow-ups live in
  B04 Updates.
