# 2026-06-17 · Storage backend: SQLite default, Dolt optional behind a seam

**Question.** The CMS forkable refactor makes monition ship out-of-the-box. Dolt is a
122 MB Go binary and the #1 adoption barrier for a forker. Does monition need Dolt?

**Evidence.** The code uses Dolt only as `sql` (read, `-r json`), `dump`, `add`/`commit`,
and `init` — a SQL store plus a git-committable text dump. Dolt's defining VCS features
(`diff`/`branch`/`merge`/`log`/`checkout` of data) are **never invoked**; "data history"
is a manual affordance already covered by git history of the committed `dump.sql`. Store
access is concentrated in `store.py` (reader), `store_write.py` (writer), `init_sync.py`
(init/schema); there is **no** storage-backend abstraction (`backends.py` is the replay
runner's agent-spawn seam, unrelated). The contract + schema are MySQL/Dolt-flavored.

**Decision (user-ratified 2026-06-17).** Introduce a storage-backend seam.
**SQLite (Python stdlib, zero install) becomes the default and the tested-first path.**
The existing Dolt code is retained as a working, selectable backend behind the seam —
kept functional "in case it later earns its cost" (real data diff/branch/merge), but not
the maintenance-priority path (the suite runs against SQLite; a thin conformance subset
guards the seam against Dolt).

**Options weighed.**
- *Keep Dolt only* — rejected: pays the #1 adoption barrier for VCS features the system
  doesn't use.
- *Migrate to SQLite only (drop Dolt)* — rejected: discards working machinery and the
  future option of real data version control.
- *SQLite default + Dolt optional behind a seam* — chosen: removes the barrier for
  forkers, preserves Dolt optionality.

**Cost accepted.** Building the seam is more work than a one-way migration (no seam exists
today); the existing Dolt code becomes the Dolt backend (wrapped). Schema must be
expressed for both engines (SQLite: `TEXT` + `CHECK` for enums); the contract doc and the
column-fingerprint validation in `store.py` become backend-parameterized. **Sized as its
own monition effort** — gates `bootstrap.sh` (drops the hard `dolt` probe; dolt becomes
optional) and publish.
