# confer — feedback log

Dated provenance of how the confer protocol evolved: what was ambiguous or misapplied,
and the correction. Consult when **revising** a rule. The distilled, firing form lives in
`SKILL.md` (`## Gotchas` and the body) — this is the audit trail, not loaded on every run.

- **2026-06-11** — Both sessions started at once and each initiated, producing two threads
  for one decision. Before initiating, check for an open `type: confer` thread on the same
  decision (match on topic, not filename). If a race still happens, the earlier-created
  file wins; the other initiator deletes its thread and replies on the survivor.
- **2026-06-12** — A listener watching for `awaiting: <its repo>` slept through the other
  side converging — it wrote `## Resolution` (`awaiting: none`) and archived the file, so
  the baton never flipped and the watched path vanished. Watch loops must treat
  `resolved`/`needs-user` and a file moved to archive as wake conditions, not just the
  baton flip and mtime.
- **2026-06-12** — A thread resolved on turn 1: the opener carried position + load-bearing
  reasons + "what would change my mind" + concrete questions, which let the listener write
  the resolution directly. The four-part opener does real convergence work; keep all four
  mandatory in Turn 1.
- **2026-06-12** — Sessions paused for a user steer before passing the baton only
  sometimes — nothing required it, so a watcher could infer "not my baton" and barge
  ahead. Made it a hard rule: a turn ending in a user question sets `awaiting: user` and
  holds the baton; the other side holds on `awaiting: user`. The explicit token replaces
  the fuzzy inference.
- **2026-06-12** — A watcher woke on the first mtime bump and acted on a turn whose body
  wasn't fully written. Fix: a turn is one atomic write with the baton flipped last; the
  reader gates on the baton *and* a complete turn body; a baton-without-body is re-read as
  a torn write, not answered.
- **2026-06-12** — Both sessions tried to close the same resolved thread — one wrote
  `## Resolution` while the other moved it to archive, duplicating frontmatter stamps.
  Close-out is a one-side action: stamp `archived:` only as part of the move, and if the
  file is already gone, the other side closed it — verify the resolution landed, don't
  re-stamp.
- **2026-06-12** — On waking, a fresh read returned a *stale* snapshot (no Turn N body
  though the other side had written one) — cached file-state, not a torn write. The re-read
  must *bypass the cache* (a shell `grep`/`sed`, or re-read after a beat); re-reading
  through the same stale view just re-confirms a turn that is actually there.
- **2026-06-13** — A listener's watch loop exited reporting "no thread arrived," but the
  thread landed in the gap between the loop's final check and its exit. Any listen/watch
  timeout must do one final fresh scan before declaring nothing arrived or parking.
- **2026-06-14** — A cross-fire: both sessions initiated threads on *different* but
  entangled decisions, so each held the other's baton on a thread the other wasn't
  watching. When a watch/listen times out or parks, do one scan for *any* `type: confer`,
  `status: open`, `awaiting: <this repo>` thread before going idle.
- **2026-06-19** — A listener nearly rebutted "your cited decision doc doesn't exist /
  contradicts the ratified record" — but the initiator's session was *writing those very
  docs concurrently* as it argued, so the doc appeared (and the apparent contradiction
  resolved into an audience split) minutes later. A cited authority that's absent, empty,
  or seemingly contradictory mid-confer may just be mid-write. Re-read after a beat before
  rebutting; treat a freshly-absent cited authority like a torn write, not proof the other
  side is wrong. (Generalizes the torn-write gotcha from the *turn body* to *cited
  evidence*.)
- **2026-06-19** — CMS resolved a thread (wrote `## Resolution`) but wrote "the other side
  may archive this" and left it in `handoffs/`, unarchived. It sat resolved-but-unarchived;
  the user reported the other session seemed to be "still waiting for a reply." Fix: the
  side that writes the Resolution archives it in the *same* close-out — punting the archive
  leaves the thread reading as open and the "who archives?" question unowned.
- **2026-07-02** — A scoped confer adviser (briefed to advise exactly one named
  counterparty) ran `--listen`, and its scan matched *any* `type: confer` +
  `awaiting: <it>` hit — it took the baton on a different project's thread instead of the
  one it was briefed for, because identity was inferred from `between:`/`awaiting:` string
  matching rather than a stable id. The user had to intervene mid-verification. This also
  exposed that "torn write" detection was a timing guess (wait ~2s, re-read), not a real
  check. **Fix:** threads now carry a stable `id:` minted once at creation (the real
  identity, independent of filename/`between:`); pinning, scoped listening, and
  mid-exchange handoffs all lock onto a given id instead of a name match. Turns commit via
  temp-file + atomic rename with a trailing `<!-- END TURN N -->` marker, so completeness
  is a deterministic check instead of a timed retry. (Interim mitigation before this
  landed: monition row 185, general reach.)
