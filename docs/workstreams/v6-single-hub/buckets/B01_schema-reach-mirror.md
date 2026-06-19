# Bucket B01: v6 schema + reader contract + retire mirror

Parent: ../workstream.md
State: done
Goal for session: Define v6 columns, migrate v5→v6, reject pre-v6 reads, retire mirror.
Target duration: 35 min
Context budget: Read parent + this bucket + required touchpoints only.

## Conceptual mapping

All tasks share one mental model: *what columns v6 has and where they are validated*.
`takeaways` gains `reach`+`origin_repo`, loses `mirror`; `firings` gains `repo`. The
contract doc defines the semantics; the DDL constants + migrate implement them; the
reader fingerprint + detection-raise enforce them; the writer surface and mirror
consumers follow. Charter steps 1, 2, 6, 7 + the contract part of 11.

## Data contract / provenance

Report first (contract check):
- Which contract section applies? `Versioning and rejection`, `takeaways — per-field
  meaning`, `firings — per-field meaning`; **delete** `status × mirror` and the v1-dialect
  prose. Header `(v5)` → `(v6)`.
- Producer/consumer boundary: schema/migrate (write) → reader fingerprint (consume).
- Fields that could break downstream: `reach` enum domain; `origin_repo` canonical form
  (absolute repo root); `firings.repo` nullable on backfill; removal of `mirror` breaks
  `metrics`/`report`/`cli`.
- Validation: reader raises `StoreContractError` on a v5 store (lacks `reach`) naming
  `monition migrate`; v6 store passes both Dolt and SQLite fingerprints.

**Canonical v6 column additions (implement exactly):**
- `takeaways`: `reach enum('general','project') NOT NULL DEFAULT 'project'`,
  `origin_repo varchar(512)` (absolute repo root; nullable, backfilled on migrate).
  REMOVE `mirror`.
- `firings`: `repo varchar(512)` (host repo root at fire time; nullable — capture-or-lose).

`reach` semantics: `general` fires anywhere; `project` fires only where
`origin_repo == current_repo`. SQLite variant uses `TEXT ... CHECK(reach IN
('general','project'))` and `TEXT` for repo columns (mirror the existing v5 SQLite style).

## Tasks

- [ ] `init_sync.py`: define `V6_SCHEMA` (Dolt) + `V6_SCHEMA_SQLITE` from the v5 constants
  — add `reach`/`origin_repo` to takeaways, `repo` to firings, drop `mirror`. Point `init`
  at V6; update the "v5 schema" log strings.
- [ ] `init_sync.py` `migrate()`: add v5→v6 step — additive first (ADD reach/origin_repo/
  firings.repo, backfill `reach='project'` + `origin_repo`=store's repo root), THEN
  `ALTER TABLE takeaways DROP COLUMN mirror`. Detect v5 (has `situation`, lacks `reach`).
  Update "already v5" refusal → "already v6".
- [ ] `cli.py:175`: migrate help string "v5" → "v6".
- [ ] `store.py`: update `_REQUIRED` + `_REQUIRED_SQLITE` (add reach/origin_repo/firings.repo
  patterns, drop mirror); `Takeaway` dataclass (drop `mirror`, add `reach`/`origin_repo`);
  the `takeaways()` SELECT column list; add a v5→v6 detection raise mirroring the v4→v5 block.
- [ ] `store_write.py` `add()`: drop `mirror` param, add `reach` (default `'project'`) +
  `origin_repo` (default = current-repo when not given — **threaded in B02**; for now accept
  the param, default None). Update the `add` INSERT column list + the `show` formatting.
- [ ] `cli.py` `add`: remove `--mirror`, add `--reach`/`--origin-repo`.
- [ ] Retire `mirror` in remaining consumers: `metrics.py:55,96`, `report.py:25,35`,
  mine-session skill text in `init_sync.py:215` (drop the `--mirror candidate` instruction).
- [ ] Update `docs/contracts/takeaway-store.md` → v6 (see Data contract above).

## Required touchpoints

- `docs/contracts/takeaway-store.md`  `grep -n "^##"` then read Versioning + takeaways + firings + `status × mirror` sections
  Defines the canonical semantics; this edit bumps to v6 and deletes mirror prose.
- `src/monition/init_sync.py`  `grep -n "V5_SCHEMA\|V5_SCHEMA_SQLITE\|def migrate\|v5 schema\|--mirror\|mirror candidate"`  V5 constants + migrate + skill text
  Define V6 constants, extend migrate, fix the mine-session step-6 text.
- `src/monition/store.py`  `grep -n "_REQUIRED\|class Takeaway\|def takeaways\|run \`monition migrate\`"`  reader contract
  _REQUIRED/_REQUIRED_SQLITE, Takeaway dataclass, SELECT, detection raise.
- `src/monition/store_write.py`  `grep -n "def add\|def show\|mirror"`  writer surface
  add()/show() drop mirror, gain reach/origin_repo.
- `src/monition/cli.py`  `grep -n "mirror\|add_parser(\"migrate\"\|--reach"`  CLI surface
  add args + migrate help.
- `src/monition/metrics.py`  lines 50–100  `mirror`
- `src/monition/report.py`  lines 20–40  `mirror`
- `tests/conftest.py`  `grep -n "SCHEMA\|CREATE TABLE\|mirror\|reach"`  canonical fixture
  If conftest duplicates schema DDL it must move to v6 (and lose mirror) or the fingerprint check fails.

## Do-not-read / avoid

- `src/monition/hooks.py`, `mcp_server.py` — caller threading of `current_repo` is B02.
- `src/monition/embed.py` — cache fix is B03.
- `src/monition/replay.py:18` — "mirrors the repo" is prose, NOT the column. Do not touch.

## Design direction

- Backfill `origin_repo` from the *store's* repo root during migrate (per-repo stores
  pre-fold each belong to one repo). Canonical form = absolute repo root.
- The detection raise: a v5 store has `situation` but no `reach` column → raise
  "v5-schema store: `takeaways` lacks `reach`/`origin_repo` — run `monition migrate` to
  upgrade to v6". Add it before the generic pass, after the v4→v5 check.
- `migrate` order matters: additive + backfill must complete and commit before the
  destructive `DROP COLUMN mirror`. Confirm Dolt accepts MySQL-dialect `DROP COLUMN`
  against a scratch store (no live `.dolt` exists to test against).
- `add()` keeps `origin_repo` defaulting to None here; B02 makes hooks/cli pass current-repo.
  Do not wire `_repo_root()` into the writer in this bucket — that's B02's seam.

## Validation

- `.venv/bin/pytest` — expect the 2 known-stale failures only (test_embed, test_init_sync
  README); everything else green. Update any test asserting `mirror` or v5 fingerprints.
- Scratch-store smoke (Dolt): `monition init` a v6 store; build a v5 store, `monition
  migrate` → confirm reach/origin_repo/firings.repo present + mirror gone; reopen a v5
  store with `Store()` → expect `StoreContractError` naming migrate to v6.
- Expected: green suite (minus the 2 stale), no lint ERRORs.

## Done criteria

- [ ] Tasks complete.
- [ ] Validation passes (baseline failures unchanged; no new failures).
- [ ] Bucket `Updates` records the migrate ordering, DROP COLUMN confirmation, conftest changes.
- [ ] Parent workstream progress updated; B02 set to `next`.

## Updates

- [2026-06-18] Created. Handoff: none yet. Gotchas: Dolt drops NULL cols from JSON (use
  `row.get`); no live `.dolt` to test DROP COLUMN against — use a scratch store.
- [2026-06-18] DONE. Suite at baseline: 185 passed, 2 known-stale (test_embed onnxruntime,
  test_init_sync README), 2 skipped. Lint clean (exit 0). Dolt scratch smoke PASSED: fresh
  v6 (DROP COLUMN mirror confirmed against live Dolt), v5→v6 migrate backfills origin_repo +
  firings.repo from store repo root, reader rejects v5, idempotent "already v6" refusal.
  Edits landed:
  - init_sync.py: `_TAKEAWAYS_REACH_DDL`/`_FIRINGS_REPO_DDL`/`_TAKEAWAYS_DROP_MIRROR_DDL`;
    `V6_SCHEMA` = V5 + those (CREATE mirror then DROP in one shot — matches v4/v5 idiom);
    `V6_SCHEMA_SQLITE` written direct (reach/origin_repo, firings.repo, no mirror). migrate()
    v5→v6 step: additive+backfill, then DROP mirror checked against LIVE cols (a v1-origin
    store gains mirror during v1→v2, so stale `cols` would miss it). init→V6, "v6 schema" logs.
    Skill step-6 text `--mirror candidate` → `--reach general`.
  - store.py: HOISTED the version-ladder into `_detect_stale_schema()` run BEFORE the per-table
    pattern loop — GOTCHA: putting the reach raise inline in the takeaways branch fired before
    the older firings checks (table iteration order), mislabeling a v4 store "v5-schema" and
    breaking the pattern loop. Ladder is oldest→newest: v1, v2(decisions), v3(git_sha),
    v4(situation), v5(reach). _REQUIRED ×2, Takeaway (reach/origin_repo), SELECT updated.
  - store_write.py add()/list_rows()/resolve_add(): mirror→reach+origin_repo. cli.py: --reach
    /--origin-repo, migrate help v6. metrics.py TakeawayAudit.reach. report.py general-reach count.
  - Contract → v6 (governed): header, v6 versioning entry, v2 marked mirror-retired, takeaways
    table (reach/origin_repo), status×reach section, firings.repo row, interchange defaults,
    validation checklist (v5→v6 rejection).
  - Tests: conftest v6 (t3/t6 → reach='general' as the mirror-candidate successor); migration
    tests renamed _to_v6, assert "to v6"; refuses_v5 → v5_to_v6_then_refuses; test_embed add()
    positional "none" dropped; metrics/adopt/store/report/export_firings/conformance_dolt fixed.
  GOTCHA for B02: a positional `add(..., "none")` 8th-arg now means reach="none" → CHECK
  violation. CHARTER-RATIFIED LOSS: v6 backfills all rows reach='project'; old mirror=candidate
  intent is NOT mapped to general (dropped).
  Handoff for B02: columns exist; thread `current_repo` (NOT store path) through matchers + fire().
