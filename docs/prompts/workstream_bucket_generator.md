# Workstream + Bucket Generator Prompt

The goal of this prompt is to produce actual markdown files for a multi-session implementation effort:

1. Produce one parent workstream file: the always-read router for objective, progress, bucket order, cross-bucket invariants, global implementation notes, non-goals, and cross-bucket updates.
2. Produce as many bucket files as needed: each bucket is a short-session cluster of tasks with shared concept, edit surface, and validation.
3. Before finalizing, internally stress-test:
   - Are bucket boundaries based on context, not arbitrary feature count?
   - Is any parent content actually bucket-local?
   - Are any buckets too large for one session?
   - Are required touchpoints minimal and sufficient?
   - Are conditional/do-not-read notes preventing wasted intake?
   - Are prior mistakes, introspection notes, or bug logs converted into gotchas?
   - **If data-pipeline workstream** (ingestion, transformation, serialization, schema changes, generated datasets, source pointers, IDs/indexes, or cross-bucket data handoff): Is there a data contract? For each bucket boundary, what structure is passed forward? Are all downstream-needed fields preserved before filtering/sorting/grouping/joining? Are names like `index`, `line_number`, `source`, `id`, `rank`, and `step` unambiguous? Could a downstream bucket accidentally substitute a processed-list index for a raw-source coordinate? Is there a conservation invariant proving every input record is accounted for? Are rejected/skipped/malformed records counted separately enough to diagnose systemic schema problems? And note: renaming a field or key does not change any value derived from unchanged inputs — a rename is a naming-consistency fix only; changing derived behavior needs different inputs or logic, and the bucket must say which.
4. Respond in chat with:
   - **Files created** — file paths and one-line purpose.
   - **Assumptions made** — brief bullets.
   - **Compression rationale** — what was omitted, moved to buckets, or preserved globally, and why.
   - **Questions / risks** — only material unresolved issues.

## General information

Brevity rules:
- Every generated word must improve code quality or token efficiency.
- Parent workstream: global objective, progress, bucket index, cross-bucket invariants, global implementation notes, non-goals, updates.
- Bucket files: bucket-local tasks, touchpoints, constraints, validation, gotchas, handoff.
- Do not duplicate bucket detail in the parent.
- Prefer terse but precise instructions over narrative explanation.
- If a bucket's design direction or data contract needs more than two rounds of concern-surfacing before implementation, stop and restructure those sections into explicit **named invariants** ("Core invariant: A must match B") — prose guidance allows ambiguity that only surfaces as concerns after reading; named invariants force resolution at spec time.

File naming rules:
- Create files under `docs/workstreams/[workstream-slug]/` unless another location is specified.
- Parent file: `docs/workstreams/[workstream-slug]/workstream.md`.
- Bucket files: `docs/workstreams/[workstream-slug]/buckets/B##_short_slug.md`.
- Use lowercase kebab-case for `[workstream-slug]` and bucket slugs.
- Use stable bucket IDs: `B01`, `B02`, `B03`, etc.
- Bucket filenames must begin with their bucket ID.
- Keep names short but specific: `B01_policy-config.md`, not `B01_first-bucket.md`.

Bucket split rules:
- First split by conceptual mapping: group tasks that require the same mental model and nearby files.
- Then split further if a bucket is likely to exceed a short session.
- Target roughly 5-minute execution sessions; definitely split if likely above 10 minutes.
- A tiny task may share a bucket if it uses the same loaded context.
- Split tasks with unrelated edit surfaces even if they are thematically adjacent.
- Assume only one active bucket at a time. Do not design for parallel bucket execution unless explicitly requested.

Touchpoint: a bounded code region the implementer should inspect because it is edited, directly called, or preserves an invariant.

Touchpoint rules:
- Required touchpoints: likely edit surface or necessary invariant reads. No broad conceptual reads. When a prior bucket must be read for handoff only, write the touchpoint as: `grep "## Updates" B0N.md, then read from that offset` — do not list the full file as a required read.
- Do not add the always-on agent doc (CLAUDE.md/AGENTS.md) as a required touchpoint in file-creation-only buckets — it is a conditional existence check at most.
- Conditional touchpoints: insurance reads with explicit trigger conditions. When a bucket's fix lives entirely in one module, touchpoints in downstream consumers of that module are Conditional ("read only if the fix might affect X"), not Required — Required reads of downstream systems are warranted only when the bucket explicitly changes them.
- Do-not-read touchpoints: tempting distractions; encode the conclusion so the implementer does not rediscover it. Omit this section entirely if empty.
- Do NOT add a generated artifact file (a report, a dataset) as a required touchpoint unless the bucket explicitly reads or writes that file's content. If the bucket only needs the artifact's path or metadata, encode that in the bucket spec and omit the file touchpoint.
- Test-only buckets (writing tests against an existing API, no new source files): pass API signatures and helper patterns as grep touchpoints (`grep -n "def <api_fn>"`), never full source files — the implementer needs the signatures, not the implementations.
- Coverage-gap greps must include both the function/predicate names AND the emitted label/string constants those functions produce — grepping only for names misses tests that cover the same behavior via its output strings.
- Prefer line ranges, symbols, and grep queries over full-file reads.
- Format touchpoints as:
  `[file]  [line range or grep query]  [symbol/anchor]`
  followed by a short reason.

Characterization/lock buckets (locking existing behavior before extraction or refactor): `## Design direction` must specify the exact assertion levels — which API is called at each level and that exact values/full expected sets are asserted (`score == approx(X)`, `set(reasons) == {…}`). "Assert exact values only where stable and useful" is too vague and produces weaker assertions by default, missing bugs introduced during extraction.

Multi-variant buckets (introducing parallel extractors, scorers, adapters, or providers for comparison): resolve three things at spec time — (1) the path used to assess a candidate must match the path used to evaluate it, as a named invariant; (2) include a "Step 0 inspection gate" in Required touchpoints that reads the actual variant implementations before any adapter or sample code is written; (3) make the variant kind an explicit required field on any config — never inferred from adjacent properties.

## Input to convert

Goal / technical discussion:

[PASTE GOAL OR DISCUSSION HERE]

Relevant files, docs, introspection notes, bug logs, prior decisions:

[PASTE CONTEXT HERE]

## Workstream template

Use this structure for the generated parent file. Keep section names.

```markdown
# Workstream: [Name]

Progress: B01/[1-5 word focus] next
Blocked: none

## Objective

[2-4 sentence compressed objective. Global only.]

## Execution Protocol (do not change)

1. Read this workstream first. For B01, read the full file. For B02+, do NOT use `cat` — run `grep -n "^##" workstream.md` first to get section line anchors, then use bounded reads for only: Objective, Execution Protocol, Bucket Index, and Cross-Bucket Invariants — skip Deferred/Non-Goals, Estimate, and any lower boilerplate sections.
2. Use `Progress` and `Bucket Index` to select the active bucket; if none is active, select the next bucket.
2a. If the index references a bucket file that does not exist yet, read `## Bucket template` in the generator prompt before creating it.
3. Open only the selected bucket file. If its `State` is not `active`, update it to `active` before reading touchpoints.
4. Read only that bucket's required touchpoints before reporting.
5. Report first: selected bucket, required touchpoints read, current behavior, proposed edits, validation plan, and extra touchpoints if needed.
6. Only edit after the plan is clear.
7. Run the bucket's validation.
8. Update the bucket file's `Updates` section with completed tasks, discoveries, gotchas, test results, and handoff notes.
9. Update this workstream's `Progress`, `Bucket Index`, and `Updates` only for progress, sequencing changes, cross-bucket discoveries, and cross-bucket gotchas. Also update the next bucket file's `State` from `later` to `next`. Use the Read tool (not Bash `cat`) to open workstream.md before editing it — Edit requires a prior Read call.
10. Keep only one bucket active at a time unless the user explicitly authorizes parallel execution.

## Bucket Index

| B | State | File | Goal | Depends |
|---|---|---|---|---|
| B01 | next | buckets/B01_short_slug.md | [short goal] | — |
| B02 | later | buckets/B02_short_slug.md | [short goal] | B01 |

States: `next`, `active`, `blocked`, `done`, `deferred`, `later`.

## Cross-Bucket Invariants

- [Global invariant the implementer must preserve across buckets.]

## Deferred / Non-Goals

- [Out-of-scope item the implementer may be tempted to do.]

## Global Implementation Notes

- [Implementation detail relevant across the whole workstream.]

## Updates

- [YYYY-MM-DD HH:MM] Initial plan created. Next: B01/[focus].
```

Workstream file rules:
- Do not include bucket-local touchpoints, detailed task lists, or bucket-local validation.
- Put discoveries here only if they affect later buckets or the whole workstream.
- Keep `Progress` to one line. Use `Updates` for details.
- Keep `Bucket Index` as the source of truth for sequencing.
- `Updates` entries are chronological ascending: **append new entries at the end**, oldest entry first.

## Contract-doc trigger rule

**When to create a contract doc:** when the workstream creates, transforms, serializes, filters, joins, trains on, exports, or consumes a durable data/model artifact — generated datasets, source pointers, schema versions, feature/metric key families, config artifacts consumed at runtime, or any field/key family consumed by a later bucket or future phase.

**When to skip:** localized refactors, one-file bugfixes, behavior-only changes with no serialized artifact or cross-bucket data handoff.

**What to do:** before splitting buckets, create `docs/contracts/[contract-slug].md`. Then:

1. Add one invariant line to `## Cross-Bucket Invariants` in the parent workstream:
   ```
   - Data/model contract: preserve `docs/contracts/[slug].md`; buckets that touch [artifact/key family] must read the relevant section before editing.
   ```
2. Wire contract-touching buckets to bounded contract sections as required touchpoints (not the full doc). B01 may read the full contract if it is defining it. Later buckets read only the section that applies.
3. Add this report-first hook to any bucket that touches the contract:
   ```
   Report first (contract check):
   - Which contract section applies to this bucket?
   - What producer/consumer boundary does this bucket touch?
   - What contract fields, keys, or artifacts could this edit break?
   - What validation will prove the contract is preserved?
   ```

**Key principle:** field names are not contracts. `line_number`, `index`, `source`, `rank`, and `key` are ambiguous unless the contract defines coordinate system, producer, consumer, and validation rule.

Examples of ambiguities that must be explicit in the contract:
- `line_number` — raw file line vs parsed-entry index vs filtered-entry index. A pointer attached after filtering silently stops referencing the raw source.
- Key format — `namespace.name` vs `namespace_name`. A near-miss format breaks every consumer that groups by prefix, and nothing errors at write time.

The contract doc owns interface semantics. The workstream owns execution sequencing. Do not duplicate the full contract into every bucket — reference it with bounded section reads.

## Bucket template

Use this structure for each generated bucket file. Keep section names.

```markdown
# Bucket [B##]: [Name]

Parent: ../workstream.md
State: [next/later/active/blocked/done/deferred]  ← set `next` for the bucket that is immediately active at creation; `later` for all others
Goal for session: [10 words max].
Target duration: [estimated time, e.g. 20 min]
Context budget: Read parent + this bucket + required touchpoints only.

## Conceptual mapping

- [Why these tasks share context/edit surface.]

## Data contract / provenance

*(Omit for buckets that do not own or consume a cross-bucket data structure. If a contract doc exists for this workstream, add the relevant contract section as a required touchpoint instead of duplicating the contract here.)*

- Inputs: `[data structure/path]` — [exact meaning and producer]
- Outputs: `[field or artifact]` — [exact meaning and consumer]
- Provenance: `[source pointer / ID / index / path fields]` — [coordinate system; when attached; what must not be substituted]
- Validation: [conservation check, consistency check, rejection reasons]

**Field name rule:** When a bucket consumes a JSON/JSONL artifact produced by a prior bucket, field names in this section must be verified against a real sample of that artifact — not guessed from the prior bucket's spec. If the artifact does not exist yet at spec-writing time, mark fields as `(verify at implementation time)` so the implementer knows to inspect before writing code.

**Signal availability rule:** When specifying diagnostic or scoring fields, explicitly state what signal the pipeline actually produces. Do not design fields around concepts that require ground-truth labels the pipeline does not have.

*(Contract-touching buckets: include the report-first hook from the contract-doc trigger rule in `## Design direction` or as the first step in the session.)*

## Tasks

- [ ] [Concrete task.]
- [ ] [Concrete task.]

## Required touchpoints

- `[file]  [line range or grep query]  [symbol/anchor]`
  [Short reason.]

## Conditional touchpoints

- `[file]  [line range or grep query]  [symbol/anchor]`
  Read only if [trigger condition].

## Do-not-read / avoid

- `[file or area]`
  [Why this is distracting or already decided.]

(Omit this section if there are no distracting targets for this bucket.)

## Design direction

- [Concise guidance needed to implement correctly.]
- [Subtle constraint that would be easy to miss.]

## Validation

- [Command or manual check.]
- Expected: [observable pass condition.]

## Done criteria

- [ ] Tasks complete.
- [ ] Validation passes.
- [ ] Bucket `Updates` section records discoveries/gotchas/handoff.
- [ ] Parent workstream progress updated.

## Updates

- [YYYY-MM-DD HH:MM] Created. Handoff: none yet. Gotchas: none yet.
```

Bucket file rules:
- Bucket-specific context lives here, not in the parent.
- Include only touchpoints needed for this bucket.
- Use `Updates` for bucket-local discoveries, gotchas, test notes, and handoff.
- `Updates` entries are chronological ascending: **append new entries at the end**, oldest entry first.
- Do not mark a bucket `done` without validation or an explicit explanation of why validation was not possible.
- **Correction convention:** when a later bucket corrects a finding in an earlier (done) bucket, append a one-line `Correction (BXX): …` note directly to the original bucket's relevant section — do not leave the correction only in the later bucket's Updates. This prevents readers who enter through the original bucket from chasing a wrong hypothesis.

## Workstream Bucket Generator Updates

Introspection notes + feedback notes go here with a timestamp and a suggestion:
- 2026-06-11 00:00: Initial version for this project, instantiated from the upstream template.
- 2026-06-12: Dolt omits NULL columns from JSON output entirely — accessing `row["col"]` raises KeyError when the value is NULL, not None. For any bucket that reads nullable columns via raw `_sql()` results, spec assertions as `row.get("col")` rather than `row["col"]`. Add as a gotcha in any data-pipeline bucket that touches nullable Dolt columns.
- 2026-07-02: Perf-workstream buckets — bench medians under-show per-hit levers when session dedup caps fired hits per prompt (a batched-writes bucket looked like a regression until a 5-hit run showed the win). Spec validation as medians + an explicit multi-hit assertion run (id-truth style), never medians alone.
