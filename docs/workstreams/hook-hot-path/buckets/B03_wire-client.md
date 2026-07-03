# Bucket B03: Wire-protocol client (optional extra, fail-open)

Parent: ../workstream.md
State: done
Goal for session: dolt queries ~ms via server socket; CLI fallback intact.
Target duration: 45 min
Context budget: Read parent + this bucket + required touchpoints only.

## Conceptual mapping

- Every remaining ~160ms unit is the dolt CLI binary spawn per query. The
  sql-server is already resident (machine-wide since 2026-07-02); speaking MySQL
  wire protocol to it directly turns each query into ~1–5ms. One surface:
  `DoltBackend.execute_sql` grows a preferred transport; everything above it is
  untouched.

## Tasks

- [ ] **Design review first** (repo convention — non-trivial decision): write
      `docs/decisions/2026-07-02-wire-client-extra.md` — question, options
      (pymysql vs mysql-connector vs stdlib-socket-handshake vs stay-CLI), why
      rejected ones lost, supersession audit (grep decisions + road.md §2 for
      sql-server/write-path docs; this *extends* 2026-06-19-dolt-sql-server-write-path,
      supersedes nothing), and the contract section it affirms (single write
      path, takeaway-store.md). Propose to user before implementing.
- [ ] Add optional extra to `pyproject.toml` (e.g. `monition[wire]`); import
      guarded, absence = CLI path, zero new required deps.
- [ ] In `DoltBackend.execute_sql`: if server info present AND wire lib
      importable → one connection per process (module-level lazy), query over
      it; any wire error → log once, fall back to CLI subprocess for the rest of
      the process.
- [ ] Read server address/creds the same way the dolt CLI does
      (`.dolt/sql-server.info`) — never hardcode a port.
- [ ] Bench before/after; record in Updates.

## Required touchpoints

- `src/monition/storage_backends.py  101–181  DoltBackend.execute_sql/_run/describe`
  The transport seam; `ensure_running` call sites at 125–145.
- `src/monition/dolt_server.py  grep -n "sql-server.info\|port\|def ensure_running"`
  How server presence/port is discovered — reuse, don't reimplement.
- `pyproject.toml  grep -n "optional-dependencies" -A 10`
  Existing extras pattern ([mcp], [embed]) to mirror.
- `docs/decisions/2026-06-19-dolt-sql-server-write-path.md  1–80`
  The decision this extends (incl. its 2026-07-02 correction block).

## Conditional touchpoints

- `tests/test_dolt_server.py  grep -n "def test"`
  Read only when writing the fallback test — mirrors its spawn/stop fixtures.

## Do-not-read / avoid

- MySQL protocol internals / hand-rolled handshake: if no acceptable client lib,
  the answer is "stay on CLI", not a bespoke protocol implementation.

## Design direction

- **Named invariant: transport, not a second path.** Identical SQL text goes
  through wire or CLI; results normalized to the same dict shape (watch: wire
  clients return `None` for NULL where dolt CLI JSON *omits* the key — normalize
  to omission or audit `.get()` discipline downstream).
- **Named invariant: fail-open chain** — wire error → CLI subprocess → (absent
  store) silent return. Kill-server-mid-hook test proves it.
- Connection per hook process is enough (hooks are cold processes); do not build
  pooling.
- Timeouts: connect timeout ≤0.5s so a wedged server costs less than the CLI
  path it replaces.

## Validation

- `env -u MONITION_STORE .venv/bin/pytest -x -q` green with AND without the
  wire lib installed (tox-less: run once, `pip uninstall` in a throwaway venv or
  monkeypatch the import, run targeted tests again).
- Fail-open test: start scratch server, begin a hook, kill server → hook
  completes via CLI, no exception escapes.
- Bench: fire-hook total ≤ ~0.3s, prompt-hook ≤ ~0.5s warm (exit targets).

## Done criteria

- [ ] Tasks complete (design review user-accepted before code).
- [ ] Validation passes.
- [ ] Bucket `Updates` section records discoveries/gotchas/handoff.
- [ ] Parent workstream progress updated.

## Updates

- [2026-07-02 16:25] Created. Handoff: none yet. Gotchas: none yet.
- [2026-07-02 17:50] DONE (design review user-ratified: pymysql accepted).
  `docs/decisions/2026-07-02-wire-client-extra.md` written; `[wire]` extra in
  pyproject; `dolt_server.address()` added; wire transport inside
  `DoltBackend.execute_sql` (lazy conn per instance, autocommit, 0.5s connect
  timeout, db resolved via SHOW DATABASES + normalized basename); `describe()`
  rerouted through execute_sql. Transport errors (2003/2006/2013) → CLI
  fallback; query errors → StorageBackendError identical to CLI. **Measured:
  0.9ms/query wire vs 151.7ms CLI.** Parity verified on hub + tests
  (tests/test_wire.py, 5 tests incl. kill-server-mid-use fallback); suite green
  320 passed WITH the lib, 28 passed/5 skipped targeted run WITHOUT it.
  Gotcha worth keeping: dolt CLI `-r json` stringifies all values ONLY
  through the server — serverless direct access emits native JSON numbers;
  consumers tolerate both, wire mirrors the through-server shape. Bench after:
  prompt-hook 431ms, fire-hook 52ms — exit targets already met pre-B04.
