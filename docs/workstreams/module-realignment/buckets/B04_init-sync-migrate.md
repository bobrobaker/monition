# Bucket B04: init / sync / migrate

Parent: ../workstream.md
State: done
Goal for session: one-command adoption; idempotent, transparent, dry-runnable.
Target duration: 40 min
Context budget: Read parent + this bucket + required touchpoints only.

## Conceptual mapping

- The host-repo mutation surface in one bucket: everything that writes into a
  host project (store DDL, settings.json merge, skills, README line) shares the
  idempotence/transparency rules of spec decision 6.

## Tasks

- [ ] `monition init`: check `dolt` on PATH (clear failure, no half-created
      store); create `<root>/monition/` Dolt store with v2 DDL (mirror
      tests/conftest.py DDL — enum domains exactly per contract); idempotent
      merge of guarded hook entries (B03's canonical strings) into
      `.claude/settings.json` (never touch unrelated keys; create file if
      absent); materialize skills into `.claude/skills/` with a version stamp
      line; append the install-requirement line to README if present; print
      every change made; `--dry-run` prints the would-be diff and writes
      nothing.
- [ ] `init` offers (prints, never installs unasked) the pre-commit snippet
      running `monition dump`; a `--with-dump-hook` flag installs it.
- [ ] `monition sync`: regenerate hook entries + skills; per skill compare
      installed hash vs stamped generation — untouched → rewrite, locally
      edited → warn and skip.
- [ ] `monition migrate`: v1-dialect store (status domain contains
      `upstream_candidate`/`mirrored`) → v2 axes: `upstream_candidate` →
      (`active`, `candidate`); `mirrored` → (`active`, `mirrored`); others →
      (unchanged, `none`). Refuse on already-v2. Record the mapping in the
      contract's v2 History note (one sentence; the only contract edit allowed
      here).
- [ ] Skill content: port `mine-session` from CMS as the packaged template
      (full text, materialized — spec decision 5).

## Data contract / provenance

- DDL must match the fingerprint check in `src/monition/store.py` exactly —
  Core invariant: **init's DDL passes the reader's own contract check** (test
  it: init a tmp store, open with the reader, no StoreContractError).

## Required touchpoints

- `tests/conftest.py`  grep -n "CREATE TABLE\|enum"  the v2 DDL to mirror
- `src/monition/store.py`  grep -n "REQUIRED\|enum\|fingerprint\|StoreContractError"  what init's output must satisfy; what migrate's input check reuses
- `<CMS>/.claude/settings.json`  (full read, short)  the settings shape being merged into
- `<CMS>/.claude/skills/mine-session/SKILL.md`  (full read)  skill template source
- `docs/specs/2026-06-11-module-realignment.md`  bounded read of decisions 5–6  idempotence/transparency rules

## Conditional touchpoints

- `docs/contracts/takeaway-store.md` §Versioning — read only when writing the
  migrate mapping sentence.

## Do-not-read / avoid

- Interchange format / `--adopt` — B05's concern; keep init's surface free of it.
- Any config-file design for store paths — convention only (parent Non-Goals).

## Design direction

- Idempotence assertion level: exact — run `init` twice on a tmp repo; second
  run reports "no changes" and the tree hash is identical.
- settings.json merge: parse-modify-serialize JSON; preserve key order where
  trivial; never regex-edit.
- Version stamp format: one HTML comment line with package version + content
  hash (exact format is implementer's choice — record it in Updates; sync must
  parse it back).

## Validation

- `.venv/bin/pytest` green: init-on-tmp-repo (store opens via reader, hooks
  merged, skills stamped), double-init idempotence, dry-run writes nothing,
  sync hash matrix (untouched/edited), migrate on a v1 fixture (reader accepts
  result; row mapping exact).
- Expected: all pass; no test touches a real repo.

## Done criteria

- [x] Tasks complete.
- [x] Validation passes.
- [x] Bucket `Updates` section records discoveries/gotchas/handoff.
- [x] Parent workstream progress updated.

## Updates

- [2026-06-11 19:55] Created. Handoff: none yet. Gotchas: none yet.
- [2026-06-11] Done. `src/monition/init_sync.py`: `init` (dolt preflight →
  clear failure before any change; v2 DDL identical to conftest's, gated by
  opening the result with the reader; parse-modify-serialize settings merge
  keyed on our exact guarded command strings; stamped skill materialization;
  README line; dump hook offered by default, installed via `--with-dump-hook`,
  never overwrites an existing pre-commit), `sync` (re-merge + hash-matrix:
  absent→install, untouched→upgrade, edited→WARN and skip), `migrate`
  (v1→v2: add `mirror`, map `upstream_candidate`→(active,candidate),
  `mirrored`→(active,mirrored), shrink the status enum; refuses already-v2 and
  unrecognized domains; success gate = reader fingerprint check). CLI: `init
  --root/--dry-run/--with-dump-hook`, `sync --root`, `migrate --store`.
  Version stamp format (sync parses it back):
  `<!-- monition-skill v<VERSION> sha256:<hex-of-body> -->` as line 1, body
  after; no stamp ⇒ treated as user-owned (edited). VERSION constant lives in
  init_sync.py ("0.1.0") — bump manually with pyproject until packaging needs
  more. Contract edit (the one allowed): migrate mapping sentence appended to
  the v2 Versioning note.
  Tests (10): store-opens-via-reader, double-init tree-digest idempotence,
  dry-run zero-write, no-dolt clear failure, unrelated-settings preservation,
  dump-hook flag + never-overwrite, sync upgrade/edited matrix, v1 fixture
  migration with exact row mapping, refuse-on-v2, CLI end-to-end. 64 total
  green, lint 0.
  Gotchas: (1) packaged mine-session skill deliberately diverges from the CMS
  original — `monition add`/`monition commit` instead of tools/takeaway.py,
  contract pointer instead of method/takeaway-store.md (it targets fresh host
  repos; CMS picks it up via sync at B06). (2) `dolt init` leaves the DDL
  uncommitted in the new store — same as the test fixtures; reader accepts;
  first `monition commit` snapshots it. (3) settings.json key order: existing
  keys keep their positions; our entries append (json round-trip preserves
  insertion order).
