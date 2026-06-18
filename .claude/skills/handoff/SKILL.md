---
name: handoff
description: Save a decision-ready handoff of the current session's context — goal, state, next actions, key decisions with the why, the one open judgment — so a future cold-start session resumes in seconds. Use when the user invokes /handoff [--goal <goal>], says "write a handoff" / "save context for next time", or is wrapping up mid-task and wants the thread resumable.
---

# handoff

You are packaging this session's context for a future cold-start session. Governing
principle: **maximize completed reversible work; surface only the judgment.**

1. Write `handoffs/YYYY-MM-DD <goal-slug>.md` (create the dir if missing). One file
   per goal — a second handoff for the same goal **updates the existing file**, never
   spawns a sibling.
2. Frontmatter: `goal:` · `created:` · `status: open`. Sections, lean (drop empty
   ones):
   - **Goal** — one line.
   - **State** — what's *done* vs what's *verified*, never conflated; what's in flight.
   - **Next actions** — ordered; the first one concrete enough to start cold.
   - **Key context** — files touched, decisions made *with the why*, gotchas hit and
     their workarounds.
   - **Open decision** — the one pending judgment, pre-packaged: options weighed,
     recommendation stated. "None pending" is a legitimate entry.
   - **Pointers** — the docs the next session should load, nothing more.
3. Lifecycle (for the consuming session): when the work moves past a handoff,
   metabolize any durable lesson out of it (via /codify), then **delete the file** —
   a handoff is session residue, never knowledge. Open ≳2 weeks means it died (delete)
   or became a runbook (promote it).
