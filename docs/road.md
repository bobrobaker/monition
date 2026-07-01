# monition Roadmap

## 1. How to use this doc

Purpose: orient sessions around project phase, history, next work, and bounded
implementation surfaces.

Current phase marker:

`<----- Ongoing phase ----->`

A **phase** is a high-level deliverable with stable interfaces. A **workstream** is a
refinable effort inside a phase. A **bucket** is a bounded implementation slice,
usually sharing files, invariants, or tests.

Each phase states: deliverable, surfaces, durable design decisions, file/doc changes,
validation, token estimate, and exit criteria. Keep details high-level enough to start
a refinement conversation, not enough to implement directly.

---

## 2. Design positions (durable, cross-phase)

- **One owner for the machinery; one CMS-managed store.** Monition owns all
  takeaway machinery — store schema, hook executors, `init`/`sync`/`migrate`,
  reader, metrics, report, scoring. Rows live in a **single CMS-managed store**
  (the "hub"), with the project/general distinction carried as columns (`reach` +
  `origin_repo`), not physical per-repo boundaries. monition resolves the store
  from `MONITION_STORE` → `<repo-root>/monition/` fallback (unset = standalone
  mode); CMS owns the hub's location + lifecycle. Backend: **Dolt is our own
  default** (the hub is a Dolt store); SQLite stays the recommended default only
  for external/standalone hosts that won't install dolt — see
  `docs/decisions/2026-06-18-dolt-default-ours-sqlite-external.md`. Cross-machine
  distribution deferred to the Dolt-server seam. Field semantics are never
  reinterpreted outside the data contract in `docs/contracts/takeaway-store.md`.
  *(Ratified via CMS confer 2026-06-18 —
  `docs/decisions/2026-06-18-single-store-general-project-scoping.md`; supersedes
  the former per-project-store position. Implementation is the pending v5→v6 step;
  the contract still describes per-repo stores until then.)*
- **Trigger-as-data.** Rows own *what fires when*; the module owns *how matching
  executes*. The founding bet is untouched by the ownership realignment.
- **Fail-open everywhere — absent and broken.** A hook must never block a
  session. Hook entries guard on the command's existence (absent module → silent
  no-op); a present-but-crashing module leaves the session unblocked and appends
  stderr to `~/.local/state/monition/hook-errors.log`. Both are tested exit
  criteria, not aspirations.
- **Offline before online.** Analytics over accumulated firings/ratings come before
  the live scorer; the online EV path lands only when there is eval data to score
  against. Growing honest eval data (sparse ratings beat dense dutiful ones) is
  early-phase work.
- **EV vocabulary.** Benefit rate = `f_hit × ΔP(fail) × W × D × M`; cost rate =
  `f_trigger × inject_tokens` plus the corpus-wide false-fire tax. `f_hit/f_trigger`
  is trigger precision. Keep a gotcha while benefit rate > cost rate; a diverging
  reversibility multiplier `M` is the signal to graduate from gotcha to built gate.
- **No daemon until measured.** Plain CLI; if hook-path latency ever bites, the first
  remedy is `dolt sql-server`, not custom resident code.
- **Lexical first.** Trigger/retrieval analysis starts keyword/lexical; embeddings
  arrive later behind the same interface.
- **Routing is method; CMS owns it.** The lesson-routing discipline (whether a
  mined lesson becomes a store row or a governance edit) is canonical at CMS
  `method/lesson-routing.md`. Monition's mine-session skill template carries a
  domain-stripped copy with a routing-version provenance line; CMS version bumps
  reach the template at monition's consent gate, then `monition sync` propagates
  to graduated projects via the existing skill hash-check. (Confer resolution
  2026-06-12, lesson-routing-ownership.)
- **Replay-ablation runner is monition's machinery; the tier-3 discipline
  configures it.** Monition owns the per-condition replay-ablation runner
  (snapshot→worktree→re-run→diff): variation-source-agnostic (axis is a free
  parameter — a firing row or a non-firing governance artifact; only monition-store
  reads are `export-firings`-gated) and returning structured per-condition artifacts.
  CMS owns the tier-3 discipline on top (rubric, failure-mode taxonomy, scope-holdout,
  portfolio fan-out). Firing-grain decision context is a *minimum fingerprint at fire
  time* (git SHA+dirty already v4; + trigger match + situational excerpt/pointer;
  un-truncate `on_demand`); session-altitude context is recovered by joining
  `session_id` to CMS's durable session-grain archive — CMS does not retain
  firing-grain. (Confer resolution 2026-06-14, eval-engine-seam-and-archive-durability;
  capture detail in `docs/decisions/2026-06-13-firing-capture-minimum-for-cheap-eval.md`;
  v1 runner design in `docs/decisions/2026-06-14-replay-ablation-runner.md`, ratified;
  v1 build spec in `docs/specs/2026-06-14-replay-ablation-runner.md`.)

---

## 3. Phase roadmap

### Phase 1 — Offline analytics over the takeaway-store contract

**Status:** exited (2026-06-11). Contract reviewed against the live CMS store,
producer code, and test coverage — verified accurate, no amendments. Contract,
reader (`src/monition/store.py`), metrics, report CLI, and Dolt-backed synthetic
fixtures all landed; 18 tests pass; live `monition report` against the CMS store
runs clean and write-free. Validation setup: `python3 -m venv .venv &&
.venv/bin/pip install pytest`, then `.venv/bin/pytest` with `~/.local/bin` on PATH
for dolt.

**Deliverable:** the automated form of the manual rate-and-tighten audit:
(a) `docs/contracts/takeaway-store.md` — per-field semantics, coordinate systems,
forbidden near-misses, versioning with rejection-on-mismatch — written first and
validated against a live reference store;
(b) `monition report <store-path>` — noise accumulators, never-fired entries,
per-trigger precision from ratings, spec-tightening recommendations;
(c) the EV vocabulary (benefit rate, cost rate, precision) as tested functions, even
where live data is still sparse;
(d) synthetic store fixtures with known ground truth so the analytics are testable
before real ratings accumulate.

**Surfaces:** `src/monition/` (store reader — the single approved reader; metrics;
report), `tests/`, `docs/contracts/`.

**Design:**

- Contract before code: no module consumes store data until the contract section it
  relies on is written.
- One reader, one validation point: every store access flows through the approved
  reader; ad-hoc `dolt sql` parsing elsewhere is a contract violation.
- Phase 1 is strictly read-only against real stores; writes happen only to synthetic
  fixtures under `tests/`.

**File/doc changes:** `docs/contracts/takeaway-store.md`; `src/monition/` package
(reader, metrics, report CLI); `tests/` with fixture builders; `pyproject.toml` with
the `monition` entry point.

**Validation:** `pytest` green; one live run of `monition report` against the CMS
store producing a correct audit of its current rows.

**Estimate:** 2–3 focused sessions (~300–450k tokens).

**Exit:** report runs against both synthetic fixtures and the live CMS store; the
contract has been reviewed against actual store behavior; zero writes to any real
store.

---

### Phase 2 — Moduleization + CMS cutover

**Status:** complete (2026-06-11). Spec:
`docs/specs/2026-06-11-module-realignment.md` (accepted with CMS amendments via
confer, 2026-06-11). Workstream: `docs/workstreams/module-realignment/`.

**Deliverable:** Monition as the installable module owning all takeaway machinery:
(a) CMS's store CLI (takeaway lifecycle commands) and hook executors ported into
the package, characterized against the CMS originals;
(b) `monition init`/`sync`/`migrate` — one-command adoption per project, idempotent
and transparent (`--dry-run`), skills materialized with version stamps and
hash-checked on sync;
(c) the tier-0 interchange format (a contract section) plus `monition init
--adopt <file>` — the one-way graduation step importing an incubated project's
file-based lessons into store rows;
(d) the CMS cutover: delete `tools/takeaway*.py`, rewire hooks to guarded
`monition` calls, `git mv takeaways monition`, zero data loss verified by content
hash.

**Surfaces:** `src/monition/` (CLI, executors, init/sync/migrate), `tests/`,
contract preamble + interchange section, CMS repo at cutover (consented).

**Design:**

- Global editable install (`uv tool install --editable .`); one install serves
  every project, edits propagate instantly; the broken-working-tree risk is
  softened to silence by fail-open.
- Fail-open covers absent *and* broken (spec decisions 4 and 14): existence guard
  in the hook command string; stderr from crashes logged to the per-machine state
  log. Uninstall test and crash test are exit criteria.
- Behavioral identity: ported code reproduces the CMS originals exactly; the CMS
  `tools/takeaway*.py` files are the characterization oracle until cutover.
- The contract is demoted from treaty to spec of the code↔data boundary; the
  fingerprint check stays and `monition migrate` becomes the repair path it
  points to. Schema stays v2.
- Tier-0 frozen executor: Monition owns the interchange format; the CMS payload
  cites it, never duplicates it. Frozen-ness is load-bearing.

**Validation:** `pytest` green (existing 18 + init/sync/migrate/adopt/fail-open
coverage); uninstall test silent; crash test unblocked and logged; `init --adopt`
round-trips a tier-0 fixture; CMS store content hash unchanged at cutover; one
end-to-end smoke firing.

**Exit:** spec §Success criteria — `monition init` on a fresh repo yields working
capture/disclosure; CMS cutover complete; instantiate protocol updated.

---

### Phase 3 — Online scoring

**Status:** complete 2026-06-12 (`docs/workstreams/online-scoring/`, B01–B03 done).

**Deliverable:** a `monition score` call that the module's own executors delegate
the fire/suppress decision to. Decisions are logged with their EV reasoning to a
`decisions` Dolt table beside `firings` (schema v3) so decision quality is itself
auditable. Cold start: always-fire below an evidence threshold (N rated firings
per takeaway; N ~3, deferred) — Monition only suppresses what it has proof is
noise.

**Exit:** a wired project's firing decisions flow through Monition and are logged;
suppression happens only with evidence; fail-open paths still pass.

---

### Phase 4 — Tuning and retrieval

**Status:** complete 2026-06-12 (`docs/workstreams/tuning-retrieval/`, B01–B05 done).

**Deliverable:** the EV scorer tuned against accumulated ratings (the eval data
from Phases 1–3), and hybrid lexical+embedding trigger matching behind the
existing retrieval interface. Candidate: an MCP query surface for `on_demand`
takeaways — never the backbone (disclosure stays harness-deterministic).

**Exit:** measurable improvement of fire/suppress decisions against the rating log
versus the always-fire baseline. `monition tune` reports `noise_saved_pct` vs the
always-fire baseline. `monition query` performs hybrid on_demand retrieval:
lexical keyword pass plus embedding similarity (fastembed via the
`monition[embed]` extra; fails open to lexical-only). MCP server (B05) shipped
2026-06-12: `monition mcp-serve` exposes the `match_gotchas` pull tool (explicit
query only — never the backbone).

---

### Phase 5 — Trigger/Filter refinement (the relevance cascade)

**Status:** paused 2026-06-21 at B02 — **NO-GO** (`docs/workstreams/relevance-cascade/`).
The head did not clear the usefulness gate; B03–B05 did not start, no artifact shipped.
Verdict + full result: `docs/decisions/2026-06-21-relevance-cascade-b02-no-go.md`.

**Deliverable (attempted):** reduce `on_demand` firing noise (the dominant noise source)
with a cost-ordered, certainty-gated **cascade** of relevance Layers on the *passive* fire
path. The decisive layer `L2′` is a learned head over full prompt⊕row embeddings, no
inline LLM (the LLM is an offline label oracle only). Grounded:
`docs/decisions/2026-06-18-noise-targets-the-filter-not-the-gate.md` (Update —
2026-06-21); spike branch `spike/relevance-cascade`. Contract:
`docs/contracts/relevance-cascade.md`.

**Why paused:** the spike's "0.78 grouped-CV AUC" was **leakage-inflated** (B01 red-team
C1/C2); under honest row-disjoint leave-row-out CV the head is **~0.67**, and the 95% CI
lower bound (~0.55–0.58) does not clear the 0.60 usefulness bar — a *volume* wall (only 46
distinct rows), not a model bug. Operationally the head suppresses only ~20% of noise at
≥90% helpful retention. Revisit (overnight/autonomous candidate) must re-open two false
spike premises: the 0.78 headline AND the prematurely-buried "metamatch" negative (also
measured on the same leaky n=102 fixture, so equally untrusted). Cascade orchestrator (B03)
and metamatch are **not live** — only the B01 dataset + B02 head exist (`src/monition/relevance/`).

**Exit (gated) — fail branch taken:** the head had to clear a usefulness bar on the
**human-only** split (B02 GO/NO-GO) before runtime integration. It did not; per this exit
clause the phase paused with the finding recorded; no integration on an unproven head.

---

### Phase 6 — Violation signatures + firing-evidence capture (the recall column)

**Status:** planned (framed 2026-07-01,
`docs/decisions/2026-07-01-row-lifecycle-pr-framing-and-mutation-track.md`).
Prerequisite for Phase 7 — sequencing is load-bearing: mutation without this signal
mutates on ~8%-coverage vibes.

**Deliverable:** make a row's ground truth observable so its confusion matrix has a
false-negative column. (a) An optional **violation signature** per row — a
machine-checkable probe (regex/check over transcript or diff) for the failure the row
warns about; authored at mine time for rows where one exists, never mandatory. (b) A
post-session (or Stop-hook-adjacent, fail-open) evaluator that classifies sessions
into fired∧avoided / fired∧hit / **not-fired∧hit**, logging the third as the
trigger-broadening signal ratings structurally cannot produce. (c) Firing rows carry
the **full matched evidence** (the text/path/tool-call the trigger matched on), not a
lossy preview — the training substrate for Phase 7. The autoflag corpus
(CMS `tools/flag_corpus.py`) is the in-house proof of the transcript-signature
pattern.

**Design constraints:** signatures are data on the row (the disclosure machinery
stays dumb); evaluation is offline/fail-open, never on the blocking hook path; a row
without a signature simply has no FN column (degrades to today's precision-only
view).

**Exit:** ≥1 real not-fired∧hit event captured and surfaced in `monition report` /
the rating pass; firings verifiably store full match evidence.

---

### Phase 7 — The mutation engine (rows improve, not just fire-or-die)

**Status:** planned (same framing decision). Gated on Phase 6 signal actually
accumulating.

**Deliverable:** rows mutate along the determinism ladder instead of only firing or
dying. (a) **Trigger-module abstraction**: a row's trigger is a swappable, composable
module (keyword / glob / semantic / tool-call / state probe; layered combinations);
includes the new trigger kinds as modules, e.g. PreToolUse tool-call patterns for
"about to run X" rows. (b) **Mutation proposals as an audit-cadence read**: from
FP (rated noise) + FN (signature) evidence, propose per-row: tighten / broaden /
migrate down the ladder (semantic → keyword → glob → tool-call) / merge with a
near-duplicate / **graduate** (fires nearly every session, consistently helpful →
propose promotion to an always-on surface and retirement here) / **stale** (referents
vanished → refresh or retire). Proposals go through the mine-session consent gate as
row edits — the engine recommends, the human accepts. (c) **Per-row threshold
calibration** as the semantic module's tunable parameter (`tune` becomes an actuator
under the same P/R objective, replacing advisory text). (d) Batch-dump attribution:
shared-cause noise batches attribute to the breadth/prompt layer first, per the
06-18 Filter-not-Gate decision, before pushing any single row toward suppression.

**Design constraints:** mutation = search over trigger-module space maximizing recall
at a precision floor, preferring the most deterministic module at equal performance;
module candidates judged with the spike's `layer_eval` discipline (rank-normalized
conditional lift); no learned component ships without a B02-grade pre-registered
gate. Every mutation is a consented row edit with provenance (old spec recorded), so
`replay` can evaluate mutations counterfactually.

**Exit:** at least one full lifecycle observed end-to-end on the live hub — a row
born broad, tightened/migrated from evidence, and either graduated or stably
high-precision — plus a measured injected-volume reduction at equal-or-better
helpful-rate vs. the pre-mutation baseline.

---

### Next

Phase 5 (above) is the ongoing phase, dispatched 2026-06-21. Phase 4 exited
2026-06-12.

**Rating-collection discipline — confer resolved 2026-06-17 (CMS owns the discipline; monition the substrate).** The fire/suppress gate (`monition score`) was starved — 0 ratings collected organically (the fire-time `rate:` hint never fires), CMS store 33% rated, host repos 0%. Resolution: CMS owns an **evidence-gated** rating pass in `mine-session` (LLM-auto; rate only firings the in-context session evidences, mandatory per-rating citation, no-evidence→no-rating; head-not-tail policy; one batched lighter-than-rows consent gate). Canonical in CMS; domain-stripped mirror in monition's `SKILL_MINE_SESSION`, propagated to **adopted** repos via `monition sync` (verified: sync materializes skills full-text + stamp hash-check). Tier-0 untouched. **monition obligations:** (done 2026-06-17) `export-firings --unrated-only`/`--session`; head-not-tail metric on `export-firings` — per-row `fire_count`/`rated_count`/`precision`/`rating_priority` + `--order-by priority` (boundary math in `export.py`, `rating_priority = fire_count × closeness`, closeness `1.0` for cold-start else peaks at `EV_THRESHOLD`); (follow-up, unbuilt) fold CMS's handed-off template into `SKILL_MINE_SESSION` + bump `VERSION`; trigger `monition sync` across adopted repos once the template lands.

**Cross-project near-term arc complete (2026-06-13).** CMS shipped P1 (session-archive
v1, incl. the backfill↔wrap seam monition flagged) in CMS `7e635db`; monition's
prompt-hook + MCP were wired into CMS in `2eba47e`. All monition obligations on the
shared roadmap are landed (P1m retrievals-log, P2 export-firings, eval-context v4,
P4 harvested-counterfactual). **monition is off the critical path.** Both remaining
phases are gated/deferred: P3 (CMS tier-3) is gated on labeled-trace volume; P4's
synthesized-replay half stays the criticality-gated fallback (below). Build order +
status: tracked in the cross-project roadmap.

**Eval substrate — ownership seam (confers `2026-06-12 evals-substrate-and-
governance-module-evaluation` + `2026-06-12 cms-eval-tier3-ownership`, both
resolved; the latter user-ratified).** The eval substrate is three tiers split
across an ownership seam, not one module. **Monition** owns the *row-coupled*
eval (tiers 1–2) and the *provenance substrate*, and *exposes* it; **CMS** owns +
ships the tier-3 *discipline* (a `method/` doc + per-project payload harness, not
a central service) for evaluating *context-providing modules* — governance lines,
prompts, skills; the **generated project** owns its trace corpus and failure-mode
labels. The seam is the M-ceiling: a lesson graduates out
of monition's measurable row tier exactly when it becomes a gate/governance line,
so tier 3 is by construction the post-graduation regime and is **not** re-owned by
the row store. That graduation seam is a **continuity, not a gap**: row
helpful-rate and governance failure-rate are two estimators of one quantity —
ΔP(fail), the benefit term in the EV formula — so the graduation handoff metric is
tier-3's first computation, consuming monition's row-side prior via the read-verb.
Tier 3 is a **graduation-tier** discipline (gated on labeled-trace volume, never
day-one), with portfolio-altitude (cross-project) scope-holdout as its primary
design. Monition builds the substrate and the read-verb; it does **not** build a
tier-3 evaluator. Cross-project build order: tracked in the cross-project roadmap.

Open candidates:

- **`monition export-firings` read-verb — DONE (landed 2026-06-13, contract v1).**
  `monition export-firings --format jsonl` emits one JSON object per firing —
  firings + ratings + v4 provenance, denormalized with the parent takeaway's
  `one_liner`+`kind` — each carrying a per-record export `schema_version` stamp
  (starts at `1`, distinct from store v4). Read-only through the single approved
  reader; fail-open (empty store → empty stream); v1 filters are `--since`,
  `--rated-only`/`--unrated-only` (mutually exclusive), and `--session` (the last
  two added 2026-06-17 to drive the rating worklist), everything else P3 filters
  client-side. Canonical contract landed as
  `docs/contracts/export-firings.md`, a sibling to the retrievals-log schema,
  **owner-at-birth** (CMS drafted the field list; monition reviewed and owns the
  canonical). Monition also owns the cross-substrate **schema discipline**
  (additive-column + version-stamp + `helpful|noise`/NULL outcome vocabulary) and
  the **ΔP(fail) common currency** that scales the graduation seam — cross-substrate
  questions are answered by join-on-demand through the reader, never a merged store.
  Owner-review finding encoded in the contract: `firings.trigger_kind` is an open
  varchar and now also carries `resurrection` (synthetic helpful-equivalent firings
  from P4's consent gate) — flagged to P3 as injected counterfactuals, not organic
  disclosures; queued for CMS field-alignment confirm.

- **Eval-context capture — DONE (landed 2026-06-13, contract v4).** `firings`
  gained fire-time provenance: `git_sha`, `git_dirty`, `model`, and
  `monition_version` — captured at every fire (fail-open, all nullable;
  unavailable dimensions stay honestly NULL, never guessed). The git state is
  captured by the write surface (the only layer that knows the host repo); the
  model is supplied by the executor (harness state the writer can't see). The
  contract bumped v3→v4 (`docs/contracts/takeaway-store.md`), the reader's
  fingerprint now requires the columns, and `monition migrate` is cumulative
  through v4 (an additive `ALTER TABLE firings`). These columns are impossible to
  backfill, which is why this landed first — it unblocks both `export-firings`
  and suppression-resurrection.
- **Suppression resurrection via recurrence — DONE (landed 2026-06-13).**
  `monition add` runs the Phase 4 similarity matcher (lexical + embedding,
  fail-open to lexical) against the currently-suppressed candidate set *before*
  inserting; a near-match means the lesson is being re-learned — near-direct
  counterfactual evidence the suppression was wrong. **Schema reconciliation:**
  there is no "suppressed" *status* (rows are `active|retired`); suppression is
  the EV scorer's computed per-firing decision, so a row is "suppressed" =
  *its latest `decisions` row is `suppress`*. **Consent gate = detect-and-refuse:**
  `add` refuses the silent insert and prints the gate (exit 3); the caller
  (mine-session skill / human) re-runs with `--resolve new | merge:ID |
  log-helpful:ID`. Because suppression is computed, "un-suppress" *is*
  `log-helpful` — recording the recurrence as a `helpful`-equivalent firing
  (tagged `trigger_kind='resurrection'`) that lifts precision back over
  threshold; `merge` folds the wording in (no duplicate); `new` overrides. This
  is the **harvested natural counterfactual** the confer settled monition should
  prefer *before* any synthesized replay — an observed ΔP(fail) sample with no
  test agent in the loop. Synthesized replay-of-rows (hand a test agent the
  captured environment with/without the candidate firing) remains the
  **criticality-gated fallback** (still deferred) for when traffic doesn't hand
  you the counterfactual. No contract bump (firing `trigger_kind` is free-form
  varchar). Tests: `tests/test_resurrection.py`.
- **`dolt sql-server` write-path seam — DONE (landed 2026-06-19).** Concurrent
  `dolt sql -q` firing writes to the single hub failed `cannot update manifest:
  database is read only` (verified 8/10 lost under 10-way contention) — file-based
  Dolt serializes writes via a one-writer manifest lock, and a bounced firing is a
  lost eval-substrate row. **Key finding that shrank the fix:** when a
  `dolt sql-server` runs on the store, the dolt CLI auto-detects it (via
  `.dolt/sql-server.info`) and routes *every* `dolt sql -q` through it — so the
  existing subprocess path becomes contention-free with **no MySQL client and no
  retry-on-lock**. The whole fix is a lifecycle module (`src/monition/dolt_server.py`)
  that ensures a server is running; `DoltBackend` calls `ensure_running` before each
  `dolt sql -q` (writes *and* describes — a describe racing a spawn would else read
  as "table missing"). Opt-in via `MONITION_SQL_SERVER` (mirrors the embed daemon;
  default off = unchanged); auto-routing means whoever spawns it fixes the whole
  fleet, so CMS sets it machine-wide. CLI: `sql-server-status` / `sql-server-stop`.
  Decision: `docs/decisions/2026-06-19-dolt-sql-server-write-path.md`. Tests:
  `tests/test_dolt_server.py`. **Unblocks** `instrument --global` (now buildable).
- **B05 mcp-server — DONE (landed 2026-06-12).** `monition mcp-serve` (FastMCP via
  the `monition[mcp]` extra) exposes `match_gotchas` as an explicit pull tool, plus a
  prompt-driven `on_demand` hook; never the backbone (disclosure stays
  harness-deterministic). (`docs/workstreams/tuning-retrieval/buckets/B05_mcp-server.md`.)
- The session-archive retrieval router (confer thread
  `2026-06-12 confer session-archive-eval-substrate`, resolved): CMS runs a
  separate flat retrievals log day one; monition owns the log schema at birth
  (CMS drafts, monition reviews and lands it as a sibling contract doc in
  `docs/contracts/`) and the router graduates here when monition grows a
  surface not bound to per-project stores. **Schema landed 2026-06-12 (P1m):**
  `docs/contracts/retrievals-log.md` (v1). The router itself stays in CMS until
  it graduates per that doc's "Graduation" section.
- **`monition mirror <id> <state>` lifecycle verb — deferred (raised by CMS,
  2026-06-14).** The `mirror` column has a setter only at `add` time (`--mirror`);
  no verb transitions an existing row's mirror state — `retire` touches `status`,
  `query` is read-only — so a `candidate` row can never be marked `mirrored`/`none`
  post-hoc and the candidate→mirrored lifecycle can't close. Surfaced when CMS chose
  to route its own domain-free lessons at mine-time instead of queuing them as
  `candidate` (per CMS's `2026-06-14-cms-self-lessons-route-at-mine-time` decision):
  the existing CMS-store candidate flags are stale-but-inert, and reconciling them
  needs this verb. Deferred — gated on a real need to transition mirror state; the
  cleanup it enables isn't worth doing on its own yet.
- **`monition log-recurrence <id>` verb — DONE (landed 2026-06-14).** Logs a
  mine-time "already covered by this row" recurrence as a helpful-rated firing
  against an *active* row (tagged `trigger_kind='recurrence'`, distinct from
  `'resurrection'`; no consent gate; no `firings` contract bump — v5 free-form
  `trigger_kind`). Captures load-bearing-row evidence that otherwise evaporates,
  and is the **accelerant** toward the ≥10-rated `monition tune` gate. CMS owns the
  mine-session discipline that calls it — on an already-covered skip of a
  *low-firing `on_demand`* row (high-firing / `session_start` rows stay with the
  fire+rate loop; that double-count guard is CMS's, not the verb's), added **once
  the verb ships**. Resolved on confer thread
  `2026-06-14 confer recurrence-logging-scorer-signal` (archived).
- **Deferred-set disposition — settled 2026-06-14 (confer
  `monition-deferred-work-clock`, subsumed by the above).** monition fires in a CMS
  host with real, rated traffic (clock started ~2026-06-13). The *only* pull-forward
  is `log-recurrence` (above); the **EV-tune loop** (≥10-rated gate, in sight not
  near; automating `tune` stays a separate design decision, not a deferred build),
  **`monition doctor`** (pain-gate not tripped — the lone v4→v5 friction self-resolved
  via its own error instruction), and the **multi-machine/config store path** (no
  driver) all stay parked. They self-revisit when their gates trip.
