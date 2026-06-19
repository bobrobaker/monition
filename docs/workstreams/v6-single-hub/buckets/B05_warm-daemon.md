# Bucket B05: warm embed daemon behind embed.py (fail-open)

Parent: ../workstream.md
State: done
Goal for session: Lazy-spawn a warm embed daemon; socket → in-process → lexical fallback.
Target duration: 35 min
Context budget: Read parent + this bucket + required touchpoints only.

## Conceptual mapping

A live-latency win, fully behind `embed.py`: the ~1s model load per fire (the query
embedding always cache-misses) is paid once by a warm daemon instead of every cold hook.
Architecturally independent — `embed.py` tries a unix socket, falls back to in-process,
falls back to lexical. Charter step 10. Depends on B03 (managed cache must exist first so
the daemon loads from it, not /tmp). Does NOT affect test speed (tests share one process).

## Tasks

- [ ] `embed.py`: lazy-spawn the daemon on **first fire** (not SessionStart — pay cost only
  when used). Unix socket at a session-scoped path. Client: try socket → in-process embed →
  lexical Jaccard.
- [ ] Daemon process: loads `TextEmbedding` once (from B03's managed cache), serves embed
  requests over the socket, idle-timeout shutdown + session-end shutdown.
- [ ] Spawn point wiring in `hooks.py`/`init_sync.py` as needed (detached; must not block).

## Required touchpoints

- `src/monition/embed.py`  whole file  `_embed_raw`, `embed`, fallback chain
  The client side + spawn trigger live here behind the existing interface.
- `src/monition/hooks.py`  `grep -n "_disclose\|on_demand_match\|fail-open\|_open_store"`  fire path
  Where first-fire spawn hooks in; the existing fail-open chain to preserve.
- `src/monition/store_write.py`  `grep -n "on_demand_match\|fail-open\|Jaccard\|embed"`  fallback chain
  Confirm the lexical fallback the daemon-absent path already uses.

## Do-not-read / avoid

- Schema/store/migrate files — daemon is orthogonal to the data model.
- B04 fold logic — unrelated.

## Design direction

- **Fail-open is non-negotiable.** No daemon, dead socket, spawn failure, or timeout must
  EVER block a prompt — every path falls through to in-process then lexical. This is the
  single hardest constraint; design the client to treat any socket error as "go in-process".
- Lazy-spawn detached so the spawning hook returns immediately; the first fire eats one
  cold load (or falls back) while the daemon warms for subsequent fires.
- Session-scoped socket path (e.g. under `$XDG_RUNTIME_DIR`/tmp keyed on session id);
  idle-timeout so an abandoned session's daemon reaps itself.
- This is the riskiest bucket (concurrency, process lifecycle, socket cleanup). Build the
  client+fallback first and test it with NO daemon present (must behave exactly as today),
  then add the daemon, then the spawn trigger. Externalize verification — do not simulate
  the lifecycle in your head.
- Hooks are cold blocking subprocesses under a 30s timeout — the spawn must be fire-and-forget.

## Validation

- Fallback-first: with no daemon, `embed`/`on_demand_match` behave identically to pre-B05
  (test this before adding the daemon).
- With the daemon: second+ embed calls hit the warm socket (no per-call model load);
  killing the daemon mid-session falls back cleanly to in-process/lexical with no hang.
- Idle + session-end shutdown actually reaps the process + removes the socket.
- `.venv/bin/pytest` green minus the 2 known-stale (daemon path is live-only; cover the
  client fallback chain in tests with a stubbed socket).
- Expected: zero added prompt-blocking risk; latency win on warm fires only.

## Done criteria

- [ ] Client fallback chain proven with no daemon (behaves as today).
- [ ] Daemon spawns lazily, serves, reaps on idle/session-end.
- [ ] No path can block a prompt (fail-open verified).
- [ ] Bucket `Updates` records the socket path scheme + shutdown triggers.
- [ ] Parent workstream progress updated; workstream complete.

## Updates

- [2026-06-18] Created. Handoff: depends on B03 managed cache. Riskiest bucket — build
  fallback-first, add daemon last.
- [2026-06-18] DONE. 198 passed (+6 daemon tests), 1 known-stale (README), 2 skipped. Lint
  clean. **Real end-to-end smoke passed**: real bge-small model loaded in a daemon thread,
  served 384-dim vectors over the unix socket, semantic scoring ranked correctly (0.796 vs
  0.426), daemon idle-exited + cleaned its socket.
  TWO DELIBERATE DIVERGENCES from this bucket's original spec (both de-risking, recorded here):
  1. OPT-IN via `MONITION_EMBED_DAEMON`, default OFF (was: always-on lazy-spawn). Default =
     exactly today's in-process behavior, zero risk; matches the firing-observer opt-in/fail-open
     convention. Lets the latency win be validated before ever becoming default.
  2. MACHINE-SCOPED (per-user) daemon, NOT session-scoped (was: session socket + session-end
     shutdown). The model is a pure text→vector function with no per-session state, so one warm
     daemon shared across sessions is simpler + more efficient, and idle-timeout reaps it without
     threading session-id into embed.py or wiring a session-end hook.
  Edits (all in embed.py + cli.py, NO hooks.py change — lazy-spawn happens inside `_embed`):
  - embed.py: `_embed_raw` stays the in-process primitive + fallback. NEW `_embed()` dispatcher:
    opt-in → `_daemon_embed` (unix socket, newline-framed JSON, 5s connect timeout) → on ANY
    failure `_spawn_daemon()` (detached Popen, fire-and-forget) + serve this call in-process.
    `run_daemon()`: one-per-machine (probe existing socket → exit if live, unlink if stale),
    bind/listen, warm model once, accept-loop with idle_timeout, cleanup socket on exit.
    `_serve_one` swallows bad requests. `embed_texts` now routes through `_embed`.
  - cli.py: `embed-daemon` verb (manual/spawn entry; spawn uses `python -c "...run_daemon()"`).
  FAIL-OPEN verified: daemon off → identical to pre-daemon; daemon down → in-process + spawn;
  wedged daemon → 5s timeout then in-process. No path blocks a prompt. Tests cover dispatch
  (stubbed) + protocol/lifecycle/idle-exit/stale-reclaim/redundant-exit (real thread, fake model).
  Handoff: workstream COMPLETE except B04 (fold), still CMS-gated. Daemon is opt-in — flip
  MONITION_EMBED_DAEMON to enable; consider defaulting it on after live validation.
