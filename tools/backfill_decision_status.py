#!/usr/bin/env python3
"""Backfill `status:` frontmatter onto legacy decision docs — assisted classification,
human-confirmed. A one-shot migration helper for the decision-status convention
(docs/decisions/README.md), for a repo that adopted the convention after it already had
decision docs.

Part of the managed vendored set: re-vendored into a fork by `./bootstrap.sh --update`.
Each fork runs it **once against its own `docs/**/decisions/` corpus** — it is repo-scoped
and never reaches across repos.

Never silently stamps. A false bare `status: decided` on a retired doc asserts "live" — the
exact failure the convention exists to prevent — so:
  * default run is a **dry-run worklist**: each unmarked doc, a *proposed* status, and the
    evidence behind the proposal. It writes nothing.
  * `--apply` opens a **per-item accept / skip / edit gate**; only an explicit accept writes.
  * any partial/whole supersession signal downgrades the proposal and surfaces the evidence
    so the human — not this script — makes the live-vs-dead call.

Idempotent: a doc that already has `status:` is never in the worklist, so re-running is a
no-op. Zero-dependency stdlib. Imports its vendored sibling `lint_skeleton` for the
single-source discovery predicate, frontmatter parse, and link resolution — it does not
reinvent them.
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lint_skeleton as ls  # noqa: E402  (sibling import after path setup)

# These two patterns are ADVISORY INPUT to the human gate, NOT a hardened parser of the
# decision-doc format. The banner grammar's single source of truth is docs/decisions/README.md
# ("Status frontmatter" / the supersession-banner convention); if it changes, that doc and
# `lint_skeleton.check_decision_status` own the change — this helper only *hints*.
# Verb STEMS, not full words: "supersedes"/"superseded"/"replaces"/"replaced by" all match.
SUPERSEDE_RE = re.compile(r"supersed|deprecat|obsolet|retir|replac", re.I)
# A doc-level supersession banner per docs/decisions/README.md:
#   > **Superseded by [<date> — <slug>](<file.md>)**
# The captured group is the successor link target → candidate `superseded_by:`.
BANNER_RE = re.compile(r"^>\s*\*\*\s*superseded by\s*\[[^\]]*\]\(([^)\s]+)\)", re.I | re.M)
# YYYY-MM-DD date prefix on a decision filename, for "is the linker later?" ordering.
DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def _date_key(path):
    """ISO date prefix of a decision filename (lexically sortable), or '' if undated."""
    m = DATE_RE.match(os.path.basename(path))
    return m.group(1) if m else ""


def decision_docs():
    """Every decision doc under the active root (shares `lint_skeleton.is_decision_doc`)."""
    return [p for p in ls.md_files() if os.path.exists(p) and ls.is_decision_doc(p)]


def _inbound_links(target, corpus):
    """Docs in `corpus` that contain a relative link resolving to `target`, paired with
    whether the linking line carries supersession vocabulary. Reuses the skeleton's
    fence-stripping + link regex so link resolution never forks from the linter's."""
    hits = []
    tgt = os.path.normpath(target)
    for src in corpus:
        if os.path.normpath(src) == tgt:
            continue
        with open(src, encoding="utf-8") as f:
            text = f.read()
        body = ls.strip_code(text)
        for m in ls.LINK_RE.finditer(body):
            url = m.group(1).split("#")[0]
            if not url or "://" in url or url.startswith("mailto:"):
                continue
            resolved = os.path.normpath(os.path.join(os.path.dirname(src), url))
            if resolved == tgt:
                line = body[body.rfind("\n", 0, m.start()) + 1: body.find("\n", m.end())]
                hits.append((src, bool(SUPERSEDE_RE.search(line))))
                break
    return hits


def _registry_signal(doc):
    """A retirement mention of this doc's filename in a verdict registry (DESIGN.md /
    road.md). Best-effort evidence only. NOTE: registry discovery is CMS-shaped — a fork whose
    verdict registry has another name gets *no* registry signal (a silent false-clean), so the
    `--apply` human gate ("confirm each against your registry"), not this scan, is the authority
    on supersession."""
    base = os.path.basename(doc)
    signals = []
    for reg in ("docs/DESIGN.md", "road.md", "docs/road.md"):
        path = os.path.join(ls.ROOT, reg)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            for line in f:
                if base in line and SUPERSEDE_RE.search(line):
                    signals.append(reg)
                    break
    return signals


def classify(doc, corpus):
    """Propose a `status:` for one unmarked decision doc, with the evidence behind it.

    Returns (proposed_status, superseded_by_or_None, needs_review, evidence_lines).
    Conservative ladder — only a *top-of-doc* (whole-doc) banner with a resolvable successor
    proposes `superseded`. A banner *deeper* in the body is a paragraph-level PARTIAL
    supersession per docs/decisions/README.md (the doc is still live for the rest), so it
    stays `decided` + review — proposing `superseded` there would assert the whole doc dead,
    the exact burn the convention prevents. Inbound later-links and registry hits flag for
    review but never auto-assert dead; nothing → `decided`.
    """
    with open(doc, encoding="utf-8") as f:
        text = f.read()
    body = re.sub(r"^---\n.*?\n---\n", "", text, flags=re.S)  # drop any frontmatter
    evidence = []
    needs_review = False

    banner = BANNER_RE.search(body)
    if banner:
        target = banner.group(1)
        resolved = os.path.exists(os.path.normpath(os.path.join(os.path.dirname(doc), target)))
        # Doc-level = the banner is the first real content (top of doc, per README). Anything
        # before it that isn't blank/heading means the banner is a paragraph-level partial.
        pre = [l for l in body[:banner.start()].splitlines()
               if l.strip() and not l.lstrip().startswith("#")]
        if resolved and not pre:
            evidence.append(f"doc-level (top) supersession banner → {target}")
            return "superseded", target, False, evidence
        if not resolved:
            evidence.append(f"banner target {target} does not resolve — review")
        else:
            evidence.append(f"inline (partial?) supersession banner → {target}; "
                            "whole-vs-part is the human's call")
        needs_review = True

    later_links = [src for src, sup in _inbound_links(doc, corpus)
                   if sup and _date_key(src) > _date_key(doc)]
    if later_links:
        rels = ", ".join(os.path.relpath(s, ls.ROOT) for s in later_links)
        evidence.append(f"later doc(s) link here with retirement language: {rels}")
        needs_review = True

    reg = _registry_signal(doc)
    if reg:
        evidence.append(f"retirement mention in registry: {', '.join(reg)}")
        needs_review = True

    if not evidence:
        evidence.append("no supersession signal — default to decided")
    return "decided", None, needs_review, evidence


def with_status(text, status, superseded_by=None):
    """Return `text` with `status:` (and `superseded_by:`) inserted into its frontmatter,
    creating a frontmatter block if none exists. Does not disturb existing keys."""
    keys = [f"status: {status}"]
    if superseded_by:
        keys.append(f"superseded_by: {superseded_by}")
    block = "\n".join(keys)
    m = ls._FM_RE.match(text)
    if m:
        return f"---\n{m.group(1)}\n{block}\n---\n" + text[m.end():]
    return f"---\n{block}\n---\n{text}"


def build_worklist():
    """Unmarked decision docs with their proposals. Empty when the repo is fully marked."""
    corpus = decision_docs()
    work = []
    for doc in sorted(corpus):
        with open(doc, encoding="utf-8") as f:
            text = f.read()
        if ls._frontmatter(text).get("status"):
            continue  # already marked → idempotent skip
        status, sup, review, evidence = classify(doc, corpus)
        work.append((doc, status, sup, review, evidence))
    return work


def _render(item):
    doc, status, sup, review, evidence = item
    rel = os.path.relpath(doc, ls.ROOT)
    head = f"status: {status}" + (f"  superseded_by: {sup}" if sup else "")
    flag = "  ⚠ REVIEW" if review else ""
    lines = [f"{rel}", f"  proposed: {head}{flag}"]
    lines += [f"    · {e}" for e in evidence]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true",
                    help="open the per-item accept/skip/edit gate and write accepted status (default: dry-run)")
    ap.add_argument("--root", help="repo root to operate on (default: this tool's repo)")
    args = ap.parse_args(argv)

    saved_root = ls.ROOT
    if args.root:
        ls.ROOT = os.path.abspath(args.root)
    try:
        return _run(args)
    finally:
        ls.ROOT = saved_root  # never leave the vendored module's global clobbered


def _run(args):
    work = build_worklist()
    if not work:
        print("All decision docs already carry `status:` — nothing to backfill.")
        return 0

    print(f"{len(work)} unmarked decision doc(s):\n")
    for item in work:
        print(_render(item))
        print()

    if not args.apply:
        print("Dry run. Re-run with --apply to confirm and write (per-item gate).")
        return 0

    print("--apply: confirm each against your registry. [a]ccept / [s]kip / "
          "type 'decided' or 'superseded <file.md>' to edit.\n")
    written = []
    for doc, status, sup, _review, _ev in work:
        rel = os.path.relpath(doc, ls.ROOT)
        ans = input(f"{rel} → {status}{(' ' + sup) if sup else ''} : ").strip()
        if ans in ("", "a", "accept"):
            pass
        elif ans in ("s", "skip"):
            print("  skipped"); continue
        elif ans.startswith("decided"):
            status, sup = "decided", None
        elif ans.startswith("superseded"):
            parts = ans.split(None, 1)
            if len(parts) != 2:
                print("  'superseded' needs a successor file — skipped"); continue
            status, sup = "superseded", parts[1].strip()
        else:
            print("  unrecognized — skipped"); continue
        # Validate BEFORE writing (B-2): a bad `superseded_by:` must never reach disk, so a
        # non-zero exit can't lie about on-disk state. Pure check — no module-global channel.
        if status == "superseded":
            msg = ls.validate_superseded_target(doc, sup)
            if msg:
                print(f"  {msg} — not written"); continue
        with open(doc, encoding="utf-8") as f:
            text = f.read()
        with open(doc, "w", encoding="utf-8") as f:
            f.write(with_status(text, status, sup))
        written.append(doc)
        print(f"  wrote status: {status}" + (f"  superseded_by: {sup}" if sup else ""))

    if not written:
        print("\nNothing written.")
        return 0
    print(f"\n{len(written)} doc(s) written (each validated before write); "
          "decision-status convention holds.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
