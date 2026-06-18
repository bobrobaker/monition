# Workstream: Module Realignment (Phase 2)

Progress: all done (B01–B06 complete, 2026-06-11)

## Objective

Turn Monition into the installable module that owns all takeaway machinery, per
`docs/specs/2026-06-11-module-realignment.md` (accepted with CMS amendments via
confer, 2026-06-11): port CMS's store CLI and hook executors into the package,
build `init`/`sync`/`migrate`/`--adopt`, then cut CMS over. Data stays
per-project; fail-open covers absent *and* broken.

## Execution Protocol (do not change)

1. Read this workstream first. For B01, read the full file. For B02+, do NOT use `cat` — run `grep -n "^##" workstream.md` first to get section line anchors, then use bounded reads for only: Objective, Execution Protocol, Bucket Index, and Cross-Bucket Invariants — skip Deferred/Non-Goals, Estimate, and any lower boilerplate sections.
2. Use `Progress` and `Bucket Index` to select the active bucket; if none is active, select the next bucket.
2a. If the index references a bucket file that does not exist yet, read `## Bucket template` in the generator prompt before creating it.
3. Open only the selected bucket file. If its `State` is not `active`, update it to `active` before reading touchpoints.
4. Read only that bucket's required touchpoints before reporting.
5. Report first: selected bucket, required touchpoints read, current behavior, proposed edits, validation plan, and extra touchpoints if needed.
6. Only edit after the plan is clear.
7. Run the bucket's validation.
8. Update the bucket file's `Updates` section with completed tasks, discoveries, gotchas, test results, and handoff notes.
9. Update this workstream's `Progress`, `Bucket Index`, and `Updates` only for progress, sequencing changes, cross-bucket discoveries, and cross-bucket gotchas. Also update the next bucket file's `State` from `later` to `next`. Use the Read tool (not Bash `cat`) to open workstream.md before editing it — Edit requires a prior Read call.
10. Keep only one bucket active at a time unless the user explicitly authorizes parallel execution.

## Bucket Index

| B | State | File | Goal | Depends |
|---|---|---|---|---|
| B01 | done | buckets/B01_governed-docs.md | Rewrite CLAUDE.md, road.md, contract preamble to module world | — |
| B02 | done | buckets/B02_store-cli-port.md | Port takeaway.py lifecycle commands into package, characterized | B01 |
| B03 | done | buckets/B03_hook-executors.md | Port hook executors; guarded fail-open (absent + broken) | B02 |
| B04 | done | buckets/B04_init-sync-migrate.md | `monition init`/`sync`/`migrate` | B03 |
| B05 | done | buckets/B05_interchange-adopt.md | Tier-0 interchange format in contract + `init --adopt` | B04 |
| B06 | done | buckets/B06_cms-cutover.md | CMS cutover: delete tools, rewire, rename, verify | B05 |

States: `next`, `active`, `blocked`, `done`, `deferred`, `later`.

## Cross-Bucket Invariants

- Data contract: preserve `docs/contracts/takeaway-store.md`; buckets touching
  store fields, matching semantics, or the interchange format read the relevant
  section before editing. B01 retitles/reframes the preamble; B05 adds the
  interchange section; nothing else edits the contract.
- Behavioral identity: ported code reproduces CMS originals exactly — fnmatch
  per-pattern split/strip, per-session dedup via `firings`, `"unknown"` session
  fallback, repo-relative paths, JSON/output formats. CMS's
  `tools/takeaway*.py` are the characterization oracle and MUST survive
  untouched until B06.
- Fail-open: a hook must never block a session. Absent module → silent no-op
  (existence guard in the command string); broken module → session unblocked,
  stderr appended to `~/.local/state/monition/hook-errors.log`.
- Real-store safety: nothing writes to `<CMS>` (store or repo) before
  B06; tests write only to tmp/fixture stores.
- Schema stays v2 throughout; the `decisions` table is Phase 3.
- Vocabulary: "Monition store" (the per-project Dolt instance, convention path
  `<repo-root>/monition/`), "takeaways" (rows). Never "monitions" for rows.
- Trigger-as-data: rows own what-fires-when; the module owns only how matching
  executes.

## Deferred / Non-Goals

- `monition score`, `decisions` table, cold-start threshold — Phase 3.
- MCP on-demand query surface — Phase 4 candidate.
- Tier-0 payload authoring (markdown lessons + frozen executor in the CMS
  payload) — CMS-session work; B05 only owns the format and the importer.
- `monition doctor` — deferred unless the error log proves insufficient.
- Config for non-convention store paths; multi-machine install story.

## Global Implementation Notes

- Source spec: `docs/specs/2026-06-11-module-realignment.md` (decisions 1–14).
  Consent for CMS-side edits: confer thread "2026-06-11 confer
  takeaway-machinery-ownership".
- Install mode: global editable (`uv tool install --editable .`); entry point
  already in `pyproject.toml`.
- Host repo root in hooks: `$CLAUDE_PROJECT_DIR` (set for hook commands),
  fallback `git rev-parse --show-toplevel` from cwd.
- Validation everywhere: `.venv/bin/pytest` with `~/.local/bin` on PATH for dolt.

## Updates

- [2026-06-11 19:55] Initial plan created from the realignment spec. Next: B01/governed-docs.
- [2026-06-11] B01 done (lint 0; contract diff confined to preamble + one
  Versioning repair-path line; one deliberate "read-only" hit remains in road.md's
  Phase 1 history block). Cross-bucket note for B02/B05: the contract's producer
  table now names commands generically ("module lifecycle commands") because
  subcommand names aren't settled; if B02's chosen names warrant naming them in
  the table, that contract edit belongs to B05 per the invariants.
- [2026-06-11] B02 done: WriteStore + 10 subcommands wired, 24 characterization
  tests, 42 total green, lint 0. Cross-bucket: `resolve_store_path()` in
  store_write.py is the convention-path resolver B03's hooks should reuse; after
  B06's rename, `monition dump` prints `monition/dump.sql` (oracle printed
  `takeaways/dump.sql`) — check CMS pre-commit hook for string expectations.
- [2026-06-11] B03 done: hooks.py executors + guarded_hook_command(), uninstall
  and crash tests both green (spec exit criteria). 54 tests, lint 0.
  Cross-bucket: B04 writes `guarded_hook_command("fire-hook"/"session-brief")`
  into settings.json verbatim; B06 must update the injection framing text
  (still names tools/takeaway.py for byte-identity) and the executor
  byte-match tests with it.
- [2026-06-11] B04 done: init/sync/migrate + 10 tests (64 total, lint 0).
  Cross-bucket: packaged mine-session skill already speaks `monition` commands
  (not tools/takeaway.py) — at B06, CMS's skill upgrade flows through `sync`'s
  hash check (CMS's installed copy has no stamp → "edited" → WARN; expect a
  manual accept there). Migrate's mapping sentence added to the contract's v2
  note (the one allowed B04 contract edit); B05's interchange section is the
  only remaining contract change.
- [2026-06-11] B05 done: interchange section in contract (additive), adopt.py
  importer through WriteStore.add, `monition adopt` + `init --adopt`. 68 tests,
  lint 0. All contract edits this workstream allows are now complete — B06
  touches no Monition-side contract text except the executor hint strings in
  hooks.py and their byte-match tests.
- [2026-06-11] B06 done: user explicitly consented to settings.json write;
  tools/takeaway*.py deleted; CMS commit 1b8dda9 (pre-commit passed: lint +
  monition dump). Post-cutover: 33 tests pass, 35 skip (oracle gone by design).
  Phase 2 complete. road.md phase marker moved to Phase 3.
