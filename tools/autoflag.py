#!/usr/bin/env python3
"""Stop hook: deterministic backstop for the autoflagger.

Tier 1 is the agent itself — a CLAUDE.md rule has it self-flag flag-worthy moments
inline (the semantic judgment, free, with full context). This script is tier 2: a
mechanical net for moments the agent skips when context is crowded. It has two layers,
both LLM-free and deterministic:

  - a fixed **regex floor** — the unambiguous, keyword-detectable *admitted-error*
    class (the same pattern `mine-session` step 0b hunts); and
  - a **self-improving lexical layer** (`flag_corpus.py`) that scores the response
    against a corpus of known flag-worthy phrasings and fires on a strong match. The
    corpus is seeded from the regex patterns and grows at mine-time from the manual
    flags this layer missed, so its recall converges on the phrasings that recur.

Both append a flag to this session's file under `~/.claude/session-flags/<session_id>.md`
— the same per-session store `/flag` writes and `/mine-session` drains. This hook is
**read-only on the corpus**: all corpus mutation happens at mine-time (see
`flag_corpus.py`), never here, where concurrent sessions would clobber a shared file.

Three load-bearing properties, mirroring craft_reminder.py — fires at most once per
matched snippet (a backstop that repeats becomes noise), never blocks the stop, and
fails open (malformed input or any error exits silently; a bookmark has no business
stopping work). The lexical layer is an optional import: if it can't load, the regex
floor still fires.

Wire in .claude/settings.json:

    {"hooks": {"Stop": [{"hooks": [
        {"type": "command", "command": "python3 tools/autoflag.py"}]}]}}

(Path is relative to the project; use "$CLAUDE_PROJECT_DIR/tools/autoflag.py" if the
hook may run from another cwd.)
"""
import hashlib
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

# The lexical layer lives beside this script. Import is fail-open: a fork without it
# (or a load error) degrades to the regex floor, never an error in the Stop hook.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import flag_corpus
except Exception:
    flag_corpus = None

FLAGS_DIR = Path.home() / ".claude" / "session-flags"

# Admitted-error patterns — kept tight to avoid false positives. Each marks a moment
# mine-session step 0b would treat as a governance-change candidate.
PATTERNS = [
    r"\bI was wrong\b",
    r"\bI was mistaken\b",
    r"\bmy mistake\b",
    r"\bI should have (?:checked|verified|read|tested|looked|run)\b",
    r"\bI (?:asserted|claimed|said|stated|assumed)\b[^.]{0,60}\bwithout (?:verifying|checking|testing|reading)\b",
    r"\bI didn'?t (?:verify|check|test|read|run)\b",
    r"\bI (?:incorrectly|wrongly|falsely) (?:assumed|claimed|stated|said|reported)\b",
    r"\bturns out (?:I was|that was) (?:wrong|mistaken|incorrect)\b",
]
_RX = re.compile("|".join(PATTERNS), re.IGNORECASE)


def last_assistant_text(transcript_path):
    """Return the text of the final assistant message in the transcript, or ''."""
    text = ""
    try:
        with open(transcript_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if obj.get("type") != "assistant":
                    continue
                content = (obj.get("message") or {}).get("content")
                if isinstance(content, str):
                    text = content
                elif isinstance(content, list):
                    parts = [
                        b.get("text", "")
                        for b in content
                        if isinstance(b, dict) and b.get("type") == "text"
                    ]
                    if any(parts):
                        text = "\n".join(p for p in parts if p)
    except Exception:
        return ""
    return text


def matched_sentence(text, match):
    """The sentence containing the match, trimmed to a one-liner."""
    start = text.rfind(".", 0, match.start()) + 1
    end = text.find(".", match.end())
    end = len(text) if end == -1 else end + 1
    sentence = " ".join(text[start:end].split())
    return sentence[:160].rstrip()


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return  # fail open

    # Don't act on a stop the agent is already being forced to continue.
    if data.get("stop_hook_active"):
        return

    transcript = data.get("transcript_path")
    if not transcript:
        return

    text = last_assistant_text(transcript)
    if not text:
        return

    session = str(data.get("session_id", "unknown"))

    # Layer 1 — regex floor: the unambiguous admitted-error class.
    m = _RX.search(text)
    if m:
        _write_flag(session, "GOVERNANCE", matched_sentence(text, m),
                    "the response contained an admitted-error signal mine-session 0b "
                    "routes to a governance candidate")

    # Layer 2 — self-improving lexical match (optional, read-only on the corpus).
    if flag_corpus is not None:
        try:
            hit = flag_corpus.score_text(text)
        except Exception:
            hit = None
        if hit:
            _write_flag(session, hit["label"], hit["sentence"],
                        f"lexical match (score {hit['score']}) on the learned phrase "
                        f"{hit['phrase']!r}", layer="lexical")


def _write_flag(session, label, summary, reason, layer="regex"):
    """Append one auto-flag, deduped to once per (session, matched-snippet). Mirrors
    craft_reminder.py's /tmp-marker idiom; fails open on every step."""
    summary = " ".join((summary or "").split())[:160].rstrip()
    if not summary:
        return
    # Dedup key is the punctuation/case-collapsed snippet, so the regex and lexical
    # layers — which segment sentences differently (regex keeps the trailing '.', the
    # lexical splitter drops it) — land on the SAME marker when they catch one moment.
    # First writer wins; the regex floor runs first, so an admitted error stays one
    # GOVERNANCE flag rather than a GOVERNANCE + lexical pair.
    key = re.sub(r"[^a-z0-9]+", " ", summary.lower()).strip()
    digest = hashlib.sha1((session + key).encode("utf-8")).hexdigest()[:12]
    marker = Path("/tmp") / f"autoflag_{session}_{digest}"
    if marker.exists():
        return  # already flagged this snippet this session
    try:
        marker.touch()
    except Exception:
        pass  # if /tmp is unwritable we may double-flag; still better than silent loss

    entry = (
        f"\n## [{label}] Auto-flag ({layer}) — {summary}\n"
        f"> Auto-flagged by tools/autoflag.py (Stop-hook backstop): {reason}. "
        f"Verify it's real before acting on it.\n"
        f"> Flagged: {date.today().isoformat()}\n"
    )
    flags_file = FLAGS_DIR / f"{session}.md"
    try:
        FLAGS_DIR.mkdir(parents=True, exist_ok=True)
        with open(flags_file, "a", encoding="utf-8") as fh:
            fh.write(entry)
    except Exception:
        return  # fail open


if __name__ == "__main__":
    main()
