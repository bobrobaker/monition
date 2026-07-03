---
name: deploy
description: Wire the CMS machinery into a repo with one command — detect fork-vs-existing-repo, run bootstrap.sh, health-check, walk the interactive steps. Use when the user invokes /deploy [path] [flags], says "wire up this repo" / "set up CMS here" / "onboard this project", or right after forking CMS. NOT for executing roadmap work (that's /dispatch), and NOT a replacement for running bootstrap.sh by hand.
---

# deploy

The design rationale (the deterministic/judgement split, the global-archive rule, the flag
surface) lives in `method/deploy.md` — read it the first time you run this or edit the deploy
path. The executable procedure is below; it is self-sufficient.

This skill is the **one entry point** after a fork. It drives `bootstrap.sh` (which owns every
deterministic action) and supplies the judgement bash can't: target detection, doctor triage, and
the interactive steps. Everything it calls is idempotent — safe to re-run.

1. **Detect the target — gate before doing anything.** Resolve the target repo (the `[path]`
   argument, else cwd). Is it a CMS clone? Cheap check: it has `bootstrap.sh` **and** `method/`
   **and** `.claude/skills/`. → **in-place**, run `./bootstrap.sh` from inside it. Otherwise it's
   an arbitrary repo → run `<cms-clone>/bootstrap.sh <target>` (**apply-to-target**). State which
   mode and why in one line before acting. If the target isn't a git repo, stop and say so
   (bootstrap requires one).

2. **Resolve arguments from the invocation.** Pass through whatever the user gave:
   `--hub PATH` (join a shared store) or `--standalone` (per-repo); `--embed` (semantic extra);
   `--approve-mcp` (write the project-MCP approval); `--fix-path`; `--force-hookspath` (repoint
   an existing non-`.githooks` `core.hooksPath` — bootstrap refuses to do this silently);
   `--link-global` (in-place only, to single-source the global skills from this clone). Defaults: the `[mcp]` extra is installed
   unless `--no-mcp`; `[wire]` (the sql-server MySQL-wire transport) rides along unconditionally
   regardless — tiny, pure-python, fail-open. If neither a hub nor `$MONITION_STORE`/`$CMS_LANDING_ZONE` is set and the
   user didn't say, **ask** hub-vs-standalone before running (it decides where takeaways live) —
   don't guess.

3. **Run `bootstrap.sh`** with the resolved flags. It installs, arms, creates-or-joins the store,
   merges the hooks (honoring the global-archive rule — see `method/deploy.md`), optionally writes
   the MCP approval, and ends by printing the `--doctor` health check.

4. **Read the doctor output and triage.** Each line is `PASS|WARN|FAIL  check  detail`.
   - All `PASS` → report done; stop.
   - **Mechanical-and-safe** fixes — just apply them: MCP not approved → re-run with
     `--approve-mcp`; PATH missing → `--fix-path`; hooks/store missing → re-run bootstrap.
   - **Needs a decision** — surface to the user, don't silently act: a missing `[mcp]` extra when
     monition was *already installed* (fixing it means `--reinstall`, which rewrites their global
     `monition` CLI); a stale monition version (`monition-ver` FAIL — same `--reinstall` decision);
     an ambiguous hub; a foreign `.githooks/pre-commit` or `core.hooksPath` that bootstrap refused
     to overwrite (merging their hooks is theirs to own, or `--force-hookspath` for the path). A
     `FAIL` breaks the takeaway/MCP loop and must be resolved; a `WARN` is degraded-but-working —
     name it and let them choose. A `hook-errors` WARN means the hooks have been **failing
     silently** — read the named log before declaring the deploy healthy.

5. **Walk the interactive residue.** The steps a script must not do unattended: confirm the MCP
   **trust** decision before approving; offer (don't assume) the PATH edit; for an arbitrary repo
   that already had a `.claude/settings.json`, confirm the hook merge landed without disturbing
   their own hooks (bootstrap merges, never clobbers — verify, then say so).

Re-running `/deploy` is the recovery path: every step is idempotent (the store step always
re-reaches `monition init`/`instrument`, so missing hooks heal), so a partial deploy is fixed by
running it again with the missing flags. For an applied target, the deploying CMS clone's path is
recorded as `env.CMS_SRC` in the target's `.claude/settings.local.json` — resolve `bootstrap.sh`
through it for recovery runs and `--update` (the script never travels with the target).
