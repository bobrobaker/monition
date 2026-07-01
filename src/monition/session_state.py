"""Per-machine, per-session harness state that must not live in the store.

Compaction markers: Claude Code can compact a session mid-flight (the
SessionStart hook fires with ``source == "compact"``), wiping previously
injected takeaway text from the context window while the per-session dedup
(`WriteStore._not_yet_fired`) would still suppress a re-fire — the row looks
disclosed, but the disclosure is gone. The session-brief executor records the
store's current MAX(firings.id) at each compaction; dedup then counts only
firings with id greater than the latest marker, re-arming every row disclosed
before the compaction.

This is machine-local session state, not store data: `firings`/`decisions`
rows are FK-validated against `takeaways` (a synthetic marker row would fail
the reader's orphan check), and a compaction is an event of one harness
session on one machine — so a state file under XDG_STATE_HOME is the honest
home. Reads fail open (a corrupt or absent file means "never compacted");
write failures propagate for the caller to log.
"""
import json
import os
from datetime import datetime, timedelta

# Markers older than this are pruned at write time. A marker only matters while
# its session can still fire, so a horizon of days is generous; pruning keeps
# the state file from growing without bound.
MARKER_RETENTION_DAYS = 30


def _state_dir():
    state = os.environ.get("XDG_STATE_HOME") or os.path.join(
        os.path.expanduser("~"), ".local", "state"
    )
    return os.path.join(state, "monition")


def _marker_file():
    return os.path.join(_state_dir(), "compaction-markers.json")


def _load():
    try:
        with open(_marker_file()) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}  # fail-open: unreadable state == no compaction recorded


def record_compaction(session_id, max_firing_id):
    """Record that `session_id` was compacted while the store held firings up
    to `max_firing_id`. Overwrites any earlier marker for the session — only
    the latest compaction matters for dedup. Prunes expired markers in the
    same write."""
    if not session_id:
        return
    now = datetime.now()
    horizon = (now - timedelta(days=MARKER_RETENTION_DAYS)).isoformat()
    markers = {
        sid: m for sid, m in _load().items()
        if isinstance(m, dict) and m.get("at", "") >= horizon
    }
    markers[str(session_id)] = {"floor": int(max_firing_id),
                                "at": now.isoformat()}
    os.makedirs(_state_dir(), exist_ok=True)
    with open(_marker_file(), "w") as f:
        json.dump(markers, f)


def compaction_floor(session_id):
    """Highest firing id that predates `session_id`'s latest compaction — the
    dedup floor. 0 when the session was never compacted (every firing counts)."""
    if not session_id:
        return 0
    m = _load().get(str(session_id))
    if not isinstance(m, dict):
        return 0
    try:
        return int(m["floor"])
    except (KeyError, TypeError, ValueError):
        return 0
