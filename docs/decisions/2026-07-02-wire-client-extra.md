---
status: decided
---
# Wire-protocol client for the resident sql-server (optional extra)

**Date:** 2026-07-02 · **Status:** accepted (user-ratified: "I'm okay with pymysql
dependency") · **Workstream:** hook-hot-path B03 (road.md Phase 8)

## Question

With the resident `dolt sql-server` covering the hub, every store query still pays
~160ms of dolt *CLI client* cost per invocation (fork/exec + Go binary startup +
connect + teardown; the query itself is ~0 — measured 2026-07-02). A hook event
issues 3–6 queries, so the CLI spawn tax alone keeps hooks above the Phase 8
targets (prompt ≤0.5s, fire ≤0.3s). How do hooks reach ~ms per query without
creating a second store path?

## Decision

Speak MySQL wire protocol directly to the already-running sql-server via
**`pymysql`, as the optional extra `monition[wire]`** — a transport inside
`DoltBackend.execute_sql`, nothing more:

- Guarded import; extra absent → CLI path, byte-for-byte today's behavior. Base
  install stays dependency-free (the [mcp]/[embed] pattern).
- Wire is used only when `dolt_server.running(store)` says the server accepts;
  address from `.dolt/sql-server.info` (PID:PORT:UUID) via the existing
  `_read_info` — never a hardcoded port.
- **Transport, not a second path**: identical SQL text; results normalized to the
  CLI JSON shape — verified live 2026-07-02: *through the server*, dolt `-r json`
  emits every value as a string and omits NULL keys entirely (serverless direct
  access emits native JSON numbers instead; consumers tolerate both, discovered
  by the fallback tests). The wire layer mirrors the through-server shape —
  stringify non-None (datetime → `%Y-%m-%d %H:%M:%S`, Decimal via `str()` scale
  preserved), drop None keys — since wire only runs where a server accepts.
  A parity test runs the same queries through both transports and diffs.
- **Fail-open chain preserved**: transport-level errors (connect failure, lost
  connection) close the connection and fall back to the CLI subprocess; *query*
  errors (syntax, missing table) raise `StorageBackendError` exactly like the
  CLI path — a bad query must fail identically, not get silently re-run.
- One lazy connection per backend instance (hooks are cold processes; no
  pooling). `autocommit=True` to match per-invocation CLI semantics.
  `connect_timeout` ≤0.5s so a wedged server costs less than the CLI path.

## Options considered and why the rejected ones lost

- **pymysql — CHOSEN.** Pure-python, MIT, tiny, mature; nothing to build; exactly
  the capability needed.
- *mysql-connector-python* — heavier, C-extension variants and licensing
  friction; no needed capability beyond pymysql.
- *mysqlclient (C)* — native build dependency in the hook path; against the
  zero-install ethos that made SQLite the external default.
- *Hand-rolled MySQL handshake* — bespoke protocol code is a maintenance sink
  (auth plugins, charsets); explicitly listed do-not-do in B03.
- *Stay on CLI* — keeps ~160ms × N per hook; Phase 8 targets measured
  unreachable (B01/B02 got prompt-hook to ~1.5s; the residue is CLI spawns).

## Supersession audit

Grepped `docs/decisions/` + `road.md §2` for sql-server/write-path/daemon docs:
**extends** `2026-06-19-dolt-sql-server-write-path.md` (incl. its 2026-07-02
correction block — the flags are hand-set machine-wide, which is what makes the
server reliably present for this client); supersedes nothing. Affirms
`docs/contracts/takeaway-store.md` single-write-path: all writes still flow
through `WriteStore` → `DoltBackend`; this changes how bytes reach the server,
not what is written or by whom.
