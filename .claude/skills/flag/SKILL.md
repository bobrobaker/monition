---
name: flag
description: Mid-session flag for mine-session — mark something worth capturing as a monition row, governance change, or postmortem candidate without breaking flow. Use when the user invokes /flag [note] [--label monition|governance|postmortem], says "flag this", "make a note of this for mine-session", or "this should be a monition". NOT for immediate codification (that's /codify).
---

# flag

You are capturing a mid-session observation so mine-session can act on it at wrap time.

**Pipeline:** you (tier 1, semantic judgment) and `autoflag.py` (tier 2 — a Stop-hook
backstop) both append to `~/.claude/session-flags/<id>.md`; `/mine-session` drains that
file at wrap and routes each entry. Tier 2 has two LLM-free layers: a fixed
admitted-error **regex floor**, and a **self-improving lexical matcher**
(`tools/flag_corpus.py`) that fires on a strong match to a corpus of known flag-worthy
phrasings and grows that corpus at mine-time from the manual flags it missed. The
statusline **⚑** widget counts this queue. (The ❖ widget is unrelated — that counts
monition firings, not /flag bookmarks.)

## What to do

1. **Parse the invocation.** The user may supply:
   - A note (free text describing what to flag)
   - `--label monition` — candidate trigger row
   - `--label governance` — candidate CLAUDE.md rule or always-on artifact
   - `--label postmortem` — warrants a full `/postmortem` analysis; the incident was large or costly
   - No label — general seed; mine-session decides routing

2. **If the note is thin or absent**, synthesize it from the immediate conversation context — what just happened that the user wants flagged? State what you're capturing and confirm it before writing.

3. **Append to this session's flag file** — `~/.claude/session-flags/$CLAUDE_CODE_SESSION_ID.md`. Flags are per-session so `/statusline` can count this session's flags and `/mine-session` can attribute them (it drains this session's file plus any from *dead* sessions, so nothing is orphaned — but never a live concurrent session's file). Run a bash append so the session id resolves from the env; fill `LABEL`, the summary, the note, and the date as literal text before running:
   ```bash
   d=~/.claude/session-flags; mkdir -p "$d"
   cat >> "$d/${CLAUDE_CODE_SESSION_ID:-unknown}.md" <<'EOF'
   ## [LABEL] <one-line summary>
   > <note or synthesized context>
   > Flagged: <ISO date>
   EOF
   ```
   Where `[LABEL]` is `MONITION`, `GOVERNANCE`, `POSTMORTEM`, or `GENERAL`. If `$CLAUDE_CODE_SESSION_ID` is unset the file falls back to `unknown.md`, which `/mine-session`'s directory sweep still drains.

4. **Confirm to the user** in one line: what was flagged and under which label. Don't interrupt flow — no headers, no summary sections.

## Anti-goals

- Don't route immediately to /codify or /postmortem unless the user explicitly asks — the flag is a lightweight bookmark, not an action.
- Don't ask clarifying questions if you can infer the intent from context.
