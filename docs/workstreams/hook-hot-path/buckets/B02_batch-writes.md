# Bucket B02: Batch the per-prompt write path

Parent: ../workstream.md
State: done
Goal for session: disclosed phase = one write spawn, non-blocking observer.
Target duration: 30 min
Context budget: Read parent + this bucket + required touchpoints only.

## Conceptual mapping

- The `disclosed` phase (1.2–1.6s) is a per-fired-hit loop: one `store.fire()`
  INSERT spawn per hit + one blocking observer subprocess per hit; decisions are
  already batched (June 20 lever). Same shape, same file (`hooks.py:_disclose` +
  `store_write.fire`).

## Tasks

- [ ] Add a batched fire path: collect per-hit rows in `_disclose`, write them in
      ONE invocation, recover real per-row firing ids, format `[tX/fY]` lines
      after the write.
- [ ] Make `_notify_observer` non-blocking: `subprocess.Popen` fire-and-forget
      (keep one spawn per firing — the observer contract counts calls ≡ firings;
      drop only the wait, not the calls).
- [ ] Bench before/after with `tools/hook_bench.py` (B01) on a scratch copy;
      record in Updates.

## Required touchpoints

- `src/monition/hooks.py  171–210  _disclose`
  The loop being batched; decisions batching at the bottom is the pattern.
- `src/monition/store_write.py  507–560  fire / INSERT INTO firings`
  Current single-row INSERT + how the returned firing id is produced.
- `src/monition/store_write.py  562–  write_decisions`
  The existing batched-INSERT pattern to mirror.
- `src/monition/hooks.py  148–168  _notify_observer`
  Blocking `subprocess.run` + OBSERVER_TIMEOUT_S to convert to Popen.

## Conditional touchpoints

- `src/monition/session_state.py  grep -n "dedup\|firing"`
  Read only if per-session dedup consumes firing ids at write time.

## Design direction

- **Named invariant: `[tX/fY]` ids must equal rows written.** A multi-VALUES
  INSERT under MySQL/Dolt returns LAST_INSERT_ID = first id of the batch, and
  consecutiveness is a lock-mode assumption — do NOT assume. Safe recovery:
  single invocation containing one INSERT per row each followed by
  `SELECT LAST_INSERT_ID()`, or one multi-row INSERT + `SELECT id, takeaway_id
  FROM firings WHERE id >= LAST_INSERT_ID()` re-matched by takeaway_id +
  session. Verify the chosen form's JSON output shape against a live scratch
  store before wiring.
- Fail-open: if the batched write errors, fall back to the current per-hit
  `store.fire()` loop (slow but correct), never drop firings silently.
- Observer Popen: no wait → OBSERVER_TIMEOUT_S becomes irrelevant on the happy
  path; keep stderr swallowed; a crashed observer must stay invisible.

## Validation

- `env -u MONITION_STORE .venv/bin/pytest -x -q` green.
- On a scratch store: fire 3 hits in one prompt; `monition rate f<id>` works for
  each injected id (id-truth invariant, end-to-end).
- Bench: prompt-hook disclosed ≤ ~450ms with 2–3 firings (was 1.2–1.6s).

## Done criteria

- [ ] Tasks complete.
- [ ] Validation passes.
- [ ] Bucket `Updates` section records discoveries/gotchas/handoff.
- [ ] Parent workstream progress updated.

## Updates

- [2026-07-02 16:25] Created. Handoff: none yet. Gotchas: none yet.
- [2026-07-02 17:20] DONE. `fire_batch(hits, ...)` added (one multi-row INSERT +
  one session-filtered read-back; git provenance once per prompt; per-row SQL
  single-sourced with fire() via `_firing_values`; id assignment by takeaway_id
  match against the read-back, raising StoreContractError on count/id mismatch);
  `_disclose` collects gate-passing hits and batch-fires with per-hit fallback
  on any batch error; `_notify_observer` → fire-and-forget Popen (DEVNULL
  streams, OBSERVER_TIMEOUT_S removed; observer tests updated to Popen
  contract). Suite green (315). **Id-truth verified end-to-end**: 5-hit prompt
  on a scratch store → all 5 `[tX/fY]` pairs match written rows, `rate` works.
  Per-hit write cost: was 3 spawns/hit (INSERT + MAX(id) + git), now 2 spawns +
  1 git TOTAL per prompt. Bench median disclosed 865ms — ABOVE the 450ms
  checkpoint, for two reasons discovered here: (1) the bench prompt fires only
  1–2 hits after session dedup, so the batch win barely shows at low hit
  counts (fixed cost is now 3 spawns: firings INSERT + read-back + decisions
  INSERT); (2) `disclosed` also contains `store.firings()` — a FULL
  firings-table read (~6k rows) at ~200-400ms. Handoff → B03: the wire client
  collapses the 3 fixed spawns to ~ms; consider also narrowing the firings read
  (`WHERE takeaway_id IN (scored ids)`) — score() only consumes rows for the
  hit takeaways (verify against score() internals first).
