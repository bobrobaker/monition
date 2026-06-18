# Data contract — Monition store (v5)

This contract is the spec of the code↔data boundary: it binds the Monition module
(the machinery) to any Monition store (the data) — a per-project store directory
containing the `takeaways`, `firings`, and `decisions` tables, addressed by path
(convention: `<repo-root>/monition/`). Rows own *what fires when* (trigger-as-data);
the module owns *how matching executes* and never reinterprets a field beyond what
is written here.

**Storage backends.** `monition init` defaults to **SQLite** (`store.db` in the store
directory; stdlib `sqlite3`, zero install). An optional **Dolt** backend can be selected
with `monition init --dolt`; it requires the `dolt` binary and is retained for future
data-VCS use. Backend detection is automatic: `.dolt/` present → Dolt; `store.db` → SQLite.
The contract is backend-agnostic; only type-family assertions differ (MySQL dialect for
Dolt, SQLite types for SQLite).

Validated against a live reference store on 2026-06-11.

## Producers and consumers

| Artifact | Produced by | Consumed by |
|---|---|---|
| `takeaways` rows | module lifecycle commands — add (via `/mine-session`, `/codify`); retire flips status | module hook executors (`match`, `session-start`); module reader (analytics, scoring) |
| `firings` rows | module fire command, called by the disclosure executors | module reader (precision, noise, audit metrics); `monition score` (evidence for fire/suppress) |
| `firings.outcome` | module rate command (human/agent judgment, after the fact) | module reader — the only ground-truth eval signal; `monition score` — evidence for EV computation |
| `decisions` rows | `monition score`, called by disclosure executors | write-only Phase 3; Phase 4 reader for retrospective tuning |
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

**v2 (2026-06-11):** the overloaded v1 `status` enum was split into two
orthogonal axes — `status` (`active|retired`: does this row fire) and a new
`mirror` column (`none|candidate|mirrored`: mirror-back state). A v1-dialect store
— one whose `status` domain still contains `upstream_candidate`/`mirrored` — is
**rejected with an explicit migrate-the-store message**, never silently coerced:
mapping v1 statuses onto v2 axes is a migration (`monition migrate` is the repair
path), not a reader guess. The migration maps `upstream_candidate` →
(`active`, `candidate`) and `mirrored` → (`active`, `mirrored`); `active`/`retired`
keep their status with `mirror = 'none'`.

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

**v5 (2026-06-14, current):** adds `situation` to `firings` — a short
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

## `takeaways` — per-field meaning

| Field | Type | Meaning |
|---|---|---|
| `id` | int, auto | Takeaway id. Rendered as `tN` in injection labels. **Not a firing id** — see near-misses. |
| `created` | datetime | Insertion time. Naive local server time; no timezone. |
| `kind` | enum `gotcha\|rule\|preference` | Lesson genre. Closed domain. |
| `scope` | varchar, nullable | Human-facing tags. Free text; never machine-matched. |
| `trigger_kind` | enum `edit_path\|session_start\|on_demand` | Which executor may fire this row. Closed domain. |
| `trigger_spec` | varchar, nullable | Coordinates depend on `trigger_kind` — see below. |
| `one_liner` | varchar(500) | **The fired payload.** The only text injected at disclosure time; cost accounting (`inject_tokens`) is computed over this plus the executor's framing lines, never over `full_content`. |
| `full_content` | text, nullable | The why + workaround. Pulled on demand (`show <t-id>`); zero passive context cost. |
| `source` | varchar, nullable | Provenance pointer (origin session/commit), attached at mining time. Never substituted or regenerated; if it's missing, it stays missing. |
| `status` | enum `active\|retired` | Firing lifecycle only — see below. |
| `mirror` | enum `none\|candidate\|mirrored` | Mirror-back state, orthogonal to firing — see below. |

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
  rank first, semantic hits by similarity descending. Absent or broken
  embeddings degrade silently to lexical-only; the embedding cache is derivable
  state outside the store and never contract data. Dedup semantics: same
  per-session `_not_yet_fired` filter as `edit_path`. Two executors bind it:
  the UserPromptSubmit hook (`monition prompt-hook`) matches the user's prompt
  text, EV-scores, dedups per session, fires with `trigger_context` = prompt
  (truncated to 200 chars); the MCP tool `match_gotchas` (`monition mcp-serve`)
  is an explicit pull — no scorer gate, no session dedup (`session_id` NULL),
  firings still logged.

### `status` × `mirror` — two axes, one meaning each

- `status` answers exactly one question: does this row fire. `active` is
  firing-eligible; `retired` is kept for history, never fires, and is excluded from
  precision denominators. Nothing else may influence firing eligibility.
- `mirror` tracks mirror-back state and **never affects firing**: `none` (default),
  `candidate` (domain-free, queued for the sweep — keeps firing locally while it
  waits), `mirrored` (landed upstream). Any status/mirror combination is valid.
- History note: under the v1 schema, mirror-back state lived inside `status`, and
  rows marked `upstream_candidate` or (before 2026-06-11) `mirrored` silently
  stopped firing — firing counts from v1-era data undercount those rows.

## `firings` — per-field meaning

One row per actual disclosure.

| Field | Type | Meaning |
|---|---|---|
| `id` | int, auto | Firing id. Rendered as `fN` in injection labels. |
| `takeaway_id` | int | FK to `takeaways.id` (not DB-enforced; reader validates referential integrity and raises on orphans). |
| `fired_at` | datetime | Naive local server time. |
| `session_id` | varchar, nullable | Harness session id. May be the literal string `"unknown"` (executor fallback) — treat as an anonymous bucket, not a real session. |
| `trigger_kind` | varchar | Copy of the firing trigger kind, written by the executor. |
| `trigger_context` | varchar(512), nullable | What matched. Coordinates by kind: `edit_path` → the repo-relative path that matched (same coordinate system as `trigger_spec` matching); `on_demand` → a prompt preview (≤200 chars); `session_start` → NULL. |
| `outcome` | enum `helpful\|noise`, nullable | Post-hoc rating. **NULL means unrated — missing data, never "noise" and never "neutral".** |
| `git_sha` | varchar(40), nullable | **v4 provenance.** Host-repo `HEAD` at fire time, captured by the write surface. NULL = not captured (a pre-v4 firing, or git unavailable) — never substituted. |
| `git_dirty` | tinyint(1), nullable | **v4 provenance.** 1 if the host repo had uncommitted changes at fire time, else 0 — `git_sha` is misleading without it. NULL when `git_sha` is NULL (undeterminable). |
| `model` | varchar(64), nullable | **v4 provenance.** Model id in effect at fire time, supplied by the executor (harness state the writer can't see). NULL = not surfaced by the harness — missing data, never guessed. |
| `monition_version` | varchar(32), nullable | **v4 provenance.** Installed monition version that logged the firing — which module build scored/disclosed it, distinct from `git_sha` (the host repo, not monition). NULL = undeterminable. |
| `situation` | text, nullable | **v5 firing-grain context.** A short decision-context excerpt at fire time (capped ~4000 chars): `on_demand` → the un-truncated user prompt; `edit_path` → an excerpt of the content being written/edited; `session_start` → NULL (its `session_id`+`fired_at` is the only locator). Impossible to backfill. The cheap-eval pairs this with a `session_id` join to the session archive (which holds only session-grain context). NULL = the executor had no excerpt, or a pre-v5 firing. |

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
- **Evidence-based** (`cold_start = 0`): fire if `ev_score >= EV_THRESHOLD`, else
  suppress. `N_COLD_START` and `EV_THRESHOLD` are module constants in
  `src/monition/score.py`; Phase 4 tunes them against the accumulated ratings log.
- **Fail-open**: any error in the scorer is logged to
  `~/.local/state/monition/hook-errors.log` and treated as cold-start fire. A
  scoring error never blocks a session.
- **Read-back (Phase 4)**: the approved reader (`Store`) exposes `decisions()` for
  retrospective analysis; `monition report` and `monition tune` consume it.

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
  and ignored (the additive-column rule's mirror); non-`key: value` lines
  before `full_content:` are ignored as prose.
- A line that is exactly `full_content:` switches the block to verbatim mode:
  every following line until block end is the `full_content` value
  (leading/trailing blank lines stripped, interior preserved).

**Required:** `kind`, `trigger_kind`, `one_liner` — domains per the
`takeaways` field table. **Optional:** `trigger_spec` (same coordinate
systems, same fnmatch dialect as §`trigger_spec` coordinate systems),
`scope`, `source`, `full_content`. **Absent by design:** `id`/`created`
(assigned at import), `status`/`mirror` (schema defaults apply:
`active`/`none`).

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

## Validation requirements (tests must cover)

- [ ] Reader raises on: missing table, missing required column, changed enum domain.
- [ ] Reader tolerates an additive unknown column.
- [ ] Reader raises on a `firings.takeaway_id` with no matching takeaway row.
- [ ] NULL `outcome` excluded from both numerator and denominator of precision.
- [ ] Trigger simulation reproduces fnmatch slash-crossing on a fixture
      (`payload/*` vs `payload/a/b`).
- [ ] Only `status = 'active'` rows counted firing-eligible; `mirror` value has no
      effect on eligibility.
- [ ] A v1-dialect store (old `status` enum domain) rejected with a message naming
      the migration, not a generic type mismatch.
- [ ] `session_id = "unknown"` bucketed separately from real sessions.
- [ ] Live check: `monition report <store-path>` runs without writes
      (store working set unchanged after the run).
