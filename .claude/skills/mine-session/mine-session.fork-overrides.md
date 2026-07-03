<!--
Fork overrides for the mine-session skill. Each `## swap <key>` section below is the
FORK-facing replacement for the `<!-- forkgen:swap <key> -->` marker in SKILL.md.
monition's regen (regen_from_cms.py) splices these in when it generates the
domain-stripped copy it ships to forks. This file is the single source for the fork's
wording — edit fork variants HERE, never in monition's package. CMS itself never
renders this file (its own skill uses the `forkgen:strip` block instead).
-->

## swap step6

6. **Routing a domain-free lesson — queue it upstream.** A transferable lesson (one
   that survives domain-stripping) is queued to `handoffs/upstream-candidates.md` for
   the mirror-back sweep that pulls it up to the shared machinery; a lesson that only
   applies to this repo stays a local row (`--reach project`, the default). A row meant
   to fire across every repo, not just where authored, is `--reach general`. Under
   the single-hub store that reach choice IS the promotion for row-shaped lessons —
   rows live in the shared hub, so queue upstream only what changes the machinery's
   prose (docs, skills, templates), not row content.
