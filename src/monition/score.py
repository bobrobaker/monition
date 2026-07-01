"""EV scorer — fire/suppress decisions with cold-start fail-open.

Cold start (evidence_count < N_COLD_START): always fire — except the
cold-pause case below.
Evidence-based: precision = helpful / total_rated; fire if >= EV_THRESHOLD.
Every call writes one row to the decisions table via WriteStore.
"""
from .store_write import WriteStore

N_COLD_START = 3
EV_THRESHOLD = 0.5

# Cold-pause: under the plain cold-start rule an unrated row fires forever
# (measured at 55% of live traffic). A row with N_UNRATED_PAUSE or more
# lifetime firings and ZERO ratings is suppressed — decision "suppress",
# reason "cold-pause" — until any rating arrives. This does NOT starve the
# rating path: ratings arrive at mine time via `export-firings` over PAST
# firings (the 15+ already logged), and `--order-by priority` ranks a
# cold-paused row near the top (rated_count 0 → boundary_closeness 1.0 times
# high traffic). In the decisions table a cold-pause is the unique signature
# decision='suppress' AND cold_start=1 (a plain cold start always fires), so
# it stays distinguishable without widening the decision enum.
N_UNRATED_PAUSE = 15


def score(takeaway_id, store_path, session_id=None, store=None, firings=None,
          defer_write=False):
    """Score a takeaway and log the decision. Returns the decision dict.

    `store`: reuse an already-open WriteStore (hooks pass their open store so the
    per-hit Dolt open+schema-validation is paid once per prompt, not once per hit).
    None → open from `store_path` (the CLI `monition score` path).
    `firings`: a pre-fetched firings list shared across a prompt's hits, so the whole
    firings table is read once per prompt, not once per hit. None → read from the
    store (the CLI path). A prompt-loop snapshot is safe: firings created mid-loop
    carry outcome=None and are excluded from `rated` regardless.
    `defer_write`: skip writing the decision row and just return the dict, so the
    caller can batch a whole prompt's decisions into one INSERT. The returned dict
    carries everything the row needs. Default False → write inline (CLI path)."""
    ws = store if store is not None else WriteStore(store_path)
    all_firings = ws.firings() if firings is None else firings
    rated = [
        f for f in all_firings
        if f.takeaway_id == takeaway_id and f.outcome is not None
    ]
    evidence_count = len(rated)
    lifetime = sum(1 for f in all_firings if f.takeaway_id == takeaway_id)

    reason = None
    if evidence_count == 0 and lifetime >= N_UNRATED_PAUSE:
        # cold-pause: heavy traffic, zero feedback — stop firing until any
        # rating arrives (see the N_UNRATED_PAUSE comment above)
        decision = "suppress"
        cold_start = True
        ev_score = None
        reason = "cold-pause"
    elif evidence_count < N_COLD_START:
        decision = "fire"
        cold_start = True
        ev_score = None
    else:
        helpful = sum(1 for f in rated if f.outcome == "helpful")
        ev_score = helpful / evidence_count
        cold_start = False
        decision = "fire" if ev_score >= EV_THRESHOLD else "suppress"

    if not defer_write:
        ws.write_decision(takeaway_id, session_id, decision, evidence_count,
                          cold_start, ev_score)

    return {
        "decision": decision,
        "cold_start": cold_start,
        "evidence_count": evidence_count,
        "ev_score": ev_score,
        # not a decisions-table column: the distinct suppress reason
        # ("cold-pause") for state-log/CLI legibility
        "reason": reason,
    }
