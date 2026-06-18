# Bucket B04: On-Demand Embedding Retrieval

Parent: ../workstream.md
State: done
Goal for session: Hybrid lexical+embedding matching behind `on_demand_match`.
Target duration: 30 min
Context budget: Read parent + this bucket + required touchpoints only.

## Conceptual mapping

Extends B03's lexical `on_demand_match` with embedding similarity. The interface
is unchanged; the implementation adds a semantic pass over rows the lexical pass
missed. Decisions resolved 2026-06-12 with the user: backend is **fastembed**
(ONNX local inference, optional extra — no torch), cache is a **derivable JSON
sidecar in XDG cache**, never in the Dolt store.

## Data contract / provenance

- Inputs: `query: str` (caller's free text); per-row embed text =
  `one_liner + " " + trigger_spec` (both from active on_demand takeaways).
- Outputs: same JSON shape as B03 — list of `{id, one_liner}`; lexical hits
  first (B03 order), then semantic-only hits ranked by similarity descending.
- Provenance: embedding cache at `$XDG_CACHE_HOME/monition/embed-cache.json`
  keyed by `sha256(model_name :: text)` — regenerable, deletable, never store
  data; the contract does not change shape, only the on_demand matching note.
- Validation: with embeddings unavailable (not installed, model fails, IO
  error), output must be byte-identical to B03 lexical-only behavior.

## Tasks

- [ ] `src/monition/embed.py`: `MODEL_NAME`, `SIM_THRESHOLD = 0.6` (module
  constants, monkeypatchable), `embed_texts` (cache-through), `cosine`,
  `semantic_scores(query, texts)`; lazy fastembed import inside the raw call.
- [ ] `store_write.on_demand_match`: semantic pass over non-lexical rows inside
  a `try/except Exception` — fail-open to lexical-only.
- [ ] `pyproject.toml`: `[project.optional-dependencies] embed = ["fastembed>=0.3"]`.
- [ ] Contract: extend the on_demand bullet — hybrid matching when the embed
  extra is present, lexical-only degradation otherwise.
- [ ] Tests (`tests/test_embed.py`): fake deterministic backend via monkeypatch
  on the raw-embed seam; hybrid adds semantic hit; lexical-first ordering;
  threshold cutoff; fail-open equals lexical; cache hit skips backend; dedup
  applies to semantic hits; real-model test `skipif` fastembed absent.

## Required touchpoints

- `src/monition/store_write.py`  `grep -n "def on_demand_match" -A 14`  on_demand_match
  The B03 lexical pass this wraps.
- `tests/test_on_demand.py`  full file
  B03 test patterns + fixture rows to extend.

## Do-not-read / avoid

- `src/monition/hooks.py` — on_demand is not hook-path; no executor wiring here.
- `src/monition/score.py` — retrieval, not scoring.

## Design direction

- Core invariant: the text embedded at match time is the same text a future
  evaluation would embed (`one_liner + trigger_spec`) — no separate assess/eval
  paths.
- Fail-open wraps the entire semantic pass, import included. No logging
  dependency on hooks.py (would be circular); silent degradation is acceptable
  because lexical output is still a valid result.
- Cosine in pure Python — corpus is tens of rows; no numpy dependency.
- Cache is load-all/save-all JSON; fine at this scale, revisit only if measured.

## Validation

- `pytest tests/test_embed.py` and full suite — green without fastembed installed.
- Lint clean.
- Expected: query semantically near keywords but not containing them → hit via
  the fake backend test; all B03 tests unchanged.

## Done criteria

- [ ] Tasks complete.
- [ ] Validation passes.
- [ ] Bucket `Updates` section records discoveries/gotchas/handoff.
- [ ] Parent workstream progress updated.

## Updates

- [2026-06-12] Created as deferred. Promote to `later` when embedding model decision is made.
- [2026-06-12] Promoted to active: user chose to build ahead of need (the exercise
  is the point). Backend decision: fastembed via consent question.
- [2026-06-12] Done. 79 passed (78 + real-model test), 35 skipped, lint clean.
  `embed.py` (MODEL_NAME=BAAI/bge-small-en-v1.5, SIM_THRESHOLD=0.6, JSON
  cache-through in XDG cache); hybrid pass in on_demand_match; `monition[embed]`
  extra; contract on_demand bullet now describes hybrid + degradation.
  Gotcha: installing fastembed flipped test_on_demand.py::test_match_no_hit —
  the real model scores "deployment rollback" ≥0.6 against the migration row,
  so lexical-contract tests must pin semantic_scores off (autouse fixture).
  Test seams: fake `_embed_raw` for embed internals, fake `semantic_scores`
  for hybrid logic; real model behind skipif(fastembed absent).
