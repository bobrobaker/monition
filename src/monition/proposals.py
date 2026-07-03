"""`monition propose` — the audit-cadence proposal engine (B06).

Read-side only: walks per-row evidence (rated firings with B04 batch
attribution, violations, match_evidence, store-wide traffic) and emits typed
proposals — tighten / broaden / migrate / merge / graduate / stale — each
citing the firing/violation ids and excerpts a human can verify in seconds.
Proposals are a READ (rendered text or JSON), never store rows; applying one
is an explicit consent act through the narrow mutation verbs (`retarget`,
`set-trigger`, `retire`) — no auto-apply anywhere (framing decision
2026-07-01, contract §mutations).

Deterministic rules over evidence — no learned scorer (a learned ranker owes
a B02-grade pre-registered gate and is out of this engine's scope). Candidate
literals are judged by running the PRODUCTION matchers over stored
match_evidence (assess-path == eval-path, contract §Trigger modules) and, where
both label classes exist, scored with the graduated layer_eval `auc` (reuse,
not rebuild). Semantic (θ) tightening is NOT re-implemented here — that is
`monition calibrate` (B03; apply parked NO-GO).

B04 discount: noise that arrived in a shared-cause batch (>= BATCH_MIN_SIZE
firings on one delivery moment) attributes to the breadth/prompt layer, never
to the row — only SOLO noise counts toward per-row tighten evidence
(decision 2026-06-18, hub-verified 80% of rated noise is batch-borne).
"""
import json
import os
import re
import subprocess
from collections import defaultdict
from datetime import datetime, timedelta
from itertools import combinations

from . import metrics
from . import modules

# Evidence floors — a rule below its floor emits a note, never a proposal
# (the handoff's one-exemplar caution made explicit).
MIN_SOLO_NOISE = 2        # tighten: solo-noise lexical firings per keyword
MIN_VIOLATIONS = 2        # broaden: organic FN exemplars per row
MIN_HELPFUL_SEMANTIC = 2  # migrate: helpful semantic firings per row
MIN_COFIRE_SESSIONS = 3   # merge: distinct sessions a pair co-fired in
MERGE_MIN_SHARED_TOKENS = 3  # merge: spec/one-liner tokens the pair shares
GRADUATE_MIN_RATED = 5
GRADUATE_MIN_PRECISION = 0.8
GRADUATE_SESSION_SHARE = 0.5  # fired in >= this share of all store sessions
STALE_RECENT_DAYS = 14    # a row that fired this recently is not stale
MERGE_PAIR_CAP = 10       # rendered pairs; overflow is logged, never silent

MIN_TOKEN_LEN = 4
_TOKEN_RE = re.compile(r"[a-z0-9_][a-z0-9_\-./]{3,}")
# Crude but deterministic: common English glue that would otherwise survive
# the cross-exemplar intersection and read as a trigger candidate.
_STOPWORDS = frozenset("""
    about after again also always because been before being between both
    could does down each every first from have here into just like more
    most much must never only other over same should since some such than
    that their them then there these they this those through under until
    very want were what when where which while will with without would
    your session sessions user file files
""".split())


def _tokens(text):
    """Candidate literal tokens of a text: lowercased, len >= MIN_TOKEN_LEN,
    stopwords out. Deterministic — the whole candidate-generation story."""
    if not text:
        return set()
    toks = {t.strip(".-/") for t in _TOKEN_RE.findall(text.lower())}
    return {t for t in toks if len(t) >= MIN_TOKEN_LEN and t not in _STOPWORDS}


def _evidence(firing):
    """Parsed match_evidence dict, or None (absent/unparseable — fail-open,
    like every other evidence consumer)."""
    if not firing.match_evidence:
        return None
    try:
        ev = json.loads(firing.match_evidence)
    except (ValueError, TypeError):
        return None
    return ev if isinstance(ev, dict) else None


def _auc(scores, labels):
    """layer_eval discrimination for a candidate (reuse, not rebuild).
    None when numpy (embed extra) is absent or a class is missing."""
    try:
        from .relevance.eval import auc
    except Exception:
        return None
    v = auc(scores, labels)
    return None if v != v else round(v, 3)  # NaN -> None


def _spec_keywords(trigger_spec):
    return [k.strip() for k in (trigger_spec or "").split(",") if k.strip()]


def _excerpt(text, limit=90):
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


# ---- per-class rules --------------------------------------------------------


def _tighten(rows, by_row, sizes):
    """Drop a keyword that only ever produced solo noise. Bar: zero helpful
    lexical firings lost, re-checked by running the production lexical
    matcher over every evidenced rated query (assess-path == eval-path)."""
    props = []
    for t in rows.values():
        if t.status != "active" or t.trigger_kind != "on_demand":
            continue
        keywords = _spec_keywords(t.trigger_spec)
        if len(keywords) < 2:
            continue  # dropping the only keyword is retire, not tighten
        rated = [(f, _evidence(f)) for f in by_row.get(t.id, ())
                 if f.outcome is not None]
        lex = [(f, ev) for f, ev in rated
               if ev and ev.get("module") == "lexical" and ev.get("query")]
        for kw in keywords:
            solo_noise = [f for f, ev in lex if ev.get("keyword") == kw
                          and f.outcome == "noise"
                          and sizes.get(f.id, 1) < metrics.BATCH_MIN_SIZE]
            helpful_on_kw = [f for f, ev in lex if ev.get("keyword") == kw
                             and f.outcome == "helpful"]
            if len(solo_noise) < MIN_SOLO_NOISE or helpful_on_kw:
                continue
            new_spec = ",".join(k for k in keywords if k != kw)
            helpful_lost = [
                f for f, ev in lex
                if f.outcome == "helpful"
                and modules.lexical_match(new_spec, ev["query"]) is None
            ]
            if helpful_lost:  # the B03 worked-example bar: zero loss
                continue
            noise_dropped = [
                f for f, ev in lex
                if f.outcome == "noise"
                and modules.lexical_match(new_spec, ev["query"]) is None
            ]
            fids = ",".join(f"f{f.id}" for f in solo_noise)
            props.append({
                "class": "tighten", "verb": "retarget",
                "takeaway_id": t.id, "one_liner": t.one_liner,
                "proposed_spec": new_spec,
                "evidence": [
                    f"drop keyword {kw!r}: {len(solo_noise)} solo-noise "
                    f"lexical firings, 0 helpful on it"
                ] + [
                    f"  f{f.id} noise: \"{_excerpt(ev['query'])}\""
                    for f, ev in lex if f in solo_noise
                ] + [
                    f"replay over {len(lex)} evidenced rated lexical firings: "
                    f"helpful lost 0, noise dropped {len(noise_dropped)}"
                ],
                "apply": (f"monition retarget {t.id} '{new_spec}' "
                          f"--source 'propose:tighten {fids}'"),
            })
    return props


def _broaden(rows, violations_by_row, notes):
    """Violations name sessions the trigger missed. Rows below the exemplar
    floor get a note, never a proposal (one exemplar is an anecdote)."""
    props = []
    for tid, vs in sorted(violations_by_row.items(), key=lambda kv: str(kv[0])):
        t = rows.get(tid)
        if t is None or t.status != "active":
            continue
        if len(vs) < MIN_VIOLATIONS:
            notes.append(
                f"t{tid}: {len(vs)} violation — below the "
                f"{MIN_VIOLATIONS}-exemplar floor, no broaden proposal")
            continue
        token_sets = [_tokens(v.evidence) for v in vs if v.evidence]
        common = set.intersection(*token_sets) if token_sets else set()
        spec = t.trigger_spec or ""
        # novelty: a token the current spec already lexically hits is not a
        # broadening candidate (the trigger did not miss it for that reason)
        candidates = sorted(
            (tok for tok in common
             if modules.lexical_match(spec, tok) is None),
            key=lambda s: (-len(s), s))[:5]
        evidence = [
            f"{len(vs)} organic violations (sessions: "
            + ", ".join(sorted({v.session_id for v in vs})[:5]) + ")"
        ] + [
            f"  v{v.id} ({v.session_id}): \"{_excerpt(v.evidence)}\""
            for v in vs[:4]
        ]
        prop = {
            "class": "broaden", "verb": "retarget",
            "takeaway_id": tid, "one_liner": t.one_liner,
            "candidates": candidates,
            "evidence": evidence, "apply": None,
        }
        if candidates and t.trigger_kind == "on_demand":
            best = candidates[0]
            new_spec = f"{spec},{best}" if spec else best
            prop["proposed_spec"] = new_spec
            prop["evidence"].append(
                "common literals across all exemplars: "
                + ", ".join(repr(c) for c in candidates))
            prop["apply"] = (f"monition retarget {tid} '{new_spec}' "
                             "--source 'propose:broaden "
                             + ",".join(f"v{v.id}" for v in vs) + "'")
        elif candidates:
            prop["evidence"].append(
                "common literals across all exemplars: "
                + ", ".join(repr(c) for c in candidates)
                + f" — row is {t.trigger_kind}, not on_demand; the trigger "
                "change is a human call (set-trigger / retarget)")
        else:
            prop["evidence"].append(
                "no spec-novel literal common to all exemplars — trigger "
                "broadening needs a human-authored spec (evidence above)")
        props.append(prop)
    return props


def _migrate(rows, by_row, sizes):
    """Every helpful semantic hit's query shares a stable literal -> propose
    the keyword (a step down the determinism ladder). Candidate must lexically
    match ALL helpful semantic queries and ZERO solo-noise queries, via the
    production matcher; discrimination reported with layer_eval auc."""
    props = []
    for t in rows.values():
        if t.status != "active" or t.trigger_kind != "on_demand":
            continue
        rated = [(f, _evidence(f)) for f in by_row.get(t.id, ())
                 if f.outcome is not None]
        rated = [(f, ev) for f, ev in rated if ev and ev.get("query")]
        helpful_sem = [(f, ev) for f, ev in rated
                       if ev.get("module") == "semantic"
                       and f.outcome == "helpful"]
        if len(helpful_sem) < MIN_HELPFUL_SEMANTIC:
            continue
        common = set.intersection(*(_tokens(ev["query"])
                                    for _, ev in helpful_sem))
        solo_noise = [(f, ev) for f, ev in rated if f.outcome == "noise"
                      and sizes.get(f.id, 1) < metrics.BATCH_MIN_SIZE]
        spec = t.trigger_spec or ""
        candidates = []
        for tok in sorted(common, key=lambda s: (-len(s), s)):
            if modules.lexical_match(spec, tok) is not None:
                continue  # spec already covers it lexically
            if any(modules.lexical_match(tok, ev["query"]) is None
                   for _, ev in helpful_sem):
                continue  # production matcher disagrees -> not a candidate
            if any(modules.lexical_match(tok, ev["query"]) is not None
                   for _, ev in solo_noise):
                continue  # hits solo noise -> would import the noise
            candidates.append(tok)
            if len(candidates) == 3:
                break
        if not candidates:
            continue
        best = candidates[0]
        scores = [1 if modules.lexical_match(best, ev["query"]) else 0
                  for _, ev in rated]
        labels = [1 if f.outcome == "helpful" else 0 for f, _ in rated]
        auc = _auc(scores, labels)
        new_spec = f"{spec},{best}" if spec else best
        props.append({
            "class": "migrate", "verb": "retarget",
            "takeaway_id": t.id, "one_liner": t.one_liner,
            "proposed_spec": new_spec, "candidates": candidates,
            "auc": auc,
            "evidence": [
                f"literal {best!r} appears in all {len(helpful_sem)} helpful "
                f"semantic queries and 0 of {len(solo_noise)} solo-noise "
                f"queries (production lexical_match)"
            ] + [
                f"  f{f.id} helpful (sim {ev.get('score')}): "
                f"\"{_excerpt(ev['query'])}\""
                for f, ev in helpful_sem[:4]
            ] + ([f"layer_eval auc over {len(rated)} rated evidenced "
                  f"firings: {auc}"] if auc is not None else []) + [
                "caution: substring keywords match MENTIONS as well as acts "
                "(B05, f4459) — judge the queries above, not just the counts"
            ],
            "apply": (f"monition retarget {t.id} '{new_spec}' "
                      f"--source 'propose:migrate "
                      + ",".join(f"f{f.id}" for f, _ in helpful_sem) + "'"),
        })
    return props


def _merge(rows, firings, notes):
    """Active near-duplicates: two rows repeatedly fired on the SAME delivery
    moment across distinct sessions AND overlap in what they say (shared
    spec/one-liner tokens). Co-firing alone is NOT duplication evidence — on
    the hub it is dominated by B04 batch dumps, where one broad prompt lights
    unrelated rows together (verified live 2026-07-02: the top co-fire pairs
    were image-files x worked-examples rows); the content overlap is what
    separates clones from co-broad rows."""
    moments = defaultdict(set)
    for f in firings:
        if f.session_id is None or f.trigger_context is None:
            continue
        moments[(f.session_id, f.trigger_kind, f.trigger_context)].add(
            f.takeaway_id)
    pair_sessions = defaultdict(set)
    for (session_id, _, _), tids in moments.items():
        active = sorted((t for t in tids
                         if t in rows and rows[t].status == "active"),
                        key=str)
        for a, b in combinations(active, 2):
            pair_sessions[(a, b)].add(session_id)

    def _row_tokens(t):
        return _tokens(f"{t.one_liner or ''} {t.trigger_spec or ''}")

    shared_by_pair = {}
    for (a, b), sessions in pair_sessions.items():
        if len(sessions) < MIN_COFIRE_SESSIONS:
            continue
        shared = _row_tokens(rows[a]) & _row_tokens(rows[b])
        if len(shared) >= MERGE_MIN_SHARED_TOKENS:
            shared_by_pair[(a, b)] = shared
    pairs = sorted(((p, s) for p, s in pair_sessions.items()
                    if p in shared_by_pair),
                   key=lambda kv: (-len(kv[1]), str(kv[0])))
    if len(pairs) > MERGE_PAIR_CAP:
        notes.append(f"merge: {len(pairs) - MERGE_PAIR_CAP} further co-firing "
                     f"pairs beyond the rendered {MERGE_PAIR_CAP} "
                     "(rerun after acting on these)")
        pairs = pairs[:MERGE_PAIR_CAP]
    props = []
    for (a, b), sessions in pairs:
        ta, tb = rows[a], rows[b]
        props.append({
            "class": "merge", "verb": "merge",
            "takeaway_id": a, "other_id": b,
            "one_liner": ta.one_liner,
            "evidence": [
                f"t{a} \"{_excerpt(ta.one_liner, 60)}\" and "
                f"t{b} \"{_excerpt(tb.one_liner, 60)}\" co-fired on the same "
                f"moment in {len(sessions)} distinct sessions: "
                + ", ".join(sorted(sessions)[:5]),
                "shared content tokens: "
                + ", ".join(sorted(shared_by_pair[(a, b)])[:8]),
                f"specs: t{a}={ta.trigger_spec!r} t{b}={tb.trigger_spec!r}",
            ],
            # survivor choice is judgment — render the moves, decide nothing
            "apply": (f"human: pick survivor; fold specs via retarget, then "
                      f"monition retire <loser of t{a}/t{b}>"),
        })
    return props


def _graduate(rows, by_row, firings):
    """Fires in most sessions, consistently helpful -> belongs on an
    always-on surface. Names the target surface; writing it is the
    human's/CMS's move — monition only retires after."""
    all_sessions = {f.session_id for f in firings
                    if f.session_id and f.session_id != "unknown"}
    if not all_sessions:
        return []
    props = []
    for t in rows.values():
        if t.status != "active":
            continue
        fs = by_row.get(t.id, ())
        rated = [f for f in fs if f.outcome is not None]
        helpful = [f for f in rated if f.outcome == "helpful"]
        if len(rated) < GRADUATE_MIN_RATED:
            continue
        precision = len(helpful) / len(rated)
        sess = {f.session_id for f in fs
                if f.session_id and f.session_id != "unknown"}
        share = len(sess) / len(all_sessions)
        if precision < GRADUATE_MIN_PRECISION or share < GRADUATE_SESSION_SHARE:
            continue
        surface = ("the global ~/.claude/CLAUDE.md (row reach is general)"
                   if t.reach == "general"
                   else f"{t.origin_repo}/CLAUDE.md" if t.origin_repo
                   else "the origin repo's CLAUDE.md (origin_repo unset)")
        props.append({
            "class": "graduate", "verb": "graduate",
            "takeaway_id": t.id, "one_liner": t.one_liner,
            "target_surface": surface,
            "evidence": [
                f"fired in {len(sess)}/{len(all_sessions)} store sessions "
                f"({share:.0%}); precision {precision:.2f} "
                f"({len(helpful)}/{len(rated)} rated helpful)",
            ],
            "apply": (f"human/CMS: move the content to {surface}, then "
                      f"monition retire {t.id}"),
        })
    return props


def _git_files(repo):
    """Tracked files of a local repo, or None when unreadable (not a dir, not
    a git repo, git absent) — the caller notes and skips, never errors."""
    if not repo or not os.path.isdir(repo):
        return None
    try:
        r = subprocess.run(["git", "-C", repo, "ls-files"],
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    return r.stdout.splitlines()


def _stale(rows, by_row, notes, git_files=_git_files):
    """edit_path rows whose glob matches nothing tracked in their origin repo
    — the referent vanished. Recent firing vetoes (something still matches,
    e.g. untracked files); unresolvable repos are noted, not guessed at."""
    cutoff = datetime.now() - timedelta(days=STALE_RECENT_DAYS)
    props = []
    unresolvable = []
    for t in rows.values():
        if t.status != "active" or t.trigger_kind != "edit_path":
            continue
        if not t.trigger_spec:
            continue
        fs = by_row.get(t.id, ())
        last = max((f.fired_at for f in fs), default=None)
        if last is not None and last >= cutoff:
            continue  # fired recently -> the glob still hits something real
        files = git_files(t.origin_repo)
        if files is None:
            unresolvable.append(f"t{t.id}")
            continue
        if any(modules.glob_match(t.trigger_spec, p) is not None
               for p in files):
            continue
        props.append({
            "class": "stale", "verb": "stale",
            "takeaway_id": t.id, "one_liner": t.one_liner,
            "evidence": [
                f"glob {t.trigger_spec!r} matches 0 of {len(files)} tracked "
                f"files in {t.origin_repo}",
                ("never fired" if last is None
                 else f"last fired {last.date().isoformat()}"),
            ],
            "apply": f"monition retire {t.id}",
        })
    if unresolvable:
        notes.append("stale: origin repo unresolvable locally for "
                     + ", ".join(unresolvable) + " — skipped, not judged")
    return props


# ---- engine -----------------------------------------------------------------


def propose(store, git_files=_git_files):
    """All proposal classes over one store read. Returns
    {"summary": {...}, "proposals": [...], "notes": [...]} — a pure READ."""
    rows = {t.id: t for t in store.takeaways()}
    firings = list(store.firings())
    sizes = metrics.batch_sizes(firings)
    by_row = defaultdict(list)
    for f in firings:
        by_row[f.takeaway_id].append(f)
    violations_by_row = defaultdict(list)
    for v in store.violations():
        violations_by_row[v.takeaway_id].append(v)

    notes = []
    proposals = (
        _tighten(rows, by_row, sizes)
        + _broaden(rows, violations_by_row, notes)
        + _migrate(rows, by_row, sizes)
        + _merge(rows, firings, notes)
        + _graduate(rows, by_row, firings)
        + _stale(rows, by_row, notes, git_files=git_files)
    )
    notes.append("semantic (θ) tighten proposals are `monition calibrate` "
                 "(B03) — run it separately; its apply stays parked")
    rated = [f for f in firings if f.outcome is not None]
    solo_noise = [f for f in rated if f.outcome == "noise"
                  and sizes.get(f.id, 1) < metrics.BATCH_MIN_SIZE]
    return {
        "summary": {
            "active_rows": sum(1 for t in rows.values()
                               if t.status == "active"),
            "rated_firings": len(rated),
            "solo_noise": len(solo_noise),
            "violations": sum(len(v) for v in violations_by_row.values()),
            "proposals": len(proposals),
        },
        "proposals": proposals,
        "notes": notes,
    }


_CLASS_ORDER = ("tighten", "broaden", "migrate", "merge", "graduate", "stale")


def render(result):
    """Human-readable proposal report. Every proposal shows its evidence and
    the exact consent command (or the human move) — never applies anything."""
    s = result["summary"]
    lines = [
        "monition propose — audit-cadence mutation proposals (read-only)",
        f"{s['active_rows']} active rows, {s['rated_firings']} rated firings "
        f"({s['solo_noise']} solo noise after batch discount), "
        f"{s['violations']} violations -> {s['proposals']} proposals",
    ]
    by_class = defaultdict(list)
    for p in result["proposals"]:
        by_class[p["class"]].append(p)
    for cls in _CLASS_ORDER:
        if not by_class[cls]:
            continue
        lines.append("")
        lines.append(f"{cls.upper()} ({len(by_class[cls])})")
        for p in by_class[cls]:
            lines.append(f"- t{p['takeaway_id']} "
                         f"\"{_excerpt(p['one_liner'], 70)}\"")
            for e in p["evidence"]:
                lines.append(f"    {e}")
            if p.get("apply"):
                lines.append(f"    apply: {p['apply']}")
    if result["notes"]:
        lines.append("")
        lines.append("notes:")
        lines.extend(f"- {n}" for n in result["notes"])
    return "\n".join(lines)
