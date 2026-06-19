# Workstream: v6 single-hub + global reach + semantic unblock

Progress: COMPLETE + handed off (2026-06-19). B01–B05 + fold-everything-in done; cutover confer resolved (CMS owns/executes deletion + bootstrap rework). monition's v6 involvement is closed.
Blocked: none.

## Objective

Execute the v6 refactor charter (`docs/2026-06-18-v6-refactor-charter.md`): collapse
per-repo takeaway stores into one Dolt hub, carry the general/project distinction as
`reach`+`origin_repo` columns (not physical boundaries), retire the vestigial `mirror`
column, fix `fire()` provenance + add `firings.repo`, and unblock semantic matching
(managed embed cache + warm daemon). Schema v5→v6, one bump, final. Charter is the
brief — trust source over prose; line numbers are hints (the firing-observer merge
shifted `hooks.py` ~+5).

## Execution Protocol (do not change)

1. Read this workstream first. For B01, read the full file. For B02+, do NOT use `cat` — run `grep -n "^##" workstream.md` first to get section line anchors, then use bounded reads for only: Objective, Execution Protocol, Bucket Index, and Cross-Bucket Invariants — skip Deferred/Non-Goals and lower boilerplate.
2. Use `Progress` and `Bucket Index` to select the active bucket; if none is active, select the next bucket.
3. Open only the selected bucket file. If its `State` is not `active`, update it to `active` before reading touchpoints.
4. Read only that bucket's required touchpoints before reporting.
5. Report first: selected bucket, required touchpoints read, current behavior, proposed edits, validation plan, and extra touchpoints if needed.
6. Only edit after the plan is clear.
7. Run the bucket's validation.
8. Update the bucket file's `Updates` section with completed tasks, discoveries, gotchas, test results, and handoff notes.
9. Update this workstream's `Progress`, `Bucket Index`, and `Updates` only for progress, sequencing changes, cross-bucket discoveries, and cross-bucket gotchas. Also update the next bucket file's `State` from `later` to `next`. Use the Read tool (not Bash `cat`) to open workstream.md before editing it.
10. Keep only one bucket active at a time unless the user explicitly authorizes parallel execution.

## Bucket Index

| B | State | File | Goal | Depends |
|---|---|---|---|---|
| B01 | done | buckets/B01_schema-reach-mirror.md | v6 schema + reader contract + retire mirror | — |
| B02 | done | buckets/B02_repo-threading.md | MONITION_STORE resolution + origin filter + provenance/firings.repo | B01 |
| B03 | done | buckets/B03_embed-cache.md | Managed embed cache_dir + pre-fetch (the actual semantic unblock) | — |
| B04 | done | buckets/B04_fold-verb.md | `migrate --fold-into` (Dolt→Dolt); verb built+tested, real run held on CMS | B01 |
| B05 | done | buckets/B05_warm-daemon.md | Warm embed daemon behind embed.py, fail-open | B03 |

States: `next`, `active`, `blocked`, `done`, `deferred`, `later`.

## Cross-Bucket Invariants

- **One final v6.** No v7. The gate-revision filter layers (`noise-targets-the-filter`)
  have nil schema footprint and stay deferred, so deferring them never forces another bump.
- **Data contract: `docs/contracts/takeaway-store.md`.** B01 bumps it v5→v6 (drop `mirror`
  + the `status × mirror` and v1-dialect sections; add `reach`/`origin_repo`/`firings.repo`).
  Any later bucket touching `takeaways`/`firings` columns reads the relevant section first.
- **`current_repo` derives ONLY from `_repo_root()` (`CLAUDE_PROJECT_DIR`/git) — never from
  the store path.** Once the store is the shared hub, `os.path.dirname(self.path)` is the hub,
  not the host repo. This is the central bug class B02 fixes; B04/B05 must not reintroduce it.
- **Firing-observer seam preserved.** `_notify_observer` (`hooks.py`, ~`:115`, called ~`:148`)
  must survive B02's `_disclose`/provenance edits. Contract: `docs/contracts/firing-observer.md`.
- **Both DDL variants stay in lockstep.** `V6_SCHEMA` (Dolt) and `V6_SCHEMA_SQLITE` move
  together; SQLite stays the recommended default for external hosts, we run Dolt.
- **Fail-open is non-negotiable.** No matching/embed/observer/daemon path may ever block a
  prompt. Preserve the existing `on_demand_match` fail-open chain.

## Deferred / Non-Goals

- Gate-revision filter LAYERS + layered-Filter structure refactor (own anti-goal: no
  per-context noise data yet). Origin filter is a plain predicate, not a layered framework.
- New trigger kinds (skill-invocation) — orthogonal breadth.
- Multi-writer / team-share distribution — rides the Dolt-server seam; build when a second
  writer exists. `origin_repo`-filtered export stays trivial meanwhile.
- SQLite in-place v5→v6 migration — no v5 SQLite store exists to upgrade.
- Tier-3 evaluator — CMS's, not monition's.
- `export-firings` repo exposure — `firings()` reads named columns, so `repo` isn't
  auto-exposed; surfacing to tier-3 is additive. Defer unless CMS's eval wants it now.

## Global Implementation Notes

- **Line numbers are hints.** The firing-observer merge shifted `hooks.py` ~+5 vs the
  charter. Grep symbols (`def fire`, `_REQUIRED`, `V5_SCHEMA`, `_notify_observer`).
- **Two known-stale tests — not v6 breaks.** `test_embed::test_real_model_semantic_neighbors`
  (onnxruntime env) and `test_init_sync::test_init_creates_working_store_and_wiring`
  (README asserts "uv tool install"; actual says "pip install"). Baseline is 185 passed,
  2 failed, 2 skipped.
- **Dolt omits NULL columns from JSON output entirely** — `row["col"]` raises `KeyError`
  on a NULL value, not None. For nullable v6 reads (`firings.repo`, `origin_repo` on
  backfilled rows) use `row.get("col")`.
- **`migrate()` is Dolt-only** (raises without `.dolt`). v5→v6 = additive first (ADD
  `reach`/`origin_repo`/`firings.repo`, backfill), THEN `ALTER TABLE takeaways DROP COLUMN
  mirror`. No live `.dolt` store exists under the repo — confirm `DROP COLUMN` against a
  scratch store. `dolt` binary IS on PATH.

## Updates

- [2026-06-18] Initial plan created from the v6 refactor charter. Split the charter's
  "spine" (steps 1–7,9,11) into B01 (schema-shape) + B02 (caller-threading) + B03 (embed
  cache) by edit surface — one mega-session was too large. B04=fold (charter 8, CMS-gated),
  B05=daemon (charter 10, independent). Next: B01/v6-schema-reach-mirror.
- [2026-06-18] B01 DONE. v6 schema + reader contract + mirror retirement landed; suite at
  baseline (185 passed, 2 known-stale, 2 skipped), lint clean, Dolt scratch smoke passed
  (DROP COLUMN + v5→v6 backfill confirmed against live Dolt). Cross-bucket gotcha: the
  version-detection ladder must run oldest→newest BEFORE the per-table column checks —
  hoisted into `store.py:_detect_stale_schema()`. B02 next: thread `current_repo` (from
  `_repo_root()`, never the store path) through matchers + `fire()`; columns already exist.
- [2026-06-18] B02 DONE. MONITION_STORE resolution + reach filter + provenance/firings.repo
  threaded through hooks/cli/mcp; observer seam preserved. 188 passed (+3 reach tests), lint
  clean, hub smoke passed. Cross-bucket call: reach_clause is fail-open — `current_repo=None`
  skips the filter, and `origin_repo IS NULL` fires anywhere (under-specified project row).
  Real v6 project rows always carry origin_repo (add stamps / migrate backfills), so isolation
  holds; the NULL fail-open is what keeps legacy NULL-origin fixtures firing. Next: B03 (embed
  cache, independent of the hub work). B04 fold still blocked on CMS hub-path confer.
- [2026-06-18] B03 DONE. embed cache_dir fix + `embed-warm` verb. The fix unblocked the
  real-model semantic test (one of the charter's two "known-stale" failures now passes) —
  confirming the ephemeral /tmp cache was the actual semantic-death cause. Suite: 192 passed,
  1 failed (README install-line drift, pre-existing/out-of-scope), 2 skipped. Did not auto-wire
  warm into init (surprise download + test hazard) — CMS bootstrap calls the verb per the
  deployment seam. Next runnable: B05 (warm daemon, depends on this managed cache). B04 still
  CMS-gated.
- [2026-06-18] B05 DONE. Opt-in (MONITION_EMBED_DAEMON, default off) machine-scoped warm embed
  daemon behind embed.py; fail-open chain daemon→spawn+in-process→lexical, no hooks.py change.
  198 passed (+6), lint clean, real-model end-to-end socket smoke passed. Two de-risking
  divergences from spec: opt-in (not always-on) + machine-scoped (not session-scoped) — see
  bucket. WORKSTREAM COMPLETE except B04 (fold), still blocked on CMS hub-path confer. The v6
  schema/reach/provenance + semantic unblock + daemon are all shipped; the fold is the only
  remaining piece and needs CMS to confirm the hub path before the fold-everything-in run.
- [2026-06-18] B04 UNBLOCKED. CMS confer resolved (archived `handoffs/archive/2026-06-18-confer-hub-path-confirmation.md`):
  hub = `$CMS_LANDING_ZONE/monition/` = `/home/bolun/projects/brain2/monition/` (literal target),
  Dolt backend, sources all Dolt (CMS/Corpus/RCA/fathom). Build the path-agnostic fold verb +
  scratch Dolt→Dolt tests now; HOLD the real fold-everything-in until CMS stands up the hub
  (CMS_LANDING_ZONE currently unset, brain2/monition/ not yet created) and signals it exists.
  GOTCHA self-correction: my confer Turn 1 wrongly floated an XDG path (lifted from the stale
  CMS hub-location handoff) — corrected in-thread; the architectural docs (charter L44/170,
  CMS DESIGN.md) had always said the landing zone. Live instance of the archived-docs flag.
- [2026-06-19] FOLD-EVERYTHING-IN EXECUTED + init decomposition shipped. (1) `init` decomposed
  into `init-store` + `instrument` primitives (2026-06-19 confer + decision; committed 7c9238d).
  (2) All four sources (CMS/Corpus/RCA/fathom) migrated v5→v6 + folded into brain2/monition;
  conservation exact `(2,1,1)→(62,266,457)`, FK integrity + reach isolation verified, no dups.
  DISCOVERY: the hub was already live (CMS had mined 2 general gotchas + 1 firing into it) — the
  fold's per-source before/after conservation handled the non-empty hub cleanly. Remaining:
  CMS-owned cutover (retire the 4 per-repo stores; point host repos at the hub). v6 workstream COMPLETE.
- [2026-06-19] Cutover confer RESOLVED (archived `handoffs/archive/2026-06-19-confer-v6-cutover.md`)
  — clean handoff, nothing further needed from monition. CMS executes: delete all four per-repo
  stores (`git rm dump.sql` + `rm -rf .dolt`; rows preserved in hub + git history), retire the
  CMS/monition forkable reference exhibit; host repos already resolve to the hub via machine-wide
  MONITION_STORE (no re-instrument). Sequencing: cutover now, bootstrap.sh rework next (CMS-side).
  **monition's v6 arc is fully closed.**
- [2026-06-19] B04 DONE (verb). `monition migrate --store <source> --fold-into <hub>` —
  non-destructive Dolt→Dolt copy: requires v6 source, offset-id remap keeps FK refs intact,
  idempotency guard on origin_repo, per-table conservation check, commits the hub. 203 passed
  (+5 fold tests), lint clean, CLI smoke passed. WORKSTREAM CODE-COMPLETE. The only thing left
  is the operational fold-everything-in run (migrate each of CMS/Corpus/RCA/fathom to v6, then
  fold into /home/bolun/projects/brain2/monition/) — held until CMS stands up the hub + signals.
