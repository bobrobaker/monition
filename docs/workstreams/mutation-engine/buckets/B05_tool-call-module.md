# Bucket B05: Tool-call module + executor

Parent: ../workstream.md
State: done
Goal for session: "About to run X" rows fire on tool calls.
Target duration: 45 min
Context budget: Read parent + this bucket + required touchpoints only.

## Conceptual mapping

- The first NEW module on the determinism ladder, and the proof the B01/B02
  seam composes: a `tool_call` trigger kind matching PreToolUse tool
  name + input patterns (e.g. Bash command `git push`), firing at execution
  moment instead of prompt-text moment. One surface: module + fire-hook
  executor + schema/contract per B01's enum decision.

## Data contract / provenance

- Inputs: PreToolUse hook JSON (`tool_name`, `tool_input`) — the existing
  fire-hook already receives it for Write|Edit; a tool_call row matches against
  tool name + a bounded input field (B01 decided the spec spelling; verify
  against a real hook payload at implementation time).
- Outputs: firings with `trigger_kind='tool_call'`, `match_evidence` =
  `{"module":"tool_call","pattern":…,"tool":…,"matched":<the input text>}`;
  schema/contract changes per B01 (enum widening = v8 rung + fingerprint +
  migrate, with the table-presence guard).
- Validation: contract §Versioning updated if v8; conformance on both backends.

## Tasks

- [x] Implement the module per B01's spec; wire into the PreToolUse executor
      (extend the existing fire-hook matcher dispatch; the settings.json
      matcher may need widening from `Write|Edit` — check instrument()).
- [x] Schema/migrate/reader updates per B01's enum decision (v8 rung: version
      order + per-indicator table guards). (Already shipped atomically in B03
      — nothing left to do here; confirmed by the tool_call insert test.)
- [x] EV-scoring, session dedup, and injection-cost accounting apply unchanged
      (a tool_call fire is a disclosure like any other — same _disclose path,
      dedup test in tests/test_tool_call.py).
- [x] Migrate ONE consenting live row end-to-end as the smoke test (candidate:
      t91 "about to git push" → Bash `git push`), via the consented narrow verb
      with old-spec provenance — this is the first live ladder migration and
      feeds the exit gate. (User consented 2026-07-02; applied via
      `set-trigger`; live tool_call firing f4459 observed same session.)

## Required touchpoints

- `docs/contracts/takeaway-store.md  grep -n "Trigger modules"  spec spelling`
- `src/monition/hooks.py  grep -n "def fire_hook\|tool_input\|file_path"  PreToolUse executor`
- `src/monition/init_sync.py  grep -n "_merge_hook_entries\|Write|Edit"  hook matcher instrumentation`
- `src/monition/store.py  grep -n "_detect_stale_schema"  ladder (if v8)`
  Version-order + table-presence guards, both load-bearing.

## Conditional touchpoints

- `tests/test_init_sync.py  grep -n "test_migrate"  migrate test pattern`
  Read when writing the v8 migrate test.

## Design direction

- Hook budget: PreToolUse fires on EVERY matched tool call — the tool_call
  match must be pure string/glob work on already-loaded rows (no embeddings,
  no extra store reads).
- Fail-open: malformed tool_input → no match, never an exception.
- Do not auto-migrate any row — the t91 migration is a consented edit and the
  road's lifecycle exemplar.

## Validation

- Full suite green incl. new conformance + migrate tests on both backends; a
  synthetic-store hook test proves a tool_call row fires on a matching Bash
  input and not on a non-matching one.
- Expected: live smoke — after consent, t91 fires on an actual `git push`
  PreToolUse moment with tool_call match_evidence.

## Done criteria

- [x] Tasks complete.
- [x] Validation passes.
- [x] Bucket `Updates` section records discoveries/gotchas/handoff.
- [x] Parent workstream progress updated.

## Updates

- [2026-07-01 20:11] Created. Handoff: none yet. Gotchas: none yet.
- [2026-07-02] Built and tested; t91 migration awaiting user consent. Shipped:
  `modules.tool_call_match` (spec: `{"tool", "field", "contains"}` JSON —
  exact tool name + any-of case-sensitive substring on one bounded
  tool_input field; pure string work, fail-open read-side, strict write-side
  gate `validate_tool_call_spec` in add + set_trigger);
  `WriteStore.match_tool_call`; fire_hook runs BOTH flows (edit_path on
  file_path + tool_call on tool_name/tool_input, one _disclose per flow —
  never per hit, the O(N) firings-read antipattern); instrument matcher
  widened `Write|Edit` → `Write|Edit|Bash`; `set_trigger` narrow verb
  (`migrate_kind` mutation, kind+spec atomic, event-grain provenance) + CLI
  `set-trigger`; contract §trigger_spec gains the tool_call coordinate
  system. 13 new tests; suite 312 passed / 2 skipped. This repo synced
  (matcher replaced, foreign hooks preserved).
  Discoveries: (a) `_merge_hook_entries` keyed staleness on command only — a
  matcher-only change silently never propagated; fixed (entry matcher now
  part of the currency check) and the v8 widening immediately exercised it.
  (b) **Dialect quoting bug (pre-existing, live)**: `esc()` used MySQL
  backslash-escaping on both backends; on SQLite (backslashes literal) any
  value with `\` or `'` corrupted — an apostrophe in a prompt context broke
  the firing INSERT → hook fail-open, silent. Fixed at the seam:
  `backend.quote()` per dialect, store methods use `self._val`; module-level
  `val`/`esc` are Dolt-only (the fold). Round-trip regression tests in both
  conformance suites. Flagged for mining.
  Gotchas: settings.json hook changes need a session restart to take effect
  — the live t91 smoke test fires in the NEXT session's first `git push`.
  Handoff: after t91 consent + a live tool_call firing lands, the exit-gate
  exemplar (row born broad → migrated down the ladder) is half-proven; the
  helpful-rate half accrues from its ratings.
- [2026-07-02] t91 migration CONSENTED and applied (`migrate_kind` mutation
  logged with full old kind+spec; verified via reader + production
  `match_tool_call`). Live smoke landed immediately: the hook config
  reloaded in-session and t91 fired as f4459 — on a Bash command whose
  python-heredoc CONTAINED "git push origin main" rather than an actual
  push. Rated noise (honest dilution). New gotcha for the exit-gate
  narrative and B06: **tool_call substring needles match mentions as well as
  acts** (a heredoc, an echo, a grep pattern) — same caution as v7's
  URL-shaped violation signatures; a future mutation proposal might prefer
  anchored needles (e.g. command starts with "git push") if mention-noise
  recurs. First lifecycle half proven: born broad (on_demand keywords) →
  migrated down the ladder with provenance → firing at execution moments.
