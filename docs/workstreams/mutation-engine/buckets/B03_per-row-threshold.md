# Bucket B03: Per-row semantic threshold

Parent: ../workstream.md
State: done
Goal for session: `tune` becomes a gated per-row threshold actuator.
Target duration: 45 min
Context budget: Read parent + this bucket + required touchpoints only.

## Conceptual mapping

- One concept (the semantic module's threshold becomes row data, moved by that
  row's own ratings) across a small edit surface: the threshold storage (per
  B01), the semantic module read path, and the `tune` verb.

## Data contract / provenance

- Inputs: rated firings per row (67 rows have ≥3 ratings at workstream
  creation); `match_evidence` semantic scores — the score production matched at
  (verify field shape against a real firing row at implementation time).
- Outputs: per-row threshold value at B01's decided location; a decision-doc'd
  objective (recall at precision floor).
- Provenance: every threshold change is a consented row edit with old value
  recorded (B01's provenance representation).
- Validation: pre-registered gate (below) — registered BEFORE measuring.

## Tasks

- [x] Pre-register the gate in this file's Updates before computing anything:
      metric (e.g. replay-simulated noise reduction at no helpful-firing loss,
      vs the global SIM_THRESHOLD baseline), the row set (rows with ≥3 ratings
      and semantic traffic), and the pass bar.
- [x] Implement per-row threshold read in the semantic module (NULL = global
      default; no behavior change for untouched rows).
- [x] `tune` computes proposed per-row thresholds from that row's rated firings
      + match_evidence scores; PRINTS proposals with evidence; applies only via
      an explicit consented flag (narrow verb, old value recorded).
      (Verb surface: `calibrate`, per the user-accepted seam split — `tune`
      stays the Gate report.)
- [x] Run the gate via `replay` on a scratch snapshot; report pass/fail
      honestly — a NO-GO parks the actuator (advisory mode stays), it does not
      lower the bar. (Ran as a same-code-path scoring simulation — registered
      deviation. Result: NO-GO; apply parked.)

## Required touchpoints

- `docs/contracts/takeaway-store.md  grep -n "Trigger modules"  threshold storage per B01`
- `src/monition/score.py  grep -n "EV_THRESHOLD\|N_COLD_START\|def score"  the gate this must not entangle`
  Threshold tunes the Filter (matching), not the Gate (suppression) — keep the
  seam clean per 2026-06-18-noise-targets-the-filter-not-the-gate.
- `src/monition/report.py  grep -n "render_tune"  current advisory output`
- `src/monition/cli.py  grep -n "\"tune\""  verb wiring`

## Conditional touchpoints

- `src/monition/replay.py  grep -n "def "  replay surface`
  Read when wiring the gate measurement.

## Design direction

- One interpretable parameter per row, moved by that row's own ratings — this
  is the deliberately-different middle path the B02 NO-GO left open; do NOT
  introduce features, embeddings-of-ratings, or any trained component here.
- Rows below 3 ratings are untouchable (cold-start rules unchanged).
- Scratch-store discipline for all measurement (snapshot + MONITION_STORE).

## Validation

- Full suite green; gate result recorded in Updates with the pre-registered
  bar quoted verbatim next to the measured number.
- Expected: untouched rows behaviorally identical; tune-applied rows change
  only via consent.

## Done criteria

- [x] Tasks complete.
- [x] Validation passes (or NO-GO honestly recorded and actuator parked).
- [x] Bucket `Updates` section records discoveries/gotchas/handoff.
- [x] Parent workstream progress updated.

## Updates

- [2026-07-01 20:11] Created. Handoff: none yet. Gotchas: none yet.
- [2026-07-02] **Pre-registered gate** (registered before any measurement;
  verb surface decided: `calibrate`, `tune` untouched — user-accepted):
  - **Input data**: rated `on_demand` firings on a hub snapshot with a stored
    `situation` (v5+). Each is re-scored through the production path
    (`modules.lexical_match` first; if no lexical hit, semantic cosine via the
    same embed call `modules.semantic_rank` uses). Lexical-path firings are
    excluded from θ math (θ cannot affect them) but their share of rated noise
    is reported alongside (no silent scope shrink). Stored v7 semantic-evidence
    scores (n=20 rated) serve as a re-scorer sanity check: report agreement;
    large disagreement stops the run for diagnosis instead of proceeding.
  - **Row set**: active on_demand rows with ≥3 rated re-scorable firings and
    ≥1 semantic-path rated firing.
  - **Split**: per-row time split by `fired_at` — first ceil(70%) calibration,
    rest held-out eval; eval pooled across rows.
  - **Proposal rule** (fixed now, the actuator implements exactly this):
    θ_r = max(SIM_THRESHOLD, min calibration helpful semantic score); rows with
    zero helpful semantic calibration firings get θ_r = 1.0 (semantic
    effectively requires near-exact match; domain stays [0,1] per B01 —
    tighten-only, never below the global 0.6; broadening awaits FN signal,
    B06). Rows where θ_r suppresses no calibration noise are skipped (no-op).
  - **Metric** (held-out, pooled over proposed rows, both sides measured on
    the same holdout): noise_suppressed = held-out semantic noise firings with
    score < θ_r; helpful_lost = held-out semantic helpful firings with score
    < θ_r.
  - **Pass bar (verbatim at evaluation time): helpful_lost == 0 AND
    noise_suppressed ≥ 10% of held-out semantic noise firings.**
  - NO-GO parks the apply path (proposals stay advisory); the bar does not
    move after seeing numbers.
  - **Registered deviation**: the bucket text says "run the gate via `replay`";
    `replay` is the worktree/live-agent ablation runner whose variation axis is
    context fragments — re-running ~300 sessions to vary one scalar is not the
    fit. The gate runs as a same-code-path scoring simulation (the modules the
    executors call) on a scratch snapshot; assess-path == eval-path is
    preserved by construction.
- [2026-07-02] **Gate result: NO-GO — actuator parked, advisory stays.**
  Bar (verbatim from the registration above): *"helpful_lost == 0 AND
  noise_suppressed ≥ 10% of held-out semantic noise firings."* Measured on the
  hub snapshot (295 rated situation-bearing on_demand firings → 272
  semantic-path, 23 lexical; re-scorer sanity check vs the 20 stored v7
  semantic scores: mean abs diff 0.0000 — exact agreement): 16 rows proposed;
  held-out semantic noise 4, suppressed 3 (**75% reduction — bar met**);
  held-out helpful 2, **lost 1 — bar broken** (t79: θ=0.617 from calibration
  min-helpful, holdout helpful scored in [0.600, 0.617)). Verdict honest
  NO-GO; `calibrate --apply` refuses with the citation; `calibrate` (advisory
  proposals) and `calibrate --gate` remain.
  Diagnosis for the next attempt (rule change = new registration, new data —
  the bar did not move): the proposal rule θ = min(calibration helpful) has
  ZERO safety margin, so any boundary-adjacent held-out helpful fails it;
  a margin- or quantile-bearing rule re-gated once match_evidence accumulates
  (~weeks, not days) is the obvious candidate. Scope stays attractive: 93/100
  rated noise is semantic-path (θ-addressable), and holdout noise suppression
  was 3/4.
  Shipped regardless of the NO-GO (mechanism, not policy): v8 atomic migration
  (sem_threshold + tool_call enum + mutations table, Dolt ALTERs; SQLite
  takeaways-table REBUILD because CHECK constraints can't be ALTERed — rows
  copied byte-identical, AUTOINCREMENT sequence preserved, tested);
  per-row θ read inside `modules.semantic_rank` (NULL → global, untouched
  rows byte-identical — parity suite still green); narrow
  `WriteStore.set_threshold` verb (domain [0,1], on_demand-only, event-grain
  `mutations` row with old value captured pre-write); `monition calibrate`
  CLI (proposals / --gate / --apply-parked); `Store.mutations()` reader.
  Tests: tests/test_calibrate.py (9), v7→v8 rebuild test in test_init_sync;
  full suite 294 passed / 2 skipped. Fixtures bumped to V8 (conftest,
  conformance, fold, dolt_server).
  Gotchas: (a) SQLite CHECK-constraint widening = table rebuild — remember for
  any future enum change; (b) editable install means the LIVE hooks flipped to
  v8 code the moment store.py changed — **the hub must be migrated promptly
  or every hook on this machine fails open (no injections)**; migration was
  prepared but the permission classifier requires the user to run it (see
  handoff); (c) hub calibration data was extracted to scratch BEFORE the
  reader flipped to v8 — sequencing matters on editable installs.
  Handoff: B05 consumes the already-widened enum; B06 consumes `mutations` +
  the re-gate discipline recorded here.
- [2026-07-02] Hub migrated to v8 (user-authorized): 169 takeaways / 4430
  firings / 0 mutations read clean; live on_demand matching verified against
  the migrated hub (lexical + semantic evidence intact). Hooks healthy — the
  fail-open window is closed.
