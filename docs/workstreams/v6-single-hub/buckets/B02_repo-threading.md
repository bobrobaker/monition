# Bucket B02: MONITION_STORE resolution + origin filter + provenance/firings.repo

Parent: ../workstream.md
State: done
Goal for session: Resolve hub via MONITION_STORE; thread current_repo; filter + record repo.
Target duration: 35 min
Context budget: Read parent + this bucket + required touchpoints only.

## Conceptual mapping

One mental model: *where `current_repo` comes from and who must pass it*. Once the store
is the shared hub, `os.path.dirname(self.path)` no longer equals the host repo — so every
matcher gains a `(reach='general' OR origin_repo = :current_repo)` predicate, `fire()`
records the host repo, and provenance reads the host repo not the store dir. Charter
steps 3, 4, 5. Depends on B01 (the columns must exist).

## Data contract / provenance

Report first (contract check):
- Which contract section applies? `firings — per-field meaning` (`repo`), `takeaways`
  (`reach`/`origin_repo` consumed by the filter). Read-only here — B01 defined them.
- Producer/consumer boundary: hooks/cli/mcp callers (produce `current_repo`) → matchers +
  `fire()` (consume/record).
- Provenance: `current_repo` = absolute repo root from `_repo_root()`
  (`CLAUDE_PROJECT_DIR`/git) — **never** the store path. `firings.repo` captured at fire
  time = capture-or-lose-forever (same discipline as `git_sha`/`situation`).
- Validation: a `project` row with `origin_repo == repo A` does not match in repo B; a
  `general` row matches in both; `firings.repo` populated on every new fire.

## Tasks

- [ ] `store_write.py` `resolve_store_path()`: consult `MONITION_STORE` first, fall back to
  `<repo-root>/monition/`. Unset = standalone/no-hub.
- [ ] `hooks.py` `_open_store()`: resolve store via the new path logic; keep the returned
  `repo` from `_repo_root()` — **independent of store location**.
- [ ] `store_write.py` `match`/`on_demand_match`/`session_start`: add `current_repo` param +
  the `(reach='general' OR origin_repo = :current_repo)` predicate (plain SQL predicate, NOT
  a layered filter framework). Thread `current_repo` from the internal self-call (`fire`+rate
  helpers around `:333`).
- [ ] Thread `current_repo` from every external caller: `hooks.py` executors (`_repo_root()`);
  `cli.py:343,355,356` (query/match/session-start — cwd/git); `mcp_server.py:26` (on_demand_match — cwd/git).
- [ ] `store_write.py` `fire()`: take `current_repo`, replace `os.path.dirname(self.path)` in
  the `_git_provenance(...)` call (the hub bug), and record `repo` in the firings INSERT.
  Thread from `cli.py:357`, `mcp_server.py:29`, and `hooks._disclose`.
- [ ] `hooks.py` `_disclose`: pass `current_repo` through to `fire()`. **Preserve the
  `_notify_observer` call.**
- [ ] `store_write.py` `add()` (from B01): default `origin_repo` to `current_repo` when not
  given; ensure `hooks`/`cli` `add` pass it.
- [ ] Confirm `fire_hook`'s `fp.startswith(repo + os.sep)` gate keys on `_repo_root()` (it
  already does via `_open_store`'s second return) — keep it that way after the resolution change.

## Required touchpoints

- `src/monition/store_write.py`  `grep -n "def resolve_store_path\|def match\|def on_demand_match\|def session_start\|def fire\|def add\|os.path.dirname(self.path)"`  matchers + fire + resolution
  The core edit surface: predicate threading + provenance fix + repo record.
- `src/monition/hooks.py`  `grep -n "_repo_root\|_open_store\|_disclose\|_notify_observer\|fp.startswith"`  executors
  Resolve store, thread repo, preserve observer seam, keep the startswith gate on _repo_root.
- `src/monition/cli.py`  lines 336–360  query/match/session-start/fire/add dispatch
  Derive current_repo (cwd/git) and pass to each verb.
- `src/monition/mcp_server.py`  lines 18–35  `match_gotchas_impl`
  on_demand_match + fire need current_repo (cwd/git).
- `docs/contracts/firing-observer.md`  `grep -n "^##"` then the seam section
  Confirm the observer contract the `_disclose` edit must not break.

## Conditional touchpoints

- `tests/` matching/firing tests  `grep -rn "\.match(\|on_demand_match\|\.fire(\|origin_repo\|reach"`
  Read if existing tests call these signatures positionally — adding `current_repo` shifts them.

## Do-not-read / avoid

- `init_sync.py` schema/migrate — B01 owns it; columns already exist here.
- Gate-revision / layered-filter machinery — the origin filter is ONE predicate, deferred otherwise.

## Design direction

- `current_repo` for cli/mcp: derive from cwd via git toplevel (mirror `_repo_root()`'s
  fallback), since they lack `CLAUDE_PROJECT_DIR`. Factor a shared helper if clean; do not
  over-abstract.
- The predicate is additive to existing WHERE clauses — `reach='general'` rows must keep
  firing everywhere; only `project` rows gate on `origin_repo`.
- `firings.repo` is nullable: old firings have none; read via `row.get("repo")` (Dolt drops
  NULL cols from JSON).
- The provenance fix is the load-bearing correctness change: `_git_provenance(current_repo)`,
  not the store dir. Verify the host `git_sha`/`git_dirty` now reflect the host repo when the
  store is elsewhere.

## Validation

- `.venv/bin/pytest` — green minus the 2 known-stale; update signature-shifted tests.
- Scratch smoke: store with a `project` row (origin_repo=A) + a `general` row → match from
  repo A returns both, from repo B returns only general. Fire a takeaway with the store at a
  hub path (MONITION_STORE set elsewhere) → `firings.repo` = host repo, `git_sha` = host repo's.
- Add a v6 fixture + filter test + a provenance-under-hub test.
- Expected: green suite (minus 2 stale), no lint ERRORs, observer call still present.

## Done criteria

- [ ] Tasks complete.
- [ ] Validation passes; new filter + provenance tests added.
- [ ] `_notify_observer` preserved (grep confirms the call survives).
- [ ] Bucket `Updates` records the current_repo helper shape + any signature shifts.
- [ ] Parent workstream progress updated; B03 set to `next` (B03 is independent — may also run before B02).

## Updates

- [2026-06-18] Created. Handoff: depends on B01 columns. Gotcha: the `fp.startswith` gate
  already uses `_repo_root()` — this is a don't-regress, not a fix.
- [2026-06-18] DONE. 188 passed (+3 new reach tests), 2 known-stale, 2 skipped. Lint clean.
  Hub smoke passed: MONITION_STORE wins for store path; current_repo stays the host repo.
  Edits:
  - store_write.py: NEW `current_repo()` (host repo, hub-independent) + `resolve_store_path()`
    now MONITION_STORE-first. NEW `reach_clause(repo)` threaded into match/on_demand_match/
    session_start. `fire()` takes current_repo → provenance from it (falls back to store dir
    only for None self-calls) + records `firings.repo`. add() stamps origin_repo=current_repo()
    for project rows. log_helpful_equivalent/log_recurrence thread current_repo.
  - hooks.py: _open_store MONITION_STORE-aware (repo still from _repo_root); _disclose threads
    current_repo; all 3 executors (fire_hook/session_brief/prompt_hook) capture repo + pass it.
    `_notify_observer` PRESERVED. fp.startswith gate still on _repo_root (don't-regress held).
  - cli.py + mcp_server.py: derive current_repo() once, thread through every matcher + fire.
  KEY DESIGN CALL (reach_clause semantics, recorded in contract):
  - current_repo=None → reach filter NOT applied (fail-open; only explicit pulls cli-query/mcp
    without a repo hit this; all auto-injection hooks supply repo).
  - `origin_repo IS NULL` → fires anywhere (under-specified project row = fail-open, matches the
    store's NULL-is-missing stance). Real v6 project rows always carry origin_repo (add stamps /
    migrate backfills), so isolation holds for every properly-specified row. This is why the
    legacy canonical-fixture project rows (NULL origin) keep firing under hooks — NOT a bug.
  GOTCHA: turning the filter strict (NULL excluded) broke 14 hook/mcp tests whose fixtures have
  NULL origin_repo; the IS NULL fail-open is the deliberate resolution. Contract updated.
  Handoff: B03 (embed cache) is independent — may run next; B04 still CMS-gated.
