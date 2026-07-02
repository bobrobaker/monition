"""`export-firings` — the tier-3 eval read-verb.

Emits one JSON object per firing as JSONL, denormalizing the parent takeaway's
`one_liner` and `kind` so each record is self-contained for cross-project eval.
Read-only, point-in-time, fail-open (an empty store yields an empty stream).
Reads go through the single approved store reader (`store.Store`); nothing here
writes.

Canonical schema: `docs/contracts/export-firings.md`. The per-record
`schema_version` is *this export contract's* version (still `1`), distinct from
the store schema version (v5). `situation` (firing-grain decision-context excerpt)
is an **additive** field — added without a stamp bump, per the contract's rule
that additive columns grow the export and consumers ignore unknown fields.
"""
import json
from datetime import datetime

from .score import EV_THRESHOLD, N_COLD_START
from .store import StoreContractError

EXPORT_SCHEMA_VERSION = 1


def _parse_since(since):
    try:
        return datetime.strptime(since, "%Y-%m-%d")
    except ValueError:
        raise StoreContractError("--since must be a date in YYYY-MM-DD form")


def _row_stats(firings):
    """Per-takeaway aggregates over the whole store: total firings (traffic),
    rated count, helpful count. Computed once, denormalized onto every record."""
    stats = {}
    for f in firings:
        fire, rated, helpful = stats.get(f.takeaway_id, (0, 0, 0))
        fire += 1
        if f.outcome is not None:
            rated += 1
            if f.outcome == "helpful":
                helpful += 1
        stats[f.takeaway_id] = (fire, rated, helpful)
    return stats


def _rating_priority(fire_count, rated_count, helpful_count):
    """The head-not-tail metric: how much a *new* rating on this row is worth.
    `traffic * boundary_closeness` — high only when the row fires a lot AND a
    rating could move the gate. Boundary math lives here (the substrate), never
    in the consuming skill (the discipline). See the confer 2026-06-17.

    - cold-start (rated < N_COLD_START): boundary_closeness = 1.0 — any rating is
      maximally informative (it moves the row toward leaving the always-fire floor).
    - evidence-based: closeness peaks at the fire/suppress threshold and falls to 0
      at a settled 0%/100%, so settled rows score ~0 regardless of traffic.
    """
    if rated_count < N_COLD_START:
        closeness = 1.0
    else:
        precision = helpful_count / rated_count
        closeness = max(0.0, 1.0 - abs(precision - EV_THRESHOLD) / EV_THRESHOLD)
    return round(fire_count * closeness, 4)


def _record(firing, takeaway, stats):
    """One export record. NULL provenance/outcome is preserved verbatim
    (None -> JSON null), never coerced. `stats` carries the parent row's
    store-wide aggregates for the denormalized rating-value fields."""
    fire_count, rated_count, helpful_count = stats
    precision = helpful_count / rated_count if rated_count else None
    return {
        "schema_version": EXPORT_SCHEMA_VERSION,
        "firing_id": firing.id,
        "takeaway_id": firing.takeaway_id,
        "one_liner": takeaway.one_liner,  # denormalized: self-contained record
        "kind": takeaway.kind,            # denormalized
        "outcome": firing.outcome,        # helpful|noise|None (unrated)
        "fired_at": firing.fired_at.isoformat(),
        "session_id": firing.session_id,  # may be "unknown" (anonymous bucket)
        "trigger_kind": firing.trigger_kind,  # open varchar; "resurrection" = synthetic
        "trigger_context": firing.trigger_context,
        "situation": firing.situation,  # v5: firing-grain decision-context excerpt
        # v7: lossless match evidence (JSON string) — what production matched
        # on; the trigger-learning substrate. Additive, no schema_version bump.
        "match_evidence": firing.match_evidence,
        "git_sha": firing.git_sha,
        "git_dirty": firing.git_dirty,
        "model": firing.model,
        "monition_version": firing.monition_version,
        # head-not-tail rating-value signals (denormalized parent-row aggregates;
        # additive, no schema_version bump). CMS's mine-session step orders on these.
        "fire_count": fire_count,         # traffic: total firings of the parent row
        "rated_count": rated_count,       # how much evidence already exists
        "precision": (round(precision, 4) if precision is not None else None),
        "rating_priority": _rating_priority(fire_count, rated_count, helpful_count),
    }


def export_records(store, since=None, rated_only=False, unrated_only=False,
                   session=None, order_by="fired_at"):
    """Read-only snapshot: one dict per firing, joined to its takeaway. The store
    reader already rejects firings that orphan a takeaway, so the join is total.

    `since` (YYYY-MM-DD) keeps firings on/after that date; `rated_only` keeps only
    firings with a non-NULL outcome; `unrated_only` keeps only firings with a NULL
    outcome (the rating worklist — its complement); `session` keeps only firings
    of that exact session_id (scope a rating pass to one session). `rated_only`
    and `unrated_only` are mutually exclusive; the caller enforces that.

    `order_by` selects emission order: `fired_at` (default — store/insertion order,
    the prior behavior) or `priority` (the head-not-tail worklist: highest
    `rating_priority` first, so a budgeted rating pass walks the most valuable
    firings first). Per-row stats are computed store-wide regardless of filters, so
    `fire_count`/`precision` reflect the true row, not the filtered slice.
    Everything else a consumer filters client-side.
    """
    by_id = {t.id: t for t in store.takeaways()}
    all_firings = list(store.firings())
    stats = _row_stats(all_firings)
    since_dt = _parse_since(since) if since else None
    out = []
    for f in all_firings:
        if since_dt is not None and f.fired_at < since_dt:
            continue
        if rated_only and f.outcome is None:
            continue
        if unrated_only and f.outcome is not None:
            continue
        if session is not None and f.session_id != session:
            continue
        out.append(_record(f, by_id[f.takeaway_id], stats[f.takeaway_id]))
    if order_by == "priority":
        # stable sort: rating_priority desc, then traffic desc; ties keep fired_at order
        out.sort(key=lambda r: (r["rating_priority"], r["fire_count"]), reverse=True)
    return out


def render_jsonl(records):
    """JSONL: one compact JSON object per line. Empty input -> empty string (a
    valid empty stream)."""
    return "\n".join(json.dumps(r, ensure_ascii=False) for r in records)
