# 2026-06-18 · v6 refactor charter — single Dolt hub + global reach + semantic-filter unblock

**Status.** Consolidated execution charter. The underlying decisions are ratified
(see *Source documents*); this doc is the **single executor brief** for building
them as one refactor. Executor: **monition** (the work is ~entirely machinery —
schema, reader/matcher, embed, migrate). CMS owns one thin dependency (*CMS
dependency interface* below).

**How to use this.** This points to the source decisions; it does **not** restate
their rationale — read them for *why*. Here you get the *consolidated scope*, the
*ordered build*, and the *calls made in the 2026-06-18 consolidation thread* that
aren't in any single source doc. Trust the source over this prose; verify
load-bearing claims against code (this repo's hygiene rule).

## Scope in one paragraph

Collapse the per-repo takeaway stores into **one Dolt hub**; carry the
general/project distinction as **columns** (`reach`, `origin_repo`), not physical
boundaries; retire the vestigial `mirror` column; and **unblock semantic
matching** (managed weights cache + warm daemon). Schema **v5 → v6**, one bump,
final. Everything filter-*deepening* (the gate-revision layers and the layered-
Filter refactor) is deferred — see *Deferred*.

## Source documents (pointers — do not duplicate)

Ratified decisions / terms:
- `docs/decisions/2026-06-18-single-store-general-project-scoping.md` — the hub
  model, `reach`+`origin_repo`, `mirror` retirement, impl split. **The spine.**
- `handoffs/archive/2026-06-18-confer-single-store-scoping.md` — the monition↔CMS
  confer **Resolution** (authoritative cross-repo terms).
- `docs/decisions/2026-06-18-noise-targets-the-filter-not-the-gate.md` — the gate
  revision. *Deferred here*; its schema footprint is nil, so it never forces a v7.
- `handoffs/2026-06-18 semantic-embedding-daemon.md` +
  `docs/decisions/2026-06-18-semantic-embedding-warm-daemon.md` — cache fix + daemon.
- `docs/decisions/2026-06-18-firing-observer-seam.md` — the `_notify_observer`
  seam that just landed in `hooks.py`; **must be preserved** through the filter/
  provenance edits.
- `docs/decisions/2026-06-17-storage-backend-sqlite-default.md` — SQLite-default
  decision, **amended by call #2 below** (we run Dolt; SQLite stays the recommended
  default for external hosts). Flip-flop flagged for `/postmortem`.

CMS side (the dependency):
- `CMS/handoffs/2026-06-18 CMS monition-hub-location.md` + CMS session `b00561ec`
  summary — CMS settled hub = `$CMS_LANDING_ZONE/monition/`. Note: that summary
  reasoned "SQLite hub" before call #2; the hub is **Dolt**.

To update *at implementation* (not before; both are governed files):
- `docs/contracts/takeaway-store.md` → v6 — currently v5; drop the `mirror` field +
  the `status × mirror` and v1-dialect sections (`:49-55,100,131-143`), add
  `reach`/`origin_repo`/`firings.repo`, bump the header + versioning note.
- `docs/road.md §2` — two stale spots: line ~30 says **"Backend SQLite, default"**
  (amend per call #2: we run Dolt, SQLite recommended for external hosts), and the
  deferred **`monition mirror <id> <state>` lifecycle verb** item (`:316-324`) is
  **moot** once `mirror` is retired — remove/supersede it. Add a backlink to this
  charter.

## Calls made in the consolidation thread (with why)

1. **One Dolt hub; per-repo stores collapse.** (Ratified confer.)
2. **We run Dolt for our own stores; SQLite is the *recommended* default for
   external/standalone hosts.** Why: the original Dolt→SQLite drop rested on "we
   aren't using Dolt features"; the hub model reverses that (native data
   version-control supersedes the `dump.sql` workaround; multi-writer/multi-repo
   future). Both backends already exist (`storage_backends.py`); Dolt is opt-in over
   the SQLite default. The flip-flop is flagged POSTMORTEM (this session's flag +
   the undrained `b00561ec` flag — consolidate).
3. **Discovery: `MONITION_STORE` → `<repo-root>/monition/` fallback** (unset =
   standalone/no-hub). For *us*, set `MONITION_STORE` in Claude `settings.json`
   `env` (hooks inherit it) → the Dolt hub. `bootstrap.sh` is the **fork-only**
   path; it is not on our critical path.
4. **`reach` (general|project) + `origin_repo` columns; `mirror` retired.**
   `general` fires anywhere; `project` fires only where `origin_repo == current_repo`.
5. **`firings.repo` added** — capture-or-lose-forever (same discipline as
   `git_sha`/`situation`); without it, per-repo precision on `general` rows is
   unrecoverable.
6. **`origin_repo` canonical form = absolute repo root** (from `_repo_root()` /
   `CLAUDE_PROJECT_DIR`/git). Simplest; matches the current-repo derivation exactly.
   Accepts that a moved repo breaks the key (acceptable; revisit only if it bites).
7. **Daemon IN, cache fix IN.** Cache fix is the *actual* unblock (semantic is
   silently dead — weights download into ephemeral `/tmp` inside the blocking hook).
   Daemon is a live-latency win (~1s model load per fire; the query embedding always
   cache-misses). Daemon is architecturally independent (behind `embed.py`), so it
   rides along with zero reopening risk. *Note: the daemon does not affect test
   speed — tests share one process; it's live-hook latency only.*
8. **Gate-revision filter LAYERS and the layered-Filter *structure* refactor: OUT.**
   Per the gate decision's own anti-goal — *don't build filter-refinement machinery
   before real per-context noise data exists.* The origin filter is added as a plain
   predicate, not a layered framework. Deferring the code costs nothing at the schema
   level (the gate work has nil schema footprint → still one final v6).
9. **Out/deferred:** new trigger *kinds*; multi-writer / team-share distribution;
   SQLite *in-place* migration (no v5 SQLite store exists to upgrade).

## Ordered build (audited against code)

Dependency-ordered. Symbol names are primary anchors; line numbers are hints (the
firing-observer merge shifted `hooks.py` below `_disclose`).

1. **Schema → v6** (`init_sync.py`). Define `V6_SCHEMA` (Dolt) + `V6_SCHEMA_SQLITE`
   from the v5 constants: `takeaways` +`reach enum('general','project') DEFAULT
   'project'` +`origin_repo`, −`mirror`; `firings` +`repo`. Extend `migrate()`
   (`:434`, Dolt-only — now correct) with a v5→v6 step: **additive first** (ADD
   `reach`/`origin_repo`/`firings.repo`), **then** `ALTER TABLE takeaways DROP COLUMN
   mirror` (MySQL-dialect — confirm against the live `.dolt`). Backfill
   `reach='project'`, `origin_repo` from the store's repo root. Point `init`
   (`:343`/`:350`) at V6; bump the `migrate` CLI help (`cli.py:175`, says "v5").

2. **Reader contract → v6** (`store.py`). Update `_REQUIRED` (`:25`) +
   `_REQUIRED_SQLITE` (`:64`): add `reach`/`origin_repo`/`firings.repo`, drop
   `mirror`. Update `Takeaway` (`:109`, drop `mirror`, add `reach`/`origin_repo`) and
   the `takeaways()` SELECT (`:234`). Add a **v5→v6 detection raise** mirroring
   `:209-219` ("lacks `reach`/`origin_repo` — run `monition migrate` to v6").

3. **Store resolution — `MONITION_STORE`** (`store_write.resolve_store_path:22`,
   `hooks._open_store:77`). Consult `MONITION_STORE` first, fall back to
   `<repo-root>/monition/`. Keep current-repo from `_repo_root()` (`hooks.py:66`),
   **independent of store location**. *Unblocks CMS's bootstrap wiring (their side).*

4. **Origin filter** (`store_write` `match`/`on_demand_match`/`session_start`).
   Add `(reach='general' OR origin_repo = :current_repo)` predicate. Thread
   `current_repo` from **every** caller — audit found these are not just the hooks:
   - `hooks.py` executors (`_repo_root()`),
   - `cli.py:343,355,356,357` (`query`/`match`/`session-start`/`fire` verbs — cwd/git),
   - `mcp_server.py:26,29` (`on_demand_match`+`fire` — cwd/git),
   - internal self-call `store_write.py:333`.
   Fix `fire_hook`'s `fp.startswith(repo)` gate to use `_repo_root()`, not the store
   path.

5. **Provenance fix + `firings.repo`** (`store_write.fire:198`, `hooks._disclose`).
   `fire()` takes `current_repo` (replacing `os.path.dirname(self.path)` at `:204` —
   now the *hub*, the bug) and records `repo`. `_disclose()` passes it through —
   **preserve the `_notify_observer` call** (firing-observer seam).

6. **Writer surface** (`store_write.add:107`, `cli.py`). `add()` drops `mirror`,
   gains `reach` (default `project`) + `origin_repo` **defaulting to current-repo**
   when not given. CLI `add`: remove `--mirror` (`:111`), add `--reach`/`--origin-repo`.

7. **Retire `mirror` everywhere else.** Real consumers: `store_write` `show`
   formatting; `metrics.py:55,96`; `report.py:25,35`; the **mine-session skill text**
   (`init_sync.py`, step 6 tells users `--mirror candidate` — remove). `replay.py:18`
   is a false positive (prose, not the column).

8. **`monition migrate` fold sub-verb** (`init_sync.py`, `cli.py`). New — fold per-repo
   Dolt store(s) into the Dolt hub against an explicit `--store`/target, backfilling
   `origin_repo` from each source's repo root, `reach='project'`. Dolt→Dolt, no
   cross-backend path. **Shape open:** `migrate --fold-into <hub>` vs a separate
   `migrate-fold` (needs source + target). **Confirm the hub path with CMS before the
   fold-everything-in run** — the one cross-repo dependency.

9. **Cache fix** (`embed._embed_raw:45`). Pass `TextEmbedding(model_name=…,
   cache_dir=<managed XDG path>)` (`:49` currently defaults to ephemeral
   `/tmp/fastembed_cache`); pre-fetch weights at `init`/`sync` (or a small
   `embed-warm` verb). This alone makes semantic matching work and testable.

10. **Warm daemon** (`embed.py` + spawn point in `hooks.py`/`init_sync.py`).
    Lazy-spawn on **first fire** (recommended over `SessionStart` — pays cost only
    when used), unix socket at a session-scoped path, idle-timeout + session-end
    shutdown. `embed.py` tries the socket → in-process → lexical. **Fail-open is
    non-negotiable**: no daemon must never block a prompt. Preserve the existing
    `on_demand_match` fail-open chain.

11. **Contract + tests + validation.** `docs/contracts/takeaway-store.md` → v6;
    `road.md §2` backlink. Add v6 synthetic fixtures + filter/migrate/daemon tests.
    Run `.venv/bin/pytest`. Two **known-stale** failures to not mistake for v6 breaks:
    `test_embed` (onnxruntime env) and `test_init_sync` README assertion.

## CMS dependency interface

monition builds **agnostic** to the hub path — everything resolves through
`MONITION_STORE` and an explicit `--store` target. CMS delivers:
- the **Dolt hub** at `$CMS_LANDING_ZONE/monition/` (created once per machine), and
- **populating `MONITION_STORE`** (map from `$CMS_TAKEAWAY_STORE`/`$CMS_LANDING_ZONE`
  in `bootstrap.sh`, or export directly).

The **one synchronous handoff**: CMS confirms the hub path before monition runs the
fold-everything-in step (build 8). Everything else is independent.

## Deferred (with why)

- **Gate-revision filter layers + layered-Filter structure** — their own anti-goal
  (no per-context data yet); nil schema footprint, so deferring never forces a v7.
- **New trigger kinds** (skill-invocation) — orthogonal breadth; selectivity, not
  entry points, is the open need.
- **Multi-writer / team-share distribution** — rides the Dolt-server seam; built when
  a second machine/writer actually exists. (`origin_repo`-filtered *export* stays
  trivial in the meantime.)
- **SQLite in-place migration** (v5→v6 for an existing SQLite store) — none exists;
  build when a real external SQLite store needs upgrading.

## Open items to settle at build time

- **Fold verb shape** (build 8) — subcommand vs flag on `migrate`.
- **Dolt `DROP COLUMN`** (build 1) — confirm against the live `.dolt` store.
- **`export-firings` repo exposure** — `firings()` reads named columns, so `repo`
  isn't auto-exposed; surfacing it to tier-3 is an additive `firings()` + `Firing` +
  export-record change. Defer unless CMS's eval wants per-repo precision now.
