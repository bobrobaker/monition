---
status: decided
---
# Firing capture: the minimum a firing must carry for the cheap eval

**Status:** Resolved (confer 2026-06-14, eval-engine-seam-and-archive-durability;
user-ratified). The open fact is answered — CMS's archive retains only **session-grain**
context, so the firing-grain capture minimum is now **unconditional** and lands in
monition (git SHA+dirty already v4; + trigger match + situational excerpt/pointer;
un-truncate `on_demand`) as an additive v4→v5 bump. Option **B** (join, don't fatten)
still holds for *session-altitude* context. Contract bump not yet implemented. Type:
[[design_review]] (project-internal — `firings` schema is monition substrate).

## Question

A cheap eval (LLM-judge re-poses the fire/suppress decision *with* vs *without* a
candidate takeaway, over the captured decision context, and diffs the outcome) is
the eval we will actually run — not full-environment replay. **What is the minimum
decision context such an eval needs, and how does a firing carry it** — by enriching
the `firings` schema, or by recovering it on demand from elsewhere? The capture half
is unbackfillable, so the choice must be made before more firings accumulate.

## Evidence (audit, 2026-06-13, CMS store, 93 firings, via `export-firings`)

- **Provenance mostly absent:** `git_sha` NULL 62/93 (67%), `model` NULL 78/93 (84%)
  — v4 columns exist only on recent firings; the backlog is unbackfillable for
  environment replay.
- **Decision context thin-to-absent:** `trigger_context` NULL 30/93, *all* of them
  `session_start` (carry nothing); `edit_path` carries only a file path; `on_demand`
  carries the prompt **truncated at 200 chars** (confirmed max = 200).
- **Every firing has `session_id` + `fired_at`** (100%) — a usable join key.
- Rating signal sparse: 20/93 rated.

What's actually evaporating daily is **the transcript context around each firing**,
not the firing record (durable in the store).

## Options weighed

**A — Enrich the `firings` schema** (add columns capturing fuller fire-time context:
full prompt, edit diff/hash, candidate set).
*Why it loses (as the primary path):* it guesses what the eval needs *before the eval
exists*, forces a contract bump (v4→v5), bloats every row, and still cannot capture
`session_start`'s "the whole session is the context" case. Premature schema commitment
to an uncalibrated instrument.

**B — Thin record + join to the session archive** by `session_id` + `fired_at`
(recover decision context on demand from CMS's just-shipped archive).
*Why it wins, partially:* no schema bump; follows the established "join-on-demand
through the reader, never a merged store" discipline; leverages P1. *Its risk (load-
bearing):* depends on the archive durably retaining **firing-grained** transcript
context — it currently keeps *summaries* (progressive disclosure), and the raw session
JSONL is ephemeral. If the join target only has a summary, the context at a specific
firing's timestamp may be too coarse for the cheap judge. Cross-repo dependency.

**C — Snapshot-at-issue + thin record** (the engine design): the passive record stays
thin and merely *locates* the moment; rich context comes from a deliberate snapshot
taken when an issue is flagged.
*Why it's a layer, not the answer here:* highest fidelity exactly where it matters and
no per-firing bloat, but it only covers *snapshotted* moments (no retro-eval of an
un-snapshotted firing) and requires the snapshot trigger/discipline — i.e. the engine,
which is gated on the [[confer]] over the eval-substrate seam. Out of scope for this
doc; it answers a different (criticality-gated) question.

## Decision (proposed)

**Reject A as the primary path. Default to B (join, no schema bump). Make exactly one
additive capture change now, conditional on one fact.**

- **B is the default** decision-context recovery path: join `session_id` + `fired_at`
  → session archive. No `firings` contract change for the common case.
- **The one change to make now (trigger):** stop truncating `on_demand` context at 200
  chars — widen the captured prompt — **iff** raw session transcripts are *not* durably
  retained at firing-grain. This is the only capture that is both (i) the context we
  already chose to record and (ii) currently being thrown away at write time, and it is
  additive (widen an existing column, no enum/contract semantics change). If transcripts
  *are* durably retained and joinable, even this is unnecessary and B fully covers it.
- **C (snapshot-at-issue)** is the high-fidelity layer for criticality-worthy issues,
  owned by the engine design-review + confer — not this doc.

## Rationale

The audit shows the firing record is durable but the *context* is what's bleeding, so
the fix belongs at the context layer, not (mostly) the schema. A guesses the eval's
needs before the eval exists (the same premature-instrument error that gates P3/P4); B
spends nothing and rides P1, at the cost of a durability dependency we can name and
test rather than guess. The single additive change (un-truncate `on_demand`) is the
narrow, unbackfillable, do-it-now slice that survives regardless of how the engine
seam settles — it preserves the one context we already capture.

## Open dependency → confer

B's durability risk is a **CMS dependency**: the session archive must retain
firing-joinable context, or B silently degrades. Raise in the eval-substrate-seam
[[confer]] (engine design-review), alongside the seam placement. Until ratified, no
`road.md §2` registry line and no contract edit.

## Provenance / links

- Audit: `monition export-firings --store <CMS>/monition` (2026-06-13).
- Contract that would change under A: `docs/contracts/takeaway-store.md` (firings, v4).
- Engine design-review + seam confer: pending (cross-project).
- Cross-project build order: tracked in the cross-project roadmap.
