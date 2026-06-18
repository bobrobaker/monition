# Replay-ablation runner — v1 spec

Forward spec for the v1 build, resolving the open implementation questions left by
the ratified design review `docs/decisions/2026-06-14-replay-ablation-runner.md`
(D1/B snapshot-at-issue, D2/B opaque condition set, D3/B runner-mechanism-only;
G1 variation-source-agnostic, G2 stops at structured artifacts). The
cross-project *seam* — monition owns the runner mechanism, CMS owns the tier-3
discipline — was settled by confer 2026-06-14
(`eval-engine-seam-and-archive-durability`). This spec cites
those, never re-derives them.

Produced via `/grill-me --impl` (2026-06-14): the architecture was firm going in,
so grilling was scoped to the four open implementation questions. The
execution-backend decision below was reached by **auditing** `agent-harness`
against the runner's needs (verdict in §Decisions, item 6), per the user's
instruction not to assume reuse.

## Task as understood

Build the per-condition replay-ablation runner: given a deliberately-captured
environment snapshot and a manifest of context conditions, the runner materializes
a discardable worktree per condition, injects that condition's context, runs the
task on a real interactive Claude agent, and records a structured per-condition
artifact (worktree diff + run result + outcome-check verdict). It computes **no
score**. A tier-2 caller reads the cross-condition difference directly; a tier-3
caller (CMS) feeds the artifacts to its rubric. Day-one story: *an issue happens; I
(or the in-session agent) snapshot the environment; I run the runner over that
snapshot varying what context is injected; it tells me which context was
load-bearing.*

## Vocabulary (firm)

- **Snapshot** — a deliberately-captured environment state recorded when an issue
  is flagged (a side-ref commit; see decision 4). Its ref is `snapshot_ref`.
- **Condition** — one entry in the manifest: a set of context fragments to inject
  (everything not listed is withheld) plus an outcome check. The variation axis.
- **Fragment** — an opaque unit of injected context (a takeaway one-liner, a
  CLAUDE.md line, a prompt variant). The runner is agnostic to its source (G1).
- **Artifact** — the runner's per-condition output: worktree diff + run report +
  outcome-check verdict. The runner stops here (G2).

## Goals and non-goals

**Goals:** a single-call, single-environment, single-condition-set runner that
(1) materializes a faithful-enough replay per condition from a snapshot, (2) varies
opaque context fragments, (3) runs on the subscription billing bucket, (4) emits
structured artifacts a separate discipline scores, and (5) is self-contained and
test-covered like the rest of monition.

**Non-goals (the anti-goal, made concrete):** not a scorer (G2 — no rubric,
taxonomy, scope-holdout, or fan-out; those are CMS tier-3); not an autonomous
issue-detector (detection stays a human/LLM judgment act — D3 rejected automating
it); not a faithful full-environment simulator (minimal-mock only — no
re-simulation of monition's disclosure hook, no store swap); not always-on; no
repeat-and-aggregate (CMS-discipline — the runner does one run per condition); not
the tier-3 governance evaluator (the CLAUDE.md eval-substrate seam stands). The
runner does **not** build the tier-3 evaluator and does **not** orchestrate
deployment.

## Scope and boundaries

- **Two new verbs**, both operating on the **host repo** the runner is invoked
  from: `monition snapshot` (capture) and `monition replay` (vary-and-measure).
- Only **monition-store** reads are `export-firings`-gated (G1). The manifest's
  fragments are opaque text/config; a tier-2 caller may source them via
  `export-firings`, a tier-3 caller (CMS) hands them in. The runner never special-
  cases "firing."
- The runner reads the firing's v5 `situation` + `git_sha` only as a
  locator/fingerprint linking a snapshot to its originating firing — not as the
  reconstruction (decision 4).

## Decisions and rationale (firm)

1. **Context manipulation = minimal-mock file injection (resolves OQ1).** A
   condition's included fragments are written as files into that condition's
   worktree before the agent launches (into `CLAUDE.md` and/or a known context
   path the agent reads); "without" is simple omission. One uniform mechanism
   serves tier-2 one-liners and tier-3 CLAUDE.md lines (G1). The runner does **not**
   initialize a store, wire hooks, or re-simulate disclosure-hook firing — that is
   the full-environment simulator the design rejected. *Accepted tradeoff:*
   injecting a takeaway's text as a worktree file is not byte-identical to the live
   disclosure path, so tier-2 ΔP(fail) **approximates** the real disclosure rather
   than replicating it.

2. **Execution surface = interactive `claude`, never `claude -p` (resolves OQ2).**
   Each condition runs a real interactive Claude agent (no `-p`) launched in tmux
   inside the condition's worktree, on the **subscription** billing bucket. The
   model is pinned (`--model`) and the exact model id is recorded into every
   artifact for cross-condition comparability. *Rationale:* post-2026-06-15,
   `claude -p` / the Agent SDK / GitHub Actions / third-party API clients draw from
   a smaller metered programmatic credit bucket; interactive PTY `claude` stays on
   the subscription. Avoiding `-p` is also
   backwards-compat insurance against that bucket's churn.

   *Permission posture (live-validated 2026-06-14).* An unattended agent in a fresh
   worktree hits claude's **workspace-trust dialog** and per-tool approval prompts
   with no one to answer, so it blocks at the gate and never runs the task.
   The `TmuxBackend` therefore launches with **`--dangerously-skip-permissions`** and
   passes the prompt after a **`--` end-of-options separator** (a prompt opening with
   the `---` worker-protocol header is otherwise parsed as an unknown flag and claude
   exits). Skipping permissions is acceptable *because* of the mandatory disposable-
   worktree isolation (decision 8) — the sandbox the flag's warning presumes is
   missing is exactly what the runner provides; the agent can touch nothing but a
   throwaway worktree that is force-removed after harvest. Opt out per-backend with
   `TmuxBackend(skip_permissions=False)`. The agent's stdout is teed to
   `<condition>/agent.log` so a blocked or erroring agent leaves a trace rather than
   dying silently with the tmux pane.

3. **Completion is branch-authoritative; harvest from the filesystem (resolves
   OQ2, cont.).** A condition is done when a **new commit appears on its branch**
   *or* a stable non-empty report file appears — **the branch is authoritative, the
   report advisory** (a worker that commits but skips the report still completes).
   The harvested deliverable is the **git diff on the condition branch** plus the
   outcome-check verdict; the agent transcript/report is advisory. This depends on
   no `-p` output format and no transcript parsing, so it survives surface churn.
   The agent is seeded with a worker protocol (do the task; commit to your branch,
   honoring pre-commit hooks; write your report to the outbox path; end with a
   `STATUS:` line). A per-run wall-clock timeout bounds a stuck condition.
   *(Completion contract and worker-seed protocol are adopted as **design** from
   `agent-harness`'s `wait_turn`; see decision 6 — the code is monition's.)*

4. **Snapshot convention = dirty-tree commit on a dedicated ref namespace
   (resolves OQ4).** `monition snapshot` records a throwaway commit capturing the
   **full dirty tree** (tracked + untracked) under `refs/monition/snapshots/<id>`
   — not a tag, not a stash entry (durable, namespaced, no pollution of branches/
   tags). It captures **without mutating the working tree, HEAD, branches, or
   tags** (stash-create-style: build a commit object, write only the side ref). The
   snapshot's commit message stamps the originating firing's `git_sha` (as the base
   it forked from) and `situation` fingerprint, linking snapshot↔firing.
   `snapshot_ref` passed to `monition replay` is that ref. The snapshot is the
   *reconstruction*; the firing's recorded provenance is only the *locator*.

5. **Snapshot is auto-captured on flag, by human or in-session LLM; detection
   stays judgment (resolves OQ4, cont.).** Either a human or the in-session agent
   may flag an issue and call `monition snapshot` — the **capture** is automatic
   and complete in one call; **deciding to flag** remains a judgment act, not an
   autonomous detector (automating detection is the D3 path the review rejected).
   Snapshots are idempotent per `<id>` so repeated flags for the same issue do not
   pile up redundant refs. In v1 `monition snapshot` is a plain CLI call either
   party runs; no hook/skill wiring is required.

6. **Build a self-contained runner driver in monition; borrow agent-harness's
   design, not its code; expose a pluggable backend seam (resolves the
   execution-backend fork).** *Audit verdict (2026-06-14):* existing external
   agent-runner tools were evaluated and none fit a discard-everything replay
   runner — variously untested, lacking completion-detection or diff-harvest, or
   landing-oriented (the opposite shape; e.g. a one-shot `send` with no continuity,
   or a worktree that can't take a non-branch snapshot ref or pre-run file
   injection). The part that fits is small enough to own; the part already built
   elsewhere is the part the runner can't use. *Decision:* monition implements its
   own driver (worktree-off-ref → inject files → launch interactive `claude` in
   tmux → branch-authoritative completion → harvest diff + run outcome-check →
   teardown), **borrowing the completion-contract, worker-seed, and isolation
   lessons as design**. A **pluggable execution-backend seam** lets a GUI or
   hosted-agent backend be registered later without reworking the runner core.
   Default backend: monition's tmux driver.

7. **One run per condition; sequential by default; guarded (resolves OQ3).** The
   runner does **exactly one** headless run per condition — repeat-and-aggregate is
   CMS-discipline (CMS calls the runner again for N samples). Conditions run
   **sequentially** by default, with an opt-in bounded `--parallel N`; sequential
   is the safe floor because parallel interactive agents still consume the
   subscription's 5-hour/weekly caps and N live sessions raise the contamination
   surface. Guards: a hard **cap on conditions per call** (default 8, overridable),
   a **per-run wall-clock timeout**, and **`--dry-run`** listing the worktrees/runs
   it would create without spawning agents. Model-version pinning is the only
   determinism lever the interactive surface exposes; finer non-determinism control
   is CMS's (repeat-and-aggregate).

8. **Mandatory per-condition isolation and teardown.** Each condition gets its own
   worktree on its own branch forked from the snapshot ref, auto-cleaned after
   harvest; no shared locks or shared store across conditions. This directly
   answers the contamination lesson ("the agent's own testing became the
   contaminant" — stale SingletonLock):
   one condition's run cannot mutate the host repo's working tree or another
   condition's state.

9. **Formats and CLI surface (resolves OQ5).**
   - **Manifest** — a single human/discipline-authored **YAML** file declaring:
     the minimal env to materialize, the task prompt, the `conditions` list (each =
     `id` + fragment-include set + outcome-check command), and the model pin.
   - **Output** — one **directory per condition** (worktree `diff`, run report/
     transcript, outcome-check verdict) plus a top-level **`summary.jsonl`** (one
     record per condition) for machine consumption. Bulky diffs/logs stay in the
     per-condition dirs; the summary stream stays thin — mirroring the repo's
     existing YAML-in / JSONL-out split (`export-firings` emits JSONL).
   - **Verbs** —
     `monition snapshot [--issue <desc>] [--firing <id>] [--store DIR]`
     and
     `monition replay --snapshot <ref> --manifest <file> [--out <dir>] [--parallel N] [--dry-run] [--backend <name>]`,
     fitting the existing argparse subcommand style.

## Key constraints

- **Billing:** never `claude -p` (decision 2). Tests must not spawn real agents
  (use a stub backend via the seam — decision 6).
- **Fail-open consistency with monition:** `monition replay` errors clearly if its
  backend prerequisites (tmux, `claude`) are absent and never corrupts the host
  repo; `monition snapshot` writes only under `refs/monition/snapshots/` and never
  touches the working tree, HEAD, branches, or tags.
- **Contract gating (G1):** only Monition-store reads go through `export-firings`;
  the variation input itself is opaque.
- **Seam discipline:** the runner stops at artifacts (G2). No score, no rubric, no
  aggregation, no deployment orchestration.

## Success criteria

- `monition snapshot` records a side-ref commit capturing the dirty tree (tracked +
  untracked) **without mutating** working tree / HEAD / branches / tags, and stamps
  the firing fingerprint; idempotent per `<id>`.
- `monition replay` over a **fixture snapshot + a 2-condition manifest** produces
  per-condition worktrees off the snapshot, injects each condition's fragments,
  runs the task on interactive `claude` (no `-p`), detects completion
  branch-authoritatively, and emits per-condition dirs + `summary.jsonl` carrying
  diff + outcome-check verdict — **and computes no score**.
- Worktrees auto-cleaned; condition cap, per-run timeout, and `--dry-run` enforced;
  `--parallel N` bounded.
- **Backend seam:** the default tmux driver works, and a second backend can be
  registered without touching the runner core (proven by a **stub backend** used in
  tests so the loop is covered without burning the subscription).
- `pytest` green including snapshot-capture, the stub-backend replay loop, isolation/
  teardown, and the guards; fits CLI conventions; this spec cites the design review.

## Defaults adopted

**Firm:** everything under Decisions. **Tentative (deferred to implementation):**
condition cap (8); per-run wall-clock timeout value; the `<id>` derivation scheme
for snapshots; the context-file injection path/name beyond `CLAUDE.md`; the
`summary.jsonl` record schema (version-stamped per the additive-column discipline);
`--parallel N` default ceiling.

**Resolved in v1 build (2026-06-14):** condition cap = `DEFAULT_CONDITION_CAP = 8`,
overridable via `--max-conditions`. Per-run timeout = `DEFAULT_RUN_TIMEOUT = 1800.0`s,
overridable via `--timeout`. `<id>` derivation = `firing-<n>` when `--firing` is
given, else the issue text slugified, else `snap-<UTC-timestamp>` (the firing/issue
forms are stable, so re-flagging overwrites one ref). Injection path = an arbitrary
per-fragment `path` (any worktree-relative file, not just `CLAUDE.md`) with a
`mode: append|write`, default `append`. `summary.jsonl` record = stamped
`schema_version` (`REPLAY_SCHEMA_VERSION = 1`), additive-column discipline, **no
score field**. `--parallel N` ceiling = `MAX_PARALLEL = 4` (sequential default).

## Open questions deferred to implementation

Annotated with the v1 build's resolutions (2026-06-14). RESOLVED = settled in code;
STILL DEFERRED = consciously left for a later increment.

- **Dirty-tree capture mechanism** including untracked files and submodules
  (`git stash create` captures tracked-only; capturing untracked needs a temp-index
  step) — pick the exact mechanism that keeps the working tree untouched.
  *RESOLVED (`snapshot.py`):* a throwaway temp index (`GIT_INDEX_FILE` →
  `git add -A` → `write-tree` → `commit-tree` → `update-ref`). Captures tracked +
  untracked, excludes `.gitignore`d paths, and touches neither the real index,
  working tree, HEAD, branches, nor tags. *Known v1 limit:* submodules are captured
  as gitlink pointers only, not their working-tree contents.
- **Outcome-check interface:** exit-code vs structured output; exactly what the
  verdict record holds and how a tier-2 reader vs CMS consumes it.
  *RESOLVED (`replay.py`):* exit-code authoritative — `passed = (exit_code == 0)`.
  Verdict record = `{command, exit_code, passed, stdout, stderr}` (stdout/stderr
  tail-truncated to 4000 chars), written per-condition as `verdict.json` and inlined
  into each `summary.jsonl` row. A tier-2 reader reads `passed` + the diff directly;
  a tier-3 caller (CMS) consumes the same record under its own rubric.
- **Backend-seam interface signature:** what a backend must implement
  (`spawn(worktree, prompt)`, `is_done(branch | report)`, `harvest`, `teardown`).
  *RESOLVED (`backends.py`):* `Backend` = `preflight()`, `spawn(spec)`,
  `is_done(spec)` (default branch-authoritative — new commit ⇒ done, else stable
  non-empty report; overridable), `teardown(spec)`. **Harvest and worktree lifecycle
  stay in the runner core** (generic git), keeping the seam small. Registry =
  `register_backend(name, factory)` / `get_backend(name)`; default `tmux`;
  `StubBackend` is the test seam.
- **`summary.jsonl` schema and versioning** — align with `export-firings` /
  `retrievals-log` additive-column + version-stamp discipline.
  *RESOLVED (`replay.py`):* each row stamps `schema_version`
  (`REPLAY_SCHEMA_VERSION = 1`); fields are additive (consumers ignore unknowns); no
  score field (G2). Not yet promoted to a formal `docs/contracts/` schema — earns one
  if/when a second consumer binds to it.
- **tmux/`claude` availability checks** and the precise fail-open behavior.
  *RESOLVED (`backends.py`/`replay.py`):* `TmuxBackend.preflight()` checks both on
  `PATH` and raises `BackendError` with a clear message **before any worktree is
  created**; never falls back to `claude -p`. `monition replay` errors clearly and
  leaves the host repo uncorrupted (worktree teardown in a `finally`).
- **GUI / hosted-agent backend** adoption once an upstream runner matures (the
  one-shot-send and branch-base limitations must be resolved upstream first).
  *STILL DEFERRED:* the pluggable seam is in place; no GUI backend is registered in
  v1 (the upstream one-shot-send / branch-base limits are unresolved).
- Whether `monition snapshot` later earns hook/skill wiring for the in-session
  agent (v1: plain CLI call by either party).
  *STILL DEFERRED:* v1 ships `monition snapshot` as a plain CLI call by either party,
  as specified; no hook/skill wiring.

## Provenance / links

- Design review (architecture, ratified): `docs/decisions/2026-06-14-replay-ablation-runner.md`.
- Seam: confer `2026-06-14 eval-engine-seam-and-archive-durability`.
- Firing-grain fingerprint this leans on: `docs/decisions/2026-06-13-firing-capture-minimum-for-cheap-eval.md` (v5 `situation`).
- Store-read gating: `docs/contracts/export-firings.md`.
- Verdict registry: `docs/road.md §2` ("Replay-ablation runner is monition's machinery…").
