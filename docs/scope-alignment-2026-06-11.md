# Monition scope alignment — 2026-06-11 (grill-me artifact)

Settles the ownership question raised at the end of the bootstrap session. Supersedes
the intake answer "Monition is a consumer of the store, not a co-owner" — ownership of
the *machinery* moves to Monition; per-project ownership of the *data* stands.

## Task as understood

Monition is the module that owns the takeaway discipline end to end: the machinery
that stores and fires takeaways, the value layer that decides whether a firing is
worth its context cost, and the eval layer that measures both. It is conceptually
part of the user's context-management system and physically its own repo.

## Vocabulary (settled)

- **Takeaway** (row; *gotcha* = the most common kind) — one mined lesson with its
  trigger.
- **Takeaway corpus** — the per-project Dolt database (`takeaways` + `firings`).
  Replaces "store", which is too generic; "store" persists only as an alias in
  legacy filenames until renamed.
- **Monition machinery** — schema, `takeaway.py` CLI, disclosure executors, payload
  templates for all of the above.
- **Monition** (proper noun) — the repo/module owning machinery + value layer + evals.

## Decisions (firm)

1. **Machinery ownership moves to Monition.** Schema, CLI, executors, and their
   payload templates migrate from CMS to the monition repo. CMS instantiates new
   projects by pulling that machinery from Monition — Monition is the upstream for
   everything takeaway-shaped. CMS keeps its own *corpus* (its data stays put, like
   any project's).
2. **Data stays per-project.** Each repo's corpus populates slowly as that project
   runs. No central takeaway database.
3. **Separate repos, settled.** Monition is CMS's peer, not a subdirectory. Each
   stays independently dispatchable; CMS depends on Monition only at instantiation
   time, never at session runtime (fail-open stands).

## Decisions (tentative defaults, accepted)

4. **Write authority is earned, per action type.** Monition starts recommend-only.
   Reversible actions (retire) become auto-applicable once eval precision
   demonstrates trust; spec rewrites stay propose-only longer.
5. **Directive/guidance evals are in-charter, later phase.** The
   disclosure-logged + outcome-rated substrate extends to proactive guidance
   (CLAUDE.md lines, profile lines, method rules). Guidance becomes rows
   (`trigger_kind = always_on`) only where per-firing eval is actually wanted;
   prose stays prose until a specific line is contested.

## Non-goals

- A central cross-project takeaway database.
- Row-ifying governance docs wholesale (CMS v1's failure, inverted).
- A runtime dependency of any project on the monition repo.

## Consequences for roadmaps (not yet executed)

- **Monition road.md re-scopes:** new early phase "absorb the machinery" (move
  `takeaway.py`, executors, schema doc, payload templates from CMS; rename
  store→corpus in the moved artifacts); the online scoring seam shifts one phase
  later. The takeaway-store contract becomes Monition-internal documentation plus
  an instantiation interface consumed by CMS.
- **CMS changes:** `method/takeaway-store.md` moves with the machinery (CMS keeps a
  pointer); CMS pulls the machinery from the installed `monition` module; CMS's
  `takeaways/` corpus and its wiring stay in CMS.
- Both changes go through each repo's consent gate in a fresh session — nothing
  moves on the strength of this artifact alone.

## Open questions deferred to implementation

- Pull mechanism at instantiation (copy from path vs. git submodule vs. generated
  from monition templates).
- Whether `firings` gains a corpus-version column when machinery and contract merge
  into one repo.
- Naming migration mechanics (file/table renames vs. alias-only).
