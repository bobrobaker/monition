# Workstream: Tuning and Retrieval (Phase 4)

Progress: B01–B05 done — workstream complete (2026-06-12)
Blocked: none

## Objective

Read back the Phase 3 `decisions` table to measure EV scorer quality vs the
always-fire baseline, produce a `monition tune` recommendation, and add a lexical
`on_demand` matching engine for future MCP-driven disclosure. Embedding retrieval
and the MCP server are deferred until real usage drives them.

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
| B01 | done | buckets/B01_decisions-readback.md | `Store.decisions()` + report quality metrics | — |
| B02 | done | buckets/B02_threshold-tune.md | `monition tune`: improvement vs always-fire | B01 |
| B03 | done | buckets/B03_on-demand-lexical.md | `on_demand` keyword matching engine | — |
| B04 | done | buckets/B04_on-demand-embed.md | Embedding retrieval behind same interface | B03 |
| B05 | done | buckets/B05_mcp-server.md | MCP server + UserPromptSubmit hook wrapping `on_demand_match` | B03 |

States: `next`, `active`, `blocked`, `done`, `deferred`, `later`.

## Cross-Bucket Invariants

- Data contract: `docs/contracts/takeaway-store.md` — decisions section is the
  source of truth for the `decisions` table fields. B01 may read that section in
  full; B02 reads only the Decision semantics subsection.
- `decisions` reads go only through `Store.decisions()` — never raw `dolt sql`
  outside the approved reader.
- Tuning is recommendation-only: `monition tune` prints recommended constants and
  exits — it never auto-patches `score.py`. Constants in `score.py` are changed
  manually after reviewing the recommendation.
- Fail-open everywhere: tuning errors (e.g., insufficient data) print a warning and
  exit 0; they do not block sessions.
- on_demand matching uses the same per-session dedup semantics as edit_path: a
  takeaway fired once in a session is not re-fired in the same session.
- Contract update in B03: remove "no executor binds them yet (v1)" from the
  `on_demand` trigger_spec row — B03 binds it.

## Deferred / Non-Goals

- Auto-applying threshold changes — always recommendation-only.
- Embedding model selection / integration — B04, deferred.
- MCP server — B05, deferred (candidate).
- Multi-machine / config-based store path — deferred globally.
- `monition doctor` — deferred globally.

## Global Implementation Notes

- `Decision` dataclass fields: `id`, `takeaway_id`, `session_id`, `decided_at`,
  `decision` (fire|suppress), `evidence_count`, `cold_start` (bool), `ev_score`
  (Optional[float]). `ev_score` is NULL/None when `cold_start=True`.
- Dolt omits NULL columns from JSON output entirely — use `.get()` for nullable
  fields (`ev_score`, `session_id`) in `_sql()` results. (See generator prompt
  Updates, 2026-06-12.)
- `monition tune` exit criterion: show suppress_count, estimated_noise_saved,
  and improvement_pct vs always-fire baseline. "Sufficient data" gate: warn and
  exit if total evidence-based decisions < 10.
- B03's `on_demand_match(query, session)` returns JSON in the same shape as
  `match()` — list of `{id, one_liner}` dicts — so callers are interchangeable.
- B03 is independent of B01/B02 (different edit surface); it can be done after B01
  or in parallel if explicitly authorized.

## Updates

- [2026-06-12] Initial plan created. Phase 3 complete (B01–B03 done). Next: B01/decisions-readback.
- [2026-06-12] B01 done. Decision dataclass + Store.decisions() + decision_quality() + report block.
  Gotcha: adding decisions rows to conftest broke test_score.py queries by takeaway_id alone — fixed
  by adding session_id filter to those queries. 54 passed, lint clean. Next: B02/threshold-tune.
- [2026-06-12] B02 done. tune_recommendation() + render_tune() + monition tune CLI. 60 passed,
  lint clean. Next: B03/on-demand-lexical.
- [2026-06-12] B03 done. on_demand_match() + monition query CLI + contract update. CLI note:
  `match` was taken; used `query`. 68 passed, lint clean. B04/B05 deferred. Phase 4 complete.
- [2026-06-12] B04 un-deferred at user request (build ahead of need) and done: fastembed
  backend (consent question), hybrid pass in on_demand_match, `monition[embed]` extra.
  Cross-bucket gotcha: tests that pin lexical-only behavior must monkeypatch
  embed.semantic_scores off — a live model legitimately adds semantic hits. 79 passed, lint clean.
- [2026-06-12] B05 un-deferred at user request and done, scope expanded to both prompt-driven
  surfaces: `monition prompt-hook` (UserPromptSubmit executor — backbone-style: EV-scored,
  session-deduped, registered by init/sync) and `match_gotchas` MCP tool (`monition mcp-serve`,
  FastMCP via `monition[mcp]` extra, registered in `.mcp.json` — explicit pull: no scorer gate,
  no session dedup). Note the original "MCP surface is never the backbone" invariant: the
  prompt hook IS a backbone extension, deliberately, per user request. Contract on_demand row
  updated with both bindings. 92 passed, lint clean. Workstream complete.
