# 2026-06-21 · No store-mutation primitive — isolate synthetic writes instead

Status: decided. Scope: project-internal (monition store write surface). Sibling:
`2026-06-19-dolt-sql-server-write-path.md` (the write-path contract this protects),
`2026-06-18-noise-targets-the-filter-not-the-gate.md` (why per-row trigger editing
is demoted, which kills the `modify` case).

**Supersession audit (2026-06-21):** grep of `docs/decisions/`, `road.md`, and the
contract found nothing this overturns. It *affirms* — does not change — the write
surface documented in `docs/contracts/takeaway-store.md` (`takeaways`: add via
`/mine-session`/`/codify`; `retire` flips status), and declines to extend it with a
mutation/delete verb.

## Question

Do we need a `modify rows` or `delete rows` primitive on the store? Prompted by the
observation that other sessions are removing test/synthetic rows by manipulating the
Dolt substrate directly — i.e. raw `dolt sql DELETE` against the hub, bypassing the
module write path.

## Decision

**No new primitive — not `purge`, not `delete`, not `modify`.** The real need is
narrow (remove junk that should never have been in the hub), and it is better served
by removing the *cause* than by widening the write surface:

1. **Synthetic writes go to a scratch store, never the hub.** Instrumentation /
   measurement / test rows use `--store` / `MONITION_STORE` (or a tmp SQLite), seeded
   from a `monition snapshot` when realistic corpus size matters, and discarded with
   `rm`. This is now a standing rule in `CLAUDE.md` §Working here.
2. **Junk already in the hub → Dolt's own version control**: `revert` the introducing
   commit (clean when the junk is its own commit — mine commits are reasonably
   isolated) or `retire` for the soft path. Never a raw `DELETE`.

## Why the bypass is the actual problem

The store contract is single-write-path: all writes flow through module commands /
`WriteStore`, all reads through the one approved reader. A raw `dolt sql DELETE` is a
contract violation done **blind** — no guard against deleting a row with rated
firings, which are the irreplaceable eval substrate (the firings/ratings the tier-3
evaluator and `export-firings` consume). Verified, not hypothetical: hub commit
`vkht1ltv…` ("mine: hook-latency perf levers — … purge synthetic measurement rows")
removed rows that way, because the `MONITION_TRACE` instrumentation session wrote
synthetic rows into the production hub in the first place. The fix is upstream: don't
pollute the hub, and the purge need evaporates.

## Options considered and why the rejected ones lost

- **A — guarded `purge` verb** (hard-DELETE + cascade firings/decisions; refuse rows
  with rated firings; `--force` override). Rejected *for now*: it pulls the bypass
  back under the contract, but it widens the write surface to serve a need that
  isolation removes at the root. Build-ahead-of-reuse. It stays the right answer only
  for the one residual case below.
- **B — generic `modify` / column-setter verb.** Rejected: the existing narrow
  mutators already cover every mutation the system performs — `retire` (status),
  `merge_resurrection` (content), `rate` (outcome). The only uncovered field is
  `trigger_spec`, and `2026-06-18-noise-targets-the-filter-not-the-gate.md` demoted
  per-row `trigger_spec` editing to a ~2-case cleanup tool (the real noise lever is a
  cross-cutting first-line filter, not hand-editing rows). A general setter would be
  built for a path the design already decided is secondary.
- **C — sanctioned raw-SQL escape hatch** (bless a documented `dolt sql DELETE`
  procedure). Rejected: formalizes the contract hole instead of closing it, and keeps
  the un-guarded eval-evidence risk.
- **D — `retire` only, do nothing else.** Insufficient on its own: `retire` is a soft
  status flip, so genuine test garbage lingers in `--status retired` and pollutes
  counts. Fine as the soft path; not the answer for "never was a lesson" junk. Pairs
  with isolation (1) above.

## Anti-goals

- Do **not** add a hard `DELETE` that can orphan firings/decisions or destroy rated
  firings.
- Do **not** treat `retire` as a substitute for keeping synthetic rows out of the hub
  — isolation is the primary fix; `retire`/`revert` are the retroactive cleanup.

## The one residual that would reopen `purge`

Junk **tangled into a mixed commit** with real rows you want to keep: `revert` is
commit-granular, so it would take the good with the bad, and `retire` only soft-hides
it. If that case recurs, it is the narrow, specific signal that justifies revisiting
**option A** (guarded `purge`, rated-firing guard + `--force`) — a much smaller target
than "test rows" broadly. We have not hit it yet.
