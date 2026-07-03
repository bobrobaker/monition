---
name: wrap-session
description: Wrap a session into the global session archive so a half-remembered future query ("I remember working on X") can be found. Live mode summarizes the current context; backfill mode (<session-id>) reads a past transcript. Use when the user invokes /wrap-session [session-id], says "wrap this session" / "archive this session" / "backfill session <id>", or is ending a session worth being able to find again. NOT for a decision-ready resume of in-flight work (that's /handoff).
---

# wrap-session

Two modes depending on whether an argument was passed:

**Live mode** (no argument): you are wrapping the current session. Governing
principle: **summarize only from what is already in your context window.** The
prompt cache is warm; re-reading the transcript spends tokens to re-derive what
you already hold.

**Backfill mode** (`/wrap-session <session-id-or-path>`): the live window was
missed; wrap from the transcript instead. Quality will be lower than a live wrap
(compacted content is unrecoverable; only text turns survive extraction). Use for
important missed sessions, not every drive-by.

Two writes — the rich summary file (rung 2 of the disclosure ladder) and the
one-line index entry in `sessions.md` (rung 1). **Fail open:** if a step's input
is missing, write what you can. An index line with no token counts still beats no
trace.

**Capture tooling lives globally**, not in the current repo: the helpers below
(`session_tokens.py`, `extract_session.py`) operate on the global archive, so they
resolve through the dotfile anchor `~/.claude/cms/tools/` (a symlink to the canonical
CMS clone, created by `bootstrap --link-global`). Below, **`<tools>`** means the first
of `~/.claude/cms/tools/` or `$CLAUDE_PROJECT_DIR/tools/` that exists — the latter only
when you are working inside the CMS clone itself and never linked.

1. **Identify the session and establish the content source.**

   *Live mode:* Get the session marker and provisional token line from the
   session-token helper in `--print` mode. Find it at
   `<tools>/session_tokens.py` and run `python3 <path> --print`.
   It prints a `<!-- session: <id> -->` marker and a `tokens:` line. This
   session's id is `$CLAUDE_CODE_SESSION_ID` (the harness sets it per session) —
   the source of truth, because newest-by-mtime misidentifies the session when
   another runs in the same cwd concurrently. If neither helper path exists, take
   the marker id from `$CLAUDE_CODE_SESSION_ID` (fall back to the newest
   `~/.claude/projects/<cwd-slug>/<id>.jsonl`) and skip the counts. Content source
   is the context window — do not re-read the transcript.

   *Backfill mode:* The argument is either a session ID or a `.jsonl` path.
   - If it looks like a path: use it directly; session ID is the filename stem.
   - If it looks like an ID: `find ~/.claude/projects -name "<id>.jsonl" 2>/dev/null | head -1`
     to locate the transcript.
   - Run `python3 <tools>/extract_session.py <jsonl-path> --cap 40000`
     and read its output — this is your content source instead of the context window.
   - There is no live `tokens:` line to write; the SessionEnd hook already wrote
     one in the floor entry. Preserve it when updating the index entry in step 3.

2. **Write the summary file** to
   `~/.claude/logs/sessions/<YYYY-MM-DD>-<project>-<session-id>.md` (create the
   `sessions/` directory if missing; `<project>` is the cwd basename, spaces and
   slashes collapsed to `-`). Lean, prose-rich, embedding-friendly — a snapshot of
   this session as it ended, not maintained afterward:

   ```
   ---
   date: <YYYY-MM-DD>
   project: <project>
   session: <session-id>
   source: wrap-session
   title: >-
     <one line — what this session was about>
   abstract: >-
     <1–2 sentences of prose — the embed-text a semantic search vectorises:
     what this session was about, named so a half-memory matches it>
   files:
     - <one absolute path per line; omit the whole key if none — see below>
   ---

   **Did:** 2–5 bullets — what was built, changed, decided, or figured out.
   **Decisions:** the load-bearing calls, each with a one-clause why (omit if none).
   **Artifacts:** files, paths, commands, PRs touched (omit if none).
   **Open / next:** unfinished threads, or "none".
   ```

   The folded scalars (`>-`) keep free-text titles/abstracts valid YAML without
   escaping; `source: wrap-session` applies in both modes — you ran the skill
   explicitly. *Live mode:* write from context you still hold; do not re-read the
   transcript or files — if a detail has fallen out of context, say so rather than
   re-fetching it. *Backfill mode:* write from the extracted trace you read in
   step 1. The summary is a point-in-time snapshot; a reader treats its claims as
   true *as of that date*, not now.

   **The `files:` list is the staleness-capture signal** — the files this session
   changed, so a later retrieval can warn that the summary may be stale if they
   have moved since. Unlike the prose, get it *deterministically*, not from
   memory: run the trace extractor in `--files` mode over this session's
   transcript. Find it at `<tools>/extract_session.py` and run
   `python3 <path> --files ~/.claude/projects/<cwd-slug>/<session-id>.jsonl`. Paste its output
   under `files:` as a YAML list (one `  - <path>` per line), keeping `files:` the
   last frontmatter key. Fail open: if the extractor errors or lists nothing, omit
   the `files:` key — retrieval just skips the staleness check. This reads the
   transcript mechanically (like the token helper); it is not re-summarising.

   **A summary file may already exist for this session** — a `source: backfill`
   stub the corpus seeder wrote before you wrapped. A live wrap supersedes it: read
   the existing file (the Write guard requires a prior read), then overwrite with
   your `source: wrap-session` version. Wrap always wins over backfill. If the file
   is already `source: wrap-session`, you have wrapped before — overwrite with this
   fresher one.

3. **Write the index entry** in `~/.claude/logs/sessions.md`. First check whether
   the file already contains this session's `<!-- session: <session-id> -->`
   marker — a backfill pass or the SessionEnd floor may already have written one.
   **If the marker exists, update that entry in place:** replace its `## …` title
   line with your title and ensure a `summary:` pointer line sits under the marker.
   Do not append a second entry for the same session. Only if no marker exists,
   **append** a fresh entry (newest entry last):

   ```
   ## <YYYY-MM-DD> · <project> · <title>

   <!-- session: <session-id> -->
   summary: sessions/<YYYY-MM-DD>-<project>-<session-id>.md
   ```

   Keep the marker line exactly as `--print` emitted it: the SessionEnd hook finds
   it to insert the final `tokens:` line beneath it. The `## …` header *is* the
   index line — its title is what a fuzzy search reads first, so make it specific
   ("session-archive trace extractor", not "CMS work").
