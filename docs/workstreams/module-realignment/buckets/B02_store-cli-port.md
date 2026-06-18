# Bucket B02: Store CLI port (characterized)

Parent: ../workstream.md
State: done
Goal for session: takeaway.py's command surface lives in the package, behavior-identical.
Target duration: 40 min
Context budget: Read parent + this bucket + required touchpoints only.

## Conceptual mapping

- One source file (`<CMS>/tools/takeaway.py`) ports into one package
  surface (`monition` subcommands + a writer module). Same SQL, same semantics,
  same output strings — a characterization port, not a redesign.

## Data contract / provenance

- Inputs/outputs: the v2 Monition store tables — `docs/contracts/takeaway-store.md`
  §"`takeaways` — per-field meaning", §"`firings` — per-field meaning",
  §"Dedup semantics" are the binding sections (required touchpoints below).
- Provenance: `source` column never substituted; `firings.trigger_context` for
  edit_path is the repo-relative match path.
- Validation: characterization diff against the CMS original (see Validation).

## Tasks

- [ ] Add a write-capable store module (e.g. `src/monition/store_write.py`)
      alongside the reader: `add`, `fire`, `rate`, `retire`, `dump`, plus the
      query paths `match`, `session-start`, `show`, `list`. Reuse the reader's
      contract/fingerprint check before any write.
- [ ] Wire them as `monition` subcommands with argument names and output
      formats identical to `takeaway.py` (JSON arrays for match/session-start,
      `firing N` line for fire, dump format byte-identical).
- [ ] Port the matching helper exactly: per-pattern comma split + strip +
      `fnmatch.fnmatch`; per-session dedup via `_not_yet_fired` query shape.
- [ ] Characterization tests: on a fixture store copy, run CMS
      `takeaway.py <cmd>` and `monition <cmd>` with identical args; assert
      byte-identical stdout for `match`, `session-start`, `show`, `list`,
      `dump`; assert identical resulting table contents (SELECT * dump) after
      `add`/`fire`/`rate`/`retire`.

## Required touchpoints

- `<CMS>/tools/takeaway.py`  (full read, ~260 lines)  the port source and oracle
- `src/monition/cli.py`  (full read, 26 lines)  subcommand wiring point
- `src/monition/store.py`  grep -n "def \|StoreContractError"  reader API + fingerprint check to reuse, not duplicate
- `tests/conftest.py`  grep -n "def \|INSERT INTO"  fixture-builder pattern for store copies
- `docs/contracts/takeaway-store.md`  §trigger_spec coordinate systems + §Dedup semantics (grep -n "^##" first)  binding semantics

## Conditional touchpoints

- `<CMS>/takeaways/` live store — read only if a fixture can't
  reproduce a behavior question; never write (cross-bucket invariant).

## Do-not-read / avoid

- `src/monition/metrics.py`, `report.py` — untouched by this bucket.
- Any redesign temptation (better arg names, richer JSON): rejected at spec
  time; identity now, improvements after cutover.

## Design direction

- Report first (contract check): which contract sections bind each ported
  command; what the characterization diff will prove.
- Characterization assertion level: byte-identical stdout for read commands;
  full-table equality (every column, every row) for write commands. Datetime
  columns (`NOW()`) are the only permitted divergence — normalize or freeze
  them explicitly in the test, never widen the assertion.
- The CMS originals must remain untouched — they are the oracle until B06.

## Validation

- `.venv/bin/pytest` — all existing 18 tests plus new characterization tests green.
- Expected: zero diffs in characterization runs (modulo normalized datetimes).

## Done criteria

- [x] Tasks complete.
- [x] Validation passes.
- [x] Bucket `Updates` section records discoveries/gotchas/handoff.
- [x] Parent workstream progress updated.

## Updates

- [2026-06-11 19:55] Created. Handoff: none yet. Gotchas: none yet.
- [2026-06-11] Done. `src/monition/store_write.py`: `WriteStore(Store)` — inherits
  the reader's fingerprint validation and `_sql`, so every lifecycle command is
  contract-checked on open; ports add/list/show/match/session-start/fire/rate/
  retire/dump **and `commit`** (not in this bucket's task list, but part of
  takeaway.py's surface — included per the goal line "command surface ...
  behavior-identical"). `cli.py` wires them as subcommands, arg names identical
  to the oracle, plus `--store` (default: convention path via
  `$CLAUDE_PROJECT_DIR`, fallback `git rev-parse --show-toplevel`, + `/monition`
  — `resolve_store_path()`, reusable by B03 hooks). Helpers `esc`/`val`/`iid`
  ported verbatim, including the t3/f4 id forms.
  Characterization (`tests/test_characterization.py`, 24 tests): oracle runs from
  a copied repo layout (tmp/tools/takeaway.py + tmp/takeaways/) because the
  script hardcodes its store relative to its own path — CMS original and live
  store untouched. Byte-identical stdout for list/show/match/session-start/dump
  (+ dump.sql file bytes); full-table equality after add/fire/rate/retire with
  only `created`/`fired_at` normalized; one multi-step lifecycle sequence test.
  All 42 tests green (`.venv/bin/pytest`, dolt on PATH); lint exit 0.
  Gotchas for B03/B06: (1) the port store fixture must be *named* `takeaways/`
  or dump's parent-relative stdout differs — after the B06 `git mv takeaways
  monition`, `monition dump` will print `monition/dump.sql`; any CMS doc/hook
  asserting the old string must update. (2) `python -m monition.cli` in
  subprocess tests needs PYTHONPATH=src (package not installed in the venv;
  pytest only injects pythonpath in-process). (3) Error-path behavior
  (RuntimeError vs StoreContractError wording) intentionally NOT characterized —
  only success-path stdout/table state is the contract.
