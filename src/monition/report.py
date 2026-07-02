"""Render the audit as the report `monition report <store-path>` prints."""
from .metrics import audit, decision_quality, tune_recommendation


def _pct(x):
    return "-" if x is None else f"{x:.0%}"


def _fmt_pct(x):
    return f"{x:.1%}"


def render(store):
    takeaways = store.takeaways()
    firings = store.firings()
    decisions = store.decisions()
    violations = store.violations()
    audits = audit(takeaways, firings)
    dq = decision_quality(decisions)

    by_status = {}
    for t in takeaways:
        by_status[t.status] = by_status.get(t.status, 0) + 1
    rated = sum(1 for f in firings if f.outcome is not None)
    unknown_sessions = sum(1 for f in firings if f.session_id == "unknown")
    general = sum(1 for t in takeaways if t.reach == "general")

    lines = [f"Takeaway store audit — {store.path}", ""]
    lines.append(
        f"{len(takeaways)} takeaways ("
        + ", ".join(f"{v} {k}" for k, v in sorted(by_status.items()))
        + f"); {len(firings)} firings, {rated} rated"
        + (f"; {unknown_sessions} from anonymous sessions" if unknown_sessions else "")
    )
    if general:
        lines.append(f"{general} general-reach (fire in every repo)")
    lines.append("")

    header = f"{'id':>4} {'kind':<10} {'trigger':<32} {'fires':>5} {'+':>3} {'-':>3} {'prec':>5}"
    lines.append(header)
    lines.append("-" * len(header))
    for a in audits:
        trig = f"{a.trigger_kind}({a.trigger_spec or '-'})"
        if len(trig) > 32:
            trig = trig[:29] + "..."
        lines.append(
            f"{a.takeaway_id:>4} {a.kind:<10} {trig:<32} "
            f"{a.fires:>5} {a.helpful:>3} {a.noise:>3} {_pct(a.precision):>5}"
        )
    lines.append("")

    # v7 recall column: not-fired∧hit events — the trigger-broadening signal
    # ratings can't produce. Per contract, never folded into precision.
    if violations:
        by_row = {}
        for v in violations:
            by_row.setdefault(v.takeaway_id, []).append(v)
        signed = sum(1 for t in takeaways if t.violation_signature)
        lines.append(
            f"False negatives (not-fired∧hit; {signed} signature-bearing "
            f"row(s), {len(violations)} event(s)):")
        for tid in sorted(by_row):
            vs = by_row[tid]
            sessions = ", ".join(v.session_id for v in vs[-3:])
            lines.append(
                f"  t{tid}: {len(vs)} missed session(s) (latest: {sessions})"
                " — trigger too narrow?")
        lines.append("")

    recs = [a for a in audits if a.recommendation]
    if recs:
        lines.append("Recommendations:")
        for a in recs:
            lines.append(f"  t{a.takeaway_id}: {a.recommendation}")
            for ctx in a.noise_contexts:
                lines.append(f"      noise on: {ctx}")
            for ctx in a.helpful_contexts:
                if a.noise_contexts:
                    lines.append(f"      helpful on: {ctx}")
    else:
        lines.append("Recommendations: none — corpus is pulling its weight.")

    if dq.total > 0:
        lines.append("")
        lines.append(
            f"Decision quality (N={dq.total}): "
            f"{dq.cold_start_count} cold-start, "
            f"{dq.evidence_based_count} evidence-based, "
            f"{dq.suppress_count} suppressed"
        )
        lines.append(
            f"Noise saved vs always-fire baseline: {_fmt_pct(dq.noise_saved_pct)}"
        )
        if not dq.sufficient_data:
            lines.append(
                f"  (insufficient evidence-based data for threshold tuning "
                f"— run `monition tune` when evidence_based >= 10)"
            )

    return "\n".join(lines)


def render_tune(store):
    from .score import N_COLD_START, EV_THRESHOLD
    decisions = store.decisions()
    dq = decision_quality(decisions)
    rec = tune_recommendation(dq, n_cold_start=N_COLD_START,
                              ev_threshold=EV_THRESHOLD)
    lines = [f"monition tune — {store.path}", ""]
    lines.append(
        f"Decisions: {dq.total} total "
        f"({dq.cold_start_count} cold-start, "
        f"{dq.evidence_based_count} evidence-based, "
        f"{dq.suppress_count} suppressed)"
    )
    lines.append(
        f"Noise saved vs always-fire: {_fmt_pct(dq.noise_saved_pct)}"
    )
    lines.append(f"Recommendation: {rec}")
    return "\n".join(lines)
