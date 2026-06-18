# Module realignment — Monition as an installable module

Alignment artifact from the 2026-06-11 grilling session (`/grill-me --impl`).
Status: **accepted with CMS amendments** — reviewed via confer thread
"2026-06-11 confer takeaway-machinery-ownership", resolved
same day. Decisions 13–14 below incorporate the amendments; cutover is unblocked.

## Task as understood

Reverse the consumer-only scope. Monition stops being a read-only value layer over
stores owned elsewhere and becomes an **installable module** that owns all takeaway
machinery — store schema, trigger executors, `init`/`sync`/`migrate`, reader,
metrics, report, and (next phase) score. Host projects install it once per machine
and run `monition init`; all data stays per-project. CMS becomes the first
installer and stops owning `tools/takeaway*.py`.

## Vocabulary (firm)

- **Monition** — the initiative *and* this module/repo. Never the rows.
- **Takeaways** (or gotchas) — the rows: the lessons themselves.
- **Monition store** — a per-project Dolt instance, created by `monition init` at
  the convention path `<repo-root>/monition/`. ("Store" alone is avoided.)

## Goals and non-goals

**Goals:** one owner for machinery (no fork-drift); one-command adoption per
project; data, ratings, and decisions stay per-project; fail-open everywhere;
every incubated CMS project gets working gotcha capture/disclosure on day one.

**Non-goals:** online scoring (next phase); an MCP server (noted as a candidate
query surface for `on_demand` in a later phase — never the backbone, because
disclosure must be harness-deterministic, not model-invoked); multi-store or
configurable store paths (convention only until a second need exists); central
data storage of any kind; rewriting outside Python (it is a CLI tool whose
language is invisible at every boundary).

## Decisions and rationale (firm)

1. **This repo is the module's home — not a CMS subfolder.** Homing shared
   infrastructure inside its first consumer inverts the dependency and makes CMS
   load-bearing for unrelated projects.
2. **No hand-maintained copies in host repos.** Distribution by copy is a fork;
   the contract fingerprint check is a tripwire, not a sync mechanism, and it
   cannot see behavioral drift in executor code at all. Hooks call the installed
   CLI.
3. **Install: global editable install** (`uv tool install --editable
   ~/projects/monition`-style). One install serves every project; edits propagate
   instantly. Accepted risk: a broken working tree degrades all projects at once —
   softened to silence by fail-open.
4. **Fail-open is designed in and tested.** Hook entries written by `init` guard
   on the command's existence (`command -v monition >/dev/null && monition
   fire-hook || true`). Module uninstalled ⇒ zero noise, everything behaves as if
   Monition never existed. This is a tested exit criterion, answering the CMS
   handoff's sharpest objection.
5. **Skills are materialized, not pointers.** `init`/`sync` install full skill
   text into `.claude/skills/` with a version stamp; `sync` hash-checks — untouched
   skills upgrade silently, locally-edited ones warn and are left alone. Keeps all
   executable behavior inside the protected skill surface (user's correction of the
   thin-shim default).
6. **`init` is invasive but idempotent and transparent:** merges its hook entries
   into `.claude/settings.json` (never touching others), installs skills, prints
   exactly what changed; `--dry-run` shows the diff. Offers (never imposes) a
   pre-commit hook running `monition dump`. Checks for the `dolt` binary and fails
   clearly rather than half-creating a store.
7. **Decision log = a `decisions` Dolt table** beside `firings` (schema v3),
   shipped with the scoring phase. The co-ownership objection dissolved when
   ownership unified.
8. **Cold start: always-fire below an evidence threshold** (N rated firings per
   takeaway; N deferred). Monition only suppresses what it has proof is noise.
9. **The contract survives, demoted from treaty to spec** of the code↔data
   boundary (retitled for Monition stores). The fingerprint check stays — old
   store data legitimately meets newer code — and `monition migrate` becomes the
   repair path the check points to.
10. **Trigger-as-data survives.** Rows still own *what fires when*; the module
    owns *how matching executes*. The founding bet is untouched.
11. **CMS upstream contract changes from mirror-back to version-bump semantics**
    for this machinery. The self-containment cost applies only to *graduated*
    projects (see decision 13): incubated projects stay fully self-contained at
    tier 0; a per-machine Monition install is required only after graduation.
    Accepted: single-machine reality, fail-open absence, plus a README line
    dropped by `init`.
12. **Roadmap restructure:** Phase 2 = moduleization + CMS cutover; Phase 3 =
    scoring (`monition score`, decisions table, cold-start rule); Phase 4 =
    tuning/retrieval (+ possible MCP on-demand surface). Phase 1's exit stands.
13. **Tier-0 incubation path (CMS amendment, accepted).** Incubated projects do
    not require a Monition install: the CMS payload ships a self-contained
    file-based loop — lessons as structured markdown blocks (same fields as the
    store schema) plus a small *frozen* stdlib executor, copied in, fail-open.
    `monition init --adopt <file>` is the graduation step, importing the blocks
    mechanically; adoption is one-way. Built in Phase 2 with fixture tests so
    the format is validated, not just specced. **Monition owns the interchange
    format** as a section of the contract doc; the CMS payload cites it, never
    duplicates it. Frozen-ness is the load-bearing property: if tier-0 matching
    semantics ever need to evolve in lockstep with the store's, this design is
    void and the day-one story must thin instead (per the confer thread).
14. **Fail-open covers broken, not just absent (CMS condition, accepted).** The
    existence guard alone swallows exists-but-crashes (the editable-install
    failure mode of decision 3). The hook guard appends stderr to a per-machine
    state log (`~/.local/state/monition/hook-errors.log`); a crash test —
    monition present but failing → session unblocked *and* failure visible in
    the log — joins the uninstall test as a Phase 2 exit criterion. `monition
    doctor` deferred unless the log proves insufficient.

## CMS cutover checklist (Phase 2, blocked on CMS review)

- Delete `tools/takeaway.py`, `takeaway_fire.py`, `takeaway_brief.py`.
- Rewire `.claude/settings.json` hooks to guarded `monition` calls.
- Rewire `.githooks/pre-commit`'s dump line to `monition dump` (lint half
  untouched — CMS's own concern).
- `git mv takeaways monition` + path updates in docs/hooks.
- Live store data untouched (already v2); zero-data-loss verified by content hash.
- CMS doc edits, consented in a CMS session: `docs/DESIGN.md` (seams, upstream
  contract), `method/takeaway-store.md`, `method/instantiate.md` (+1 step: run
  `monition init` in fresh projects).
- One smoke firing end-to-end; one uninstall test (silence).

## Success criteria (module phase)

`monition init` on a fresh repo yields working capture/disclosure; CMS cutover
complete with store content hash unchanged; uninstall test silent; crash test
(present-but-broken) unblocked and logged; `init --adopt` round-trips a tier-0
fixture file into store rows; `pytest` green (existing 18 + new
init/sync/migrate/adopt/fail-open coverage); instantiate protocol updated.

## Consent path

Completed 2026-06-11: CMS reviewed via the confer thread
"2026-06-11 confer takeaway-machinery-ownership" and accepted the realignment
with amendments 13–14 (incorporated above). The handoff `2026-06-11 monition
module-boundary-review.md` is answered by this spec (audit steps superseded;
its objections addressed in decisions 4, 11, 13, 14). CMS implements the tier-0
payload and its three governed-doc edits at cutover; Monition implements
everything else. Monition-side governed docs (CLAUDE.md, road.md, contract
preamble) are rewritten as the first act of Phase 2.

## Defaults adopted

**Firm:** everything under Decisions. **Tentative (deferred to implementation):**
cold-start N (~3); version-stamp format; hook timeout values; `decisions` table
columns; second-machine install story (README line only for now).

## Open questions deferred

- Exact `decisions` schema and what `score` logs per decision (Phase 3 design).
- Whether `on_demand` gets an MCP query surface (Phase 4 candidate).
- Config surface if a project ever needs a non-convention store path (deferred
  until it exists).
