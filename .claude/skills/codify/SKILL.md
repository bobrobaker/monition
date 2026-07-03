---
name: codify
description: Turn a one-off correction or agreed convention into durable governance, routed to the right layer — personal config, this project, or the shared system. Use when the user invokes /codify, says "make this a rule" / "remember this as a convention", or when a reusable rule or anti-pattern surfaces mid-conversation. Proposes and gets acceptance before writing.
---

# codify

You are turning a correction or convention into durable governance. Codifying changes
future behavior, so the gate is absolute: **never write before explicit acceptance.**

1. **Classify the layer** — where does this belong? First decisive test wins:
   - **Personal** — it encodes how *you* work (taste, workflow) or depends on your
     environment, and a stranger who forked this repo would be wrong to inherit it.
     → your global `~/.claude/` (a CLAUDE.md line, a global skill, a hook).
     *Test: "would a forker be wrong to inherit this?"*
   - **System (general)** — it improves the context-management system itself and holds
     for any project using it (survives stripping both your domain and your
     environment). → the reference implementation: a shared skill, a `method/` doc, or
     the linter. Anything touching cross-project state lands behind the landing-zone
     resolver (`$CMS_LANDING_ZONE`, else in-repo `landing/`) so it ships generic, not
     wired to your vault. *Test: the domain-and-environment strip.*
   - **This project** — neither; specific to the repo you're in. → step 2.

2. **Route to the form** within that layer — run the route-to-form ladder in
   `method/lesson-routing.md` (tests 2–4, first decisive wins): an **owning surface**
   that already fires at the right moment (a skill's lean `SKILL.md` gate or a
   supporting file in its dir, a hook, a prompt, a linter, a governance surface named
   in CLAUDE.md §Map — procedure changes land here, and a destination keeps its own
   admission rules); else a **describable-trigger** takeaway row (Monition is a
   declared dependency, always present); else an **every-session** CLAUDE.md line. codify
   adds one project-local tier the mining ladder lacks: **file-local** — a one-line
   gotcha next to the code it protects. Then draft the **smallest durable edit** at that
   destination.

3. **Show it verbatim, then gate by blast radius.** Show the exact text, exact
   destination, and what behavior changes. A personal or project-local edit needs the
   user's ok. An edit to the **shared reference implementation ships to everyone who
   forks it** — confirm it explicitly; never write it on inference.

4. **Apply only after acceptance**, keeping the *why* on the same line as the rule.

5. **Mechanical?** Propose a linter check instead of or alongside the prose — each
   check's comment names the rule it shadows.

6. **Cross-layer propagation.** If the rule is *system-general* but you're in a project
   that isn't the reference implementation, queue it — append `YYYY-MM-DD | rule |
   origin` to the landing zone's `upstream-candidates.md` (`$CMS_LANDING_ZONE`, else the
   repo's `handoffs/`) for the mirror-back sweep. When you *are* in the reference
   implementation, apply directly. The queue is how a lesson reaches the system at all.
