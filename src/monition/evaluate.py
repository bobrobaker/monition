"""Offline session evaluator — the recall column (Phase 6).

For every firing-eligible row that carries a violation signature, classify one
session into the three observable confusion-matrix cells:

  fired∧avoided   — the row fired, the failure never appeared
  fired∧hit       — the row fired AND the failure appeared anyway
  not-fired∧hit   — the failure appeared and the row never fired (the
                    false-negative cell ratings structurally cannot produce)

Only the third cell is persisted (a `violations` row, idempotent per
takeaway×session); the other two are derivable at read time from `firings`
plus a re-run (contract §Violation semantics).

Runs at mine time — inside the mine-session rating pass, where the transcript
is warm and a human is already reviewing the worklist — never on the blocking
hook path. Fail-open per row: an unparseable spec, unknown kind, or broken
pattern skips that row with a note and evaluates the rest.
"""
import json
import os
import re

from .store_write import SIGNATURE_KINDS

# Contract §Violation signatures: transcript_regex matches with these flags.
SIGNATURE_FLAGS = re.IGNORECASE | re.MULTILINE

# Bounded context around the match, each side — enough for a human to judge
# the event real during the rating pass without re-opening the transcript.
EXCERPT_CONTEXT_CHARS = 300


def _string_leaves(node, out):
    if isinstance(node, str):
        out.append(node)
    elif isinstance(node, dict):
        for v in node.values():
            _string_leaves(v, out)
    elif isinstance(node, list):
        for v in node:
            _string_leaves(v, out)


def extract_transcript_text(path):
    """Matchable text of a session transcript.

    A JSONL line contributes every string leaf (message text, tool inputs,
    tool results — the places a failure event actually shows up), newline-
    joined; signatures never see the raw JSON framing, whose escaping would
    break patterns. A non-JSON line contributes itself verbatim, so a plain-
    text transcript degrades gracefully.
    """
    chunks = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                node = json.loads(line)
            except ValueError:
                chunks.append(line)
                continue
            _string_leaves(node, chunks)
    return "\n".join(chunks)


def evaluate_session(store, transcript_path, session_id, repo=None):
    """Classify `session_id` against every signature-bearing row; persist
    not-fired∧hit events through `store.log_violation` (the single write
    path). Returns the report dict `render_report` formats."""
    text = extract_transcript_text(transcript_path)
    fired = {f.takeaway_id for f in store.firings()
             if f.session_id == session_id}
    report = {"session": session_id, "rows": 0, "fired_avoided": [],
              "fired_hit": [], "not_fired_hit": [], "skipped": []}
    for t in store.takeaways():
        if not (t.firing_eligible and t.violation_signature):
            continue
        # Same reach semantics as the matchers: a project row from another
        # repo is not this session's business; missing repo context fails open.
        if repo and t.reach == "project" and t.origin_repo and t.origin_repo != repo:
            continue
        report["rows"] += 1
        try:
            spec = json.loads(t.violation_signature)
            kind = spec.get("kind") if isinstance(spec, dict) else None
            if kind != "transcript_regex":
                report["skipped"].append(
                    (t.id, f"unknown signature kind {kind!r} "
                           f"(this monition runs: {', '.join(SIGNATURE_KINDS)})"))
                continue
            m = re.search(spec["pattern"], text, SIGNATURE_FLAGS)
        except Exception as e:  # fail-open per row, never per run
            report["skipped"].append((t.id, f"broken signature: {e}"))
            continue
        if m is None:
            if t.id in fired:
                report["fired_avoided"].append(t.id)
            continue
        lo = max(0, m.start() - EXCERPT_CONTEXT_CHARS)
        excerpt = text[lo:m.end() + EXCERPT_CONTEXT_CHARS]
        if t.id in fired:
            report["fired_hit"].append(t.id)
        else:
            out = store.log_violation(t.id, session_id, evidence=excerpt,
                                      repo=repo)
            report["not_fired_hit"].append((t.id, out))
    return report


def render_report(report):
    lines = [
        f"evaluated {report['rows']} signature-bearing row(s) against "
        f"session {report['session']}",
        f"  fired∧avoided: {len(report['fired_avoided'])}"
        + (f"  ({', '.join(f't{i}' for i in report['fired_avoided'])})"
           if report["fired_avoided"] else ""),
    ]
    if report["fired_hit"]:
        lines.append(
            f"  fired∧hit:     {len(report['fired_hit'])}  "
            f"({', '.join(f't{i}' for i in report['fired_hit'])}) — fired but "
            "the failure still appeared; payload may need work")
    else:
        lines.append("  fired∧hit:     0")
    if report["not_fired_hit"]:
        lines.append(
            f"  not-fired∧hit: {len(report['not_fired_hit'])} — the "
            "trigger-broadening signal:")
        for tid, out in report["not_fired_hit"]:
            lines.append(f"    t{tid} → {out}")
    else:
        lines.append("  not-fired∧hit: 0")
    for tid, why in report["skipped"]:
        lines.append(f"  skipped t{tid}: {why}")
    return "\n".join(lines)


def default_session_id(transcript_path):
    """Harness transcripts are `<session-id>.jsonl`; the filename stem is the
    id when the caller doesn't pass one explicitly."""
    return os.path.splitext(os.path.basename(transcript_path))[0]
