---
name: handoff
description: Save a decision-ready handoff of the current session's context so a future cold-start session (here or in another project) resumes in seconds. Use when the user invokes /handoff [--goal <goal>], says "write a handoff", "save context for next time / the next session", or is wrapping up mid-task and wants the thread resumable.
---

# handoff

You are packaging this session's context for a future cold-start session. Governing
principle: **maximize completed reversible work; surface only the judgment.**

## Gotchas

- **Same goal → update the existing file, don't spawn a sibling.** Before writing,
  check both `$CMS_LANDING_ZONE/handoffs/` and the project's `handoffs/` for an
  existing file matching this project and goal. A second handoff for the same goal
  updates that file — two sibling files for the same goal create a split-brain that
  the next session has to reconcile.
- **"Done" ≠ "verified".** In the State section, a step is *done* when the code/change
  exists; it is *verified* only when it has been run and confirmed to behave correctly.
  Never conflate them — a cold-start session that inherits a false "verified" wastes its
  first round rediscovering the gap.

## Where it goes

Resolve in order:

0. **Project override** — if the current project's `CLAUDE.md` directs handoffs to a specific
   location (e.g. "`/handoff` writes to `handoffs/`"), honor it: project instructions win, and a
   project that keeps handoffs in-repo is a deliberate choice, not a misroute. Only when the
   project says nothing about handoff placement do the defaults below apply.
1. **`$CMS_LANDING_ZONE/handoffs/`** — if `CMS_LANDING_ZONE` is set, an absolute path to
   your cross-project store. Use this whenever it is reachable, regardless of which project
   the session is in.
2. **`<repo root>/handoffs/`** — per-project fallback when no landing zone is set (create
   the directory if missing).

Filename: `YYYY-MM-DD <project> <goal-slug>.md` (e.g. `2026-06-10 myapp auth-refactor`).
One file per goal — a second handoff for the same goal **updates the existing file**, never
spawns a sibling.

## What it contains

Frontmatter: `project:` (repo name) · `goal:` · `created:` · `status: open`. Then, lean —
every section earns its place, empty ones are dropped:

- **Goal** — what the next session is trying to achieve, one line. With `--goal <goal>`,
  scope the whole handoff to that goal; without it, cover the session's main thread.
- **State** — what's *done* vs what's *verified* (don't conflate them); what's in flight.
- **Next actions** — ordered; the first one concrete enough to start cold, no archaeology
  required.
- **Key context** — files touched (real paths), decisions made *with the why*, gotchas hit
  and their workarounds.
- **Open decision** — the one pending judgment, pre-packaged: options weighed, recommendation
  stated, so the next session decides in seconds. "None pending" is a legitimate entry.
- **Pointers** — paths to the roadmap, workstream docs, or reference nodes the next session
  should load. Nothing more.

## Lifecycle

- **Pick-up:** at the start of a session resuming this work, check `$CMS_LANDING_ZONE/handoffs/`
  (and the project's `handoffs/`) for `status: open` files matching the project and goal.
- **Consumption:** when a handoff has been absorbed and the work moved past it, metabolize
  any durable lesson out of it (via /codify or /mine-session), then **delete the file** — a
  handoff is session residue, not knowledge, and is never cited as evidence.
- **Staleness:** an `open` handoff past its horizon is a smell, and the horizon depends on
  the kind:
  - A **carry-forward** handoff (front-loading context for a session that hasn't started) is
    stale in **days** — untouched past that means the pick-up didn't happen on schedule.
  - A **bridge** handoff (between sessions on actively-moving work) is more patient (~2 weeks).
  - Resolutions — **a handoff is a transfer envelope, not a backlog**: the work died →
    delete; it quietly became a runbook → promote it to a durable doc in the project; the
    work is real but never started (or stalled past its horizon) → route the work into the
    target repo's `road.md`/`debt.md` (or equivalent) *with its context*, then delete the
    envelope; do the pick-up instead only when it is genuinely about to happen.

## Recent changes

- 2026-07-02 — envelope-not-backlog: un-started work routes to the target repo's
  road/debt, then the envelope is deleted (audit found the delete lifecycle unenforced).

Full dated log: [feedback.md](feedback.md).
