"""EV vocabulary and audit metrics over contract-typed records.

Pure functions: no store access here. The EV formulas are road.md's design
position made executable; the audit functions automate the manual
rate-and-tighten loop. Per the contract, an unrated firing (outcome None) is
missing data — it never enters a precision numerator or denominator.
"""
import fnmatch
from dataclasses import dataclass, field
from typing import List, Optional

# ---- EV vocabulary ---------------------------------------------------------


def benefit_rate(f_hit, delta_p_fail, work_at_risk, detectability_mult=1.0,
                 reversibility_mult=1.0):
    """f_hit × ΔP(fail) × W × D × M. D and M are fan-out multipliers, ≥ 1."""
    if detectability_mult < 1.0 or reversibility_mult < 1.0:
        raise ValueError("D and M are fan-out multipliers and must be >= 1")
    return f_hit * delta_p_fail * work_at_risk * detectability_mult * reversibility_mult


def cost_rate(f_trigger, inject_tokens, false_fire_tax=0.0):
    """f_trigger × inject_tokens, plus the corpus-wide false-fire tax."""
    return f_trigger * inject_tokens + false_fire_tax


def keep(benefit, cost):
    """Keep the takeaway while benefit rate exceeds cost rate."""
    return benefit > cost


def trigger_precision(helpful, noise):
    """helpful / (helpful + noise) over RATED firings only; None when unrated.

    This is the observable form of f_hit / f_trigger, both denominated in
    disclosures per session (the firing log's native unit — injection cost is
    paid once per session, so per-session disclosure IS the cost event). The
    caller must never fold unrated firings into either count.
    """
    rated = helpful + noise
    return None if rated == 0 else helpful / rated


# ---- audit -----------------------------------------------------------------


@dataclass
class TakeawayAudit:
    takeaway_id: int
    kind: str
    trigger_kind: str
    trigger_spec: Optional[str]
    status: str
    mirror: str = "none"
    fires: int = 0
    helpful: int = 0
    noise: int = 0
    unrated: int = 0
    precision: Optional[float] = None
    noise_contexts: list = field(default_factory=list)
    helpful_contexts: list = field(default_factory=list)
    recommendation: str = ""


def spec_matches(trigger_spec, path):
    """Reproduce the store executor's matching exactly: comma-split,
    whitespace-strip, fnmatch per pattern (where * crosses '/')."""
    return any(
        fnmatch.fnmatch(path, g.strip())
        for g in (trigger_spec or "").split(",")
    )


def _recommend(a):
    if not a.fires:
        if a.status == "active":
            return "never fired — widen trigger_spec or fold into a doc"
        return ""
    if a.noise and not a.helpful:
        return "all rated firings were noise — narrow trigger_spec or retire"
    if a.noise and a.helpful:
        return ("mixed ratings — narrow trigger_spec toward the helpful "
                "contexts; compare context lists")
    if not a.helpful and not a.noise:
        return "fires but never rated — no eval signal; rate a few firings"
    return ""


def audit(takeaways, firings):
    """One TakeawayAudit per takeaway, in id order."""
    by_id = {}
    for t in takeaways:
        by_id[t.id] = TakeawayAudit(
            takeaway_id=t.id, kind=t.kind, trigger_kind=t.trigger_kind,
            trigger_spec=t.trigger_spec, status=t.status, mirror=t.mirror,
        )
    for f in firings:
        a = by_id[f.takeaway_id]
        a.fires += 1
        if f.outcome == "helpful":
            a.helpful += 1
            if f.trigger_context:
                a.helpful_contexts.append(f.trigger_context)
        elif f.outcome == "noise":
            a.noise += 1
            if f.trigger_context:
                a.noise_contexts.append(f.trigger_context)
        else:
            a.unrated += 1
    for a in by_id.values():
        a.precision = trigger_precision(a.helpful, a.noise)
        a.recommendation = _recommend(a)
    return [by_id[k] for k in sorted(by_id)]


# ---- decision quality -------------------------------------------------------


@dataclass
class DecisionQuality:
    total: int = 0
    cold_start_count: int = 0
    evidence_based_count: int = 0
    suppress_count: int = 0
    noise_saved_pct: float = 0.0
    avg_ev_score_suppressed: Optional[float] = None
    avg_ev_score_fired: Optional[float] = None
    sufficient_data: bool = False


def tune_recommendation(dq: DecisionQuality, n_cold_start: int = 3,
                        ev_threshold: float = 0.5) -> str:
    """Qualitative threshold recommendation given accumulated decisions."""
    if dq.total == 0:
        return "no decisions recorded yet — fire and rate some sessions first"
    if not dq.sufficient_data:
        return (
            f"insufficient evidence-based data ({dq.evidence_based_count} decisions,"
            f" need ≥10) — recommendation deferred"
        )
    if dq.suppress_count == 0:
        return (
            f"no suppressions yet — all evidence-based decisions fired; "
            f"consider lowering N_COLD_START from {n_cold_start} if early "
            f"evidence looks reliable"
        )
    if dq.avg_ev_score_suppressed is not None:
        gap = abs(dq.avg_ev_score_suppressed - ev_threshold)
        if gap <= 0.1:
            return (
                f"threshold appears well-placed "
                f"(mean suppress ev_score: {dq.avg_ev_score_suppressed:.2f} "
                f"vs EV_THRESHOLD={ev_threshold})"
            )
        if dq.avg_ev_score_suppressed > ev_threshold:
            return (
                f"suppressed takeaways averaged ev_score "
                f"{dq.avg_ev_score_suppressed:.2f} > EV_THRESHOLD={ev_threshold} "
                f"— consider raising threshold to reduce over-suppression"
            )
    return (
        f"suppressed {dq.suppress_count}/{dq.evidence_based_count} evidence-based "
        f"decisions ({dq.noise_saved_pct:.1%} noise saved vs always-fire)"
    )


def decision_quality(decisions: List) -> DecisionQuality:
    """Summarise scored decisions: savings vs always-fire baseline."""
    dq = DecisionQuality(total=len(decisions))
    if not decisions:
        return dq
    cold = [d for d in decisions if d.cold_start]
    evidence = [d for d in decisions if not d.cold_start]
    suppressed = [d for d in evidence if d.decision == "suppress"]
    fired_ev = [d for d in evidence if d.decision == "fire"]
    dq.cold_start_count = len(cold)
    dq.evidence_based_count = len(evidence)
    dq.suppress_count = len(suppressed)
    dq.noise_saved_pct = len(suppressed) / max(1, dq.total)
    dq.sufficient_data = dq.evidence_based_count >= 10
    if suppressed:
        scores = [d.ev_score for d in suppressed if d.ev_score is not None]
        dq.avg_ev_score_suppressed = sum(scores) / len(scores) if scores else None
    if fired_ev:
        scores = [d.ev_score for d in fired_ev if d.ev_score is not None]
        dq.avg_ev_score_fired = sum(scores) / len(scores) if scores else None
    return dq
