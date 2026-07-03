---
status: decided
---
# 2026-07-02 · A prompt-level boilerplate gate in `prompt_hook`, extracted from the paused cascade

Status: decided and implemented. Project-internal (pure hook machinery — no
cross-repo confer). Supersedes nothing; narrows a scope already staked out by
`docs/workstreams/relevance-cascade/buckets/B03_cascade-runtime.md` (the `L0`
admissibility layer, "regex non-prompt / `<task-notification>`") and
`B04_hook-integration.md` (wiring it into `prompt_hook`'s passive path) — that
whole workstream is `PAUSED 2026-06-21` on the **learned `L2′` head's** B02
NO-GO (honest LORO AUC ~0.67, failed the usefulness gate — see
`docs/workstreams/relevance-cascade/workstream.md`). `L0` itself was never
evaluated or refuted; it is orthogonal to the failed head and evidenced on its
own, so it lands standalone rather than waiting on the paused workstream to
resume.

**Supersession audit:** grepped `docs/decisions/` for prior calls this could
contradict or supersede. None found — closest prior art is
`2026-06-18-noise-targets-the-filter-not-the-gate.md` ("a noise rating targets
the Filter, not the Gate"), which this decision is *consistent with and an
instance of*: the boilerplate gate is a Filter-stage fix (stop matching before
the row ever reaches the Gate) responding to noise that traces to
mis-targeted prompts, not bad rows — it does not amend or supersede that
decision. The only other doc naming this exact mechanism is
`docs/workstreams/relevance-cascade/*` (a workstream file, not a
`docs/decisions/` entry — no `status:` field to update there); its `PAUSED`/
`NO-GO` status is unchanged by this decision, see "Status" note above.

## Question

`prompt_hook` (`src/monition/hooks.py`) treats every `UserPromptSubmit` payload
as a real user question and runs it through `on_demand_match`. Some payloads
are not — a Task-tool subagent's completion notice re-enters the transcript as
if it were typed by the user, carrying real prose (a `<summary>`, a `<result>`
dump) that lexically/semantically matches stored rows just as well as a real
prompt does. On a broad multi-subagent session this saturates the injection
cap every turn, and worse: whoever clears the cap by rating firings ends up
batch-rating a whole cap's worth of unrelated rows "noise" because the *shared
cause* was an unmatchable notification, not any one row being wrong. Rows
t91–t98 in the hub carry exactly this pattern (see evidence below). Should
`prompt_hook` filter these out before matching, and on what basis?

## Decision

Add a **prefix gate**, checked before `on_demand_match` runs: a prompt whose
stripped text *starts with* an evidenced harness-boilerplate opening is
skipped entirely — no lexical/semantic match, no firing, no decision row. The
skip is logged to the same state log the `[capped]` line already uses
(`[boilerplate] skipped harness-generated prompt session=<id>`), so it is
quiet but auditable, never silent.

`_BOILERPLATE_PREFIXES` currently holds one entry:

- `"<task-notification>"` — evidenced directly: 837 of 5,878 `on_demand`
  firings in the hub (`/home/bolun/projects/brain2/monition`, live Dolt store,
  read via `dolt sql`) carry a `trigger_context`/`situation` that opens with
  this exact tag, all sharing the fixed `<task-id>` / `<tool-use-id>` /
  `<output-file>` / `<status>` / `<summary>` / `<note>` / `<result>` shape a
  Task-tool completion notice always has. Rows t91–t98 show noise ratings
  landing on firing batches whose shared `trigger_context` is this tag
  (confirmed per-row via `dolt sql` against `firings.outcome` grouped by
  `takeaway_id`).

**Deliberately a prefix check, not a contains check.** A prompt that merely
*mentions* `<task-notification>` mid-text — a human pasting an example, asking
about the format — is real user content and must still be matched; only a
leading match is boilerplate. Covered by
`test_human_prompt_mentioning_task_notification_still_matches` in
`tests/test_prompt_hook.py`.

## Patterns investigated and rejected for lack of evidence

Before adding a second prefix, the same hub was queried for other repeatable
harness shapes. None cleared the bar (a real, repeatable *opening* string,
not a guess):

- **`<command-name>/clear</command-name>` inside a "Summarise the session
  transcript in this message… # Session trace…" dump** — real, but only 2
  distinct sessions / 6 firings, and no *stable prefix* (the opening line
  varies by session id and turn count). Likely a diagnostic/summarization
  script constructing a meta-prompt, not a fixed harness notification shape.
  Left ungated; revisit if it recurs with a fixed opening.
- **`<local-command-*>`, `<bash-*>`, `<monitor-*>`, `Caveat:`, "This session is
  being continued from a previous conversation"** — zero occurrences in the
  hub's `on_demand` firings. No evidence to act on.
- Everything else with a leading `<...>` tag in the hub *is* `<task-notification>`
  — no other tag prefix appears at all (`dolt sql` distinct-prefix scan).

## Why a prefix skip, not a candidate-level filter

The paused cascade's `L0` was scoped as one stage among several
(admissibility → learned relevance), gating *candidates* after
`on_demand_match` already ran. Here there is nothing left to gate: a
wholly-harness-generated prompt has no candidates worth matching in the first
place, so the cheaper and more honest fix is to never call `on_demand_match`
at all — no wasted lexical/semantic work, and no firing/decision rows exist
to later mis-attribute as noise. This is strictly narrower than the cascade's
scope and does not depend on `L2′` (the piece that failed its gate).

## Anti-goals

- Do **not** grow this into a generic "looks systemy" classifier. Every entry
  in `_BOILERPLATE_PREFIXES` must cite a real, repeated opening string from
  live firing data, per the comment above the constant in `hooks.py`.
- Do **not** silence the skip. It logs through the same `hook-errors.log`
  convention as `[capped]` specifically so a quiet failure mode doesn't become
  an invisible one.
- Do **not** conflate this with the relevance-cascade workstream's revival —
  that workstream stays paused on `L2′`; this decision does not reopen it.

## Rating-candidate priority (companion investigation, no change made)

The same audit that surfaced t91–t98 also asked whether unrated-firing
candidates for the `/mine-session` rating pass are already ordered by firing
volume (top-firers first). They are: `export_records()`
(`src/monition/export.py:105`) computes `rating_priority = fire_count ×
boundary_closeness` per row (cold-start rows at `closeness=1.0`, so raw
traffic dominates their ordering) and `--order-by priority` (wired in
`cli.py`, already the prescribed pull command in the `mine-session` skill
template, `_generated_cms.py:35`) sorts `unrated`-filtered candidates by it,
descending. This already lands top-firers first regardless of the unrated
filter, since `fire_count`/`rated_count` are computed store-wide, not over the
filtered slice. No change made — this predates the current session
(shipped in Phase 7, commit `d65e9dc`) and already does what was asked.

## Update — 2026-07-02, post-decision helpful-side check

The evidence above queried only the noise side of the predicate (t91–t98's noise
batches). Querying the *good* outcomes under the same predicate (`trigger_context LIKE
'<task-notification>%'`): **756 unrated, 57 noise, 24 helpful** — i.e. ~30% of the
*rated* firings in the gated class were rated helpful (store-wide rated split: ~52/48).
So the gate has measurable collateral: a row injected while the main agent processes a
subagent result can genuinely help (verified live the same day: t33 fired on a
task-notification turn and was rated helpful for matching the audit finding being
processed). The gate stands — 24 helpful across 837 class firings (~3%) does not cover
the class's cost (injection-cap saturation, batch mis-ratings, per-notification hook
latency), and most such rows re-fire on the session's real prompts anyway — but the
post-gate re-measurement should weigh the lost-helpful channel, not just the volume
drop. (Check prompted by hub row t92: never call a shape-defined subset safe-to-drop
from the bad side alone.)
