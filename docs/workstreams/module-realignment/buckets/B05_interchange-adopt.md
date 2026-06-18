# Bucket B05: Interchange format + `init --adopt`

Parent: ../workstream.md
State: done
Goal for session: tier-0 lessons import mechanically; format owned by contract.
Target duration: 30 min
Context budget: Read parent + this bucket + required touchpoints only.

## Conceptual mapping

- The CMS amendment (spec decision 13): one schema owner, two serializations.
  Format definition and its only consumer (`--adopt`) must land together so the
  format ships validated, not just specced.

## Data contract / provenance

- Output: new contract section "Tier-0 interchange format" in
  `docs/contracts/takeaway-store.md` — consumed by the CMS payload (cites it,
  never duplicates) and by `init --adopt`.
- Inputs: a tier-0 markdown lessons file — structured blocks carrying the
  takeaway fields (`kind`, `trigger_kind`, `trigger_spec`, `one_liner`,
  `full_content`, `scope`, `source`). No `status`/`mirror` (defaults apply);
  no ids (assigned at import).
- Provenance: imported rows get `source` from the block (never substituted);
  adoption is one-way — the file is not updated from the store afterward.
- Validation: round-trip fixture (see Validation).

## Tasks

- [ ] Write the contract section: block syntax, required/optional fields, field
      domains by reference to the existing tables (cite, don't restate),
      `trigger_spec` carries the same fnmatch dialect, unknown extra keys
      tolerated-and-ignored (mirror of the additive-column rule), malformed
      blocks rejected with counts (never silently skipped).
- [ ] Implement `monition init --adopt <file>` (and `monition adopt <file>` for
      an existing store): parse blocks → insert via B02's add path → report
      imported/rejected counts with per-rejection reasons.
- [ ] Fixture round-trip test: tier-0 fixture file → adopt → store rows match
      expected exactly (every field); malformed-block fixture → rejected with
      named reasons, valid siblings still imported; conservation check:
      imported + rejected == blocks parsed.

## Required touchpoints

- `docs/contracts/takeaway-store.md`  grep -n "^##" then §takeaways per-field table + §Versioning  field domains the format references; where the new section slots
- `docs/specs/2026-06-11-module-realignment.md`  bounded read of decision 13  the amendment being implemented (incl. frozen-ness caveat)
- `src/monition/`  grep -n "def add\|def _insert" src/monition/*.py  B02's add path signature (verify at implementation time — B02 names it)

## Conditional touchpoints

- Confer thread archive (in the cross-project store) — read only if the format's
  scope vs the consuming project's responsibilities seems ambiguous.

## Do-not-read / avoid

- Writing the tier-0 *executor* or payload content — CMS-session work (parent
  Non-Goals). This bucket ships format + importer only.

## Design direction

- Report first (contract check): the new section must not alter any existing
  contract semantics; validation = diff shows additions only.
- Format design constraint (load-bearing, from the confer resolution): the
  format must stay parseable by a *frozen* tier-0 executor — prefer dumb,
  line-oriented structure over anything needing a real markdown parser.
- Rejection assertion level: exact — reasons as stable strings, counts asserted.

## Validation

- `.venv/bin/pytest` green including round-trip, rejection, and conservation
  tests.
- Expected: contract diff is purely additive; adopt fixture imports cleanly.

## Done criteria

- [x] Tasks complete.
- [x] Validation passes.
- [x] Bucket `Updates` section records discoveries/gotchas/handoff.
- [x] Parent workstream progress updated.

## Updates

- [2026-06-11 19:55] Created. Handoff: none yet. Gotchas: none yet.
- [2026-06-11] Done. Contract gains §"Tier-0 interchange format (lessons
  file)" (before §Excluded inputs; purely additive — diff verified): blocks
  start at a line exactly `## takeaway`; `key: value` headers (first-colon
  split, trimmed); `full_content:` switches to verbatim-until-next-block;
  unknown keys ignored (additive-rule mirror); prose outside blocks ignored;
  required kind/trigger_kind/one_liner with domains cited from the takeaways
  table; status/mirror/id/created absent by design.
  `src/monition/adopt.py`: `parse_blocks` / `check_block` / `adopt` — inserts
  via B02's `WriteStore.add` (so adopted rows go through the same SQL path the
  oracle defined), per-block stable rejection strings ("missing required
  field: <k>", "invalid kind: <v>", "invalid trigger_kind: <v>"), conservation
  asserted in code. CLI: `monition adopt <file> [--store]` and `monition init
  --adopt <file>` (init then import; dry-run prints "would adopt").
  Tests (4): parse shapes incl. multi-paragraph full_content + ignored unknown
  key; exact rejection reasons; round-trip — 2 imported with every field
  asserted (defaults active/none), 3 rejected with named reasons, valid
  siblings imported; adopted edit_path row actually fires through
  `WriteStore.match` (fnmatch dialect end-to-end). 68 total green, lint 0.
  Gotchas: (1) a `full_content` line that is exactly `## takeaway` cannot be
  expressed — block end wins; acceptable for the frozen dialect, documented by
  the syntax itself. (2) trigger_spec is carried verbatim including interior
  spaces ("payload/*, schema/*") — matching strips per-pattern at match time,
  so adopted specs need no normalization.
