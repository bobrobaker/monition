# Bucket B03: On-Demand Lexical

Parent: ../workstream.md
State: done
Goal for session: `on_demand` keyword matching engine + contract update.
Target duration: 20 min
Context budget: Read parent + this bucket + required touchpoints only.

## Conceptual mapping

All tasks share the `store_write.py` / `store.py` / `contracts/takeaway-store.md`
edit surface. The `on_demand` trigger_kind exists in the schema but has no executor.
This bucket adds the lexical matching engine (keyword matching against trigger_spec)
and updates the contract to reflect the new binding.

## Data contract / provenance

Report first (contract check):
- Which contract section applies? `### trigger_spec coordinate systems` — the
  `on_demand` row: "comma-separated keywords; no executor binds them yet (v1)".
- Producer: `WriteStore.on_demand_match(query, session)` (new). Consumer: future
  MCP server (B05); direct CLI callers.
- Inputs: `query: str` — free-text query from caller. `trigger_spec` per row:
  comma-separated keywords, whitespace-trimmed (same format as existing fields).
- Outputs: JSON list of `{id, one_liner}` dicts — same shape as `match()`.
- Matching: a row matches if any keyword from its trigger_spec appears as a
  case-insensitive substring of the query. (Verify at implementation time: is the
  matching direction keyword-in-query or query-word-in-keywords? Spec says keywords
  are in trigger_spec and query is the caller's text — so: does query contain keyword.)
- Dedup: same per-session dedup as `match()` — rows fired once this session are excluded.

## Tasks

- [ ] Add `WriteStore.on_demand_match(query, session=None)` to `store_write.py`:
  - SELECT active on_demand takeaways.
  - For each, check if any `trigger_spec` keyword appears (case-insensitive) in
    `query`.
  - Apply `_not_yet_fired(hits, session)` dedup.
  - Return `json.dumps(hits)` — list of `{id, one_liner}` dicts.
- [ ] Update `docs/contracts/takeaway-store.md`:
  - In `trigger_spec` coordinate systems: change the `on_demand` bullet from
    "no executor binds them yet (v1)" to "matched by `WriteStore.on_demand_match(query)`
    (v3 lexical executor); a row matches if any keyword appears case-insensitively
    in the caller's query string".
- [ ] Add `monition match <query> [--store PATH]` subcommand to `cli.py`:
  - Calls `WriteStore.on_demand_match(query)`, prints JSON to stdout.
  - Useful for ad-hoc testing and scripted integration.
- [ ] Add tests to `tests/test_on_demand.py`:
  - `test_match_returns_keyword_hit`: fixture takeaway with trigger_kind=on_demand,
    trigger_spec="migration" → query "database migration" → returns that row.
  - `test_match_case_insensitive`: trigger_spec="Migration" → query "migration" → matches.
  - `test_match_no_hit`: query "deployment" → row with trigger_spec="migration" → empty list.
  - `test_match_session_dedup`: same row already fired this session → excluded.

## Required touchpoints

- `src/monition/store_write.py`  lines 95–120  `_not_yet_fired`, `match`, `session_start`
  Pattern to follow for `on_demand_match` — same dedup helper, same return format.
- `docs/contracts/takeaway-store.md`  `grep -n "on_demand"` then bounded read of
  `trigger_spec coordinate systems` section
  Current contract text to update + exact wording to replace.
- `src/monition/cli.py`  `grep -n "def \|subparsers\|add_parser\|args.cmd"`
  CLI dispatch pattern for the new `match` subcommand.

## Conditional touchpoints

- `tests/conftest.py`  `grep -n "on_demand\|canonical_store\|SCHEMA"`
  Read only if adding an `on_demand` takeaway to the canonical fixture is needed for
  the dedup test — check existing fixture rows first.

## Do-not-read / avoid

- `src/monition/hooks.py` — no new executor wiring here (B05 handles MCP entry point).
- `src/monition/score.py` — on_demand scoring is out of scope for this bucket.

## Design direction

- Matching direction: query contains keyword (not keyword contains query). This allows
  short keywords ("migration", "auth") to match against longer free-text queries.
  Case-insensitive: `kw.lower() in query.lower()`.
- Return shape must exactly match `match()` output: `json.dumps([{id: int, one_liner: str}, ...])`.
  Do NOT include trigger_spec or other fields — callers use the same shape as edit_path hits.
- `_not_yet_fired` dedup: same per-session semantics. Pass `session=None` → no dedup
  (all matching rows returned) — same behavior as `match(path, session=None)`.
- No scoring call in this bucket: `on_demand_match` is a retrieval function, not an
  executor. Scoring for on_demand is deferred until B05 wires it.
- Contract update tone: state the binding factually ("v3 lexical executor"), avoid prose.
  Match the terseness of the other trigger_spec bullets.

## Validation

- `pytest tests/test_on_demand.py` — new tests pass.
- `pytest` — full suite green.
- `python tools/lint.py` — no ERRORs.
- Expected: `monition match "database migration" --store <path>` returns JSON with
  matching on_demand rows; non-matching query returns `[]`.

## Done criteria

- [ ] Tasks complete.
- [ ] Validation passes.
- [ ] Bucket `Updates` section records discoveries/gotchas/handoff.
- [ ] Parent workstream progress updated.
- [ ] Contract update committed: `on_demand` executor binding documented.

## Updates

- [2026-06-12] Created. Handoff: none yet. Gotchas: none yet.
- [2026-06-12] Done. 68 passed, 35 skipped, lint clean.
  Added `WriteStore.on_demand_match(query, session)`. Added `monition query <text>`
  CLI. Updated contract: on_demand bullet now describes the lexical executor.
  Added t7 (on_demand, trigger_spec="migration, schema") to conftest ROWS.
  Gotcha: adding t7 broke hardcoded `len(takeaways) == 6` counts in test_store.py
  and test_report.py — updated to 7.
  CLI note: `match` was already taken (edit_path path-matching); used `query`
  as the on_demand CLI subcommand instead.
