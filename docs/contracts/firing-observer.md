# Integration contract — the firing observer (`MONITION_FIRING_OBSERVER`)

This contract is the **outbound notification** Monition emits when a takeaway
fires: an opt-in side channel that lets a host wire each firing to a local effect
(e.g. a status-line counter, a desktop notification, a log) **without Monition
knowing or hard-coding anything about that effect**. Unlike the store-data
contracts in this directory (Monition owns a schema others *read*), here Monition
owns an **invocation shape** others *implement*.

Rationale and the options weighed live in
`docs/decisions/2026-06-18-firing-observer-seam.md`. This doc is the stable
interface a consumer depends on.

## The knob

Set the environment variable **`MONITION_FIRING_OBSERVER`** to a command. On every
takeaway that actually fires, Monition invokes:

```
<MONITION_FIRING_OBSERVER> --session <session_id> --text <slug>
```

- The env-var value is **`shlex`-split**, so it may carry an interpreter or flags:
  `python3 /path/to/observer.py`, `/usr/local/bin/notify`, etc.
- `--session <session_id>` — the firing session's id (the hook's `session_id`).
- `--text <slug>` — a short human-readable label for the firing (the takeaway's
  one-liner).

**Default: unset → no-op.** Monition ships no observer and no machine-local path.
Absent the env var, nothing is invoked. This is what keeps Monition distributable:
the host opts in by naming a command; Monition never assumes one exists.

## Semantics

- **One call per fired row.** A single hook invocation can fire several takeaways;
  the observer is called once per fired row, so an observer that counts sees a
  running total equal to the number of firings.
- **Only real firings.** The call sits *after* the score gate and the `store.fire`
  log. A score-**suppressed** hit is not a firing and never reaches the observer.
- **Covers all trigger kinds.** The call is at the single disclosure choke point
  (`_disclose` in `src/monition/hooks.py`), so it fires uniformly for
  `edit_path` and `tool_call` (PreToolUse), `session_start` (SessionStart), and
  `on_demand` (UserPromptSubmit) firings.

## Fail-open guarantees

The observer is a side effect, never a dependency of disclosure:

- The spawn is wrapped in its **own `try/except`**; any error is logged to the
  per-machine hook-error log and swallowed.
- **Fire-and-forget** (since 2026-07-02, hook hot-path): the hook `Popen`s the
  observer with detached stdio and never waits — a wedged observer costs the
  session nothing, and the hook's exit reparents the child for reaping. (This
  replaced the earlier 5s `OBSERVER_TIMEOUT_S` hang ceiling; observers should
  still return in milliseconds — they may now overlap the session's next
  activity.)
- A failing, slow, or missing observer **never blocks, delays, or suppresses** the
  firing or the context injection that already happened.

## Example — the author's status line

The reference consumer is a Claude Code status-line widget that shows a per-session
firing count. Wire it host-side (never in Monition):

```bash
export MONITION_FIRING_OBSERVER="python3 $HOME/.claude/statusline/statusline_flag.py"
```

That helper accepts exactly `--session <id> --text <slug>` and bumps a per-session
`⚑` counter. Any other consumer implementing the same argv shape works identically.
