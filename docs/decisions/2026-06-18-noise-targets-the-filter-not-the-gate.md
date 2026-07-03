---
status: decided
---
# 2026-06-18 · A noise rating targets the Filter, not the Gate

**Status.** Design **direction**, investigation-grounded, **not implemented**.
**Amended 2026-06-20** (audit-grounded): the deferred layer-set question is now
resolved and the first-line lever is reframed — see *Update — 2026-06-20* at end.
**Amended 2026-06-21** (spike-validated): the 06-20 cheap-signal reframe is itself
superseded — a worktree spike refuted threshold/metaness filtering and validated a
learned embedding relevance head; see *Update — 2026-06-21* at end.
**Amended 2026-06-21** (B02 NO-GO): the spike's empirical numbers (the "leakage-free
0.78" and the metaness-match verdict) did NOT survive honest row-disjoint evaluation —
the honest head is ~0.67 and failed the B02 gate; the workstream is paused. Filter-not-Gate
still stands. See `docs/decisions/2026-06-21-relevance-cascade-b02-no-go.md`.
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

## Update — 2026-06-20 (audit-grounded)

The "wait for data" anti-goal has lapsed and the deferred layer-set question is
answered by an audit of the live hub (`monition report` over the v6 hub). The core
decision (Filter not Gate) stands; what changes is **which Filter layer is
first-line**.

**Data gate satisfied.** At write-time there were ~4 ratings; the anti-goal blocked
build until the ≥10-rated `tune` gate. The hub now holds **136 rated firings (66
helpful / 70 noise)**, and every noise firing carries `trigger_context`
(`store.py:135`). The blocker is gone — proceeded to audit, not build.

**Finding 1 — the noise is `on_demand` and *cross-row*, not per-row.** 54 of ~70
rated noise firings are on `on_demand` rows (`edit_path` noise is ~16 and mostly a
clean glob fix, e.g. t8: drop `.claude/*`, keep `tools/takeaway*.py`). The
`on_demand` noise concentrates on a few recurring **meta-prompts** — the user musing
about / asking about the system itself — each lighting up a *band* of rows at once.
Measured: `"When I ask you to help make a decision… you pull from your knowledge
vault"` = 0 helpful / 5 noise across 5 rows; `"Read the recent refactor notes…
/catch-me-up on support structures"` lit **19 rows**. The semantic Filter
(`store_write.on_demand_match:159`) treats reflective talk-about-the-system as a work
context and matches a whole class of system-rows.

**Finding 2 — the meta-prompt class is *not* cleanly droppable** (the global-prefilter
trap, verified against the helpful side). `"Read the recent refactor notes…"` is **5
helpful / 4 noise**: helpful on orientation / handoff / decision-helper rows, noise on
narrow technical-gotcha rows. The *same prompt* is right for one row and wrong for
another — so there is no binary "suppress `on_demand` on meta-prompts." This is the
decision's own anti-conflation, now at *prompt* granularity: the signal is
prompt × row, not prompt alone.

**Reframe — the first-line layer is cross-cutting, not per-row `trigger_spec`.**
Because one prompt fires 5–19 rows, narrowing each row's `trigger_spec`
independently (the originally-implied fix) is the wrong primary tool: it hand-edits
dozens of rows to fight a handful of prompts, and the per-row noise stats are
confounded by the shared cause. The first-line Filter layer is **row-breadth ×
prompt-specificity**: narrow technical-gotcha rows must clear a *higher match bar* so
they stop matching broad meta-prompts, while orientation/handoff rows stay loose.
Per-row `trigger_spec` narrowing is **demoted to a cleanup tool** for the ~2 cleanly
separable `edit_path` cases.

**Consequences for the options.** This pulls the design *toward* Option B's spirit —
the discriminator is a prompt × row interaction, not a static glob in `trigger_spec`
— without adopting B's per-context EV overlay. Re-examine B's graduation once the
breadth layer is specified. The Gate (`score.py`) stays last-resort; note it already
removes **51.6% of noise vs always-fire**, so its job here is unchanged. **Before
suppressing any of the ~17 `on_demand` "noise-everywhere" rows, apply the breadth
layer and re-measure** — most are narrow rows misfiring on meta-prompts and may clear
without retirement.

**Open for the first implementation bucket.** (1) How to encode "row breadth class" —
an explicit field, inferred from `trigger_spec` specificity, or learned from the
helpful/noise context spread `metrics.audit()` already computes
(`metrics.py:101-108`)? (2) The match-bar mechanism — a per-class cosine threshold in
`on_demand_match` vs a prompt-intent classifier on the hook path (the latter leans on
the warm-embedding daemon, `embed.py`). That is the layer's design question, now
concrete enough to dispatch.

## Update — 2026-06-21 (spike-validated)

> **⚠ Superseded in part — 2026-06-21 (B02 NO-GO).** Two empirical claims below did NOT
> survive honest evaluation, see `docs/decisions/2026-06-21-relevance-cascade-b02-no-go.md`:
> (1) Finding #4's "**0.78 grouped-CV AUC (whole-prompt holdout — leakage-free)**" was
> **leakage-inflated** — a whole-prompt holdout over only ~46 rows leaks ROW identity (a
> per-row prior alone hits 0.77), so it is *not* leakage-free. Honest row-disjoint
> leave-row-out CV puts the head at **~0.67**, and it failed the B02 usefulness gate.
> (2) Finding #3's metaness-match verdict ("real but insufficient, ~0 conditional lift")
> was measured on the **same leaky n=102 fixture**, so it is equally untrusted and should
> be re-tested before being relied on. **The core decision (Filter not Gate) still
> stands**; only the spike's empirical numbers are corrected. The relevance-cascade
> workstream is paused.

A throwaway worktree spike (`spike/relevance-cascade`) built the structure and replayed
it against the **102 rated `on_demand` firings** from the live hub. It **supersedes the
06-20 per-kind-threshold / breadth-class framing**: those directions were tested and
refuted; a learned embedding head was validated. The core decision (Filter not Gate)
still stands.

**What was built (durable artifacts):**

- **The Layer concept** — a relevance estimator with a known *cost*:
  `evaluate(context, candidates) → {id: (category, certainty)}`, with `ABSTAIN`
  first-class. Per-prompt gates are the uniform-verdict special case.
- **A cost-ordered, certainty-gated cascade orchestrator** — runs layers cheapest-first
  on the *unsettled* residual; stops at `TARGET_CERTAINTY` or a `TIME_BUDGET`
  (= fraction × hook window). Pre-emptive budget check; fail-closed-on-firing at commit.
- **`layer_eval` — the "should this layer earn a place?" harness.** Consumes Layer
  objects + labeled firings; reports marginal AUC, redundancy, and **conditional lift**
  (separation a layer adds *given the rest*) via a CV'd combiner. This is the
  "add a layer → recommend from data" tool the workstream needs.

**Findings (AUC vs human helpful/noise, n=102):**

1. **Cheap scalar signals are refuted as the fix.** lexical 0.55, admissibility 0.53,
   cosine 0.63, metaness-match 0.64 — and an optimal *correlation-aware* combiner of all
   cheap signals reaches only ~0.61. No threshold/gate on these separates without losing
   ~half the helpful firings (blocking 38 noise costs 25 of 48 helpful).
2. **The discriminator is a (prompt × row) comprehension judgment** — deterministic
   (0 within-cell label conflicts) but *pairwise*: 8 prompts are helpful for one row and
   noise for another. So a prompt-only meta-gate has a hard ceiling.
3. **The metaness-match hypothesis is real but insufficient.** P(noise | metaness-mismatch)
   = 70% vs 45% on match — a genuine, *decorrelated* signal, but as a gate it costs ⅓ of
   helpful and adds ~0 conditional lift. The binary meta/work axis can't do *within-class*
   selection.
4. **The signal is in the embeddings.** A learned head over the **full** embedding vectors
   (not the cosine scalar) reaches **0.78 grouped-CV AUC** (whole-prompt holdout —
   leakage-free), matching an offline LLM comprehension judge (0.78) and far above cosine
   (0.63). Cosine was discarding the signal by collapsing 384 dims to one number.

**What stands → the lever.** Replace raw-cosine `L2` with **`L2′` — a learned relevance
head over the (prompt, row) embeddings**, trained on accumulated labels. Same hot-path
cost as today's semantic match (one embedding per prompt) + a microsecond head;
**no inline LLM in production.** The LLM's role is the *offline oracle* (generate extra
training labels) plus validation — never on the hook path. The cascade reduces to
**L0 (admissibility) → L2′ (learned relevance)**; the Gate (`score.py`) stays last-resort.

**Lessons recorded:**

- **Layer recommendation must be calibration-invariant** — rank-normalize signals
  (Spearman + logistic-on-ranks) before correlation/lift, else the harness grades a
  layer's arbitrary certainty curve, not its information. (This flipped a redundant↔keep
  verdict mid-spike.)
- **LLM-as-oracle ≠ LLM-as-inline-component** — an LLM that labels data to train a cheap
  shippable filter is architecturally opposite to one that runs per request; the hot-path
  cost constraint makes the former the goal here.

**Caveats / path to production (NOT yet shippable):**

- The head **overfits at n=102** (train AUC 1.00); 0.78 carries ±~0.05 error bars.
  *Firm up with more labels* — rate more firings and/or expand via the offline oracle —
  before trusting the number or training a production head.
- 0.78 is **not a clean separator**; a real operating threshold still trades some helpful
  for noise. Pick the operating point from a precision/recall curve.
- Confirm the real UserPromptSubmit window before banking the `TIME_BUDGET` (assumed 30 s).

**Artifacts:** `spike/relevance-cascade` branch — `cascade.py`, `layer_eval.py`,
`run_eval*.py`, `embed_classifier.py`; fixtures regenerable from the hub via the dump
commands in the spike README.
