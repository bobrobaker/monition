#!/usr/bin/env python3
"""Self-improving lexical layer for the flag backstop.

The regex tier in `autoflag.py` catches a fixed set of admitted-error phrasings.
This module adds a *learned* layer: it scores each sentence of a response against
a growing corpus of known flag-worthy phrasings (IDF-weighted whole-sentence
Jaccard) and fires when the best match clears a conservative threshold. The corpus
is DATA — seeded from the regex patterns, grown at mine-time from the manual flags
the matcher missed, and tightened by demeriting the entries that mis-fire — so it
converges on the phrasings that actually recur for this author.

Two hard rules, mirroring `autoflag.py` / `craft_reminder.py`:

  - **The Stop-hook path is READ-ONLY on the corpus.** Every mutation (add / credit
    / demerit) happens at mine-time, single-session — never from the hot hook path,
    where concurrent sessions would clobber a machine-global file (the per-session
    keying rule, applied to a shared resource: don't write it from the many).
  - **Fail open everywhere.** A missing or corrupt corpus yields no hit, never an
    exception — a backstop has no business raising into a Stop hook.

Storage: the live corpus is machine-local at `~/.claude/flag-corpus.json` (personal
accumulation, like `session-flags/`); the shipped seed (`flag_corpus_seed.json`,
beside this file) is the read-only floor a fork inherits. `score()` reads
live-or-seed; the mutators write live, materializing it from the seed on first write
so the seed entries carry forward.

CLI (all mine-time):
    flag_corpus.py score "<response text>"      # read-only; prints the hit or nothing
    flag_corpus.py add "<phrase>" <LABEL>       # grow recall from a miss
    flag_corpus.py credit "<phrase>"            # a fire that became a real lesson
    flag_corpus.py demerit "<phrase>"           # a fire that was noise
    flag_corpus.py list                         # dump entries + stats
"""
import argparse
import json
import math
import os
import re
import sys
from pathlib import Path

LIVE_CORPUS = Path.home() / ".claude" / "flag-corpus.json"
SEED_CORPUS = Path(__file__).resolve().parent / "flag_corpus_seed.json"

THRESHOLD = 0.4        # conservative: bias to precision; recall ramps as the corpus grows
MIN_TOKENS = 3         # a sentence thinner than this can't carry a reliable signal
WEIGHT_FLOOR = 0.2     # an entry at/under this is effectively pruned — it stops firing
LABELS = ("MONITION", "GOVERNANCE", "POSTMORTEM", "GENERAL")

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_SENT_SPLIT = re.compile(r"[.!?\n]+")


def _tokens(text):
    return set(_TOKEN_RE.findall(text.lower()))


def _sentences(text):
    return [s.strip() for s in _SENT_SPLIT.split(text) if s.strip()]


def _read(path):
    """Parse a corpus file, or None if absent/corrupt/wrong-shape (fail-open)."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and isinstance(data.get("entries"), list):
            return data
    except (OSError, ValueError):
        pass
    return None


def load_corpus():
    """Live corpus if present, else the shipped seed, else empty. Read path."""
    return _read(LIVE_CORPUS) or _read(SEED_CORPUS) or {"version": 1, "entries": []}


def _materialize():
    """Live corpus for mutation — seeded from the shipped seed on first write so the
    floor entries carry into the growing corpus."""
    return _read(LIVE_CORPUS) or _read(SEED_CORPUS) or {"version": 1, "entries": []}


def _idf_fn(entries):
    """Smoothed IDF over corpus phrases as documents. Smoothing (sklearn-style
    +1/+1) keeps every weight positive and stable for the tiny seed corpus, and
    gives an unseen query token the maximum weight so a sentence full of novel
    vocabulary scores low rather than undefined."""
    n = len(entries)
    df = {}
    for e in entries:
        for t in _tokens(e["phrase"]):
            df[t] = df.get(t, 0) + 1
    return lambda t: math.log((n + 1) / (df.get(t, 0) + 1)) + 1.0


def _weighted_jaccard(a, b, idf):
    union = a | b
    if not union:
        return 0.0
    den = sum(idf(t) for t in union)
    if not den:
        return 0.0
    return sum(idf(t) for t in (a & b)) / den


def score_text(text, corpus=None, threshold=THRESHOLD):
    """Best flag-worthy match for `text`, or None.

    Read-only and fail-open: any internal error returns None. Returns a dict
    {phrase, label, score, sentence} for the single highest-scoring (sentence,
    entry) pair at or above `threshold`.
    """
    try:
        corpus = corpus if corpus is not None else load_corpus()
        entries = corpus.get("entries") or []
        if not entries:
            return None
        idf = _idf_fn(entries)
        prepared = [(e, _tokens(e["phrase"]), float(e.get("weight", 1.0)))
                    for e in entries]
        best = None
        for sent in _sentences(text):
            st = _tokens(sent)
            if len(st) < MIN_TOKENS:
                continue
            for e, et, w in prepared:
                if w < WEIGHT_FLOOR:
                    continue  # pruned: mostly-noise, stops firing
                sim = _weighted_jaccard(st, et, idf) * w
                if sim >= threshold and (best is None or sim > best["score"]):
                    best = {
                        "phrase": e["phrase"],
                        "label": e.get("label", "GENERAL"),
                        "score": round(sim, 4),
                        "sentence": sent[:200],
                    }
        return best
    except Exception:
        return None


# --- mutators (mine-time only) ----------------------------------------------

def _save_live(corpus):
    """Atomic write to the live corpus (tmp + os.replace). Concurrent mines are
    rare (end-of-session, not per-response), and the rename is atomic, so the worst
    case is a lost increment, never a corrupt file."""
    LIVE_CORPUS.parent.mkdir(parents=True, exist_ok=True)
    tmp = LIVE_CORPUS.with_name(LIVE_CORPUS.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(corpus, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, LIVE_CORPUS)


def _reweight(e):
    """weight = 1 - noise / (helpful + noise + 1): an entry whose fires are mostly
    noise sinks toward the floor and stops firing; a mostly-helpful one stays high."""
    helpful, noise = int(e.get("helpful", 0)), int(e.get("noise", 0))
    e["weight"] = round(max(0.0, 1.0 - noise / (helpful + noise + 1)), 4)


def _norm(phrase):
    return " ".join(phrase.split()).strip()


def add(phrase, label):
    phrase = _norm(phrase)
    if not phrase:
        return "empty phrase — skipped"
    if label not in LABELS:
        return f"invalid label {label!r} (expected one of {', '.join(LABELS)})"
    corpus = _materialize()
    if any(e["phrase"].lower() == phrase.lower() for e in corpus["entries"]):
        return f"already present: {phrase!r}"
    corpus["entries"].append(
        {"phrase": phrase, "label": label, "helpful": 0, "noise": 0, "weight": 1.0})
    _save_live(corpus)
    return f"added [{label}] {phrase!r} ({len(corpus['entries'])} entries)"


def _adjust(phrase, field):
    norm = _norm(phrase).lower()
    corpus = _materialize()
    for e in corpus["entries"]:
        if e["phrase"].lower() == norm:
            e[field] = int(e.get(field, 0)) + 1
            _reweight(e)
            _save_live(corpus)
            state = "pruned" if e["weight"] < WEIGHT_FLOOR else "ok"
            return f"{field} +1 on {phrase!r} → weight {e['weight']} ({state})"
    return f"no corpus entry matches {phrase!r}"


def credit(phrase):
    """A lexical fire that became a real lesson — reinforces the entry."""
    return _adjust(phrase, "helpful")


def demerit(phrase):
    """A lexical fire that was noise — decays the entry toward the floor."""
    return _adjust(phrase, "noise")


# --- CLI --------------------------------------------------------------------

def _cli(argv=None):
    p = argparse.ArgumentParser(description="self-improving lexical flag matcher")
    sub = p.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("score", help="read-only: print the best match for text")
    sp.add_argument("text")
    sp.add_argument("--threshold", type=float, default=THRESHOLD)
    ap = sub.add_parser("add", help="grow recall from a missed manual flag")
    ap.add_argument("phrase")
    ap.add_argument("label", choices=LABELS)
    cp = sub.add_parser("credit", help="reinforce an entry whose fire was useful")
    cp.add_argument("phrase")
    dp = sub.add_parser("demerit", help="decay an entry whose fire was noise")
    dp.add_argument("phrase")
    sub.add_parser("list", help="dump corpus entries + stats")
    args = p.parse_args(argv)

    if args.cmd == "score":
        hit = score_text(args.text, threshold=args.threshold)
        print(json.dumps(hit) if hit else "")
    elif args.cmd == "add":
        print(add(args.phrase, args.label))
    elif args.cmd == "credit":
        print(credit(args.phrase))
    elif args.cmd == "demerit":
        print(demerit(args.phrase))
    elif args.cmd == "list":
        for e in load_corpus().get("entries", []):
            print(f"[{e.get('label','?')}] w={e.get('weight',1.0):<5} "
                  f"h={e.get('helpful',0)} n={e.get('noise',0)}  {e['phrase']!r}")


if __name__ == "__main__":
    _cli()
