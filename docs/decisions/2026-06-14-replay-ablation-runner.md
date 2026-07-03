---
status: decided
---
# The replay-ablation runner — v1 design

**Status:** Ratified 2026-06-14 (user). The runner build is unblocked, gated only
on a forward `docs/specs/` spec for the open implementation questions below. The
cross-project *seam* was settled by confer 2026-06-14
(`eval-engine-seam-and-archive-durability`); this
doc designs monition's side *within* that seam. Type: [[design_review]]
(project-internal — the runner is monition machinery).

**Day-one user story:** *an issue happens; I snapshot the environment; I run the
runner over that snapshot varying what context is injected; it tells me which
context was load-bearing, so I can decide how that context system should work.*

**Anti-goal:** not a continuous, always-on eval; not a faithful full-environment
simulator; not a scorer. It is a **sparse, snapshot-at-issue, minimal-mock,
vary-and-measure** mechanism whose output is structured per-condition artifacts a
*separate* discipline scores.

## Question

How does monition build the per-condition replay-ablation runner at v1 — its
environment-capture model, its interface, and the boundary between what the runner
automates and what a human (or the calling discipline) supplies?

## Settled inputs (from the confer — constraints, not open)

- **Monition owns the runner mechanism** (snapshot→worktree→re-run→diff). CMS owns
  the tier-3 *discipline* (rubric, failure-mode taxonomy, scope-holdout, the
  portfolio fan-out) and invokes the runner N times; the runner itself stays
  **single-environment, single-condition-set per call**.
- **G1 — variation-source-agnostic.** The variation axis is a free parameter: a
  takeaway-row firing (tier-2) *or* a non-firing governance artifact (tier-3). The
  runner must not hardcode "firing," and only *monition-store* reads are
  `export-firings`-gated — the variation input itself is opaque text/config.
- **G2 — stops at structured per-condition artifacts.** The runner returns the
  worktree diff + the headless run result per condition; it computes no score.

## Options weighed

### D1 — Environment-capture model (how the runner gets a faithful env to replay)

- **A — passive provenance only.** Reconstruct from the firing's recorded
  `git_sha`. *Loses:* the audit shows 67% of real firings have no SHA, and a dirty
  tree isn't reconstructable from a SHA — this is the "rely on passive capture"
  path the b-doc already rejected for fidelity.
- **B — snapshot-at-issue + discardable worktree (chosen).** A deliberate snapshot
  (a dedicated commit/stash/tag) is taken *when an issue is flagged*, while the env
  is still live; the runner materializes it in a throwaway worktree per condition.
  *Wins:* high fidelity exactly where it matters, criticality-gated by construction,
  independent of the backlog's missing provenance. The firing's v5 `situation` +
  `git_sha` are the *locator/fingerprint*; the snapshot is the *reconstruction*.
- **C — continuous full-environment capture** (snapshot every fire). *Loses:*
  enormous storage for env states almost never replayed; the cost falls on every
  fire instead of the rare issue.

**D1 decision: B.**

### D2 — Variation-axis representation (G1)

- **A — firing as the hardcoded unit.** *Loses:* rejected by G1 — tier-3 can't ride
  it, forcing two engines.
- **B — opaque condition set (chosen).** A call specifies a list of *conditions*,
  each a set of context fragments to include/exclude; the runner is agnostic to
  whether a fragment is a takeaway one-liner or a CLAUDE.md line. Tier-2 sources its
  fragments via `export-firings`; tier-3's are handed in by CMS.

**D2 decision: B.**

### D3 — v1 automation boundary (what the runner automates vs. what's supplied)

- **A — automate the whole loop** (detect the issue, minimize the env, judge the
  outcome). *Loses:* issue-detection, env-minimization (delta-debugging), and
  outcome-judging are each a research problem or a different owner's job (judging is
  CMS's rubric). Building them now is the "instrument before calibration" trap.
- **B — runner mechanism only; trigger/minimization/check human-supplied (chosen).**
  v1 = the runner + a **snapshot convention** + a **manifest format**. The human (or
  calling discipline) supplies: the snapshot (the trigger), the manifest naming the
  minimal env + task + per-condition context, and the outcome check. The runner
  executes and returns artifacts.

**D3 decision: B.**

## Decision (v1 architecture)

A single-call runner, `run(snapshot_ref, manifest) -> [per-condition artifact]`,
where:

- **snapshot_ref** points at a deliberately-captured environment (D1/B); the runner
  checks it out into one **discardable worktree per condition** (auto-cleaned).
- **manifest** (human/discipline-supplied, D3/B) declares: the minimal env to
  materialize, the task to run headless, the **conditions** (each = the context
  fragments to inject/withhold, D2/B), and the **outcome check** per condition.
- For each condition the runner materializes the worktree, applies that condition's
  context state, runs the task headless, and records a **structured artifact**: the
  worktree diff + the run result + the check's verdict (G2). It computes no score.
- **ΔP(fail) attribution** — "what mattered" — is the *difference across conditions*
  in the artifacts; a tier-2 caller reads it directly, a tier-3 caller (CMS) feeds
  the artifacts to its rubric and fan-out.

## Open implementation questions (for the build / a forward spec)

1. **Context manipulation per condition.** How a condition's "with/without fragment
   X" state is produced — for tier-2, a store with/without the row or a disclosure
   override; for tier-3, a CLAUDE.md / prompt variant. Likely a manifest-declared
   "context recipe" per condition (human-supplied in v1).
2. **Headless run surface.** Which headless invocation (`claude -p` / agent-spawn)
   and how its model/version is pinned for comparability across conditions.
3. **Determinism & cost guards.** Per-call worktree count cap; how non-determinism
   in the headless run is handled (repeat-and-aggregate is CMS-discipline, not
   runner).
4. **Snapshot convention spec.** The exact form of `snapshot_ref` (tag? stash? a
   commit on a side ref) and how the firing's `git_sha`/`situation` link to it.

These do not block ratifying the seam-conformant shape above; they are the v1 build's
first decisions and belong in a `docs/specs/` spec that cites this review.

**Resolved:** `docs/specs/2026-06-14-replay-ablation-runner.md` (v1 build spec,
`/grill-me --impl` 2026-06-14) answers all four — minimal-mock file injection per
condition (OQ1); interactive `claude` on the subscription bucket, never `claude -p`,
with branch-authoritative completion/harvest (OQ2); one run/condition, sequential
default + bounded `--parallel`, condition cap + timeout + `--dry-run` (OQ3); a
dirty-tree commit under `refs/monition/snapshots/<id>` auto-captured on
human-or-LLM flag (OQ4). It also rules the execution-backend fork: build a
self-contained driver in monition behind a pluggable backend seam, borrowing
`agent-harness`'s design (not its code) after an audit found it untested.

## Rationale

The confer fixed *who owns what*; the live risk left is building a faithful-replay
machine before knowing it's affordable or needed. D1/B and D3/B both push fidelity
and automation to **the moment and the altitude that justify them**: snapshot only
flagged issues, automate only the mechanism, leave judgment to the owner who has the
rubric. G1/G2 keep the runner a shared mechanism rather than a tier-2-only tool, so
CMS's tier-3 rides it instead of forking a second engine. The v5 `situation` capture
(b-doc, shipped 2026-06-14) is the firing-grain fingerprint D1/B leans on.

## Provenance / links

- Seam: confer `2026-06-14 eval-engine-seam-and-archive-durability`.
- Verdict registry: `docs/road.md §2` ("Replay-ablation runner is monition's machinery…").
- Firing-grain capture this depends on: `docs/decisions/2026-06-13-firing-capture-minimum-for-cheap-eval.md` (v5 `situation`, shipped).
- Cross-project build order: tracked in the cross-project roadmap.
