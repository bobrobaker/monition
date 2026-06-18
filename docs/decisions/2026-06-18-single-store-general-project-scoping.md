# 2026-06-18 · Single store with general/project scoping (replaces per-repo isolation)

**Status.** **Ratified** via confer with CMS, 2026-06-18 (thread:
`handoffs/archive/2026-06-18-confer-single-store-scoping.md`). Both repos agreed
to the hub model, the columns-not-boundaries core, and the ownership split. One
refinement landed in confer: store discovery uses a **monition-namespaced**
`MONITION_STORE` env var (not a CMS-named one) so the machinery stays
CMS-agnostic — see Decision below.

## Question

How should a takeaway that is *general* — reasonable in every repo, not specific
to one — be stored and fired, without drifting into N hand-maintained copies?

Today isolation is **physical**: one store per repo at `<repo-root>/monition/`,
and the repo boundary *is* the store boundary. A general lesson has no home — it
must be re-added to every repo's store and drifts immediately. The `mirror`
column (`none|candidate|mirrored`) was the intended promotion path to a shared
upstream, but the sweep was never built, CMS walked away from candidate rows, and
the SQLite-default switch removed its Dolt-native rationale. It is vestigial.

## Decision

Collapse to **one store** with the general/project distinction carried as
**columns, not physical boundaries** (Option A):

- New column **`reach`** (`general | project`) — machine-matched. `general` rows
  fire in any repo; `project` rows fire only in their originating repo. (Name
  chosen to avoid overloading the existing free-text `scope` column — repeating
  the v1 `status`-overload mistake is the explicit anti-goal.)
- New column **`origin_repo`** — provenance *and* the filter key for `project`
  rows. (Distinct from the existing `source`, which is session/commit.)
- The single store is **CMS-managed** (CMS owns instantiation and lifecycle per
  the deployment seam). Sharing happens at this hub, not via per-repo git commits.
- **Discovery (settled in confer):** monition resolves the store from a
  monition-namespaced `MONITION_STORE` env var, falling back to
  `<repo-root>/monition/` when unset (**unset = standalone/no-hub mode** — keeps
  monition usable without CMS). CMS *populates* `MONITION_STORE` from its own
  installer (`bootstrap.sh`), mapping from `$CMS_TAKEAWAY_STORE` or setting it
  directly — so no CMS-specific name lives in the machinery. Current-repo for the
  origin filter stays independent of store location (`hooks._repo_root()` from
  `CLAUDE_PROJECT_DIR`/git), which the audit confirmed is already separate.
- **Local SQLite now; cross-machine distribution deferred** (sub-option a). One
  store kills drift across one developer's repos immediately. "Other people will
  want it" is a real but *separate* axis — cross-machine sync — that reintroduces
  the Dolt question and is built only when a second machine actually exists.
- **`mirror` is retired**, superseded by `reach` + the hub model.

## Structural seams this touches (from the code audit, not the docs)

The per-repo coupling is structural, in three places that all assume store
location == repo location:

1. `hooks._open_store()` hardcodes `WriteStore(<root>/monition)`. → must locate
   the single store independently of the current repo.
2. `fire_hook` gates on `fp.startswith(repo)` and matches **repo-relative**
   paths; `match()`/`on_demand_match()` have no origin filter. → `project` rows
   must be filtered by `origin_repo == current_repo`; current-repo must come from
   cwd/git, not the store path. `general` rows skip the filter.
3. `fire()` reads git provenance from `os.path.dirname(self.path)`, assuming the
   store sits inside the repo it logs for. → provenance must derive from the
   current repo; firings should record which repo they fired in (else
   per-repo precision on a `general` row is unanswerable).

## Options considered and why the rejected ones lost

- **B — per-repo stores + one shared "general" store, layered at read time.**
  Keeps project isolation physical (edit_path correctness free), solves general
  drift via one shared store. Rejected: dual-source complexity everywhere —
  reader, writer, dedup, and `show <t-id>` span two stores; cross-store ID
  collisions need a namespace prefix in injection labels; which store logs a
  general firing is ambiguous. Reintroduces a two-store coordination problem A
  avoids.
- **C — finish the original mirror/upstream sweep.** Matches the existing schema,
  keeps stores committable. Rejected: coherent only with Dolt's git-native
  push/pull; SQLite has no remote/merge primitive, so it means hand-building sync.
  CMS already abandoned candidate rows. Most machinery for the least payoff.
- **D — general lessons graduate to tier-0 / governance lines (no general rows).**
  Aligned with the project's graduation seam; `sync` already distributes skills.
  Rejected as the *whole* answer: only fits **always-on** generals. A
  general-but-**trigger-shaped** lesson becomes always-on context cost and skips
  the EV scorer — losing exactly the properties that made it a row. D still
  applies to always-true generals; A is for the trigger-shaped ones. The two are
  complementary, not competing.

## Anti-goals

- Do **not** overload the existing `scope` column (free-text human tags) with the
  machine-matched discriminator — that is the v1 `status`-overload mistake.
- Do **not** build cross-machine distribution before a second consumer exists.
- Do **not** orchestrate where the store lives from monition — that is CMS's
  (deployment seam). Monition supplies the schema, the `reach`/`origin_repo`
  columns, and the executor filter; CMS owns hub location and lifecycle.

## Implementation split (agreed in confer)

- **monition (machinery):** add `reach` + `origin_repo` columns, retire `mirror`;
  `resolve_store_path()` + `_open_store()` consult `MONITION_STORE` then fall back;
  `origin_repo == current_repo` filter on `project` rows; `monition migrate`
  sub-verb folds existing per-repo stores into the hub (backfill `origin_repo` from
  repo root, `reach='project'` default).
- **CMS (discipline/installer):** populate `MONITION_STORE` from `bootstrap.sh`;
  own hub location + lifecycle; point host repos at the hub.

## Follow-ups

- Migration is the v5→v6 step (`mirror` retired; `reach` default `project`,
  `origin_repo` backfilled from each store's root).
- Firings likely need a repo dimension for per-repo precision on general rows.
- **Parked (user-scope):** public-repo store backup / eventual team-share of
  `project` rows. Not foreclosed — a future team-share is an `origin_repo`-filtered
  export (trivial on SQLite); only *multi-writer* sharing needs the deferred Dolt
  seam. The user scopes this if/when it's real.
