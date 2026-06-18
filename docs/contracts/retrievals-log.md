# Data contract — retrievals log (v1)

This contract is the schema of the **retrievals log**: the flat instrumentation
log that CMS's session-archive tooling writes, one row per recall lookup against
the progressive-disclosure ladder (index → summary → extracted transcript → raw
JSONL). It is the eval data the future retrieval router trains against.

Unlike `takeaway-store.md`, this is **not** a code↔data boundary the Monition
module enforces. It is a *schema-discipline* contract: Monition owns the canonical
schema (the field list and semantics below); CMS owns the **data and the
machinery** — it produces every row, reads its own log, and chooses the physical
encoding. Monition is neither the reader nor the writer here. This deliberate
departure from the takeaway-store's "all access through the single approved
reader" rule is the whole point of the seam: the retrievals log is a separate
substrate that lives user-level (`~/.claude/logs/`, all projects), with **no
runtime dependency on Monition** — capture and retrieval must work when Monition
is not installed (fail-open).

Provenance: confer `2026-06-12 confer session-archive-eval-substrate` (resolved),
session-archive spec decision 8 (CMS `docs/specs/2026-06-12-session-archive.md`),
cross-project roadmap phase **P1m**. Owner-at-birth: CMS drafted the field list it
needs; Monition reviewed and owns this canonical. CMS **cites** this doc, never
duplicates it.

## Why Monition owns the schema (and not the data)

`firings` is takeaway-bound (FK + dedup against `takeaways`) and per-project; no
user-level Monition store exists or is planned, so the retrievals log cannot live
in a Monition store. But the log is an **eval substrate** — the same kind of
helpful/noise signal as `firings.outcome` — so it must speak the same schema
discipline as the rest of the substrate, or the substrates fragment. Monition owns
that discipline (additive-column + version-stamp + `helpful|noise`/NULL
vocabulary) so the several logs (harness JSONL traces, session-archive summaries,
this retrievals log, `firings`/ratings, tier-3 labels) stay **separate but
join-able on demand**, never merged into one store. This matches the tier-0
interchange precedent (realignment decision 13) and the `export-firings` read-verb
contract, its sibling doc in this directory.

## Graduation

The retrieval **router** — the policy that decides which rung to climb and when to
stop — lives in CMS day one. It **graduates into Monition** if and only if Monition
grows a retrieval surface not bound to per-project stores. Until then Monition owns
only this schema; the router is CMS's. When it graduates, this contract is the
seam it crosses through, and the graduation is recorded in `docs/road.md`.

## Versioning and rejection

The log carries an **explicit version stamp** — a `schema_version` value reachable
per row (a column, or a header/manifest the physical encoding makes
per-row-attributable). This differs from the Monition store, which infers version
from a column fingerprint; here Monition does not read the log, so an explicit
stamp is the only durable version signal a downstream consumer (a join-on-demand
analysis, the future router) can key on.

- **Additive columns are the only compatible change.** New fields unknown to a
  consumer are tolerated and ignored; the schema may grow without a version bump.
- A **removed field, a renamed field, or an enum-domain change** is a contract
  break: it requires a new version of this document and a bump of the stamp.
- A consumer that reads the log keys on `schema_version` and refuses to coerce a
  version it does not understand — it raises or degrades, never guesses.

**v1 (2026-06-12, current):** the schema below.

## `retrievals` — per-field meaning

One row per recall lookup. Logical schema; CMS owns the physical encoding (a flat
table or JSONL line per row, its choice).

| Field | Type | Meaning |
|---|---|---|
| `id` | int / uuid | Retrieval id. |
| `schema_version` | int | The version stamp. `1` under this document. |
| `queried_at` | datetime | Naive local time the lookup ran. |
| `session_id` | varchar, nullable | Harness session that issued the query. May be the literal `"unknown"` — an anonymous bucket, not a real session. Same semantics as `firings.session_id`, so the two substrates join on this key. |
| `query` | text | The recall query as issued. |
| `rungs_climbed` | varchar | Which disclosure rungs were touched, in ascending-cost order: `index`, `summary`, `transcript`, `raw`. Records the rungs reached (e.g. the highest rung, or the ordered set climbed) — the cost-depth of the lookup. |
| `hit` | tinyint(1) | **Mechanical** retrieval result: `1` if the ladder returned a candidate answer, `0` if the query fell through all rungs unanswered. This is "did anything come back", **not** "was it useful" — that is `outcome`. |
| `result_ref` | varchar, nullable | Identifier of the top artifact returned (e.g. the session-summary filename). `NULL` on a miss. |
| `tokens` | int | Tokens spent climbing the ladder for this lookup — the retrieval-overhead cost signal the router optimizes against. |
| `outcome` | enum `helpful\|noise`, nullable | **Post-hoc** rating of whether the retrieval actually helped. **`NULL` means unrated — missing data, never "noise" and never "neutral".** Identical vocabulary and null-semantics to `firings.outcome`, so retrieval helpful-rate and firing helpful-rate are the same estimator of ΔP(fail). |

### `hit` vs `outcome` — two distinct signals

`hit` is mechanical and written at lookup time: the ladder either returned a
candidate or it did not. `outcome` is the eval rating, written after the fact by a
human or agent: was the returned candidate the thing the user was reaching for. A
lookup can be `hit = 1, outcome = noise` (something came back, but it was the wrong
session) or `hit = 1, outcome = NULL` (returned, never rated). This mirrors
`firings`, where the firing happening is mechanical and `outcome` is the post-hoc
judgment — and it is what lets a v1 anecdote ("the archive answered me ~8/10
times") become a real eval later.

## Validation requirements (a consumer's reader must cover)

Monition ships no reader for this log, so these bind whatever consumer reads it
(CMS's own analysis, a future join-on-demand, the graduated router):

- Reject any row whose `schema_version` the reader does not understand — never
  coerce across a version it lacks.
- Treat `outcome = NULL` as unrated (missing), never as `noise` and never as a
  neutral third value.
- Treat `hit` and `outcome` as independent — never derive one from the other.
- Tolerate and ignore additive columns unknown to the reader.
- Join to `firings` on `session_id` on demand; never merge the two stores.

## Forbidden near-misses

- **Folding the retrievals log into a Monition store.** It is user-level and
  per-machine; `firings` is per-project and takeaway-bound. They join on
  `session_id`; they do not share a store.
- **Reusing `outcome` for the mechanical result.** `hit` is the mechanical signal;
  `outcome` is the rating. Collapsing them loses the "returned but wrong" case.
- **A Monition runtime dependency in the capture or retrieval path.** Fail-open is
  load-bearing: the archive must work with Monition absent.
- **Duplicating this schema into CMS docs.** CMS cites this doc; the canonical
  lives here.
