# 2026-06-19 · Decompose `monition init` into `init-store` + `instrument`

**Status.** Design ratified via the monition↔CMS confer (2026-06-19, archived at
`handoffs/archive/2026-06-19-confer-hub-era-deployment-strategy.md`). **Built 2026-06-19**:
`init_store` + `instrument` + `init`-as-composition shipped (`init_sync.py`), `init-store`
+ `instrument` CLI verbs, tests in `tests/test_init_decompose.py`. CMS consumes the two
primitives in `bootstrap.sh`.

**Question.** The v6 single-hub model broke the deployment primitive. `monition init`
unconditionally creates a per-repo store at `<root>/monition` **and** instruments the repo
(hooks/MCP/skills) — one fused act. The hub era needs those two concerns separable in both
directions, and both repos hit it independently:
- monition (instrument side): "join a repo to the hub" wants *instrument-only* — wire
  hooks + point at `MONITION_STORE`=hub, create **no** per-repo store (fused `init` would
  litter a dead store the hub-wired hooks ignore).
- CMS (store side): standing up the hub wants *store-only* — create the Dolt store,
  instrument nothing.

**Decision.** Add **two orthogonal primitives**, retain `init` as their composition
(additive, no breaking change):
- `monition init-store <path> [--dolt]` — pure store creation (the hub, or a standalone
  store); touches only the store dir.
- `monition instrument [--root <repo>] --store <path>` — pure instrumentation: merge
  hooks/MCP/skills + point `MONITION_STORE` at `<path>`; creates **no** store. Idempotent
  and re-runnable to re-point a repo at a different store.
- `monition init` = `init-store <root>/monition [--dolt]` + `instrument --root <root>
  --store <root>/monition` — the standalone/forker one-command path, unchanged.

"Join a repo to the hub" = `instrument --store <hub>`. brain2 is not special (its fused
`init` was already correct because its local store *is* the hub → no rework).

**Options weighed.**
- *Memorize the workaround* ("init then delete the dead store" / "init then ignore the
  hooks") — rejected: drifts, re-derived each time. CMS's framing: a flag/verb beats memory.
- *Subtractive flags* (`--no-store` / `--no-instrument` on `init`) — rejected (monition's
  original proposal): names a verb by what it omits; identity goes muddy and every call
  site reasons about a negation.
- *Two verbs + `init` as composition* — **chosen**: names the two orthogonal concerns
  honestly, `bootstrap.sh` reads cleanly (`init-store <hub> --dolt` once; `instrument
  --store <hub>` per repo), and the forkable one-command `init` contract is preserved.

**Ownership.** monition owns + builds the primitives (verb *names* are monition's call;
CMS stated the consumer requirement). CMS consumes them in `bootstrap.sh`/deploy; the
broader deployment-strategy redesign (which repos, tier-0 payload, session-archive wiring,
mining) layers on top once the primitives exist — it does **not** gate them.

**Build-time constraint (forkable-lock).** `instrument` must not write an absolute
`MONITION_STORE` into the *committed* `.claude/settings.json` — that bakes a machine-local
path into the tree. It writes to gitignored local settings (`settings.local.json`) or
relies on the machine-wide env `bootstrap.sh` sets; the two must not double-source
inconsistently.

**Why the split stays clean.** `instrument` wires hooks + sets `MONITION_STORE` against an
*already-existing* store — it needs no store-schema knowledge, so the concerns don't
re-couple. (The one thing that would force flags instead.)

**Pointers.** Implementation surface: `init_sync.init()` (the fused act to factor —
`make_dolt_store`/`make_sqlite_store` → `init-store`; `_plan_settings`/`_plan_mcp`/
`_plan_skills` → `instrument`), `cli.py` (verb registration). Hub model:
`2026-06-18-single-store-general-project-scoping.md`. Backend: `2026-06-18-dolt-default-ours-sqlite-external.md`.
