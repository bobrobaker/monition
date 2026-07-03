# Bucket B04: Exit eval — before/after vs 2026-07-02 baseline

Parent: ../workstream.md
State: done
Goal for session: prove targets met; close Phase 8 or name the gap.
Target duration: 20 min
Context budget: Read parent + this bucket + required touchpoints only.

## Conceptual mapping

- Pure measurement + doc closure: run the B01 bench on the final code, compare
  against the baseline in the parent's Global Implementation Notes, verify the
  fail-open chain, update road.md Phase 8 status.

## Tasks

- [ ] `tools/hook_bench.py` on a fresh hub scratch copy, warm daemons: ≥5
      prompt-hook + ≥5 fire-hook events; report per-phase medians.
- [ ] Compare vs baseline (prompt 2.8–3.4s / fire 1.3–1.6s): exit bar is
      prompt ≤0.5s AND fire ≤0.3s. If missed, name which phase holds the gap and
      whether the parked daemon option gets un-parked — report, don't build.
- [ ] Fail-open verification: kill the scratch sql-server mid-run → hooks
      complete via CLI path; absent store → silent return (existing behavior).
- [ ] Sanity-check real-session feel: one interactive prompt in this repo,
      observe injection latency subjectively + MONITION_TRACE=1 stderr readout.
- [ ] Update `docs/road.md` Phase 8 Status (+ `### Next` line if conventions
      ask); parent workstream Progress → complete.

## Required touchpoints

- `docs/workstreams/hook-hot-path/workstream.md  Global Implementation Notes`
  The baseline numbers being compared against.
- `buckets/B01–B03  grep "## Updates" <file>, then read from that offset`
  Interim bench numbers + gotchas only — not the full buckets.
- `docs/road.md  grep -n "Phase 8" docs/road.md`
  The status line and exit criterion being closed.

## Design direction

- Measured medians, not single runs; report the distribution if variance >20%.
- A miss is a finding, not a failure: report the residual breakdown honestly
  (python ~130ms + N×connect + match math is the modeled floor ≈ 0.3–0.5s).
- The scratch store spawns its own sql-server when the machine-wide flag is on —
  bench must stop it on teardown (B01's harness owns this; verify it happened:
  no `dolt sql-server` with cwd under the scratch path survives the run).

## Validation

- Bench artifacts (trace JSONLs + summary) attached/quoted in Updates.
- Exit bar met, or gap named with next-lever recommendation.

## Done criteria

- [ ] Tasks complete.
- [ ] Validation passes.
- [ ] Bucket `Updates` section records discoveries/gotchas/handoff.
- [ ] Parent workstream progress updated; road.md Phase 8 status updated.

## Updates

- [2026-07-02 16:25] Created. Handoff: none yet. Gotchas: none yet.
- [2026-07-02 17:55] DONE. Exit bar MET: warm medians (tools/hook_bench.py,
  hub-sized scratch, n=5) prompt-hook **431ms ≤ 500ms**, fire-hook **52ms ≤
  300ms** — vs 2026-07-02 baseline 2.8–3.4s / 1.3–1.6s (6.5×/27×). Residual
  prompt-hook: disclosed 256ms (full firings read + scoring + batched wire
  writes), embed:cache_loaded 105ms, store_opened 38ms. Fail-open chain proven
  by test (test_server_killed_midway_falls_back: live server killed under an
  established wire connection → CLI serves; absent-store silent return
  pre-existing). No scratch sql-server survived any bench run (verified via
  /proc cwd scan). Suite 320 passed with wire, targeted 28 passed/5 skipped
  without. road.md Phase 8 → complete. Follow-up candidates (not needed for
  exit): narrow the firings read (WHERE takeaway_id IN — verify score()
  internals first), embed vector-cache load (105ms) if sub-300ms prompt-hook
  is ever wanted.
