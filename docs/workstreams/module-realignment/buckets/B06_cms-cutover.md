# Bucket B06: CMS cutover

Parent: ../workstream.md
State: done
Goal for session: CMS runs on the module; originals deleted; data intact.
Target duration: 30 min
Context budget: Read parent + this bucket + required touchpoints only.

## Conceptual mapping

- All cross-repo mutations in one consented, verifiable session. Consent:
  confer thread "2026-06-11 confer takeaway-machinery-ownership" + spec
  §Consent path — already granted; cite, don't renegotiate.

## Tasks

- [ ] Pre-flight: `uv tool install --editable <monition>` done;
      monition pytest green; capture CMS store content hash (working-set
      content, per the hardened read-only test's method).
- [ ] `git mv takeaways monition` in CMS; update path references
      (`.githooks/pre-commit` store-dir test, any doc mentions).
- [ ] Rewire `.claude/settings.json`: both hook entries → the canonical
      guarded command strings (B03).
- [ ] Rewire `.githooks/pre-commit`: dump line → `monition dump` (+ staged
      path `monition/dump.sql`); lint line untouched.
- [ ] Delete `tools/takeaway.py`, `tools/takeaway_fire.py`,
      `tools/takeaway_brief.py`.
- [ ] CMS doc edits (consented): `docs/DESIGN.md` (seams + upstream contract:
      machinery via version-bump, tier-0 self-contained, graduation =
      `monition init --adopt`), `method/takeaway-store.md` (machinery now the
      Monition module; store semantics text stays), `method/instantiate.md`
      (+ tier-0 ships in payload; graduation step note).
- [ ] Smoke firing: sample PreToolUse JSON for a payload-matching path piped
      to the guarded command → injection block appears, firing row written;
      then `monition report <CMS>/monition` runs clean.
- [ ] Verify: store content hash unchanged by everything except the smoke
      firing row (assert exact delta); uninstall test against the real
      settings entry (PATH-stripped sh) silent.

## Required touchpoints

- `<CMS>/.githooks/pre-commit`  (full read, 10 lines)  both rewire points
- `<CMS>/.claude/settings.json`  (full read)  hook rewire surface
- `<CMS>/docs/DESIGN.md`  grep -n "seam\|upstream\|self-contained" then bounded reads  the consented edit surface
- `<CMS>/method/takeaway-store.md`  grep -n "^##" then bounded reads of machinery-describing sections  consented edit surface
- `<CMS>/method/instantiate.md`  grep -n "^##" then the protocol-steps section  +1 step edit
- `docs/specs/2026-06-11-module-realignment.md`  §CMS cutover checklist  the authoritative task list

## Conditional touchpoints

- `<CMS>/CLAUDE.md` — read only if it references takeaway tools/paths.
- The cross-project confer thread archive — only if an edit's consent scope is questioned.

## Do-not-read / avoid

- Tier-0 payload authoring in the CMS payload — separate CMS-session work;
  cutover does not block on it (tier 0 affects *future* instantiations).
- `dump.sql` content — derived; regenerates at next commit.

## Design direction

- Order matters: rewire hooks *before* deleting tools (no window where the
  PreToolUse matcher points at a deleted file); `git mv` before rewiring so
  command strings reference the final store path.
- This bucket breaks the "nothing writes to <CMS>" invariant by
  design — it is the only bucket allowed to, and the smoke-firing row is the
  only permitted store delta.
- One CMS commit for the whole cutover, message citing the spec; CMS's own
  pre-commit (now running `monition dump`) is itself part of the validation.

## Validation

- Smoke firing fires + logs; `monition report` clean; content-hash delta ==
  smoke firing row only; uninstall test silent; CMS commit passes its own
  pre-commit (lint + `monition dump`).
- Expected: CMS fully on the module; zero takeaway data lost.

## Done criteria

- [ ] Tasks complete.
- [ ] Validation passes.
- [ ] Bucket `Updates` section records discoveries/gotchas/handoff.
- [ ] Parent workstream progress updated (workstream done; road.md Phase 2 exit
      check).

## Updates

- [2026-06-11 19:55] Created. Handoff: none yet. Gotchas: none yet.
- [2026-06-11] ~90% done; **blocked on user consent for the settings.json hook
  rewire** (Claude Code's permission classifier requires the user's own say-so
  to install auto-executing hooks in another repo — spec-file consent doesn't
  count; correct call, not renegotiated).
  Done: install (no uv on machine → equivalent global editable: `.venv/bin/pip
  install -e .` + `~/.local/bin/monition` symlink to the venv entry point —
  edits still propagate); pre-flight content hash `60d648d4…` (6 takeaways,
  8 firings); `git mv takeaways monition` (+ .gitignore path); pre-commit
  rewired to guarded `monition dump` + `monition/dump.sql`, lint half
  untouched; all consented doc edits (CLAUDE.md, DESIGN.md store bullet +
  upstream-contract machinery exception, method/takeaway-store.md full sweep
  + tier-0 Wiring rewrite, instantiate.md +1 step, mine-session skill →
  monition commands); reference sweep clean; hooks.py hint strings →
  `monition show/rate` (byte-match tests normalize this one divergence);
  68 tests green, both linters 0.
  Validation already passed against the LIVE store: smoke firing via the
  guarded command (t1/f16, session `b06-cutover-smoke`, new hint text);
  `monition report` clean; hash-minus-smoke-row == pre-flight hash exactly
  (zero data loss); uninstall test vs the real command string silent (no log
  dir created); CMS pre-commit runs green end-to-end (after fixing a lint hit:
  tilde-relative links in markdown are flagged broken — use plain text paths in CMS docs).
  Interim safety: tools/takeaway*.py RESTORED so the old settings.json hooks
  keep failing open (verified silent exit 0 against the moved store — python3
  on a deleted file would exit 2 and block PreToolUse).
  Completion (2026-06-11, user explicitly consented to settings.json write):
  settings.json applied from staged proposed file; git rm tools/takeaway*.py;
  CMS commit 1b8dda9 passed pre-commit (lint + monition dump regenerated
  monition/dump.sql) — 13 files, 378 deletions. Post-cutover: 33 Monition
  tests pass, 35 characterization/hook byte-match tests skip cleanly (oracle
  tools deleted by design). Phase 2 complete; Phase 3 is next.
