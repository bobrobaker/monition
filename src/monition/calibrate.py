"""`monition calibrate` — per-row semantic-threshold proposals (Filter-side).

The B02-NO-GO-compatible middle path: one interpretable parameter per row
(`sem_threshold`), moved by that row's own rated firings — no features, no
trained component. Distinct from `monition tune`, which reports on the Gate
(EV scorer / suppression): calibrate moves the Filter (matching), the seam
`2026-06-18-noise-targets-the-filter-not-the-gate` keeps clean.

Method (pre-registered in the B03 bucket, 2026-07-02): every rated
`on_demand` firing with a stored `situation` is re-scored through the
production modules — `lexical_match` first (lexical firings are out of θ's
reach), else the same embedding call `semantic_rank` executes
(assess-path == eval-path). The proposal rule is fixed:
θ = max(SIM_THRESHOLD, min helpful semantic score), 1.0 for rows with no
helpful semantic firing; propose only where θ suppresses ≥1 rated-noise
semantic firing. Proposals are printed with their evidence; applying one is
an explicit consent act (`--apply <t-id>`) through the narrow
`WriteStore.set_threshold` verb, which writes event-grain `mutations`
provenance.

Requires the `monition[embed]` extra — unlike the hook path (which fails open
to lexical), calibration without embeddings is meaningless, so the import
error surfaces loudly.
"""
import math

from . import modules
from .store import StoreContractError

# Rows below the cold-start rating floor are untouchable (bucket rule; matches
# the scorer's N_COLD_START).
MIN_RATINGS = 3

# The pre-registered gate: per-row time split by fired_at.
GATE_SPLIT = 0.7
# Pass bar (verbatim from the bucket): helpful_lost == 0 AND noise_suppressed
# >= 10% of held-out semantic noise firings.
GATE_NOISE_REDUCTION_FLOOR = 0.10


def _embed():
    try:
        from . import embed
    except Exception as e:  # pragma: no cover - import failure path
        raise StoreContractError(
            "calibrate requires the monition[embed] extra "
            f"(embedding import failed: {e})") from e
    return embed


def _row_text(t):
    return f"{t.one_liner} {t.trigger_spec or ''}"


def rescore(store):
    """Re-score every rated, situation-bearing on_demand firing through the
    production modules. Returns [(firing, takeaway, path, score)] with path
    'lexical' (score None) or 'semantic'."""
    embed = _embed()
    rows = {t.id: t for t in store.takeaways()}
    out = []
    for f in store.firings():
        if f.trigger_kind != "on_demand" or f.outcome is None or not f.situation:
            continue
        t = rows.get(f.takeaway_id)
        if t is None or t.trigger_kind != "on_demand":
            continue
        if modules.lexical_match(t.trigger_spec, f.situation) is not None:
            out.append((f, t, "lexical", None))
        else:
            score = embed.semantic_scores(f.situation, [_row_text(t)])[0]
            out.append((f, t, "semantic", float(score)))
    return out


def _by_row(scored):
    grouped = {}
    for item in scored:
        grouped.setdefault(item[1].id, []).append(item)
    return grouped


def _propose_theta(sim_threshold, sem_items):
    """The pre-registered proposal rule over (firing, score) semantic items."""
    helpful = [s for f, s in sem_items if f.outcome == "helpful"]
    if helpful:
        return max(sim_threshold, min(helpful))
    return 1.0


def propose(store, scored=None):
    """Per-row proposals over the full rated history. Returns proposal dicts
    sorted by suppressed-noise count descending."""
    embed = _embed()
    scored = rescore(store) if scored is None else scored
    props = []
    for tid, items in _by_row(scored).items():
        t = items[0][1]
        if t.status != "active" or len(items) < MIN_RATINGS:
            continue
        sem = [(f, s) for f, _, path, s in items if path == "semantic"]
        if not sem:
            continue
        theta = _propose_theta(embed.SIM_THRESHOLD, sem)
        current = (t.sem_threshold if t.sem_threshold is not None
                   else embed.SIM_THRESHOLD)
        noise = [s for f, s in sem if f.outcome == "noise"]
        suppressed = [s for s in noise if current <= s < theta]
        if not suppressed or theta <= current:
            continue
        helpful = [s for f, s in sem if f.outcome == "helpful"]
        props.append({
            "takeaway_id": tid,
            "one_liner": t.one_liner,
            "current": round(current, 4),
            "proposed": round(theta, 4),
            "n_rated": len(items),
            "n_lexical": len(items) - len(sem),
            "n_semantic": len(sem),
            "n_helpful_semantic": len(helpful),
            "n_noise_semantic": len(noise),
            "noise_suppressed": len(suppressed),
            "min_helpful_score": round(min(helpful), 4) if helpful else None,
        })
    return sorted(props, key=lambda p: -p["noise_suppressed"])


def apply(write_store, takeaway_id):
    """Apply the CURRENT proposal for one row — the consent gate. Recomputes
    proposals (never applies a stale printed number) and routes through the
    narrow set_threshold verb, which records the mutations provenance."""
    props = {p["takeaway_id"]: p for p in propose(write_store)}
    p = props.get(int(takeaway_id))
    if p is None:
        raise StoreContractError(
            f"no current calibrate proposal for takeaway {takeaway_id} "
            "(row below rating floor, no semantic traffic, or nothing to "
            "suppress)")
    source = (f"calibrate: {p['n_semantic']} rated semantic firings, "
              f"min_helpful={p['min_helpful_score']}, "
              f"suppresses {p['noise_suppressed']}/{p['n_noise_semantic']} noise")
    return write_store.set_threshold(p["takeaway_id"], p["proposed"],
                                     source=source)


def gate(store):
    """The pre-registered B03 gate (bucket Updates, 2026-07-02). Read-only.

    Per proposed row: time-split rated re-scorable firings (first ceil(70%)
    calibration, rest eval), θ from calibration only, then pooled held-out
    counts vs the SIM_THRESHOLD baseline — both sides on the same holdout:
    a held-out firing counts only when the baseline fires it (score >=
    SIM_THRESHOLD); it is suppressed when score < θ."""
    embed = _embed()
    scored = rescore(store)
    per_row = []
    pooled = {"holdout_noise": 0, "noise_suppressed": 0,
              "holdout_helpful": 0, "helpful_lost": 0}
    total_noise = sum(1 for f, _, _, _ in scored if f.outcome == "noise")
    lexical_noise = sum(1 for f, _, path, _ in scored
                        if f.outcome == "noise" and path == "lexical")
    for tid, items in _by_row(scored).items():
        t = items[0][1]
        if t.status != "active" or len(items) < MIN_RATINGS:
            continue
        items = sorted(items, key=lambda x: x[0].fired_at)
        k = math.ceil(len(items) * GATE_SPLIT)
        cal, ev = items[:k], items[k:]
        cal_sem = [(f, s) for f, _, path, s in cal if path == "semantic"]
        if not cal_sem:
            continue
        theta = _propose_theta(embed.SIM_THRESHOLD, cal_sem)
        cal_noise_suppressed = sum(
            1 for f, s in cal_sem
            if f.outcome == "noise" and embed.SIM_THRESHOLD <= s < theta)
        if not cal_noise_suppressed or theta <= embed.SIM_THRESHOLD:
            continue  # no proposal for this row (registered skip rule)
        ev_sem = [(f, s) for f, _, path, s in ev
                  if path == "semantic" and s >= embed.SIM_THRESHOLD]
        row_rec = {"takeaway_id": tid, "theta": round(theta, 4),
                   "cal_n": len(cal), "eval_n": len(ev),
                   "holdout_noise": 0, "noise_suppressed": 0,
                   "holdout_helpful": 0, "helpful_lost": 0}
        for f, s in ev_sem:
            side = "noise" if f.outcome == "noise" else "helpful"
            row_rec[f"holdout_{side}"] += 1
            if s < theta:
                key = "noise_suppressed" if side == "noise" else "helpful_lost"
                row_rec[key] += 1
        for key in pooled:
            pooled[key] += row_rec[key]
        per_row.append(row_rec)
    reduction = (pooled["noise_suppressed"] / pooled["holdout_noise"]
                 if pooled["holdout_noise"] else 0.0)
    return {
        "rows_proposed": len(per_row),
        "per_row": per_row,
        **pooled,
        "noise_reduction": round(reduction, 4),
        "theta_addressable_noise": (f"{total_noise - lexical_noise}/"
                                    f"{total_noise} rated noise is "
                                    "semantic-path (θ-addressable)"),
        "pass": (pooled["helpful_lost"] == 0
                 and pooled["holdout_noise"] > 0
                 and reduction >= GATE_NOISE_REDUCTION_FLOOR),
    }


def render_calibrate(props):
    if not props:
        return ("calibrate: no proposals (no active on_demand row with >= "
                f"{MIN_RATINGS} rated re-scorable firings and suppressible "
                "semantic noise)")
    lines = [f"calibrate — {len(props)} per-row threshold proposal(s) "
             "(apply with: monition calibrate --apply <t-id>)", ""]
    for p in props:
        lines.append(
            f"t{p['takeaway_id']}: {p['current']} -> {p['proposed']}  "
            f"suppresses {p['noise_suppressed']}/{p['n_noise_semantic']} "
            f"semantic noise, retains {p['n_helpful_semantic']} helpful "
            f"(min helpful score {p['min_helpful_score']}; "
            f"{p['n_rated']} rated, {p['n_lexical']} lexical)")
        lines.append(f"  {p['one_liner'][:90]}")
    return "\n".join(lines)


def render_gate(g):
    lines = [
        "calibrate gate (pre-registered, B03) — held-out vs global baseline",
        f"rows proposed: {g['rows_proposed']}",
        f"held-out semantic noise (baseline fires): {g['holdout_noise']}; "
        f"suppressed by per-row theta: {g['noise_suppressed']} "
        f"({g['noise_reduction']:.1%})",
        f"held-out semantic helpful: {g['holdout_helpful']}; "
        f"lost: {g['helpful_lost']}",
        f"scope: {g['theta_addressable_noise']}",
        f"bar: helpful_lost == 0 AND reduction >= "
        f"{GATE_NOISE_REDUCTION_FLOOR:.0%}",
        f"verdict: {'PASS' if g['pass'] else 'NO-GO'}",
    ]
    return "\n".join(lines)
