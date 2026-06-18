"""EV scorer — fire/suppress decisions with cold-start fail-open.

Cold start (evidence_count < N_COLD_START): always fire.
Evidence-based: precision = helpful / total_rated; fire if >= EV_THRESHOLD.
Every call writes one row to the decisions table via WriteStore.
"""
from .store_write import WriteStore

N_COLD_START = 3
EV_THRESHOLD = 0.5


def score(takeaway_id, store_path, session_id=None):
    """Score a takeaway and log the decision. Returns the decision dict."""
    ws = WriteStore(store_path)
    rated = [
        f for f in ws.firings()
        if f.takeaway_id == takeaway_id and f.outcome is not None
    ]
    evidence_count = len(rated)

    if evidence_count < N_COLD_START:
        decision = "fire"
        cold_start = True
        ev_score = None
    else:
        helpful = sum(1 for f in rated if f.outcome == "helpful")
        ev_score = helpful / evidence_count
        cold_start = False
        decision = "fire" if ev_score >= EV_THRESHOLD else "suppress"

    ws.write_decision(takeaway_id, session_id, decision, evidence_count,
                      cold_start, ev_score)

    return {
        "decision": decision,
        "cold_start": cold_start,
        "evidence_count": evidence_count,
        "ev_score": ev_score,
    }
