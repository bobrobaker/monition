# 2026-06-18 · A noise rating targets the Filter, not the Gate

**Status.** Design **direction**, investigation-grounded, **not implemented**.
Project-internal (pure machinery — no cross-repo confer; the row-firing pipeline is
monition's). Partially revisits the EV-gate design (`score.py`); does not delete it.
Surfaced as a parked direction in the semantic-daemon session and promoted here so
it steers the trigger/filter work when it resumes. Sibling:
`2026-06-18-semantic-embedding-warm-daemon.md` (the daemon is what makes the richer
filter layers below affordable on the hot path).

## Question

A row fires, the firing gets rated **noise**. What should the system *do* with that
signal?

Today it feeds the **Gate**. `score.py` computes one global number per row —
`ev_score = helpful / evidence_count` (`:27`), suppress if `< EV_THRESHOLD` (0.5,
`:10,30`) — across **all** that row's rated firings, with no context dimension. So a
noise rating pushes the row toward *global* suppression.

The pipeline has three stages (named this session):

- **Trigger** — `trigger_kind` hook dispatch (which executor fires). Fast.
- **Filter** — `trigger_spec` match, incl. semantic cosine
  (`store_write.on_demand_match:159`). The selective stage: *does this row apply
  here?* Slow stage (semantic load — hence the daemon).
- **Gate** — `score.py` EV. Cheap, non-LLM, evidence-based: *given it applies, is it
  worth firing?*

The question is which stage owns the response to a noise rating.

## Decision

**A noise rating is a signal about *targeting*, not *worth* — so the first-line
response belongs in the Filter, not the Gate.**

A row that is helpful in context X but noise in context Y is not a *bad row* — it is
a *mis-targeted* row. The right fix is to make the Filter more selective (add layers
— lexical → semantic → path / context / recency) so the row stops matching the noise
contexts while it keeps firing where it helps. Global EV suppression is **demoted to
a last resort**: it is correct only for a row that is noise essentially *everywhere*.

This is well-founded on data already captured, not a preference:

- `firings` records per-firing `trigger_context` and (v5) a situational excerpt
  (`store.py:135,142`).
- `metrics.audit()` **already partitions** each row's firings into
  `helpful_contexts` and `noise_contexts` (`metrics.py:101-108`). "Which contexts
  were noise" is therefore not just recordable — it is already computed per row. The
  substrate for filter-refinement exists.

Keep two axes **separate** — they were conflated this session under "more triggers":

- **More trigger *kinds*** (entry points, e.g. skill-invocation): breadth.
- **Deeper *filter*** (selectivity per firing): precision.

The noise insight argues the **second** is the higher-value direction. Adding entry
points without deepening the filter makes noise worse, not better.

## Why the current Gate response is wrong

`ev_score = helpful / evidence_count` is **context-blind** — one scalar over all
firings. Once net precision crosses below 0.5, the row is suppressed *globally*,
including in the contexts where it was the helpful majority. Suppression therefore
**conflates "this row is bad" with "this row fired in the wrong place,"** and the
failure mode is silent loss: you lose the row in X to punish its noise in Y.

## Options considered and why the rejected ones lost

- **A — status quo: noise feeds the global Gate.** Rejected: context-blind (above).
  Loses helpful firings to punish noise firings of the same row. Kept only as the
  last-resort case (noise-everywhere).
- **B — make the *Gate* context-aware instead of the Filter** (score precision per
  `trigger_context`, suppress a row only in its noise contexts). The closest
  competitor, and it uses the same `helpful_contexts`/`noise_contexts` substrate.
  Rejected as the *primary* response for three reasons: (1) it still fires-then-
  scores — the row pays the match every time and is killed after, where a tightened
  Filter stops the match up front; (2) the targeting lives invisibly in a
  statistical overlay rather than in the row's own `trigger_spec`, where "where this
  should fire" is legible and reviewable; (3) it needs accumulated per-context rated
  evidence before it can act, whereas a Filter layer (e.g. a path constraint) can
  encode targeting immediately. A per-context gate may still earn a place as a
  refinement *within* the Gate, but it is not the first-line answer to noise.
- **C — answer noise with more trigger *kinds*** (breadth). Rejected: orthogonal to
  the problem. Selectivity, not entry points, is what a noise rating asks for; more
  kinds without deeper filtering amplifies mis-targeting.
- **D — delete the Gate, do everything in the Filter.** Rejected: a row that is
  noise *everywhere* (helpful in no context) is a real case the Filter can't
  express — there is no context to exclude it from. The Gate stays as the
  last-resort suppressor; it is demoted, not removed.

## Anti-goals

- Do **not** let a single noise rating drive *global* suppression while the row is
  still the helpful majority in some context — that is the conflation this decision
  exists to end.
- Do **not** delete the Gate. It remains the correct mechanism for noise-everywhere
  rows.
- Do **not** pursue more trigger *kinds* as the answer to noise — keep breadth and
  selectivity as separate workstreams.
- Do **not** build filter-refinement machinery before there is real per-context
  noise data to refine against; the substrate exists, but the loop is gated on
  accumulated rated firings (same evidence discipline as `monition tune`).

## Seams this touches (from the code, not the docs)

1. `store_write.on_demand_match:159` — the Filter. Where new selectivity layers
   (path / context / recency, more semantic) would attach. Today: lexical → semantic
   cosine, fail-open at `:187`.
2. `score.py:10,27-30` — the Gate. `EV_THRESHOLD`, global `helpful/evidence_count`.
   This decision reframes its role (last resort) and flags the eventual per-context
   refinement (Option B) as a possible internal change, not a near-term one.
3. `metrics.py:90-114` `audit()` — already yields `helpful_contexts` /
   `noise_contexts` per row. The read-side substrate filter-refinement would consume.
4. `firings` schema (`store.py:135,142`) — `trigger_context` + v5 excerpt are the
   per-firing provenance that makes contexts learnable. No schema change needed to
   *measure*; a change may be needed to *encode* new filter layers in `trigger_spec`.

## Follow-ups

- Depends on the warm-embedding daemon
  (`2026-06-18-semantic-embedding-warm-daemon.md`): semantic filter layers are only
  affordable on the blocking hook path once the model is resident.
- When implementation starts, decide the **layer set** (which of path / context /
  recency / deeper-semantic) and how each is expressed in `trigger_spec` — that is
  the open design question this direction defers, not settles.
- `road.md §2` backlink pending (direction-setting, not yet ratified/implemented —
  same gate as the sibling daemon decision).
- Re-examine Option B (per-context Gate) once per-context rated volume is real; it
  may graduate from "rejected as first-line" to "a refinement within the Gate."
