"""Trigger modules — the interpretation layer over `trigger_kind`/`trigger_spec`.

Contract §Trigger modules: a row's trigger is a composition of modules from a
closed vocabulary, and the composition is a fixed function of `trigger_kind`:

    edit_path      -> glob(trigger_spec)
    session_start  -> always (matches every session start; there is no per-row
                      check to execute and no evidence to record — the
                      matcher's select-all IS the module)
    on_demand      -> lexical(trigger_spec) OR semantic(one_liner+trigger_spec)
    tool_call      -> tool_call(trigger_spec) — execution-moment matching (v8)

Each function answers exactly one question — does this moment match? — and on
a hit returns the v7 match-evidence dict, lossless. Everything around matching
(reach filter, per-session dedup, injection cap, EV scoring) stays in the
callers: modules never touch the store.

Assess-path == eval-path (workstream invariant): these functions are the ONE
implementation of module matching. Offline consumers (spec analysis, per-row
threshold calibration, the proposal engine, replay) import and call them —
never re-implement them.
"""
import fnmatch
import json


def glob_match(trigger_spec, path):
    """Evidence for the first pattern in the comma-separated spec that
    fnmatches `path` (repo-relative), or None. Contract §trigger_spec
    coordinate systems: per-pattern split + whitespace-strip; `*` crosses
    directory separators; case-sensitive on POSIX."""
    pattern = next(
        (g.strip() for g in (trigger_spec or "").split(",")
         if fnmatch.fnmatch(path, g.strip())), None)
    if pattern is None:
        return None
    return {"module": "glob", "pattern": pattern, "path": path}


def lexical_match(trigger_spec, query):
    """Evidence for the first keyword in the comma-separated spec appearing as
    a case-insensitive substring of `query`, or None."""
    q = query.lower()
    keyword = next(
        (kw.strip() for kw in (trigger_spec or "").split(",")
         if kw.strip() and kw.strip().lower() in q), None)
    if keyword is None:
        return None
    return {"module": "lexical", "keyword": keyword, "query": query}


def tool_call_match(trigger_spec, tool_name, tool_input):
    """Evidence for a tool-call moment, or None. Spec is a single JSON object
    (contract §trigger_spec coordinate systems, v8):

        {"tool": "Bash", "field": "command", "contains": ["git push"]}

    Matches when `tool` equals the hook's tool_name exactly AND any `contains`
    needle appears as a case-sensitive substring of tool_input[field] (which
    must be a string). Pure string work on already-loaded data — PreToolUse
    fires on every matched tool call, so no embeddings and no store reads
    belong here. Fail-open: a malformed spec or unexpected tool_input shape is
    no-match, never an exception."""
    try:
        spec = json.loads(trigger_spec or "")
        if spec.get("tool") != tool_name:
            return None
        value = (tool_input or {}).get(spec.get("field") or "")
        if not isinstance(value, str) or not value:
            return None
        needle = next(
            (n for n in spec.get("contains") or [] if n and n in value), None)
        if needle is None:
            return None
        return {"module": "tool_call", "tool": tool_name, "pattern": needle,
                "matched": value}
    except Exception:
        return None


def semantic_rank(rows, query):
    """Batch semantic module: embed `one_liner + trigger_spec` per row, keep
    rows within the row's threshold cosine of `query`, and return
    (row, evidence) pairs sorted by score descending. Batch-shaped on purpose
    — one embedding call per query, never per row (the hook path is a cold
    subprocess).

    Threshold: the row's `sem_threshold` when present (v8 per-row parameter,
    written only by the calibrate actuator), else the global SIM_THRESHOLD —
    a row dict without the key or with NULL behaves exactly as before v8.

    Fail-open: absent or broken embeddings return [] — lexical-only is a
    valid degraded result."""
    if not rows:
        return []
    try:
        from . import embed

        def threshold(row):
            thr = row.get("sem_threshold")
            return embed.SIM_THRESHOLD if thr is None else float(thr)

        texts = [f'{r["one_liner"]} {r.get("trigger_spec") or ""}'
                 for r in rows]
        sims = embed.semantic_scores(query, texts)
        from . import trace
        trace.mark("match:semantic_done")
        ranked = sorted(
            (p for p in zip(sims, rows) if p[0] >= threshold(p[1])),
            key=lambda p: p[0], reverse=True,
        )
        return [(r, {"module": "semantic", "score": round(float(s), 4),
                     "query": query})
                for s, r in ranked]
    except Exception:
        return []
