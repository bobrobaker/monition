# Data contract — `export-firings` read-verb (v1)

This contract is the schema of the **`monition export-firings` read-verb**: a
read-only, point-in-time export of a Monition store's `firings` rows as JSONL —
one JSON object per firing — for downstream evaluation. It is the row-coupled eval
substrate Monition *exposes* across the graduation seam.

Unlike `retrievals-log.md` — where Monition owns the schema but neither the reader
nor the data — here Monition owns **both the canonical schema (this doc) and the
reader** (`monition export-firings`, reading through the single approved store
reader). What Monition does **not** own is the consumer: the tier-3 evaluator that
turns this export into a named-failure-mode rate lives in CMS (see the
eval-substrate boundary in `CLAUDE.md`). This export is read-only and never
mutates the store.

Provenance: cross-project roadmap phase **P2**; the eval-substrate/export confer
(`2026-06-12`, user-ratified). Owner-at-birth, same as the `retrievals-log.md`
precedent: **CMS drafts the field list it needs; Monition reviews and owns this
canonical.** CMS **cites** this doc from its P3 work, never duplicates it.

## What it is and who consumes it

The only consumer is **P3 — CMS tier-3 evaluation** (deferred, label-gated).
P3's first computation is the **graduation handoff metric**: the row-side prior is
per-takeaway **helpful-rate** (`helpful / (helpful + noise)`) — the same ΔP(fail)
estimator the governance-failure-rate computes on the other side of the graduation
seam. Computing that rate **scoped by provenance** (per model, excluding
dirty-repo firings, keyed on engine build) is why fire-time provenance (store v4)
had to land before this export could exist. P3 reads these records cross-project,
where a live store join is awkward — hence the denormalized takeaway fields.

This makes the export **non-urgent** (nothing consumes it until P3), but its field
list is stable and it builds against the live v4 schema now.

## Versioning and rejection

Each record carries an explicit **`schema_version`** — the version of *this
export contract*, **distinct from the store schema version** (currently v5). It
starts at `1`. A consumer keys on it and refuses a version it does not understand:
it raises or degrades, never guesses.

- **Additive columns are the only compatible change.** New fields unknown to a
  consumer are tolerated and ignored; the export may grow without a version bump.
- A **removed field, a renamed field, or an enum-domain change** is a contract
  break: a new version of this document and a bump of the stamp.

**v1 (2026-06-13, current):** the record shape below. `situation` (firing-grain
decision-context excerpt, store v5) was added 2026-06-14 as an **additive** field
per the rule above — no stamp bump; consumers that don't know it ignore it.

## Record shape

`monition export-firings --format jsonl` → **one JSON object per firing** (the
firing is the rated-disclosure unit; dedup is already per `firings`). Source
columns are the live store v4 schema (`docs/contracts/takeaway-store.md`).

| Field | Source | Meaning | Req |
|---|---|---|---|
| `schema_version` | export contract (NOT store v4) | This contract's version. `1` here. The consumer keys on it. | **must** |
| `firing_id` | `firings.id` | Stable id for idempotent joins / dedup. | **must** |
| `takeaway_id` | `firings.takeaway_id` | The unit helpful-rate is computed over — the context-module identity at the graduation seam. Join key to `takeaways`. | **must** |
| `one_liner` | `takeaways.one_liner` | **Denormalized** so a record is self-contained for cross-project rubric authoring (P3 reads these where a live store join is awkward). | **must** |
| `kind` | `takeaways.kind` | **Denormalized.** `gotcha\|rule\|preference`. | **must** |
| `outcome` | `firings.outcome` | **The eval label.** `helpful\|noise`, **`null` = unrated (missing) — never noise, never neutral.** | **must** |
| `fired_at` | `firings.fired_at` | ISO 8601 naive local datetime. The time-window the prior weights over. | **must** |
| `session_id` | `firings.session_id` | **Join key** to traces / session summaries / retrievals-log. May be the literal `"unknown"` (anonymous bucket), same semantics as `firings`. | **must** |
| `trigger_kind` | `firings.trigger_kind` | Which trigger fired this disclosure. **Open varchar, not a closed enum** — see below. | **must** |
| `trigger_context` | `firings.trigger_context` | What matched (path/prompt); scopes a failure mode. Nullable. | should |
| `situation` | `firings.situation` | **Store v5, additive.** Firing-grain decision-context excerpt (un-truncated prompt / edit excerpt; `null` for `session_start` or pre-v5). Pair with a `session_id` join for session-grain context. | should |
| `git_sha` | `firings.git_sha` | v4 provenance: host-repo `HEAD` at fire time. `null` = not captured. | **must** |
| `git_dirty` | `firings.git_dirty` | v4 provenance: `true` if uncommitted changes at fire time. `git_sha` misleads without it. `null` when `git_sha` is `null`. | **must** |
| `model` | `firings.model` | v4 provenance: compute helpful-rate **per model**. `null` = undeterminable. | **must** |
| `monition_version` | `firings.monition_version` | v4 provenance: which engine build scored/disclosed it. `null` = undeterminable. | **must** |
| `fire_count` | derived (store-wide) | **Rating-value signal, additive.** Total firings of the *parent row* (traffic) — store-wide, not the filtered slice. | should |
| `rated_count` | derived (store-wide) | **Additive.** How many of the parent row's firings already have an outcome (existing evidence). | should |
| `precision` | derived (store-wide) | **Additive.** Parent row's `helpful / rated_count`, rounded; `null` when `rated_count == 0`. The same quantity the EV gate scores. | should |
| `rating_priority` | derived (store-wide) | **Additive, the head-not-tail metric.** `fire_count × boundary_closeness` — high only when the row fires a lot *and* a new rating could move the gate. Cold-start (`rated_count < N_COLD_START`) → closeness `1.0`; evidence-based → closeness peaks at the fire/suppress threshold, `0` at a settled `0%`/`100%`. **Boundary math lives in monition (substrate); the consuming skill orders on this field and owns only the budget policy.** | should |

All provenance fields are honestly `null` for pre-v4 firings — **never
substituted**. A consumer's reader must handle `null` provenance (exclude from a
provenance-scoped stratum, or bucket as unknown), never coerce.

The four rating-value fields (`fire_count`, `rated_count`, `precision`,
`rating_priority`) are **derived store-wide aggregates of the parent row**,
denormalized onto every firing — so an *unrated* firing still carries its row's
traffic and precision, and the values are stable under `--unrated-only`/`--session`
filtering (they describe the row, not the returned slice). Added 2026-06-17 per the
rating-collection confer; additive, no `schema_version` bump.

## `trigger_kind` is open; `resurrection` firings are injected counterfactuals

`takeaways.trigger_kind` is a closed enum (`edit_path|session_start|on_demand`),
but **`firings.trigger_kind` is a free-form varchar** — the executor copies a
trigger label into it, and the domain is not closed. A consumer must treat it as
open and not reject unknown values.

In particular it now also carries **`"resurrection"`**: a *synthetic*
`helpful`-equivalent firing injected by the Phase-4 suppression-resurrection
consent gate (`log_helpful_equivalent()` in `store_write.py`, via `monition add
--resolve log-helpful:ID`). These appear in the export as
`outcome=helpful, trigger_kind=resurrection`. They are **injected
counterfactuals** (evidence that a suppression was wrong), **not organic
disclosures**. P3 decides whether to count them in helpful-rate; this contract
only flags them honestly. v1 ships **no** `--exclude-synthetic` filter — they are
identifiable by `trigger_kind` and excludable client-side; a filter flag is
additive later if P3 asks.

## Out of scope (not exported in v1)

- **The `decisions` table** (`decision`, `ev_score`, `cold_start`,
  `evidence_count`) — the firing-engine's scored fire/suppress reasoning. That is
  tier-2 / P4 counterfactual-replay and engine-tuning evidence, **not** tier-3
  helpful-rate. Additive later if P4 asks; no break.
- **Derived precision columns** (`fire_count`, precision, noise rate) — computed
  at read time per the store's single-source rule. Export raw rows; P3 derives.
- **Raw occurrence counts** — `firings` is disclosures-per-session by design; the
  rated-disclosure unit *is* a firing row.

## Schema disciplines (cited, not duplicated)

The cross-substrate disciplines that bind this export are defined once and cited:

- **`outcome` vocabulary and null-semantics** (`helpful|noise`, `null` = unrated,
  never noise, never neutral — so firing helpful-rate, retrieval helpful-rate, and
  governance failure-rate are all one ΔP(fail) estimator): see
  `retrievals-log.md` §`outcome`.
- **Additive-column + version-stamp + join-never-merge** discipline: see
  `retrievals-log.md` §Versioning and rejection and §Validation requirements.
- **Source-column meanings and the v4 provenance semantics**: see
  `takeaway-store.md` §`firings` — per-field meaning.

Records **join, never merge**: `session_id` → traces / retrievals-log,
`takeaway_id` → `takeaways`. They are not folded into a store.

## CLI surface (v1)

```
monition export-firings [--store DIR] [--since YYYY-MM-DD]
                        [--rated-only | --unrated-only] [--session ID]
                        [--order-by fired_at|priority] [--format jsonl]
```

- `--store` — store directory; default the convention path `<repo-root>/monition/`.
- `--since YYYY-MM-DD` — only firings whose `fired_at` is on/after that date.
- `--rated-only` — only firings with a non-`null` `outcome`.
- `--unrated-only` — only firings with a `null` `outcome`: the **rating worklist**,
  the exact complement of `--rated-only`. Mutually exclusive with it.
- `--session ID` — only firings of that exact `session_id`; scopes a rating pass to
  one session (the warm, in-context path — rate the session you just lived through).
- `--order-by` — `fired_at` (default; store/insertion order) or `priority`
  (head-not-tail worklist: highest `rating_priority` first, so a budgeted rating
  pass walks the most valuable firings first). Canonical use:
  `--unrated-only --session <id> --order-by priority`.
- `--format` — `jsonl` is the only v1 format.

These filters are additive and do not bump the export `schema_version` (they select
records, not field shape). Everything else (per-model slices, etc.) P3 filters
client-side. The verb is
**read-only and fail-open**: it emits a valid (possibly empty) JSONL stream and
never mutates the store; an empty store yields no output and exit 0. A genuinely
broken store (no `.dolt/`, missing required column) is a contract violation
(exit 2), same as the other read verbs.

## Forbidden near-misses

- **Exporting the `decisions` table as tier-3 signal.** It is the engine's
  fire/suppress reasoning (tier-2 / P4), not the helpful/noise label.
- **Coercing `null` provenance or `null` outcome.** `null` is missing data — never
  a `noise`, never a neutral third value, never a substituted default.
- **Rejecting an unknown `trigger_kind`.** It is an open varchar; `resurrection`
  is one known synthetic value, more may appear.
- **Merging the export into a store.** It is a point-in-time snapshot that joins
  on `session_id` / `takeaway_id`; it is not a store.
- **Duplicating this schema into CMS docs.** CMS cites this doc; the canonical
  lives here.
