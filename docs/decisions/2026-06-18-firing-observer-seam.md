# 2026-06-18 · Firing-observer seam (opt-in, decoupled, fail-open)

**Question.** A firing should be able to drive a machine-local side effect — the
author's Claude Code statusline "⚑" widget, which bumps a per-session count when a
takeaway fires. Monition is distributable, so it must not hard-couple to the
author's `~/.claude/statusline/statusline_flag.py` (absent on every other install).
How does a firing reach an external observer without leaking a machine-local path
into shipped code?

**Decision.** Add a single observer call at the firing choke point `_disclose()` in
`hooks.py` — the one place all three hooks (`fire_hook`, `session_brief`,
`prompt_hook`) flow through, and the moment `store.fire(...)` has logged a real
firing. The observer is opt-in via env var, mirroring the existing `MONITION_*`
convention (`MONITION_TEST_CRASH`):

- **Opt-in / decoupled.** `MONITION_FIRING_OBSERVER` names a command. Absent the
  env var, `_notify_observer` is a no-op — monition ships no observer and no
  machine-local path. Invocation contract: `<observer> --session <id> --text <slug>`,
  the env-var prefix `shlex`-split so it can carry an interpreter
  (`python3 /path/statusline_flag.py`). This contract matches the author's existing
  CLI, so wiring is purely `export MONITION_FIRING_OBSERVER=...` host-side.
- **Fail-open (own layer).** The call sits in its own `try/except` inside
  `_notify_observer` with a `timeout` hang-ceiling (`OBSERVER_TIMEOUT_S = 5`). A bad
  command, crash, or hang is logged to the per-machine state log and swallowed —
  never blocking, delaying, or suppressing the firing/injection that already
  happened. Honors monition's two-layered fail-open doctrine (executors swallow
  everything; the guarded command string covers hard crashes).
- **Count semantics.** Called once per fired row, after the score gate and the
  `store.fire` log — so the observer's running count equals the number of firings,
  matching the ⚑ widget's intent. Suppressed hits never reach it.

**Options weighed.**
- *Hard-code the statusline path / import it* — rejected: breaks every fork and
  install that lacks the author's machine-local script.
- *Guard on script existence at a fixed path* — rejected: still bakes in a
  machine-local convention path and a specific CLI shape; the env var is both
  opt-in and location-agnostic.
- *Env-var observer command (chosen)* — decoupled, matches the `MONITION_*`
  convention, and the generic `--session/--text` contract lets any consumer (not
  just the statusline) subscribe.

**Cost accepted.** A small, defined public contract (`MONITION_FIRING_OBSERVER` and
its argv shape) that consumers depend on. The 5s timeout is a hang ceiling, not an
expected latency — real observers (a JSON write) return in milliseconds.
