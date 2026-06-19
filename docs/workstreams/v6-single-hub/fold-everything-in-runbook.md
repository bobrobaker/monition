# Fold-everything-in runbook (v6 hub consolidation)

> **EXECUTED 2026-06-19.** All four sources migrated v5→v6 and folded into
> `/home/bolun/projects/brain2/monition`. Conservation exact: hub `(2,1,1) → (62,266,457)`
> (the 2/1/1 pre-existing hub-native rows preserved). Reader opens clean (FK integrity),
> reach isolation verified, no duplicates, 4 fold commits in the hub dolt log. **Remaining:
> Step 4 cutover (retire the 4 per-repo source stores; point host repos at the hub) — CMS-owned.**
> The four source stores are now v6-in-place (uncommitted working set) pending CMS retirement.
> Steps below are the procedure as run, kept for provenance / re-runs.

The one operational step left in the v6 workstream: fold the four per-repo Dolt
takeaway stores into the single Dolt hub. The verb (`monition migrate --fold-into`,
B04) is built + tested; this is the real run. **Hard-to-reverse — runs against real
takeaway data across five repos. Execute only on the user's go.**

## Targets (verified 2026-06-19)

| Role | Path | State |
|---|---|---|
| Hub | `/home/bolun/projects/brain2/monition/` | **exists, empty, v6** ✓ |
| Source | `/home/bolun/projects/CMS/monition/` | v5 (needs migrate) |
| Source | `/home/bolun/projects/Corpus/monition/` | v5 (needs migrate) |
| Source | `/home/bolun/projects/RCA/monition/` | v5 (needs migrate) |
| Source | `/home/bolun/projects/fathom/monition/` | v5 (needs migrate) |

`reach`/`origin_repo` confirmed present on the hub; `mirror` (v5) present on all four
sources. The fold is Dolt→Dolt; all five are Dolt. `origin_repo` for each source's rows
is backfilled by its own `migrate` from that source's repo root.

## Preconditions to confirm before running

1. **Hub exists + v6 + empty** — ✓ as of 2026-06-19 (re-check `COUNT(*)` is still 0; a
   non-empty hub means a prior partial run — the per-source idempotency guard handles it,
   but confirm intent).
2. **CMS has signaled** the hub is the live target and set `CMS_LANDING_ZONE` +
   `MONITION_STORE=$CMS_LANDING_ZONE/monition` in `settings.json` `env`. (Hub existence is
   evidence, not a signal — confirm with CMS.)
3. **Backups exist:** each source carries a committed `dump.sql` (per CMS); the hub is
   empty so rollback = wipe the hub.

## Step 1 — migrate each source v5→v6 (in place; backfills origin_repo/firings.repo)

```bash
monition migrate --store /home/bolun/projects/CMS/monition
monition migrate --store /home/bolun/projects/Corpus/monition
monition migrate --store /home/bolun/projects/RCA/monition
monition migrate --store /home/bolun/projects/fathom/monition
```

Per-source. Re-running on an already-v6 source errors with "already v6 — nothing to
migrate" (benign; means it's done). Each backfills that source's `origin_repo` =
its repo root.

## Step 2 — fold each source into the hub

```bash
HUB=/home/bolun/projects/brain2/monition
monition migrate --store /home/bolun/projects/CMS/monition    --fold-into "$HUB"
monition migrate --store /home/bolun/projects/Corpus/monition --fold-into "$HUB"
monition migrate --store /home/bolun/projects/RCA/monition    --fold-into "$HUB"
monition migrate --store /home/bolun/projects/fathom/monition --fold-into "$HUB"
```

Each prints `folded N takeaways, M firings, K decisions …` and commits the hub.
**Idempotent:** re-running a source the hub already holds (by `origin_repo`) refuses
with "already folded" — so a re-run of this whole block is safe (skips done sources).

## Step 3 — verify

```bash
HUB=/home/bolun/projects/brain2/monition
# conservation: hub takeaway count == sum of the four sources' counts
monition report "$HUB"
# origin_repo coverage: should list exactly the four source repo roots
( cd "$HUB" && dolt sql -q "SELECT origin_repo, COUNT(*) FROM takeaways GROUP BY origin_repo" )
# reach isolation spot-check (run from inside one source repo, MONITION_STORE=hub):
MONITION_STORE="$HUB" monition query "<a keyword from a CMS-only row>"
#   → returns CMS's project rows + general rows; NOT other repos' project rows
```

Conservation = sum the four `folded N takeaways` lines and compare to the hub's
takeaway count. Each source's pre-fold count: `( cd <source> && dolt sql -q "SELECT
COUNT(*) FROM takeaways" )`.

## Step 4 — cutover (CMS-owned)

CMS points host repos at the hub (`MONITION_STORE` already exported) and retires/archives
the four per-repo stores. Monition's job ends at a verified fold.

## Rollback

The hub was empty pre-fold, so undo = wipe it: `( cd $HUB && dolt sql -q "DELETE FROM
firings; DELETE FROM decisions; DELETE FROM takeaways" )` (or re-`dolt` the hub to its
empty commit). Sources are unchanged except the forward-only v5→v6 migration; their
`dump.sql` backups predate it if a source itself needs restoring.
