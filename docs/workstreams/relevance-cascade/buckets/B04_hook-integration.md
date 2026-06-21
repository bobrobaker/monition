# Bucket B04: Hook Integration

Parent: ../workstream.md
State: later
Goal for session: Gate the passive on_demand path with the cascade; leave pulls ungated.
Target duration: 30 min
Context budget: Read parent + this bucket + required touchpoints only.

## Conceptual mapping

- One mental model: *wire the B03 runtime into the live fire path, passive only*. The noise
  is auto-firing on conversational prompts; explicit pulls are intentional and stay ungated.
  Edit surface: the prompt-hook executor and (carefully) the matcher seam.

## Data contract / provenance

- Inputs: candidate rows from the existing `on_demand_match` lexical+semantic stage.
- Provenance: the cascade ranks/filters *candidates*; it does not change *which* rows are
  candidates' provenance or the per-session dedup. If score logging was chosen in B01 §3,
  wire it here and bump `docs/contracts/takeaway-store.md` (firings) — nullable column,
  `head_version` alongside the score, `row.get` for NULL-omitting Dolt JSON.

Report first (contract check): does this touch the firings contract (score logging)? what
producer/consumer? what could break? how validated?

## Tasks

- [ ] Insert the cascade on the **passive** path only: `hooks.py:prompt_hook` (≈:266) where
  `on_demand_match` results are disclosed. The cascade decides which candidates fire.
- [ ] Leave `mcp_server.py` (≈:27) and `cli.py query` (≈:413) calling `on_demand_match`
  **unchanged** (ungated). If the gating lives inside `on_demand_match`, gate it behind a
  param that only `prompt_hook` sets — do not gate the shared matcher for all callers.
- [ ] Preserve per-session dedup (`_not_yet_fired`) — confirm ordering vs the cascade
  (dedup before or after gating, but a row fired once in a session still must not re-fire).
- [ ] Tag candidate rows with `kind` if the cascade/L2′ needs it (the matcher currently
  returns only `{id, one_liner}` — extend the select, do not re-query per row).
- [ ] (If B01 chose to log) wire per-firing score logging at the disclosure point.

## Required touchpoints

- `src/monition/hooks.py`  `grep -n "def prompt_hook\|on_demand_match\|_disclose\|_not_yet"`
  (≈:252–276) — the passive executor + disclosure + dedup.
- `src/monition/store_write.py`  `grep -n "def on_demand_match\|_not_yet_fired"` (≈:202,179)
  — the matcher + dedup; where gating attaches; the `{id, one_liner}` return shape.
- the B03 runtime module — `grep "## Updates" B03_cascade-runtime.md, then read from that
  offset` for the orchestrator entry signature + module path.

## Conditional touchpoints

- `src/monition/mcp_server.py` (≈:27), `src/monition/cli.py` (≈:413) — read only to CONFIRM
  they stay ungated; edit only if the gating param leaks to them by accident.
- `docs/contracts/takeaway-store.md`  firings section — read only if logging a firings column.

## Do-not-read / avoid

- `src/monition/score.py` — the EV Gate runs after disclosure; not changed here.

## Design direction

- The cascade gates the AUTO path; pulls are deliberate user asks → never gated. This is a
  cross-bucket invariant; violating it re-introduces the cost the user rejected (and silences
  intentional pulls).
- Fail-open on the hook: any cascade/embedding error → behave like today (don't crash the
  hook; degrade to current matcher or to no-suppression), per monition's fail-open rule.
- Do not re-query the store per candidate to get `kind` — widen the matcher's SELECT once.

## Validation

- A hook smoke test: a `<task-notification>` / meta prompt no longer injects the technical
  rows it used to (replay a known noise firing); a matching work prompt still injects.
- Confirm via an explicit `monition query` that pulls remain ungated (full recall).
- Per-session dedup test still green.

## Done criteria

- [ ] Cascade gates `prompt_hook` only; pulls verified ungated.
- [ ] Dedup preserved; `kind` (if needed) sourced without per-row re-query.
- [ ] Score logging wired + firings contract bumped, OR explicitly recorded as not-logging.
- [ ] Bucket `Updates` records the integration seam + any contract bump.
- [ ] Parent progress updated.

## Updates

- 2026-06-21 Created. Handoff: none yet. Gotchas: none yet.
