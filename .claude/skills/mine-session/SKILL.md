<!-- monition-skill v0.3.0 sha256:1555ff185ae34522b3eaedf8a6cb25054c50d842ca56e9dd9cfe382806047eb4 -->
---
name: mine-session
description: End-of-session mining pass — review this session for reusable lessons and house them in the Monition store with explicit triggers. Use when the user invokes /mine-session, says "mine this session" / "save the takeaways", or is wrapping up a session that hit gotchas worth keeping. NOT for mid-session one-offs the user wants codified immediately.
---

# mine-session

You are mining this session for takeaways. The store's semantics live in the
Monition store contract (`docs/contracts/takeaway-store.md` in the monition
repo) — read it before your first run in a session.

0. **Rate what fired (the eval pass) — run this first, before mining.** The store's
   fire/suppress gate trains on rated firings, and fire-time rating collects ~none (a
   session mid-task won't stop to grade an injection). So rate here, **warm**, with the
   session still in context — LLM-auto, evidence-gated, bulk-confirmed.
   - **Pull the worklist, highest-value first:**
     `monition export-firings --unrated-only --session "$CLAUDE_CODE_SESSION_ID" --order-by priority`.
     `--order-by priority` ranks by `rating_priority` (traffic × distance-to-fire/suppress
     boundary; cold-start rows rank high) — monition owns the math, you only consume the
     order. If `$CLAUDE_CODE_SESSION_ID` is unset, scope with `--since <today>` instead.
     **Fail open:** if the `monition` CLI or live store is absent, skip the pass entirely.
   - **Walk the top N** (a budget — ~15; head, not tail; stop when `rating_priority` drops
     off or evidence runs out). For each firing, look in the session for evidence the
     injected `one_liner` (it fired at `trigger_context` / `situation`) actually mattered:
     it **changed an action**, was **visibly ignored**, or was **contradicted** by what
     you did.
   - **Propose a rating ONLY where the session evidences it**, with a mandatory one-line
     citation of *what in this session* shows it. **No evidence → no rating** — never pad
     to hit coverage; an unsupported `helpful` is directional bias in the eval set, worse
     than a label missing at random. (A cold mine — rating a session you didn't live
     through — evidences little and correctly proposes ~0.)
   - **Present ONE batch for bulk confirm:** all proposed ratings at once, each line
     `<firing_id> helpful|noise — <one-line evidence>`; the user accepts the batch in a
     single gesture with per-line veto/flip. A rating is reversible eval data, so this is
     a **lighter gate** than proposing a new row.
   - **Apply the accepted lines:** `monition rate <firing_id> helpful|noise` for each.
     These ride into the `monition commit` at step 5.

   Then mine for new lessons:

1. Review the session for lessons that are **reusable** (would recur) and
   **non-obvious** (a future session wouldn't rediscover them cheaply). Mistakes,
   gotchas, corrections, and confirmed preferences all qualify; routine work does not.
2. **Route each candidate before drafting** (routing v1 — from CMS
   `method/lesson-routing.md`; run in order, first decisive test wins; under
   uncertainty prefer the row — it is the only tier with an eval loop and it
   retires cleanly):
   - *Behavior test:* can't state it as "in situation S, do/avoid X" with a
     nameable S → not routable; leave it in session notes.
   - *Owning surface:* an artifact that already fires at S (a skill that runs
     then, a hook on that event, a prompt for that task, a linter on those files,
     or a governance surface named in this repo's CLAUDE.md) gets the edit
     directly — a parallel row duplicates its trigger with worse precision.
     Procedure changes always land here. Destinations with their own admission
     rules keep them.
   - *Describable trigger, no owner:* takeaway row (`monition add`) — also the
     default when evidence is thin.
   - *Every session:* a CLAUDE.md line, only if it earns being paid every
     session forever.
   - *Mechanical shadow:* checkable-and-unambiguous violations also get a linter
     check alongside whatever prose landed above; for semantic artifacts the
     host's eval suite plays that role — the lesson must pass it before consent
     closes.

   Every landing goes through the consent gate; the proposal names the deciding test.
3. For each candidate routed to a row, draft the full row: `kind`
   (gotcha/rule/preference), `trigger_kind` + `trigger_spec` (*when should this
   fire?* — the design decision; edit_path glob, session_start, or on_demand),
   `one_liner` (what gets injected — make it a trap-warning, not a description),
   `full_content` (the why + the workaround), `source` (session/commit).
4. **Show the proposed landings and get acceptance before applying** (consent gate).
5. Insert accepted rows (`monition add …`), then snapshot the store:
   `monition commit -m "mine: <session topic>"`.
6. If a takeaway is domain-free enough to apply beyond this repo, add it with
   `--reach general` — general-reach rows fire in every repo, not just this one.
   The default `--reach project` fires only where it was authored.
