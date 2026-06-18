---
name: codify
description: Turn a one-off correction or agreed convention into durable governance — a CLAUDE.md line, a doc rule, a prompt edit — so it sticks across sessions. Use when the user invokes /codify, says "make this a rule" / "remember this as a convention", or when a reusable rule or anti-pattern surfaces mid-conversation. Always proposes the change and gets explicit acceptance before writing.
---

# codify

You are turning a correction or convention into a durable rule. Codifying changes
future behavior, so the gate is absolute: **never write before explicit acceptance.**

1. Draft the **smallest durable edit** that captures the rule, at the narrowest scope
   that will fire: CLAUDE.md only if it applies every session (the always-on test); a
   governance doc, prompt, or rule file for anything triggered; a one-line gotcha next
   to the code it protects when it's file-local.
2. Show the proposed change verbatim — exact text, exact destination — and say what
   behavior it changes.
3. Only after the user accepts: apply it, keeping the *why* next to the rule in one
   line.
4. If the rule is mechanical (checkable by code), propose a linter check instead of or
   alongside the prose — each check's comment names the rule it shadows.
5. **Upstream-candidate test.** After the rule lands, strip this project's domain from
   it. If what survives would apply to *any* project, append one line to
   `handoffs/upstream-candidates.md` (`YYYY-MM-DD | rule | origin`) and tell the user
   it's queued for the upstream template's next sweep. Domain-specific rules stay
   local; never skip the append for a rule that passes — the queue is how lessons
   reach the template at all.
