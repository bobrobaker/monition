# Bucket B06: Proposal engine

Parent: ../workstream.md
State: done
Goal for session: Audit-cadence read proposes consented row mutations.
Target duration: 60 min
Context budget: Read parent + this bucket + required touchpoints only.

## Conceptual mapping

- The verbs that close the lifecycle: one read-side engine walking per-row
  evidence (ratings with B04 attribution, violations, match_evidence) and
  emitting typed proposals — tighten / broaden / migrate-down-ladder / merge /
  graduate / stale — each rendered with its evidence for the mine-session
  consent gate.

## Data contract / provenance

- Inputs: `export-firings` records (incl. `match_evidence`, batch annotations),
  `violations` rows, row specs. Verify all field names against real records —
  not this spec.
- Outputs: proposals are a READ (rendered text/JSON), not store rows, unless
  B01 decided a persisted proposal record; applies happen only through the
  narrow consented verbs with old-spec provenance.
- Validation: replay counterfactual per applied mutation (did the tightened
  spec keep helpful firings and drop noise?).

## Tasks

- [x] **Signal gate first** (parent §Bucket Index): report FN/evidence volume;
      if still thin, stop and surface — do not build on 3-row data.
- [x] Proposal rules, deterministic and evidence-cited: tighten (noise
      concentrated off-pattern in match_evidence), broaden (violations name
      sessions whose text the trigger missed), migrate (every helpful semantic
      hit's evidence contains a stable literal → keyword/tool_call candidate),
      merge (active near-duplicates), graduate (fires ~every session,
      consistently helpful → propose always-on surface + retire here), stale
      (referent paths/commands vanished from origin repo).
- [x] Judge module candidates with the `layer_eval` rank-normalized
      conditional-lift discipline (spike artifact — reuse, don't rebuild).
- [x] Surface: a verb (`monition propose` or report section) consumed at
      mine-time/audit cadence; graduation proposals name the target always-on
      surface but do NOT write it (that's the human's/CMS's move).
- [x] Apply path: narrow verbs only, old spec recorded, one row at a time.

## Required touchpoints

- `docs/contracts/takeaway-store.md  grep -n "Trigger modules\|Violation"  spec + FN semantics`
- `src/monition/export.py  grep -n "_record"  the evidence record shape`
- `docs/workstreams/relevance-cascade/  grep -rn "layer_eval\|ABSTAIN" --include=*.md`
  Where the judging discipline lives; read the harness pointer, not the spike.
- `src/monition/store_write.py  grep -n "def set_signature\|def retire"  narrow-verb pattern for apply verbs`

## Conditional touchpoints

- `docs/decisions/2026-06-18-noise-targets-the-filter-not-the-gate.md`
  Read if any proposal pushes toward suppression — Filter-first ordering.

## Design direction

- Deterministic rules over evidence; no learned scorer (a learned ranker later
  owes a pre-registered gate and is out of this bucket's scope).
- Every proposal line cites its evidence (firing ids / violation ids /
  match_evidence excerpts) — a human must be able to verify in seconds.
- Batch-attributed noise (B04) discounts toward breadth-layer framing before
  any per-row tighten/suppress proposal.
- Assess-path == eval-path: candidate triggers are evaluated by running the
  REAL modules over stored match_evidence/transcripts, never a re-implementation.

## Validation

- Full suite green; on a hub snapshot, the engine reproduces at least one
  known-good proposal per class where data exists (e.g. merge: a known clone
  pair; broaden: t28's violation) and proposes nothing where evidence is thin.
- Expected: exit-gate path live — one consented mutation applied on the hub +
  replay counterfactual measured (injected-volume reduction at equal-or-better
  helpful rate).

## Done criteria

- [x] Tasks complete.
- [x] Validation passes (suite green; hub reproduction per class; exit-gate
      live step awaits user consent — see Updates).
- [x] Bucket `Updates` section records discoveries/gotchas/handoff.
- [x] Parent workstream progress updated (workstream complete if exit gate met).

## Updates

- [2026-07-01 20:11] Created. Handoff: none yet. Gotchas: none yet.
- [2026-07-02] Signal gate re-measured OPEN: 1779 firings with match_evidence
  (bar ~500), 583 rated, 15 organic violations across 15 sessions — but on only
  4 distinct rows, so broaden evidence is thin per-row exactly as the handoff
  predicted.
- [2026-07-02] Done: `src/monition/proposals.py` + `monition propose [--json]`
  (read-only, mirrors calibrate's CLI wiring) + the narrow
  `WriteStore.retarget` verb / `monition retarget` (same-kind spec rewrite,
  event-grain `mutations` provenance — verb was already in the contract's
  initial vocabulary, no contract edit). Semantic θ tighten NOT rebuilt —
  render points at `monition calibrate` (B03; apply stays parked). Evidence
  floors: tighten ≥2 solo-noise (B04 batch-borne excluded), broaden ≥2
  violations, migrate ≥2 helpful semantic + 0 solo-noise hits, merge ≥3
  co-fire sessions, graduate ≥5 rated @ ≥0.8 precision @ ≥50% session share,
  stale = zero glob hits in origin repo + no firing in 14d. layer_eval `auc`
  reused (lazy numpy) for migrate-candidate discrimination.
- [2026-07-02] GOTCHA (live-falsified rule, fixed): co-firing alone is NOT
  merge evidence — the hub's top co-fire pairs (116 sessions!) were unrelated
  broad rows lit together by B04 batch dumps. Added a content dimension
  (≥3 shared spec/one-liner tokens); after the fix the top pair is the real
  clone pair t112×t90 and the t113/t115/t120/t79 spawn-MCP cluster. Flagged
  for mine-session.
- [2026-07-02] Hub run (read-only): 16 proposals — 2 broaden (t46 with
  candidates, t131 evidence-only), 3 migrate (t112/t121/t122, auc 1.0), 10
  merge (top pairs plausible; 179 further pairs noted beyond the render cap),
  1 stale (t6 — `tools/takeaway*.py` really did vanish from CMS). Tighten and
  graduate = 0, verified honest: no (row,keyword) has ≥2 solo lexical noise
  (B04's 80%-batch-borne prediction), graduate near-miss t85 at 45% share vs
  50% bar. Thin-evidence silence works (t184/t28 floor notes).
- [2026-07-02] Validation: 13 new tests in tests/test_proposals.py (one
  known-good proposal per class, batch-discount negative, thin-store silence,
  retarget provenance + refusals, CLI e2e); full suite 333 passed.
- [2026-07-02] HANDOFF: exit-gate live step is the user's move — consent to
  one proposal (best counterfactual candidates: a migrate retarget on
  t112/t121/t122, or retire stale t6), then measure the replay counterfactual.
  Broaden candidates on t46 are transcript-glue tokens ('bin/bash', 'python')
  — evidence excerpts share boilerplate, not signal; treat as human-authored
  spec territory.
- [2026-07-02] CONSENTED + APPLIED (user: "consent to all"): merge t115→t113
  (t113 retargeted to the union spec, mutation logged; t115 retired — 57/73 of
  its firings were pure duplication, 1 marginal unique-helpful), migrate t122
  (+'confer-overwatch', mutation logged), stale retire t6. Declined on payload
  inspection: t112×t90 merge (distinct lessons — related-topic pair the
  shared-token filter can't separate) and t112/t121 bare-'tmux' migrates
  (mention-vs-act risk). Post-apply `propose` run confirms all three consumed.
  GOTCHA: the first apply batch ran as one shell block without abort-on-failure
  — t113's original union spec blew varchar(255), the retarget failed, and the
  dependent retire t115 still ran (half-applied merge, fixed by re-retargeting
  with a trimmed spec). Consented mutation sequences: one command per step,
  verify each. retarget/set_trigger have no write-side length gate — the
  backend error is the only guard. Also: `retire` writes no mutations row
  (pre-v8 verb) — merge/stale provenance rides the retarget source + Dolt
  history; a recorded retire verb is a candidate small follow-up.
- [2026-07-02] Exit-gate status: lifecycle observed (t91 born broad →
  consented migrate_kind → live tool_call; t113 born broad → evidence-driven
  merge). Injected-volume reduction measured on stored firings (78% of the
  retired row's traffic was duplication; shared moments inject 1 row, not 2).
  Remaining confirmation: equal-or-better helpful rate over post-mutation
  sessions — check `monition report` after a few days of accumulation.
