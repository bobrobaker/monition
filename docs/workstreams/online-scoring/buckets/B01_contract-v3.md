# Bucket B01: Contract v3

Parent: ../workstream.md
State: done
Goal for session: Add `decisions` table to contract and schema; extend migrate.
Target duration: 25 min
Context budget: Read parent + this bucket + required touchpoints only.

## Conceptual mapping

All three tasks share the same mental model: what the `decisions` table is, what
fields it carries, and how v2 stores get upgraded to v3. The contract edit defines
the semantics; the DDL constant and validator implement them; migrate wires the
upgrade path.

## Data contract / provenance

Report first (contract check):
- Which contract section applies? Versioning + new `## decisions — per-field meaning` section.
- Producer/consumer boundary: scorer (write) / no Phase 3 consumer (write-only for now).
- Fields that could break downstream: `decision` enum domain; `ev_score` nullable
  contract; `cold_start` boolean interpretation.
- Validation: reader raises `StoreContractError` on a v2 store (missing decisions
  table) with explicit migrate message; v3 store passes validation.

**decisions table schema (canonical — implement exactly this):**

```sql
CREATE TABLE decisions (
  id int NOT NULL AUTO_INCREMENT,
  takeaway_id int NOT NULL,
  session_id varchar(64),
  decided_at datetime NOT NULL,
  decision enum('fire','suppress') NOT NULL,
  evidence_count int NOT NULL,
  cold_start tinyint(1) NOT NULL DEFAULT 0,
  ev_score decimal(5,4),
  PRIMARY KEY (id)
);
```

`ev_score` is NULL when `cold_start=1` (no evidence to compute from). `evidence_count`
is the number of rated firings for this takeaway at decision time.

## Tasks

- [ ] Update `docs/contracts/takeaway-store.md`:
  - Change versioning note: v3 (2026-06-12, current) adds `decisions` table for
    scored fire/suppress decisions; v2 stores missing decisions are rejected with
    migrate message.
  - Add `## decisions — per-field meaning` section with field table.
- [ ] Update `_REQUIRED` in `src/monition/store.py`: add `decisions` entry with
  column patterns for `id`, `takeaway_id`, `decided_at`, `decision`, `evidence_count`,
  `cold_start`, `ev_score`.
- [ ] Update `_validate_schema` in `src/monition/store.py`: detect missing decisions
  table and raise with explicit v2→v3 migrate message (match the v1→v2 error style).
- [ ] Update `init_sync.py`: rename `V2_SCHEMA` → `V3_SCHEMA`, append decisions DDL,
  update the `init` log message from "v2 schema" to "v3 schema".
- [ ] Extend `migrate` in `init_sync.py` to handle v2→v3: detect v2 store (takeaways
  + firings present, decisions absent), run `CREATE TABLE decisions …`, commit.
  Keep v1→v2 path; refuse anything else.

## Required touchpoints

- `docs/contracts/takeaway-store.md`  `grep -n "^##"`, then read: Versioning section + existing table sections for style reference.
  Defines the canonical field semantics; the edit adds v3 versioning note + decisions section.
- `src/monition/store.py`  lines 20–50  `_REQUIRED` dict
  Add decisions entry here; understand the regex pattern convention.
- `src/monition/store.py`  lines 125–150  `_validate_schema`
  Understand the missing-table error path to add matching v2→v3 message.
- `src/monition/init_sync.py`  lines 25–52  `V2_SCHEMA`
  Rename to V3_SCHEMA and append decisions DDL.
- `src/monition/init_sync.py`  lines 269–300  `migrate`
  Extend to detect and execute v2→v3 migration path.

## Conditional touchpoints

- `tests/conftest.py`  `grep -n "V2_SCHEMA\|CREATE TABLE\|decisions"`
  Read if conftest duplicates the schema DDL — it must be updated to V3 too.

## Do-not-read / avoid

- `src/monition/store_write.py` — no writes to decisions in this bucket; that's B02.
- `src/monition/hooks.py` — executor wiring is B03.

## Design direction

- The `_validate_schema` missing-table path already raises `StoreContractError` with
  a message; add a v3-specific branch before the generic raise that fires when
  `takeaways` and `firings` pass but `decisions` is absent. Message should read:
  "v2-schema store: missing `decisions` table — run `monition migrate` to upgrade to v3".
- `migrate` must detect v2 (not v1, not already-v3) before acting. Check: takeaways
  present + firings present + decisions absent = v2. If decisions present, it's
  already v3 → refuse with "store is already v3 — nothing to migrate".
- `V3_SCHEMA` should be the full DDL including takeaways + firings + decisions. The
  `init` command uses it wholesale; migrate only uses the decisions fragment.
- `ev_score decimal(5,4)` — four decimal places (e.g. 0.6667). The regex pattern in
  `_REQUIRED` should be `r"^decimal"` (match prefix, tolerate precision variants).

## Validation

- `pytest` — all existing tests must still pass (no behavioral change, only schema
  extension and migrate path addition).
- Manual smoke: create a tmp v2 store (no decisions table), open with `Store()` →
  expect `StoreContractError` naming migrate; run migrate → decisions table created;
  reopen → no error.
- Expected: green suite, no lint ERRORs.

## Done criteria

- [ ] Tasks complete.
- [ ] Validation passes.
- [ ] Bucket `Updates` section records discoveries/gotchas/handoff.
- [ ] Parent workstream progress updated; B02 set to `next`.

## Updates

- [2026-06-12 00:00] Created. Handoff: none yet. Gotchas: none yet.
- [2026-06-12] Done. 33 passed, 35 skipped, lint clean.
  Gotchas:
  - `test_init_sync.py` constructed V1_SCHEMA from `ins.V2_SCHEMA` — kept V2_SCHEMA as a
    constant (takeaways + firings only) so V1 test fixture stays decisions-free. V3_SCHEMA = V2_SCHEMA + _DECISIONS_DDL.
  - v1→v2 migration path now also creates decisions table (result is v3); return message updated.
  - `test_migrate_refuses_v2` → `test_migrate_refuses_v3`; match string updated to "already v3".
  - `conftest.py SCHEMA` updated to include decisions DDL so canonical store passes v3 fingerprint check.
  Handoff for B02: `_DECISIONS_DDL` in init_sync.py is the canonical DDL; store.py `_REQUIRED["decisions"]` defines the column patterns. WriteStore.write_decision() should INSERT and dolt-commit matching the fire() pattern.
