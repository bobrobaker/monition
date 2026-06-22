# 2026-06-21 — Relevance cascade: B02 NO-GO, workstream paused

**Status:** decided · closes the active run of Phase 5 (relevance-cascade) at B02.

## Question

Does the learned relevance head `L2′` clear the B02 usefulness gate — and therefore
justify building and wiring the cascade runtime (B03–B05) into the passive `on_demand`
fire path?

## Decision

**NO-GO.** The head does not clear the gate. The relevance-cascade workstream is
**paused** at B02: B03–B05 do not start, no head artifact is serialized. This is the
fail branch the Phase 5 exit clause already anticipated ("on fail — the phase
pauses/closes with the finding recorded; no integration on an unproven head").

## The gate and the bar

The bar was set with the user **up front**, before any number was seen (so it could not
be rationalized after the fact): **the 95% CI lower bound of leave-row-out CV AUC must
exceed 0.60**, measured on the human-only B01 dataset (129 firings / 46 distinct rows),
with a usable operating point existing. The CI is a cluster bootstrap over *rows* (not
firings), because within-row firings are correlated.

## Result (honest, leak-free evaluation)

| head / feature (row-disjoint LORO) | CV-AUC | 95% CI |
|---|---|---|
| cosine alone | 0.441 | [0.33, 0.55] |
| logistic on product (spike's winner) | 0.669 | [0.551, 0.778] |
| concat | 0.628 | [0.53, 0.72] |
| PCA20(concat) | 0.638 | [0.52, 0.75] |
| PCA40(concat) — best | 0.676 | **[0.582, 0.762]** |

- **Signal is real but modest.** Every learned head lands at AUC ~0.63–0.68 — clearly
  above the 0.5 baseline and above cosine (0.44, useless under honest evaluation). The
  learned-head-beats-cosine claim holds.
- **No head clears the gate.** The best CI lower bound anywhere — even cherry-picking the
  variant *by* its CI, which is gate-gaming — is **0.582 < 0.60**.
- **Robust to model choice and regularization.** An L2 sweep {2…800} confirmed the point
  estimate plateaus at ~0.667 and only *falls* with stronger regularization (train AUC is
  1.000 with a 0.33 gap at low L2 — overfit — but the honest CV ceiling does not move).
  This is not a tuning miss.

## Why NO-GO, not "tune more" / "lower the bar"

- **It is a volume/variance wall, not a model bug.** 46 distinct rows is too few to
  estimate AUC tightly (AUC SE ≈ 0.06–0.08 here), so the CI is wide regardless of model.
- **The bar was not relaxed.** Lowering the CI-lower-bound bar to 0.55 after seeing that
  product/PCA40 clear it is the exact post-hoc rationalization the up-front bar existed to
  prevent. Offered to the user explicitly; declined.
- **Operationally the head is weak even at its best point.** At a threshold keeping ≥90%
  of helpful rows it suppresses only ~20% of noise — moving noise's share of fires from
  ~54% to ~50%. Given the asymmetric error cost (dropping a helpful row destroys the value
  the system exists to deliver; keeping a noise row only adds clutter), a weak ranker run
  conservatively buys little.

## Disposition

Paused, **not** pursuing oracle expansion now (the user's call: not worth the effort at
this time; may revisit later or hand to an overnight autonomous agent). The legitimate
expansion path, if revisited, adds **NEW rows** via the offline oracle — the 380 unrated
firings are more firings of the *same* 46 rows and would not move the row constraint.

## Revisit note — the spike rested on two false assumptions

A future revisit (see the postmortem flag, 2026-06-21) should re-open the spike's
premises, both of which proved untrustworthy on its n=102 leaky fixture:

1. **The 0.78 headline was leakage-inflated.** Under honest row-disjoint evaluation the
   head is ~0.67, not 0.78 (B01 red-team C1/C2). road.md Phase 5's "spike-validated at
   0.78" is corrected here.
2. **The metamatch ("is the prompt/row meta?") negative result is equally untrustworthy.**
   The spike buried metamatch as a "cheap proxy that doesn't separate" — but on the *same*
   leaky n=102 fixture that produced the inflated 0.78. If we distrust the positive, we
   must distrust the negative. Metamatch is a near-one-parameter signal, so it is far more
   *estimable* under data scarcity than a 384-dim head — the data wall that sinks the head
   bites it far less. It deserves an honest row-disjoint re-test before being dismissed.

Neither the cascade orchestrator (B03) nor metamatch is live — the workstream produced
only the B01 dataset and the B02 head (`src/monition/relevance/`).

## Supersession audit

- **Affirms** `docs/contracts/relevance-cascade.md` §2 (validity clause: "an artifact
  ships only if it clears the B02 usefulness gate") — the gate fired as designed; no
  artifact ships. Contract unchanged.
- **Affirms, does not supersede** `2026-06-18-noise-targets-the-filter-not-the-gate.md` —
  noise still targets the filter; the filter simply did not clear the bar at this data
  volume. That decision stands.
- **Corrects** road.md Phase 5's "spike-validated at 0.78 grouped-CV AUC" — that number
  was leakage-inflated; the honest figure is ~0.67 (this doc).
- No `road.md §2` design position is superseded.
