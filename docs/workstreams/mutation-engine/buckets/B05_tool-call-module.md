# Bucket B05: Tool-call module + executor

Parent: ../workstream.md
State: later
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

- [ ] Implement the module per B01's spec; wire into the PreToolUse executor
      (extend the existing fire-hook matcher dispatch; the settings.json
      matcher may need widening from `Write|Edit` — check instrument()).
- [ ] Schema/migrate/reader updates per B01's enum decision (v8 rung: version
      order + per-indicator table guards).
- [ ] EV-scoring, session dedup, and injection-cost accounting apply unchanged
      (a tool_call fire is a disclosure like any other).
- [ ] Migrate ONE consenting live row end-to-end as the smoke test (candidate:
      t91 "about to git push" → Bash `git push`), via the consented narrow verb
      with old-spec provenance — this is the first live ladder migration and
      feeds the exit gate.

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

- [ ] Tasks complete.
- [ ] Validation passes.
- [ ] Bucket `Updates` section records discoveries/gotchas/handoff.
- [ ] Parent workstream progress updated.

## Updates

- [2026-07-01 20:11] Created. Handoff: none yet. Gotchas: none yet.
