# Bucket B04: `migrate` fold-into-hub sub-verb (Dolt→Dolt)

Parent: ../workstream.md
State: done (verb built + tested; the real fold-everything-in run is held on CMS standing up the hub)
Goal for session: Fold per-repo Dolt store(s) into the hub, backfilling origin_repo.
Target duration: 25 min
Context budget: Read parent + this bucket + required touchpoints only.

## Conceptual mapping

New verb that consolidates per-repo Dolt stores into the single Dolt hub: read each
source's rows, backfill `origin_repo` from that source's repo root, `reach='project'`,
insert into the hub. Dolt→Dolt only (no cross-backend path). Charter step 8. Depends on
B01 (v6 columns) and the **one synchronous CMS handoff**: CMS confirms the hub path before
the fold-everything-in run.

## CMS dependency — RESOLVED (confer 2026-06-18, archived)

- **Hub path FINAL:** `$CMS_LANDING_ZONE/monition/`; on this machine
  `CMS_LANDING_ZONE = /home/bolun/projects/brain2`, so the literal `--store`/fold target
  is **`/home/bolun/projects/brain2/monition/`** (brain2 is private — may hold machine-local paths).
- **Sources (all Dolt):** `CMS`, `Corpus`, `RCA`, `fathom` — verified `.dolt/` + `dump.sql`.
  Dolt→Dolt applies to all four; no cross-backend path.
- **STILL HELD:** the hub is **not stood up yet** (`CMS_LANDING_ZONE` unset, `brain2/monition/`
  doesn't exist). **Build the verb + scratch-test Dolt→Dolt now; do NOT run the real
  fold-everything-in** until CMS `dolt init`s the hub, sets `MONITION_STORE`, and signals it exists.

## Data contract / provenance

Report first (contract check):
- Section: `takeaways`/`firings` per-field (writes rows into the hub with v6 columns).
- Producer/consumer: source per-repo stores (read) → hub store (write).
- Provenance: `origin_repo` = each *source's* repo root (absolute); `reach='project'` for
  folded rows; `firings.repo` backfilled from the source's repo root where firings are folded.
- Validation: conservation — every source row lands in the hub exactly once; counts match
  pre/post; `origin_repo` non-null on all folded rows.

## Tasks

- [ ] `init_sync.py`: implement the fold — for each source Dolt store, read takeaways +
  firings + decisions, set `origin_repo`=source repo root + `reach='project'` (+ `firings.repo`),
  insert into the target hub, commit. No cross-backend (Dolt→Dolt only); refuse SQLite sources.
- [ ] `cli.py`: register the verb. **Shape decision** (open): `migrate --fold-into <hub>`
  (flag on migrate) vs a separate `migrate-fold <source> <hub>`. Needs explicit source + target.
- [ ] Conservation check: report rows-in vs rows-out per table; refuse partial folds.

## Required touchpoints

- `src/monition/init_sync.py`  `grep -n "def migrate\|def _dolt\|DoltBackend\|_sql("`  migrate + Dolt backend
  Mirror the existing migrate/commit pattern; reuse the Dolt read/write helpers.
- `src/monition/storage_backends.py`  `grep -n "class DoltBackend\|def _sql\|def dump\|def init"`  Dolt ops
  The row read/write primitives the fold uses.
- `src/monition/cli.py`  `grep -n "add_parser(\"migrate\""`  verb registration
- `docs/2026-06-18-v6-refactor-charter.md`  `grep -n "CMS dependency"` then that section
  The exact CMS handoff terms — confirm hub path before the real run.

## Do-not-read / avoid

- SQLite backend paths — fold is Dolt→Dolt only.
- Multi-writer/team-share distribution — deferred; fold is a one-time consolidation.

## Design direction

- Keep the fold idempotent-ish: re-running must not double-insert (dedup on source id +
  origin_repo, or fold into a fresh hub). Decide and state which.
- `origin_repo` from the source's repo root — the source store *is* per-repo, so its repo
  root is unambiguous. Absolute form (matches B02's `current_repo` canonical form so the
  filter matches folded `project` rows).
- Build + unit-test against TWO scratch Dolt stores → a scratch hub. The
  fold-everything-in against the real hub waits on the CMS path confirmation.

## Validation

- Scratch: two v6 Dolt stores (repos A, B) → fold into an empty hub → hub has all rows,
  `origin_repo` ∈ {A, B} correctly, counts conserved, `reach='project'`.
- Match from repo A against the hub returns A's project rows + general; not B's project rows
  (cross-check with B02's filter).
- `.venv/bin/pytest` green minus the 2 known-stale.
- Expected: conservation holds; no cross-backend path; CMS path NOT hardcoded.

## Done criteria

- [ ] Verb implemented + registered; shape decision recorded.
- [ ] Conservation check passes on scratch stores.
- [ ] Real fold-everything-in deferred until CMS confirms hub path (note in Updates).
- [ ] Bucket `Updates` records the verb shape + dedup strategy.
- [ ] Parent workstream progress updated.

## Updates

- [2026-06-18] Created, blocked on CMS hub-path confirmation (confer running CMS-side).
  Build agnostic to the path; gate only the real run.
- [2026-06-18] CMS confer RESOLVED (archived). Hub = `/home/bolun/projects/brain2/monition/`,
  Dolt, sources all Dolt (CMS/Corpus/RCA/fathom). Built shape A.
- [2026-06-19] DONE (verb). `monition migrate --store <source> --fold-into <hub>` in
  init_sync.`fold_store` + cli. 203 passed (+5 fold tests), 1 known-stale, lint clean; real
  CLI smoke passed (two-source fold → correct hub rows, idempotency guard fires).
  DESIGN as built:
  - Non-destructive to sources; **requires v6 source** (refuses if no `reach` col → "run
    migrate --store first"). Pure copy; migrate stays the single backfill source of truth.
  - **Offset id remap**: source ids shifted by hub `MAX(id)` per table, so no collisions and
    firings/decisions→takeaways FK refs stay intact (no per-row round-trips).
  - **Idempotency**: refuses if hub already has rows for the source's `origin_repo`.
  - **Conservation**: hub per-table counts must grow by exactly the source's, else raises.
  - Dolt→Dolt only (refuses SQLite/non-Dolt); commits the hub via DoltBackend.snapshot.
  GOTCHA hit: `_insert_rows` must take the FULL column list — child tables (firings/decisions)
  carry TWO lead columns (id + takeaway_id), not just id; hardcoding `["id"]` dropped
  takeaway_id from the column list → "values does not match columns". Fixed.
  HELD: the real fold-everything-in (the four sources → brain2 hub) waits on CMS standing up
  `/home/bolun/projects/brain2/monition/` (CMS_LANDING_ZONE unset, hub not yet created) and
  signaling. Each source must be `monition migrate`d to v6 first, then folded.
