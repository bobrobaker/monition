# Bucket B05: MCP Server

Parent: ../workstream.md
State: done
Goal for session: MCP server exposing `on_demand_match` as a tool.
Target duration: 25 min
Context budget: Read parent + this bucket + required touchpoints only.

## Conceptual mapping

Wraps `WriteStore.on_demand_match()` (B03, or B03+B04 if embeddings are live)
behind an MCP tool so Claude can explicitly query gotchas during a session.
Backbone disclosure (edit_path + session_start) is unchanged — this adds a
non-harness, Claude-initiated path only.

## Tasks

- [x] [RESOLVE BEFORE STARTING] MCP server framework choice — FastMCP from the
      official `mcp` SDK, lazily imported, optional extra `monition[mcp]`.
- [x] `src/monition/mcp_server.py` — single tool `match_gotchas(query: str) -> str`.
- [x] Register in `pyproject.toml` or separate entry point — `monition mcp-serve`
      subcommand; `init`/`sync` merge the server into `<root>/.mcp.json`.
- [x] Fail-open: MCP errors never block sessions (same pattern as hooks).
- [x] Tests: direct function tests on the tool handler.

## Design direction

*(Deferred — see B03 for the matching engine this wraps.)*

Core invariant: MCP surface is never the backbone. `session_start` and
`edit_path` executors are not affected by this bucket.

## Validation

- Direct tool handler tests pass.
- `pytest` — full suite green.

## Done criteria

- [x] Tasks complete.
- [x] Validation passes.
- [x] Bucket `Updates` section records discoveries/gotchas/handoff.
- [x] Parent workstream progress updated.

## Updates

- [2026-06-12] Created as deferred (candidate). Promote to `later` when MCP tooling decision is made.
- [2026-06-12] Un-deferred at user request and done, expanded to cover both prompt-driven
  surfaces: (1) `monition prompt-hook` — a UserPromptSubmit executor (new, no CMS oracle)
  matching the user's prompt via `on_demand_match`, EV-scored + session-deduped like the
  backbone hooks; `init`/`sync` register it in settings.json. (2) `match_gotchas` MCP tool
  via `monition mcp-serve` (FastMCP, lazy import, `monition[mcp]` extra); explicit pull —
  no scorer gate, no session dedup (MCP has no session id), firings logged with
  `session_id` NULL so ratings still work. `init`/`sync` merge `.mcp.json`. Shared
  `_disclose()` helper extracted in hooks.py (oracle byte-tests unaffected; they skip
  post-cutover since CMS tools were deleted). Contract `on_demand` row now names both
  executor bindings. 92 passed, lint clean.
