<!-- monition-doc v0.4.0 sha256:6588d36407a57bbd29fede111c5c8330247b99a59451ace246ebdb2814005aaf -->
# Lesson routing — where a mined lesson lands

**Trigger:** read when routing a candidate lesson during mining (`/mine-session`) or
codification (`/codify`) — after the lesson is drafted, before the consent-gate
proposal. Output: a destination plus one line of reasoning, shown at the gate.

**Version:** routing v5 (2026-07-01). This is the canonical text; monition's
mine-session skill template carries a domain-stripped copy (confer resolution,
2026-06-12). Bump this version on any change to the tests and hand off to
monition once — `monition sync` propagates from there. (v2: test 4 names the three
CLAUDE.md scopes. v3: the re-injection precondition. v4: the scope+audience split
extended to skill files in test 4. v5: the mine-session canonical gains the recall
sweep in the rating pass and violation-signature authoring at row birth.) The `routing vN` token on
this line is a **parsed contract**: monition runs a dev-only parity test that reads it
and fails when its mirrored `ROUTING_VERSION` has fallen behind — so keep the
`**Version:** routing vN` format stable, and a bump here is the signal to re-strip.

**Precondition — the home must re-inject at S.** A lesson is *captured* only if its
destination is reloaded into context when S recurs: a row fires via its hook, a
CLAUDE.md line loads every session, a skill or `method/` doc is read when that task
runs, a linter runs at commit. A home that is **not** reloaded at S does not capture
the lesson no matter how well it's written — most commonly a **commit message** (or a
one-off doc nobody opens at S), which is invisible until deliberate git archaeology.
"It's in the commit" is not capture. Reject a non-re-injecting home and fall to the
next decisive test; prefer a row when nothing re-injecting fits.

Run the tests in order; the first decisive hit wins. Under uncertainty, prefer the
row (test 3): it is the only tier with an eval loop, and it retires cleanly.

1. **Behavior test.** State the lesson as "in situation S, do/avoid X." If S has no
   name yet, it is not routable — leave it in session notes; don't force a row.
2. **Owning surface.** Does an artifact already fire at S — a skill that runs then,
   a hook on that event, a prompt used for that task, a linter on that file class?
   Land the lesson inside that artifact: it is already a trigger with a payload,
   and a parallel row would duplicate its trigger with worse precision. Procedure
   changes always route here — a row can remind, but it can't restructure a skill.
   A destination with its own admission rules (caps, evidence gates, eval suites)
   keeps them — routing never bypasses the surface's own gate.
3. **Describable trigger.** No owning surface, but S compresses to an edit-path
   glob, session start, or on-demand keywords → takeaway row. This is also the
   default when evidence is thin (one occurrence, an unconfirmed hunch): rows are
   measurable and reversible; governance prose is neither. Domain-free rows get
   `--reach general` (they fire in every repo, not just where authored).
4. **Always-on.** S is "every session" → a CLAUDE.md line, only if it earns being
   paid for every session forever; otherwise make it a session_start row, which
   stays measurable. Pick the CLAUDE.md by **scope + audience**, not convenience —
   there are three, and they don't substitute:
   - **Project CLAUDE.md** (checked into a *public/forkable* repo): only rules fit to
     **ship to a forker**, who inherits this file. No personal or machine-local content.
   - **Global `~/.claude/CLAUDE.md`** (private, personal, all your repos, *not* shipped):
     personal cross-project rules — including **orientation about machinery you have
     installed** ("what the takeaway store is; what a firing/flag means when you see one").
     This content has **no** other home: it can't go in a public per-repo CLAUDE.md (a
     forker would inherit a fact about *your* setup), and a `session_start` row can't carry
     it either — firing is wired *per-repo*, so a row never fires in the bare repos this
     orientation must also serve. Global is the only layer loaded everywhere.
   - **No private, *versioned*, per-repo CLAUDE.md home exists**: a committed per-repo
     CLAUDE.md in a public/forkable repo is *public* (the forker gets it), and an
     un-committed local file is neither shared nor reliably versioned. So private,
     repo-scoped *contextual* guidance about the machinery → a **store row** (test 3),
     which is private-but-versioned (the store's own history) and fires by reach/origin.

   The same **scope + audience** split governs skill *files*, not just CLAUDE.md lines:
   a skill that depends on machine-local infrastructure (an absolute path, a personal
   store, an installed adviser) belongs in the **global** skill layer (`~/.claude/skills/`),
   not a forkable repo's `.claude/skills/`. Global takes precedence over project-local, so
   the enriched copy wins automatically — no per-repo coordination, and no machine-local
   detail leaks into what a forker inherits.
5. **Mechanical shadow.** If violating X is mechanically checkable and unambiguous,
   add a linter check (ERROR) or hook alongside whatever prose landed above;
   ambiguous shadows are WARN. For semantic artifacts — shipped prompts, rubrics,
   judge criteria — the project's eval suite plays the linter's role: a lesson
   landing in one must pass it before the consent gate closes.

**Re-route at audit cadence.** A row with a strong helpful record and a stable
footprint folds into its owning surface and is retired; always-on prose that stops
earning its line demotes to a row or dies. Routing is never one-shot.

Every landing — row or governance edit — goes through the consent gate, and the
proposal names which test decided.
