# Data contract — Monition store (v7)

This contract is the spec of the code↔data boundary: it binds the Monition module
(the machinery) to any Monition store (the data) — a per-project store directory
containing the `takeaways`, `firings`, `decisions`, and `violations` tables, addressed by path
(convention: `<repo-root>/monition/`). Rows own *what fires when* (trigger-as-data);
the module owns *how matching executes* and never reinterprets a field beyond what
is written here.

**Storage backends.** Two backends exist behind one seam. `monition init` defaults to
**SQLite** (`store.db` in the store directory; stdlib `sqlite3`, zero install), which is
the recommended default for **external / standalone hosts** that won't install dolt. For
**our own situation the default is Dolt** (the v6 hub is a Dolt store, selected via
`--dolt` / resolved through `MONITION_STORE`) — see
`docs/decisions/2026-06-18-dolt-default-ours-sqlite-external.md`. Backend detection is
automatic: `.dolt/` present → Dolt; `store.db` → SQLite. The contract is backend-agnostic;
only type-family assertions differ (MySQL dialect for Dolt, SQLite types for SQLite).

Validated against a live reference store on 2026-06-11.

## Producers and consumers

| Artifact | Produced by | Consumed by |
|---|---|---|
| `takeaways` rows | module lifecycle commands — add (via `/mine-session`, `/codify`); retire flips status | module hook executors (`match`, `session-start`); module reader (analytics, scoring) |
| `firings` rows | module fire command, called by the disclosure executors | module reader (precision, noise, audit metrics); `monition score` (evidence for fire/suppress) |
| `firings.outcome` | module rate command (human/agent judgment, after the fact) | module reader — the only ground-truth eval signal; `monition score` — evidence for EV computation |
| `decisions` rows | `monition score`, called by disclosure executors | write-only Phase 3; Phase 4 reader for retrospective tuning |
| `takeaways.violation_signature` | module set-signature command / `add --violation-signature` (authored at mine time, human-consented) | `monition eval-session` (the only machinery that interprets it) |
| `firings.match_evidence` | module fire command (captured by the matcher at fire time) | module reader (Phase 7 trigger-module learning trains on exactly what production matched on) |
| `violations` rows | `monition eval-session` (offline, mine-time) | module reader (`monition report` FN column; the trigger-broadening signal for Phase 7) |
| `dump.sql` | `monition dump` (derived view, regenerated at commit) | fresh-clone restore only — **excluded input** for analytics |

(Until the CMS cutover completes, CMS's `tools/takeaway*.py` remain the live
producers; they are the characterization oracle for the ported commands.)

All access flows through the module: writes through module commands, reads through
the single approved reader (`src/monition/store.py`); any code issuing SQL directly
against a Monition store (bypassing the reader) is a contract violation.

## Versioning and rejection

The store carries no explicit schema-version marker. Until one exists, **the column
fingerprint is the version check**: the reader verifies that all three required tables exist, that
every column listed below is present with the stated type family, and that the enum
domains match exactly. On any mismatch it raises (`StoreContractError`) — it never
skips rows, coerces values, or guesses. Additive columns unknown to this contract
are tolerated and ignored (the store may grow); a missing column, a renamed column,
or an enum domain change is a contract break and requires a new version of this
document.

**v2 (2026-06-11, mirror axis retired at v6):** the overloaded v1 `status` enum was
split into two orthogonal axes — `status` (`active|retired`: does this row fire) and a
`mirror` column (`none|candidate|mirrored`: mirror-back state). The `mirror` column was
**retired at v6** (vestigial; its "applies beyond this repo" intent is now `reach`), but
the v1-dialect rejection still stands: a store whose `status` domain still contains
`upstream_candidate`/`mirrored` is **rejected with an explicit migrate-the-store
message**, never silently coerced. The migration maps `upstream_candidate` →
(`active`, `candidate`) and `mirrored` → (`active`, `mirrored`); at v6 the `mirror` axis
is then dropped, so that candidate/mirrored distinction does not survive into v6.

**v3 (2026-06-12):** adds the `decisions` table for scored fire/suppress
decisions (see `## decisions — per-field meaning` below). A v2 store — one missing
the `decisions` table — is **rejected with an explicit migrate-the-store message**;
`monition migrate` is the repair path (creates the decisions table, does not touch
existing rows).

**v4 (2026-06-13):** adds fire-time provenance to `firings` —
`git_sha`, `git_dirty`, `model`, `monition_version` (see the field table below).
These are the eval-context dimensions a later replay needs, captured at the one
moment they are knowable: every firing logged without them loses those
dimensions permanently (they cannot be backfilled). A v3 store — one whose
`firings` table lacks `git_sha` — is **rejected with an explicit
migrate-the-store message**; `monition migrate` is the repair path (an additive
`ALTER TABLE firings`, does not touch existing rows — their provenance stays
NULL). `monition migrate` is cumulative: it carries any older store up through
every intermediate version to the current version.

**v5 (2026-06-14):** adds `situation` to `firings` — a short
firing-grain decision-context excerpt captured at fire time (the un-truncated
user prompt for `on_demand`, an excerpt of the content being written/edited for
`edit_path`; NULL when the executor has none, e.g. `session_start`). The
session-archive join on `session_id` recovers only *session-grain* context
(confer 2026-06-14, `eval-engine-seam-and-archive-durability`), so the firing
moment needs a source-side fingerprint; like v4 provenance it is impossible to
backfill and is captured at every fire. A v4 store — one whose `firings` lacks
`situation` — is **rejected with an explicit migrate-the-store message**;
`monition migrate` is the repair path (an additive `ALTER TABLE firings`, leaves
existing rows' new column NULL).

**v6 (2026-06-18):** collapses the per-repo stores into one hub and carries
the general/project distinction as **columns**, not physical boundaries. Adds `reach`
(`general|project`) and `origin_repo` to `takeaways`, and `repo` to `firings`; **retires
the `mirror` column**. `reach='general'` fires in any repo; `reach='project'` fires only
where `origin_repo` equals the current repo root. `firings.repo` is the host repo root at
fire time — capture-or-lose, like v4 provenance and v5 `situation`. A v5 store — one whose
`takeaways` lacks `reach` — is **rejected with an explicit migrate-the-store message**;
`monition migrate` is the repair path: additive `ALTER`s (backfilling `reach='project'`
and `origin_repo`/`firings.repo` from the store's own repo root, since a per-repo store
belongs to exactly one repo), then `DROP COLUMN mirror`.

**v7 (2026-07-01):** makes a row's ground truth observable — the recall
column (Phase 6, framed by
`docs/decisions/2026-07-01-row-lifecycle-pr-framing-and-mutation-track.md`). Adds
(a) `violation_signature` to `takeaways` — an optional machine-checkable probe for
the failure the row warns about (see `### Violation signatures`); (b)
`match_evidence` to `firings` — the **full** evidence the trigger matched on,
lossless where `trigger_context` is a bounded preview (Phase 7 trigger learning
trains on exactly what production matched); (c) the `violations` table — one row per
**not-fired∧hit** event (the failure occurred, the row did not fire), the
false-negative cell ratings structurally cannot produce because ratings only see
firings that happened. A v6 store — one whose `takeaways` lacks
`violation_signature` — is **rejected with an explicit migrate-the-store message**;
`monition migrate` is the repair path (additive `ALTER`s plus `CREATE TABLE
violations`, does not touch existing rows — their new columns stay NULL).

**v8 (2026-07-02, current):** makes triggers mutable with provenance (design:
`docs/decisions/2026-07-01-trigger-module-representation.md`; shipped with
bucket B03). Three pieces, migrated **atomically** (the v7 lesson: partial
migration makes version detection ambiguous): (a) `sem_threshold` on
`takeaways` — the semantic module's per-row parameter (see `### Trigger
modules`); (b) `trigger_kind` enum widened with `'tool_call'` — the first
post-v7 kind; its `trigger_spec` is a JSON object (coordinate system defined
when the executor ships, B05); (c) the `mutations` table — event-grain
provenance for every consented trigger mutation (see `## mutations — per-field
meaning`). A v7 store — one whose `takeaways` lacks `sem_threshold` — is
**rejected with an explicit migrate-the-store message**; `monition migrate` is
the repair path (additive `ALTER`s + `CREATE TABLE mutations` on Dolt; on
SQLite the `takeaways` table is rebuilt in place because a CHECK constraint
cannot be ALTERed — rows are copied byte-identical, ids preserved). Existing
rows are untouched — `sem_threshold` stays NULL = global default. The version
ladder's v8 rung uses per-indicator table guards (a missing `mutations` table
alone is not a version signal — same discipline as v7's `violations` guard).

## `takeaways` — per-field meaning

| Field | Type | Meaning |
|---|---|---|
| `id` | int, auto | Takeaway id. Rendered as `tN` in injection labels. **Not a firing id** — see near-misses. |
| `created` | datetime | Insertion time. Naive local server time; no timezone. |
| `kind` | enum `gotcha\|rule\|preference` | Lesson genre. Closed domain. |
| `scope` | varchar, nullable | Human-facing tags. Free text; never machine-matched. |
| `trigger_kind` | enum `edit_path\|session_start\|on_demand\|tool_call` | Which executor may fire this row. Closed domain (`tool_call` since v8). |
| `trigger_spec` | varchar, nullable | Coordinates depend on `trigger_kind` — see below. |
| `one_liner` | varchar(500) | **The fired payload.** The only text injected at disclosure time; cost accounting (`inject_tokens`) is computed over this plus the executor's framing lines, never over `full_content`. |
| `full_content` | text, nullable | The why + workaround. Pulled on demand (`show <t-id>`); zero passive context cost. |
| `source` | varchar, nullable | Provenance pointer (origin session/commit), attached at mining time. Never substituted or regenerated; if it's missing, it stays missing. |
| `status` | enum `active\|retired` | Firing lifecycle only — see below. |
| `reach` | enum `general\|project` | Where the row fires — see below. `general` = any repo; `project` = only `origin_repo`. Default `project`. |
| `origin_repo` | varchar, nullable | Absolute repo root the row belongs to (the matcher gate for `project` rows). Set to the current repo at add time; backfilled from the store's repo root at v6 migration. |
| `violation_signature` | text, nullable | **v7.** Optional machine-checkable probe for the failure the row warns about — see `### Violation signatures`. NULL = no probe exists; the row simply has no false-negative column (degrades to the precision-only view). Written by the narrow `set-signature` mutator or `add --violation-signature`; interpreted only by `monition eval-session`, **never** by the disclosure executors (the disclosure machinery stays dumb). |
| `sem_threshold` | decimal, nullable | **v8.** Per-row minimum cosine for the semantic module, domain [0,1]; NULL = the global default (`embed.SIM_THRESHOLD`). Read only by the `on_demand` semantic pass and reporting; written only by the narrow `set_threshold` verb (`calibrate --apply`, the `tune` mutation verb in `mutations`) — never a generic setter. See `### Trigger modules`. |

### `trigger_spec` coordinate systems

- **`edit_path`** — comma-separated patterns, each whitespace-stripped, matched with
  Python `fnmatch.fnmatch` against the **repo-relative path** of the file being
  written (relative to the store's host repo root, as produced by `os.path.relpath`).
  Two properties that differ from common glob dialects, both load-bearing:
  - `*` **crosses directory separators** (`payload/*` matches `payload/a/b/c`); `**`
    adds nothing over `*`.
  - Matching is case-sensitive on Linux (`fnmatch` normalizes via `os.path.normcase`,
    identity on POSIX).
  Any offline simulation of trigger matching (e.g. spec-tightening analysis) must
  reproduce these semantics exactly — same function, same per-pattern split/strip.
- **`session_start`** — spec is NULL/empty and ignored.
- **`on_demand`** — comma-separated keywords. Matched by
  `WriteStore.on_demand_match(query)` (Phase 4 hybrid executor): a row matches
  if any keyword appears as a case-insensitive substring of the caller's query
  string (lexical pass), or — when the optional `monition[embed]` extra is
  installed — if the embedding of `one_liner + trigger_spec` falls within
  `SIM_THRESHOLD` cosine similarity of the query (semantic pass). Lexical hits
  rank first, semantic hits by similarity descending. An **injection cap**
  bounds the semantic tail: lexical hits (user-designed deterministic
  triggers) are always kept; semantic hits are capped to the top
  `SEMANTIC_TOP_K` by cosine, then an overall `INJECTION_CHAR_BUDGET` (over
  one-liner chars) drops the lowest-scoring semantic hits first. Dropping is
  never silent — `on_demand_match` returns `{"hits": [...], "capped": N}` and
  the executors render a "+N more suppressed by cap" trailer; `monition query`
  is the uncapped escape hatch. Absent or broken
  embeddings degrade silently to lexical-only; the embedding cache is derivable
  state outside the store and never contract data. Dedup semantics: same
  per-session `_not_yet_fired` filter as `edit_path`. Two executors bind it:
  the UserPromptSubmit hook (`monition prompt-hook`) matches the user's prompt
  text, EV-scores, dedups per session, fires with `trigger_context` = prompt
  (truncated to 200 chars); the MCP tool `match_gotchas` (`monition mcp-serve`)
  is an explicit pull — no scorer gate, no session dedup (`session_id` NULL),
  firings still logged, injection cap still applied (the result still lands in
  the context window).

### Trigger modules (interpretation layer)

A row's trigger is a composition of **modules** drawn from a closed vocabulary.
Modules are an *interpretation layer* over the columns above — module identity is
a fixed function of `trigger_kind` (plus per-row parameters), **never inferred
from the shape of `trigger_spec` and never stored redundantly**. Every pre-v8 row
is valid unmodified; nothing about a row's spelling changes when the module view
ships (this is the trigger-as-data position: rows own *what fires when*, the
module layer owns *how matching executes*).

Module vocabulary, ordered by the determinism ladder (most deterministic first —
the mutation engine's preference order at equal performance):

| Module | Params | Deterministic? |
|---|---|---|
| `glob` | comma-separated `fnmatch` patterns | yes — exact path match |
| `tool_call` | JSON spec (**v8**; see `### trigger_spec coordinate systems`) | yes — exact tool + substring match |
| `lexical` | comma-separated keywords, case-insensitive substring | yes — exact text match |
| `semantic` | embed text (`one_liner + trigger_spec`), threshold θ | no — model + threshold |
| `always` | none | yes — fires on its event unconditionally |
| `state_probe` | *reserved* — named on the ladder, no consuming row class yet | — |

The closed `trigger_kind` → composition mapping:

| `trigger_kind` | Composition |
|---|---|
| `edit_path` | `glob(trigger_spec)` |
| `session_start` | `always` |
| `on_demand` | `lexical(trigger_spec)` **OR** `semantic(one_liner + trigger_spec, θ)` — θ = `sem_threshold` if set, else global `SIM_THRESHOLD` |
| `tool_call` (v8) | `tool_call(trigger_spec)` |

Rules the module layer binds:

- **Per-row parameters are columns, not microformat.** A module parameter the
  engine must read, aggregate over, or mutate independently gets its own nullable
  column (NULL = global default); it is never buried inside `trigger_spec`, which
  stays user-authored trigger data with a per-kind dialect. First instance:
  `sem_threshold` (v8). Engine-calibrated parameters and user-authored specs have
  different provenance and different mutators — the spelling keeps them apart.
- **Spec dialects are frozen at v7.** The three v7 kinds keep their microformats
  exactly as specified above; every kind added at v8+ spells `trigger_spec` as a
  single JSON object.
- **Composition is representable, not implemented.** A future layered trigger
  enters as a new `trigger_kind` whose JSON `trigger_spec` is a module-descriptor
  tree (`{"any": [...]}` / `{"all": [...]}`, leaves naming vocabulary modules with
  their params) — enum-widening versioning applies. No composition engine exists
  and none may be built ahead of a consuming proposal.
- **Assess-path == eval-path.** Any code that decides whether a module (or module
  candidate) matches a moment — the proposal engine, threshold calibration,
  replay — must execute the production matcher code path. The
  reproduce-the-semantics clause in `### trigger_spec coordinate systems` is the
  floor for external simulations; within monition the rule is same code, not
  re-implementation.
- **Mutation = consented row edit with provenance.** Every trigger mutation flows
  through a narrow verb (no generic setter —
  `docs/decisions/2026-06-21-no-store-mutation-primitive-isolate-instead.md`),
  records the old value before the change, and is proposed-then-accepted, never
  auto-applied. The record is event-grain in `mutations` (v8, below).

- **`tool_call`** (v8) — one JSON object (the post-v7 spec dialect):
  `{"tool": "<tool name>", "field": "<tool_input key>", "contains":
  ["<needle>", ...]}`. Matched by `WriteStore.match_tool_call(tool_name,
  tool_input)` at the PreToolUse execution moment: `tool` must equal the
  hook's `tool_name` exactly, and any `contains` needle must appear as a
  **case-sensitive substring** of `tool_input[field]` (which must be a
  string). Pure string work — no embeddings, no extra store reads (PreToolUse
  fires on every matched tool call). Fail-open on read (malformed spec or
  input shape = no match, never an error); the write-side gate
  (`validate_tool_call_spec`) rejects malformed specs at authoring time, so
  read-side skipping is the exception path. Match evidence:
  `{"module": "tool_call", "tool": …, "pattern": <the needle that hit>,
  "matched": <the full field text, lossless>}`. Dedup: same per-session
  `_not_yet_fired` filter as the other kinds. The executor binding is the
  PreToolUse fire-hook; the settings matcher must include the tools rows
  target (`Write|Edit|Bash` as of v8 — widen only when a module consumes a
  new tool).

### Violation signatures

A violation signature is **data on the row** — a JSON object describing a
machine-checkable probe for the failure the row warns about. It completes the row's
confusion matrix: with a signature, the offline evaluator can observe
**not-fired∧hit** (the failure happened and the row never fired), the recall signal
ratings cannot produce. Signatures are authored at mine time for rows where a
checkable probe exists; they are never mandatory.

Spec format (one JSON object):

- `{"kind": "transcript_regex", "pattern": "<Python regex>"}` — the only kind the
  v7 evaluator executes. The pattern is matched with `re.search`, flags
  `re.IGNORECASE | re.MULTILINE`, against the extracted text of a session
  transcript (message/tool text content, not the raw JSONL framing).
- Unknown `kind` values are **skipped with a note, never an error** — the field is
  forward-extensible (e.g. a future `diff_regex` over the session's git diff)
  without a contract break. An unparseable spec or a pattern that fails to compile
  is likewise skipped fail-open and reported by the evaluator; it must never block
  evaluation of other rows, and nothing on the hook path ever reads this field.
- Authoring gate: the writer (`set-signature` / `add --violation-signature`)
  validates JSON shape and, for `transcript_regex`, that the pattern compiles —
  malformed specs are rejected at write time, so read-side skipping is the
  exception path, not the norm.

The signature probes for **the failure event itself** (the bad command ran, the
error text appeared, the forbidden pattern was written) — not for the topic being
discussed. A signature that matches mere discussion of the failure manufactures
false FN events; prefer under-matching (missed FN events cost nothing — the row
just stays precision-only) over over-matching. Two authoring cautions from live
use: **the authoring session's own transcript quotes the pattern** (in
`set-signature` arguments and testing) — never `eval-session` the session that
authored a signature; backfill archived transcripts instead, where any match is
organic. And **URL/artifact-shaped patterns match mentions as well as acts** — a
pdf-URL pattern hits citation lists, not just fetches; anchor on the act's output
when possible, and treat mention-shaped events skeptically in the rating pass.

### `status` and `reach` — two axes, one meaning each

- `status` answers exactly one question: does this row fire. `active` is
  firing-eligible; `retired` is kept for history, never fires, and is excluded from
  precision denominators. Nothing else may influence firing eligibility.
- `reach` answers *where* an eligible row fires, never *whether*: `project` (default)
  fires only where `origin_repo` equals the current repo root; `general` fires in every
  repo. The matcher adds `(reach='general' OR origin_repo IS NULL OR origin_repo =
  :current_repo)` to its WHERE clause; `current_repo` derives from the host repo root
  (`CLAUDE_PROJECT_DIR`/git), never from the store's location (the store may be a shared
  hub). When the caller has **no** repo context (`current_repo` NULL — only the explicit
  pulls `cli query` / mcp `match_gotchas` without a detectable repo) the reach filter is
  **not applied** (fail-open). A `project` row with NULL `origin_repo` is under-specified
  and fires anywhere (same fail-open stance) — but `add` stamps the current repo and
  migrate backfills it, so every properly-created project row carries an origin and is
  truly isolated. Any status/reach combination is valid.
- History note: under the v1 schema, mirror-back state lived inside `status`, and
  rows marked `upstream_candidate` or (before 2026-06-11) `mirrored` silently
  stopped firing — firing counts from v1-era data undercount those rows. The `mirror`
  column that briefly carried that state (v2–v5) was retired at v6.

## `firings` — per-field meaning

One row per actual disclosure.

| Field | Type | Meaning |
|---|---|---|
| `id` | int, auto | Firing id. Rendered as `fN` in injection labels. |
| `takeaway_id` | int | FK to `takeaways.id` (not DB-enforced; reader validates referential integrity and raises on orphans). |
| `fired_at` | datetime | Naive local server time. |
| `session_id` | varchar, nullable | Harness session id. May be the literal string `"unknown"` (executor fallback) — treat as an anonymous bucket, not a real session. |
| `trigger_kind` | varchar | Copy of the firing trigger kind, written by the executor. |
| `trigger_context` | varchar(512), nullable | What matched, as a **bounded human-readable preview**. Coordinates by kind: `edit_path` → the repo-relative path that matched (same coordinate system as `trigger_spec` matching); `on_demand` → a prompt preview (≤200 chars); `session_start` → NULL. The lossless machine record is v7 `match_evidence` — never treat this preview as the training substrate. |
| `outcome` | enum `helpful\|noise`, nullable | Post-hoc rating. **NULL means unrated — missing data, never "noise" and never "neutral".** |
| `git_sha` | varchar(40), nullable | **v4 provenance.** Host-repo `HEAD` at fire time, captured by the write surface. NULL = not captured (a pre-v4 firing, or git unavailable) — never substituted. |
| `git_dirty` | tinyint(1), nullable | **v4 provenance.** 1 if the host repo had uncommitted changes at fire time, else 0 — `git_sha` is misleading without it. NULL when `git_sha` is NULL (undeterminable). |
| `model` | varchar(64), nullable | **v4 provenance.** Model id in effect at fire time, supplied by the executor (harness state the writer can't see). NULL = not surfaced by the harness — missing data, never guessed. |
| `monition_version` | varchar(32), nullable | **v4 provenance.** Installed monition version that logged the firing — which module build scored/disclosed it, distinct from `git_sha` (the host repo, not monition). NULL = undeterminable. |
| `situation` | text, nullable | **v5 firing-grain context.** A short decision-context excerpt at fire time (capped ~4000 chars): `on_demand` → the un-truncated user prompt; `edit_path` → an excerpt of the content being written/edited; `session_start` → NULL (its `session_id`+`fired_at` is the only locator). Impossible to backfill. The cheap-eval pairs this with a `session_id` join to the session archive (which holds only session-grain context). NULL = the executor had no excerpt, or a pre-v5 firing. |
| `repo` | varchar, nullable | **v6 firing-grain context.** Host repo root at fire time, derived from `CLAUDE_PROJECT_DIR`/git — never the store's location (the store may be a shared hub). Recovers per-repo precision for `general`-reach rows, which fire across repos. Capture-or-lose, like the v4/v5 dimensions. NULL = a pre-v6 firing, or backfilled from the store's repo root at migration. |
| `match_evidence` | text, nullable | **v7.** JSON record of **exactly what the trigger matched on**, full and lossless — where `trigger_context` is a bounded human-readable preview, this is the machine substrate Phase 7 trigger learning trains on. Shape by matching module: lexical `on_demand` → `{"module":"lexical","keyword":<the keyword that hit>,"query":<full query text>}`; semantic `on_demand` → `{"module":"semantic","score":<cosine>,"query":<full query text>}`; `edit_path` → `{"module":"glob","pattern":<the pattern that hit>,"path":<repo-relative path>}`; `session_start` → NULL (nothing is matched). Captured at fire time by the matcher (the only code that knows which keyword/pattern/score satisfied the trigger); capture-or-lose like the v4/v5/v6 dimensions. NULL = a pre-v7 firing, or a fire logged outside the matchers (manual `monition fire`, `log-recurrence`). |

All four provenance fields are **capture-time-only and impossible to backfill**;
they are written once at fire and never regenerated. They are nullable by
design — a fail-open capture never blocks a firing, and an absent dimension stays
honestly NULL rather than guessed.

### Dedup semantics (disclosure is the native unit)

Executors fire each takeaway **at most once per session**, deduped by querying
`firings` itself; repeat trigger matches within a session are suppressed and not
logged. This is the correct unit for the cost model, not a gap in it: injection
cost is paid once when the one-liner enters the session's context, and later
matches consult it for free — so `f_trigger` is denominated in **disclosures per
session**, which is exactly what `firings` records. The only analysis that needs
raw occurrence counts is spec-narrowing prediction (what would a tighter glob have
matched later in the session?), and that is reconstructed by replaying specs
against session histories — never read off `firings`.

**Compaction re-arm.** Harness compaction (SessionStart `source: "compact"`)
wipes previously injected disclosures from the context window while the
session id stays the same, so "at most once per session" would leave the row
invisibly undisclosed. The session-brief executor records a compaction marker
— the store's `MAX(firings.id)` at that moment, in a per-machine state file
under `XDG_STATE_HOME` (markers are harness-session state, never store data)
— and dedup counts only firings **after** the latest marker: rows disclosed
before the compaction may fire again.

### Derived values

`fire_count`, `last_fired`, precision, noise rate — always computed from `firings` at
read time, never stored as columns anywhere (single source of truth).

## `decisions` — per-field meaning

One row per scored fire/suppress decision. Written by `monition score`; the hook
executors call `score()` before each potential disclosure.

| Field | Type | Meaning |
|---|---|---|
| `id` | int, auto | Decision id. |
| `takeaway_id` | int | FK to `takeaways.id` (not DB-enforced; same referential contract as `firings`). |
| `session_id` | varchar, nullable | Harness session id at decision time. May be `"unknown"` — same fallback semantics as `firings.session_id`. |
| `decided_at` | datetime | Naive local server time. |
| `decision` | enum `fire\|suppress` | The scored outcome: `fire` means the executor proceeds; `suppress` means it does not. |
| `evidence_count` | int | Number of rated firings for this takeaway at decision time. |
| `cold_start` | tinyint(1) | `1` when `evidence_count` was below `N_COLD_START` — the decision was always-fire, not evidence-based. |
| `ev_score` | decimal(5,4), nullable | Computed precision (helpful / total_rated). `NULL` when `cold_start = 1`. |

### Decision semantics

- **Cold-start** (`cold_start = 1`, `evidence_count < N_COLD_START`): always fire.
  Monition only suppresses what it has proof is noise; absence of evidence is not
  evidence of noise.
- **Cold-pause** (the bounded exception to cold-start): a row with
  `N_UNRATED_PAUSE` or more lifetime firings and **zero** ratings is suppressed
  until any rating arrives. Its decisions row is `decision = 'suppress'` with
  `cold_start = 1` and `evidence_count = 0` — a signature no other scoring path
  writes, so it stays distinguishable without widening the decision enum.
  Pausing does not starve the rating path: the already-logged firings are the
  rating worklist, and `export-firings --order-by priority` ranks a cold-paused
  row at the head (rated 0 → boundary closeness 1.0 × high traffic).
- **Evidence-based** (`cold_start = 0`): fire if `ev_score >= EV_THRESHOLD`, else
  suppress. `N_COLD_START` and `EV_THRESHOLD` are module constants in
  `src/monition/score.py`; Phase 4 tunes them against the accumulated ratings log.
- **Fail-open**: any error in the scorer is logged to
  `~/.local/state/monition/hook-errors.log` and treated as cold-start fire. A
  scoring error never blocks a session.
- **Read-back (Phase 4)**: the approved reader (`Store`) exposes `decisions()` for
  retrospective analysis; `monition report` and `monition tune` consume it.

## `violations` — per-field meaning

One row per observed **not-fired∧hit** event: a session in which a row's violation
signature matched (the failure the row warns about occurred) and the row did **not**
fire in that session. This is the false-negative cell of the row's confusion matrix
— the trigger-broadening signal ratings structurally cannot produce. Written only by
`monition eval-session` (offline, mine-time, fail-open); nothing on the blocking
hook path reads or writes this table.

| Field | Type | Meaning |
|---|---|---|
| `id` | int, auto | Violation id. |
| `takeaway_id` | int | FK to `takeaways.id` (not DB-enforced; same referential contract as `firings`). |
| `session_id` | varchar | Session in which the signature hit. Required — a violation is meaningless without the session it was observed in. |
| `detected_at` | datetime | When the evaluator logged the event (naive local server time) — evaluation time, not failure time. |
| `evidence` | text | The transcript excerpt the signature matched (the `re.search` match plus bounded surrounding context) — what a human reviews to confirm the event is real before acting on it. |
| `repo` | varchar, nullable | Host repo root of the evaluated session, same semantics as `firings.repo`. |

### Violation semantics

- **Only the third cell is stored.** The evaluator classifies a session per
  signature-bearing row into fired∧avoided / fired∧hit / not-fired∧hit and reports
  all three, but persists only not-fired∧hit: fired∧avoided and fired∧hit are
  derivable at read time (join `firings` on `(takeaway_id, session_id)` against the
  eval output), while the FN event exists nowhere else.
- **Dedup: at most one violation per `(takeaway_id, session_id)`.** Re-running the
  evaluator over the same session is idempotent, never additive.
- **A violation is not a firing.** It never enters precision denominators, never
  affects per-session disclosure dedup, and never feeds the fire/suppress scorer as
  rating evidence. Its consumers are `monition report` (the FN column) and the
  Phase 7 mutation engine (trigger-broadening proposals).
- **Attribution caution** (per
  `docs/decisions/2026-06-18-noise-targets-the-filter-not-the-gate.md`): a violation
  says the *trigger* missed the moment — it is evidence about trigger coverage,
  not about payload quality, and Phase 7 must attribute it to the trigger layer.

## `mutations` — per-field meaning (v8)

One row per **consented mutation event** — event-grain, not per-field: a verb that
atomically changes several fields (e.g. a kind migration rewriting `trigger_kind` +
`trigger_spec`) is one row, so the counterfactual unit replay evaluates is the
mutation as applied, never half of one.

| Field | Type | Meaning |
|---|---|---|
| `id` | int, auto | Mutation event id. |
| `takeaway_id` | int | The mutated row. |
| `mutated_at` | datetime | When the accepted mutation was applied. Naive local time, like `created`. |
| `verb` | varchar | **Explicit** mutation kind — never inferred from which fields changed (the multi-variant rule). Open documented vocabulary, initial set: `tune`, `retarget`, `migrate_kind`, `merge`, `graduate`, `stale`. New verbs are additive and introduced by a decision doc; readers must tolerate unknown verbs (skip-with-note, like unknown signature kinds). |
| `changes` | text (JSON) | `{"<field>": {"old": <value>, "new": <value>}, ...}` for every field the verb touched. The old values are captured **before** the write — this is the provenance the framing decision requires. |
| `source` | varchar, nullable | Proposal provenance pointer (proposal/session id, or `manual`). Like `takeaways.source`: never substituted or regenerated. |

Semantics:

- **Reconstruction rule**: a row's trigger state at time T = its current state with
  the inverse of every `changes` entry after T applied, newest first. This holds
  because all trigger-field writes flow through mutation verbs from v8 on;
  pre-v8 edits are not recorded and reconstruction does not reach behind v8.
- **Backend-agnostic by construction**: this table is the contract-level
  provenance record. Dolt commit history remains an auxiliary audit trail on Dolt
  backends, but no consumer may depend on it — SQLite hosts have no history, and
  per-field archaeology across interleaved commits is not a query interface.
- **A mutation is not a firing and not a rating** — it never enters precision
  denominators or scorer evidence; its consumers are the proposal engine's
  audit view, `report`, and `replay`.

## Tier-0 interchange format (lessons file)

The serialization incubated projects use before they have a Monition store: a
markdown file whose machine-read parts are line-oriented takeaway blocks. One
schema owner, two serializations — the field names, domains, and trigger
semantics are exactly those of the `takeaways` table above (cite, don't
restate); the dialect is deliberately dumb so a *frozen* stdlib executor can
parse it without a markdown parser. This section is the format's single
definition: the CMS tier-0 payload and `monition adopt` both cite it.

**Block syntax** (line-oriented, case-sensitive):

- A block starts at a line that is exactly `## takeaway` and ends at the next
  such line or EOF. All lines outside blocks are free prose, ignored.
- Inside a block, header lines are `key: value` (single line, first colon
  splits, value whitespace-trimmed). Keys: `kind`, `trigger_kind`,
  `trigger_spec`, `one_liner`, `scope`, `source`. Unknown keys are tolerated
  and ignored (the additive-column rule's counterpart); non-`key: value` lines
  before `full_content:` are ignored as prose.
- A line that is exactly `full_content:` switches the block to verbatim mode:
  every following line until block end is the `full_content` value
  (leading/trailing blank lines stripped, interior preserved).

**Required:** `kind`, `trigger_kind`, `one_liner` — domains per the
`takeaways` field table. **Optional:** `trigger_spec` (same coordinate
systems, same fnmatch dialect as §`trigger_spec` coordinate systems),
`scope`, `source`, `full_content`. **Absent by design:** `id`/`created`
(assigned at import), `status`/`reach`/`origin_repo` (schema defaults apply:
`active`/`project`/NULL).

**Import semantics** (`monition adopt <file>`, or `monition init --adopt
<file>` for store-creation + import): blocks are imported in file order
through the module's add path; `source` is carried verbatim, never
substituted. A malformed block — missing required field, or a value outside
its enum domain — is **rejected with a counted, per-block reason; never
silently skipped**; valid sibling blocks still import. Every parsed block is
either imported or rejected (conservation). Adoption is one-way: the store
never writes back to the lessons file; tier-0 retirement of an adopted file
is the host project's concern.

## Excluded inputs

- **`dump.sql`** — a derived view regenerated at commit time; stale between commits.
  Read the live store via the approved reader, never the dump file.
- **`.dolt/` internals / `store.db` direct access** — implementation details of each
  backend; all access must flow through the approved reader.
- **Injection label strings** (`[tN/fM]`) — presentation format of the executors, not
  data; ids come from the tables.

## Forbidden near-misses

- **Takeaway id vs. firing id.** Labels like `[t3/f4]` carry both. `show` takes the
  takeaway id, `rate` takes the firing id; the CLI accepts bare or prefixed forms
  (`6` or `f6`) but the prefix is presentation only — it does not make a takeaway id
  valid where a firing id is expected. Any Monition output that names an id states
  which kind it is.
- **`outcome IS NULL` is not noise.** Precision = helpful / (helpful + noise), over
  rated firings only; unrated firings are reported as coverage, never folded into
  either side.
- **`trigger_spec` is not regex and not gitignore.** It is fnmatch with
  slash-crossing `*`. A "tightened" spec recommendation written in another dialect
  would silently change what fires.
- **Paths are repo-relative to the store's host repo**, not absolute, not relative to
  the store directory or to Monition's cwd.
- **Mirror state is not lifecycle.** A v1-dialect store (status domain containing
  `upstream_candidate`/`mirrored`) must be rejected with a migrate message — never
  mapped onto the v2 axes by the reader.
- **A violation is not a firing.** Nothing was disclosed; a `violations` row must
  never enter precision denominators, disclosure dedup, or scorer evidence counts.
- **`trigger_context` is not `match_evidence`.** The former is a bounded preview
  for humans; only the latter is the lossless record of what production matched
  on. Trigger learning that trains on the preview trains on truncation artifacts.

## Validation requirements (tests must cover)

- [ ] Reader raises on: missing table, missing required column, changed enum domain.
- [ ] Reader tolerates an additive unknown column.
- [ ] Reader raises on a `firings.takeaway_id` with no matching takeaway row.
- [ ] NULL `outcome` excluded from both numerator and denominator of precision.
- [ ] Trigger simulation reproduces fnmatch slash-crossing on a fixture
      (`payload/*` vs `payload/a/b`).
- [ ] Only `status = 'active'` rows counted firing-eligible; `reach` value has no
      effect on eligibility (it gates *where* a row fires, not *whether*).
- [ ] A v5 store (`takeaways` lacks `reach`) rejected with a message naming the
      migration to v6, not a generic type mismatch.
- [ ] A v1-dialect store (old `status` enum domain) rejected with a message naming
      the migration, not a generic type mismatch.
- [ ] `session_id = "unknown"` bucketed separately from real sessions.
- [ ] Injection cap: lexical hits never dropped; semantic hits capped top-K
      then by char budget, lowest score first; dropped count reported (trailer),
      never silent.
- [ ] Cold-pause: `N_UNRATED_PAUSE`+ lifetime firings with zero ratings →
      suppress until any rating; the paused row still heads the
      `--order-by priority` rating worklist.
- [ ] Compaction re-arm: a `source: "compact"` session brief re-arms
      per-session dedup for firings logged before the marker.
- [ ] A v6 store (`takeaways` lacks `violation_signature`) rejected with a message
      naming the migration to v7, not a generic type mismatch.
- [ ] `set-signature` rejects malformed JSON and a non-compiling
      `transcript_regex` pattern at write time.
- [ ] Evaluator: a signature hit with no firing in that session logs exactly one
      violation; re-running the evaluator on the same session adds nothing
      (idempotent); a hit with a firing logs nothing; an unknown signature kind or
      broken pattern is skipped with a note, never an error.
- [ ] `match_evidence` on a lexical hit carries the matching keyword and the
      **un-truncated** query; on a semantic hit, the cosine score and full query;
      on an `edit_path` hit, the matching pattern and repo-relative path.
- [ ] `violations` rows excluded from precision and from disclosure dedup.
- [ ] Live check: `monition report <store-path>` runs without writes
      (store working set unchanged after the run).
