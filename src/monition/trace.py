"""Opt-in latency tracer for the hook hot path.

Off by default and zero-cost when off: `mark()` does a single env check and
returns. Enabled by `MONITION_TRACE` — `=1` reports to stderr (which lands in the
per-machine `hook-errors.log` when run as a hook), or `=<path>` appends one JSONL
record per hook event to that file.

A process-global mark list is safe here because every hook (`prompt-hook` /
`fire-hook` / `session-brief`) is a fresh cold subprocess — one event per process,
no cross-request contamination. Fail-open is absolute: any tracer error is
swallowed so instrumentation can never block or break a hook.
"""
import json
import os
import sys
import time

_marks = []          # list of (label, perf_counter_seconds)
_enabled = None      # tri-state cache: None=unchecked, else bool


def enabled():
    global _enabled
    if _enabled is None:
        _enabled = bool(os.environ.get("MONITION_TRACE"))
    return _enabled


def mark(label):
    """Record a phase boundary. No-op (one env check) when tracing is off."""
    if not enabled():
        return
    try:
        _marks.append((label, time.perf_counter()))
    except Exception:
        pass


def report(event):
    """Emit ordered per-phase deltas + total for `event`, then reset. No-op when
    off. Never raises into the caller."""
    if not enabled():
        return
    try:
        marks = _marks[:]
        _marks.clear()
        if len(marks) < 2:
            return
        t0 = marks[0][1]
        total_ms = (marks[-1][1] - t0) * 1000.0
        phases = [
            {"phase": marks[i][0], "ms": round((marks[i][1] - marks[i - 1][1]) * 1000.0, 3)}
            for i in range(1, len(marks))
        ]
        record = {"event": event, "total_ms": round(total_ms, 3), "phases": phases}

        dest = os.environ.get("MONITION_TRACE", "")
        if dest and dest != "1":
            with open(dest, "a") as f:
                f.write(json.dumps(record) + "\n")
        else:
            width = max(len(p["phase"]) for p in phases)
            lines = [f"[monition-trace] {event}  total={record['total_ms']}ms"]
            lines += [f"  {p['phase']:<{width}}  {p['ms']:>9.3f} ms" for p in phases]
            print("\n".join(lines), file=sys.stderr)
    except Exception:
        pass
