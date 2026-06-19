# 2026-06-18 · Backend: Dolt is the default for *our own* hub; SQLite stays for external/standalone

**This is the active source of truth for "which storage backend."** It amends
[2026-06-17 · Storage backend: SQLite default](2026-06-17-storage-backend-sqlite-default.md)
— that decision's *external/forker-facing* half stands; its "SQLite is also **our**
default" half is overridden here. Confirms the v6 charter's call #2.

**Question.** The single-store hub model
([2026-06-18 single-store scoping](2026-06-18-single-store-general-project-scoping.md))
collapses our per-repo stores into one CMS-managed hub. The 2026-06-17 decision made
SQLite the default because Dolt's VCS features were unused and the 122 MB binary is the
#1 *forker* adoption barrier. The hub reverses the first premise for us. So: which
backend do **we** run for our own hub?

**Decision (user-ratified 2026-06-18).** Two audiences, two defaults:

- **For us (our own hub): the default is Dolt.** SQLite is **no longer under
  consideration for our own situation.** We build **Dolt-only first** for ourselves —
  the v6 hub is a Dolt database; the fold ([B04](../workstreams/v6-single-hub/buckets/B04_fold-verb.md))
  is Dolt→Dolt.
- **For external / standalone hosts: SQLite stays the recommended default.** The
  forker-adoption-barrier reasoning is unchanged for people who won't install dolt;
  `monition init` still defaults to SQLite, and the SQLite backend stays a tested,
  selectable path. Whether to invest further in SQLite-for-others is **revisited later
  if real demand appears** — not now.

**Why.** The hub model restores Dolt's value *for us*: native data version-control
(diff/branch/merge/log of the data itself) supersedes the manual `dump.sql` + git
workaround the 2026-06-17 decision leaned on, and the multi-repo / eventual multi-writer
future rides the Dolt-server seam. None of that helps a single-repo forker, so the
adoption-barrier argument — and hence SQLite-for-external — survives untouched. Splitting
by audience keeps both true instead of flip-flopping a single global default.

**Consequences.**
- B04 builds Dolt→Dolt only; no cross-backend fold path. SQLite in-place v5→v6 migration
  stays deferred (no such store exists).
- We operate the hub via `MONITION_STORE` → a Dolt store; CMS owns the hub path +
  lifecycle (see the hub-path confer, 2026-06-18).
- The `storage_backends.py` seam stays — both backends remain real; this is an operating
  *default*, not a removal of SQLite.

**Flip-flop note.** SQLite-default (2026-06-17) → Dolt-for-us (here) is a reversal of the
*our-own* default within a day. It is principled (the hub changed the premise), but the
churn itself is flagged for `/postmortem` per the v6 charter.
