# Bucket B03: Executor Wiring

Parent: ../workstream.md
State: done
Goal for session: Wire hook executors through `score()`; suppress only with evidence.
Target duration: 25 min
Context budget: Read parent + this bucket + required touchpoints only.

## Conceptual mapping

All tasks share the executor surface in `hooks.py`. The score() call wraps the
existing fire decision; fail-open means any scorer error reduces to the pre-wiring
behavior (always fire). Tests extend the existing hook test fixtures.

## Data contract / provenance

*(No new cross-bucket data structure — score() return dict is consumed inline, not
serialized. decisions rows are written inside score(); the executor sees only the
decision string.)*

## Tasks

- [ ] In `hooks.py`, modify the fire executor to call `score()` before emitting disclosure:
  - Resolve store path; call `score(takeaway_id, store_path, session_id)`.
  - If `decision == "suppress"`: skip disclosure emission (score() already logged the
    decisions row). Log a one-line suppression note to hook-errors.log (same path as
    the fail-open error log) for observability.
  - If score() raises: catch all exceptions, log to hook-errors.log, treat as fire
    (cold-start fail-open). Do not re-raise.
  - If store absent (no store path): current no-op path is unchanged (score() is never
    called when there is no store).
- [ ] Update `tests/test_hooks.py`:
  - Suppression path: fixture store with ≥ N_COLD_START rated "noise" firings → fire
    executor emits nothing.
  - Score error path: score() raises → executor still fires (fail-open).
  - Cold-start still fires (existing always-fire behavior, now via cold-start code path).

## Required touchpoints

- `src/monition/hooks.py`  full file
  Current executor logic — where to insert the score() call and suppress branch.
- `src/monition/score.py`  `grep -n "def score\|N_COLD_START\|EV_THRESHOLD"`
  B02 handoff: confirm function signature and constants before importing.
- `tests/test_hooks.py`  full file
  Existing fixture patterns and test structure to extend without breaking.

## Conditional touchpoints

- `src/monition/store_write.py`  `grep -n "def fire\|resolve_store_path"`
  Read only if unclear how the executor currently resolves the store path for the
  fire() call — the same path is passed to score().

## Do-not-read / avoid

- `src/monition/init_sync.py` — no changes here.
- `src/monition/store.py` — score() already owns the read path; no direct reader calls in hooks.

## Design direction

- Import: `from monition.score import score` at top of hooks.py. The import is
  unconditional; fail-open is at call time, not import time.
- Store path resolution: the executor already resolves the store path to call `fire()`.
  Pass the same resolved path to `score()`. If path is None/absent → skip score call
  entirely (existing no-op behavior preserved).
- session_id: pass the same session_id the executor passes to `fire()`.
- Suppression log line format: `[suppress] t{takeaway_id} session={session_id}\n`
  appended to `~/.local/state/monition/hook-errors.log` (same path as error log).
  This is observability-only; no behavior depends on it.
  Correction (2026-07-02, hook hot-path): the suppression log line was REMOVED —
  routine suppressions were drowning real errors in hook-errors.log, and the
  decisions row already records the same fact; the error log is errors-only now.
- Core invariant: the fail-open catch wraps ONLY the score() call. The fire() call
  that follows is NOT inside the try — an error in fire() should still surface as it
  does today (it is already guarded by guarded_hook_command).

## Validation

- `pytest tests/test_hooks.py` — new suppression and fail-open tests pass.
- `pytest` — full suite green, no regressions.
- Lint: `python tools/lint.py` — no ERRORs.
- Expected: hook tests include at least one suppress case, one fail-open case, and
  all pre-existing cases still pass.

## Done criteria

- [ ] Tasks complete.
- [ ] Validation passes.
- [ ] Bucket `Updates` section records discoveries/gotchas/handoff.
- [ ] Parent workstream progress updated to "all done".
- [ ] `docs/road.md` Phase 3 status updated to reflect exit criteria met.

## Updates

- [2026-06-12 00:00] Created. Handoff: none yet. Gotchas: none yet.
- [2026-06-12] Done. 44 passed, 35 skipped, lint clean.
  Implementation notes:
  - Added `_log_path()`, `_log()`, `_score_takeaway()` helpers before the executors in hooks.py.
  - Added `if not lines: return` guard in both executor loops (suppress-all case produces empty lines list).
  - New tests in `test_score_wiring.py` (separate file, no pytestmark skip) use direct function calls +
    monkeypatch on `mh._score` so tests run without CMS oracle and without subprocess.
  - Fail-open is tested by patching `_score` to raise — `_score_takeaway` catches, logs, returns True.
  - Suppression is tested by patching `_score` to return suppress → executor skips fire, output is "".
