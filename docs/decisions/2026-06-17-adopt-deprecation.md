---
status: decided
---
# 2026-06-17 · `--adopt` flag deprecation posture

**Context.** `monition init --adopt <file>` imports a tier-0 lessons file as part
of `init`. Tier-0 (the hand-crafted JSON/YAML lessons format) is being removed
upstream in CMS; new projects start from `monition init` and add rows via
`monition add` / `/mine-session`. The SQLite-default refactor is the natural
moment to revisit this path.

**Decision.** Keep `--adopt` in the CLI (no breakage to existing callers) but
remove it from the documented path. Standalone `monition init` (no flags) is the
documented and tested onboarding path; `--adopt` is an unlisted escape hatch for
anyone still holding tier-0 files.

**Rationale.**
- Dropping the flag would break anyone running `monition init --adopt ...` in
  automation; the cost is higher than keeping it silent.
- Documenting it as the path would imply tier-0 is a supported input format, which
  contradicts the upstream removal direction.
- The `adopt` sub-command (`monition adopt <file>`) is unaffected; it operates on
  an already-initialized store and has no dependency on the Dolt/SQLite backend
  choice.
