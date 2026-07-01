# 2026-07-01 — Row lifecycle: precision/recall framing, dilution-priced ratings, and the mutation track

**Status:** decided · frames Phases 6–7; also the rationale for the injection-cap /
cold-pause / dedup-at-birth changes landing now.

## Question

A store audit (CMS session, 2026-07-01) measured: 4,232 firings / 8.2% rated; 55% of
recent traffic from rows with <3 lifetime ratings (permanent cold start); no cap on
semantic fan-out (41–75 rows ≈ 3.5–6k tokens injected on session-opening/meta prompts);
three 4-copy duplicate row groups; mine-time policy exempting broad `on_demand` fires
from noise ratings. Suppression itself works (≈346k tokens avoided vs ≈350k spent).
What is the frame under which rows *improve* over their lifetime rather than only fire
or die?

## Decision

Adopt the **precision/recall frame with the trigger as a black-box module**:

- A row is `(trigger, payload)`. The trigger is a swappable, composable module —
  keyword, path glob, semantic threshold, tool-call pattern, state probe, or a layered
  combination. The engine only asks "does this module fire on this moment?".
- Ground truth per row is "the relevant moment occurred," made observable by a
  **violation signature** — a machine-checkable probe (regex/check over transcript or
  diff) for the failure the row warns about. That completes the confusion matrix:
  fired∧relevant (TP), fired∧irrelevant (FP — dilution), **not-fired∧relevant (FN)** —
  the cell ratings can never populate, because ratings only see firings that happened.
- **Mutation = search over trigger-module space, maximizing recall subject to a
  precision floor, preferring the most deterministic module at equal performance.**
  The determinism ladder — semantic → keyword → glob → tool-call → state probe — is the
  preference order: deterministic triggers are free at match time, exact in timing,
  auditable. Keywordless semantic matching is the module of last resort, demoted away
  from as firing data reveals what a row's moments look like.

Corollaries adopted with it:

1. **Irrelevant delivery is noise regardless of trigger breadth** (dilution is the
   cost). The CMS mine-session policy exempting broad-trigger fires from noise ratings
   is closed; batch dumps may be bulk noise-rated. This is what feeds the suppress gate
   on the highest-traffic rows.
2. **Cold-start is bounded, not permanent**: a row with many fires and zero ratings
   pauses until rated (`cold-pause`), instead of firing forever below the 3-rating
   gate.
3. **Semantic fan-out is capped per prompt** (top-K + char ceiling; lexical hits are
   never dropped — they are user-designed deterministic triggers). No silent
   truncation: a cap event is visible in the injection and the decision log.
4. **Duplicates fold, ratings pool**: near-duplicate detection runs against *active*
   rows at add time, and the pre-hub per-repo clone groups fold into single
   `reach=general` rows. Fragmented ratings can't clear the 3-rating gate.
5. **The unit of "already delivered" is the context window, not the session.**
   Sessions are stateless — a lesson delivered N sessions ago is gone, so cross-session
   cool-down would starve delivery. The real scheduling defects are: per-session dedup
   surviving a compaction that removed the firing from context (fix: re-arm after
   compaction), and the absence of a terminal exit for always-relevant rows (fix:
   graduation, below).
6. **Graduation criterion**: a row whose firing history converges to
   "fires nearly every session, consistently helpful" is unconditional in practice —
   it has earned guaranteed delivery (CLAUDE.md or equivalent always-on surface) and
   should exit the store's probabilistic path. Graduation and retirement are the only
   valid cross-session "cool-downs."
7. **Staleness exits the loop, doesn't lower precision**: a row whose referents
   (paths, commands, versions) no longer exist has undefined ground truth; a periodic
   probe flags it for refresh/retire rather than letting it decay into authoritative
   falsehood.

## Relation to "noise targets the Filter, not the Gate" (2026-06-18)

That decision stands and this frame is its generalization: mutation (trigger-module
search) *is* the Filter-first response, with Gate suppression the last resort for
noise-everywhere rows. Two cautions it contributes here:

- **Batch-dump noise labels carry a shared cause.** One meta-prompt lighting 19 rows
  is evidence about the prompt × row interaction, not 19 independent row defects
  (the 06-20 audit measured exactly this). Bulk noise ratings are still honest data —
  those firings *were* dilution — but the mutation engine must attribute
  shared-cause batches to the trigger/breadth layer before letting them push a row
  toward global suppression. Short-term (pre-Phase-7) the Gate consuming them is
  accepted: the injection cap shrinks batch dumps at the source, and suppression has
  a resurrection path.
- The spike's durable artifacts (the Layer concept with ABSTAIN, the cost-ordered
  cascade orchestrator, the `layer_eval` marginal-lift harness) are substrate for
  Phase 7's trigger-module evaluation — module search should be judged by the same
  rank-normalized conditional-lift discipline.

## Relation to the B02 NO-GO (2026-06-21)

This does not reopen the relevance cascade. B02 rejected a single *global learned head*
on 129 firings. Per-row threshold calibration (Phase 7) is the deliberately different
middle path: one interpretable parameter per row, moved by that row's own ratings, no
training pipeline. Any *learned* component proposed later still owes a B02-grade
pre-registered gate.

## Consequences

- Phase 6 (violation signatures + firing-evidence capture) is the data foundation; the
  mutation engine (Phase 7) consumes its FN/FP signal. Building mutation before the
  signal exists would mutate on ~8%-coverage vibes — sequencing is load-bearing.
- Firings must store the *full* matched evidence (text/path/tool-call that satisfied
  the trigger), not a lossy preview — trigger learning trains on exactly what
  production matched on.
