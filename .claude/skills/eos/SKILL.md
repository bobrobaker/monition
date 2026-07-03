---
name: eos
description: End-of-session closeout — run the three wrap-up steps in order: mine the session for takeaways, archive the session, then commit the work. Use when the user invokes /eos, says "close out" / "end of session" / "wrap up for the day", or otherwise signals the session is done.
---

# eos — end-of-session closeout

First, one hygiene glance — two cheap checks, each at most one printed line, never
blocking and never acted on without a yes:

- **Housekeep staleness** — read the stamp `/housekeep` writes on completion:
  ```bash
  f="${XDG_STATE_HOME:-$HOME/.local/state}/cms/housekeep.last"
  if [ -f "$f" ]; then a=$(( ( $(date +%s) - $(stat -c %Y "$f") ) / 86400 ));
    [ "$a" -ge 2 ] && echo "housekeep last ran ${a}d ago"
  else echo "housekeep: no run recorded"; fi
  ```
  If it prints, suggest a `/housekeep` (morning cadence) in one line — don't run it.
- **Handoff consume-check** — if this session picked up, consumed, or resolved a
  handoff doc, close its lifecycle now (delete it, or archive with a stamp per
  `handoff/SKILL.md`); a consumed handoff left `status: open` is exactly the pile the
  consume-then-delete rule exists to prevent. Skip silently if none was touched.

Then run these three in order, pausing between each — don't batch them, since each can
change what the next one sees. If a step surfaces something needing the user's call,
stop there and ask.

1. **Mine** — invoke the `mine-session` skill. Capture reusable takeaways while the
   session context is still fresh (this can write to the takeaway store).
2. **Wrap** — invoke the `wrap-session` skill to archive a findable session summary.
3. **Commit** — stage and commit this session's work. Review `git status` first and
   stage this session's files explicitly — `git add -A` only after confirming nothing
   foreign is present (a concurrent session's artifacts or stray untracked files
   sweep in silently). Push if the repo's workflow expects it. Propose a message;
   include anything steps 1–2 wrote, so the session archive lands in the commit.
