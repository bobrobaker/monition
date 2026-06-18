# Bucket B03: Hook executors + fail-open

Parent: ../workstream.md
State: done
Goal for session: hooks run from the package; absent and broken both fail open.
Target duration: 30 min
Context budget: Read parent + this bucket + required touchpoints only.

## Conceptual mapping

- Two thin CMS executors become two subcommands reading hook JSON on stdin;
  the fail-open guarantee (spec decisions 4 + 14) is designed and tested here
  because it lives in the command string + executor pair.

## Tasks

- [ ] Port `takeaway_fire.py` → `monition fire-hook`: stdin JSON, repo root
      from `$CLAUDE_PROJECT_DIR` (fallback `git rev-parse --show-toplevel`
      from cwd), store at `<root>/monition/`, repo-relative path, match → fire
      → `additionalContext` injection block, internal try/except fail-open.
      Calls B02's internals directly (no subprocess self-call).
- [ ] Port `takeaway_brief.py` → `monition session-brief` (same pattern,
      session_start).
- [ ] Define the canonical guarded command string the module emits (B04 writes
      it into settings.json): existence guard + stderr append to
      `~/.local/state/monition/hook-errors.log` (`$XDG_STATE_HOME` aware,
      mkdir -p'd) + `|| true`.
- [ ] Uninstall test: run the guard string via `sh -c` with monition stripped
      from PATH → exit 0, no stdout, no stderr.
- [ ] Crash test: monition present but failing (e.g. env `MONITION_TEST_CRASH=1`
      checked at CLI entry, or a stub executable raising) → exit 0 via guard,
      session-unblocking output contract held, traceback present in the error
      log.

## Required touchpoints

- `<CMS>/tools/takeaway_fire.py`  (full read, 59 lines)  port source: stdin shape, REPO guard, label format, additionalContext JSON
- `<CMS>/tools/takeaway_brief.py`  (full read, short)  port source
- `docs/specs/2026-06-11-module-realignment.md`  grep -n "decision 4\|^14\.\|^4\." then bounded read of decisions 4 and 14  the fail-open requirements being implemented
- `src/monition/cli.py`  grep -n "def \|subparser"  wiring point (post-B02 shape)

## Conditional touchpoints

- `<CMS>/.claude/settings.json` — read only if unsure of the exact
  hook-event JSON the executors receive (matcher/event names).

## Do-not-read / avoid

- `monition doctor` design — explicitly deferred (parent Non-Goals).

## Design direction

- Hook stdin: `session_id` may be missing → literal `"unknown"` (contract
  §firings); a file path outside the host repo → silent return (port the
  `startswith(REPO + os.sep)` guard).
- The injection message format (`[tN/fM] one_liner`, the framing lines) is
  load-bearing for cost accounting — port verbatim.
- Crash-test assertion level: exact — guard exits 0, stdout empty or valid
  hook JSON, log file contains the traceback string of the induced failure.

## Validation

- `.venv/bin/pytest` green including the uninstall + crash tests.
- Manual: `echo '<sample PreToolUse JSON>' | monition fire-hook` against a tmp
  store fires and prints the injection block.
- Expected: both fail-open tests pass; injected block byte-matches the CMS
  format for the same fixture.

## Done criteria

- [x] Tasks complete.
- [x] Validation passes.
- [x] Bucket `Updates` section records discoveries/gotchas/handoff.
- [x] Parent workstream progress updated.

## Updates

- [2026-06-11 19:55] Created. Handoff: none yet. Gotchas: none yet.
- [2026-06-11] Done. `src/monition/hooks.py`: `fire_hook()` / `session_brief()`
  call WriteStore internals directly (no subprocess self-call); root from
  `$CLAUDE_PROJECT_DIR` fallback git rev-parse; store at `<root>/monition/`;
  outside-repo guard, `"unknown"` session fallback, `[tN/fM]` labels and
  framing text ported verbatim. `guarded_hook_command(sub)` is the canonical
  string for B04: existence guard → exit 0; mkdir -p of
  `${XDG_STATE_HOME:-$HOME/.local/state}/monition`; stderr appended to
  `hook-errors.log`; `|| true`. Crash seam: `MONITION_TEST_CRASH=1` checked at
  `cli.main` entry, *before* any try/except, so the traceback escapes to the
  guard's log redirect.
  Tests (12): executor stdout byte-identical to CMS takeaway_fire/brief
  (oracle in a copied repo layout vs port via CLAUDE_PROJECT_DIR); per-session
  dedup; outside-repo and missing-store silence; uninstall test (scrubbed
  PATH → exit 0, zero output, no log file); crash test (shim on PATH +
  MONITION_TEST_CRASH → exit 0, empty stdout/stderr, traceback in log);
  healthy-guard passthrough (the manual smoke, automated). 54 total green,
  lint 0.
  Gotchas: (1) injection framing still says `tools/takeaway.py show/rate` —
  byte-identity demands it until B06; B06 must swap the hint to `monition
  show/rate` and update the executor byte-match tests then. (2) Guard tests
  must keep the real $HOME (the reader's `~/.local/bin/dolt` fallback);
  uninstall test deliberately scrubs HOME. (3) The originals' 20s subprocess
  timeout has no direct analog (in-process calls); harness hook timeouts +
  the guard cover the hang case — revisit only if real hangs appear.
