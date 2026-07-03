---
status: decided
---
# 2026-06-19 · `dolt sql-server` write-path seam (concurrent-write contention fix)

**Status.** Built 2026-06-19. `src/monition/dolt_server.py` (lifecycle),
`DoltBackend.execute_sql`/`describe` call `ensure_running` before each `dolt sql -q`,
CLI verbs `sql-server-status`/`sql-server-stop`, tests in `tests/test_dolt_server.py`.
Opt-in fork ratified by the user this session. Roadmap verdict: `docs/road.md §2`.

**Question.** Concurrent firing writes to the single Dolt hub are lost. Verified cold:
10 concurrent `dolt sql -q "INSERT INTO firings …"` → **2 succeed, 8 fail** with
`cannot update manifest: database is read only`. File-based Dolt serializes writes
behind a one-writer manifest lock; each `dolt sql -q` is a separate process that grabs
it, so concurrent writers bounce. Fail-open (hooks wrap `fire` in try/except) makes this
*lossy, not corrupting* — but firings are the eval substrate, so loss degrades the signal
capture exists to collect, and the author runs routinely-many concurrent sessions on the
live hub. How should monition make these writes safe?

**The finding that shrank the fix.** The incoming handoff anticipated a MySQL client
(pymysql), rewriting `execute_sql`/`describe`/`snapshot` to speak MySQL, plus an interim
bounded retry-on-lock. An empirical check overturned all of it: **when a `dolt sql-server`
is running on the store, the dolt CLI auto-detects it (via `.dolt/sql-server.info`,
`PID:PORT:UUID`) and routes every `dolt sql -q` through it** — verified 10/10 concurrent
subprocess writes land with a server up, even on a non-default port never passed to the
client. So the existing subprocess path becomes contention-free the moment a server runs:
**no MySQL client, no execute_sql rewrite, no retry-on-lock.** The whole fix is "ensure a
server is running."

**Decision.** A lifecycle module `dolt_server.py` whose job is to ensure a
`dolt sql-server` is *accepting* on the store; `DoltBackend` calls `ensure_running` before
each `dolt sql -q`. Mechanics that earned their place, each from a reproduced failure:
- **Gate `describe` too, not just `execute_sql`.** `describe` swallows errors into `[]`,
  so a describe racing a concurrent spawn (store lock held, server not yet accepting) reads
  as "table missing" and fails schema validation with `missing required table 'decisions'`.
  Every `dolt sql -q` subprocess must wait for the server. (Reproduced; the original
  execute_sql-only gating was ~1/5 flaky.)
- **`running()` requires *accepting* (open port), not just a live PID.** A server that has
  bound the lock but isn't listening would let a racing call fall through to direct access
  and hit the read-only lock.
- **Serialize the spawn with a `flock`.** A thundering herd of `dolt sql-server` spawns on
  one port churns the `.info` file (losers write-then-remove it); only the lock holder
  spawns, the rest block then return once it's accepting. Works across threads *and*
  separate session processes.
- **Per-store deterministic port** (sha256 of the abspath → 10000–60000) so multiple Dolt
  stores on one machine never collide on dolt's default 3306. The bound port is in `.info`;
  the CLI reads it there, so the value is transparent to readers.
- **`stop()` escalates SIGTERM → SIGKILL.** dolt clears `.info` early on SIGTERM but the
  process lingers >10s still holding the store lock, which would bounce the next direct
  write; SIGKILL guarantees the lock is released. (Off any hook path — explicit teardown.)

Empirical guardrails: server time-to-ready ~0.19s (well under the 30s hook timeout); a
stale `.info` after a hard crash self-heals (dolt detects the dead PID); `snapshot`
(`dolt add -A` + commit) and `dump` route cleanly through a running server, so enabling the
flag doesn't break maintenance verbs.

**The fork (ratified): opt-in vs default-on.** A `dolt sql-server` makes the hub safe for
*all* sessions at once — even a flagless/old monition auto-routes through a server another
session spawned (verified). So whoever spawns it fixes the fleet, with no mixed-fleet
hazard. That left one call: when does monition spawn it?
- **Opt-in `MONITION_SQL_SERVER`, default off — CHOSEN.** Mirrors the embed warm daemon
  (`MONITION_EMBED_DAEMON`) exactly; respects the "deployment is CMS's" seam — CMS sets it
  machine-wide alongside `MONITION_STORE`, and once any session has it on the whole live
  hub is covered via auto-routing; zero regression for SQLite/standalone/test/CI; default
  off = behaviourally identical to today.
  > **Corrected 2026-07-02:** "CMS sets it machine-wide" described a *convention*, not
  > automation — verified structurally in CMS: no code path there writes the global
  > `~/.claude/settings.json` env block (`bootstrap.sh`/`deploy_settings.py` only touch a
  > target repo's per-repo `settings.local.json`). The flags are the same hand-set
  > personal env step as `MONITION_STORE` itself; CMS *documents and doctors* it
  > (`link_global()` prints the reminder, `--doctor` WARNs on a Dolt hub / embed extra
  > without its flag). The cutover sat unexecuted from 2026-06-19 until 2026-07-02, when
  > both flags were set by hand and live-validated (hook latency roughly halves, variance
  > disappears). See CMS `docs/decisions/2026-06-19-monition-hub-at-landing-zone.md`
  > ("Extended 2026-07-02").
- *Default-on for the Dolt write path* — rejected: treats lost writes as a correctness bug
  that shouldn't need a flag, but spawns a lingering server from every transient Dolt store
  (one-off `monition report`, every test, CI), littering processes that need teardown
  everywhere. The opt-in's auto-routing already closes the production gap with one env var.

**Consequence.** Unblocks `instrument --global` (blanket-global firing was held on this
seam). SQLite is unaffected (its own locking; no server). Retry-on-lock was dropped — the
server eliminates contention, and the bounded ready-wait covers the only residual window.
