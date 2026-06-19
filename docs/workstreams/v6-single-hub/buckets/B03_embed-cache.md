# Bucket B03: managed embed cache + pre-fetch (the actual semantic unblock)

Parent: ../workstream.md
State: done
Goal for session: Stop weights downloading to ephemeral /tmp inside the blocking hook.
Target duration: 20 min
Context budget: Read parent + this bucket + required touchpoints only.

## Conceptual mapping

Single concern, single file (`embed.py`): semantic matching is *silently dead* because
`TextEmbedding(model_name=…)` defaults its weights cache to ephemeral `/tmp/fastembed_cache`
— re-downloaded every cold hook, under the 30s `UserPromptSubmit` timeout, so it never
completes. The fix is a managed XDG cache_dir + pre-fetch off the hook path. Independent of
the schema work (no `current_repo`, no columns). Charter step 9.

## Tasks

- [ ] `embed.py` `_embed_raw`: pass `TextEmbedding(model_name=MODEL_NAME, cache_dir=<managed
  XDG path>)`. Use `$XDG_CACHE_HOME/monition/fastembed` (fall back to `~/.cache/monition/
  fastembed`). Create the dir if missing.
- [ ] Pre-fetch weights off the hook path: add an `embed-warm` verb (or fold into
  `init`/`sync`) that instantiates `TextEmbedding` once so weights land in the managed cache.
  **Hooks must never download lazily** (cold subprocess, blocking, timeout).
- [ ] Wire the pre-fetch into `init`/`sync` so a fresh install stages weights once.

## Required touchpoints

- `src/monition/embed.py`  whole file (74 lines)  `_embed_raw`, `MODEL_NAME`, lazy import
  The only edit surface; small enough to read fully.
- `src/monition/init_sync.py`  `grep -n "def init\|def sync\|def cmd_\|act("`  init/sync wiring
  Where to stage the pre-fetch (mirror the existing `act(...)` step style).
- `src/monition/cli.py`  `grep -n "add_parser"`  verb registration
  If adding an `embed-warm` verb, register it here.

## Conditional touchpoints

- `tests/test_embed.py`  `grep -n "cache_dir\|TextEmbedding\|tmp"`
  Read if a test asserts the cache location or stubs TextEmbedding — the kwarg change may shift it.

## Do-not-read / avoid

- Schema/store files — fully orthogonal.
- The warm-daemon design — that's B05; this bucket is just the cache location + pre-fetch.

## Design direction

- The cache fix alone makes semantic matching *work and testable* — it is the real unblock,
  independent of the daemon (which is only a live-latency win). Land it standalone.
- `cache_dir` must be a stable managed path, not per-session — the whole point is persistence
  across cold hook invocations.
- Keep the lazy `from fastembed import TextEmbedding` import (cold-start import cost stays off
  the no-embed path). Fail-open: if fastembed/weights are unavailable, callers already fall
  back to lexical Jaccard — do not change that contract.
- Decide `embed-warm` verb vs fold-into-init by what's cleaner; either way it runs OFF the
  hook path. Prefer a tiny explicit verb so re-staging after a cache wipe is trivial.

## Validation

- With fastembed installed (it is): run the pre-fetch, confirm weights land in the managed
  cache dir (not `/tmp`), then a second embed call hits the cache (no re-download).
- `.venv/bin/pytest -k embed` — `test_real_model_semantic_neighbors` is the known-stale
  onnxruntime failure; confirm no *new* failures and that any cache-path assertion passes.
- Expected: weights persist across processes; lexical fallback unchanged.

## Done criteria

- [ ] Tasks complete.
- [ ] Weights resolve to the managed cache, not ephemeral /tmp.
- [ ] Pre-fetch is off the hook path (init/sync or `embed-warm`).
- [ ] Bucket `Updates` records the chosen cache path + verb decision.
- [ ] Parent workstream progress updated.

## Updates

- [2026-06-18] Created. Handoff: none yet. Independent of B01/B02 — may run any time.
- [2026-06-18] DONE. 192 passed (+3 embed-cache tests), 2 skipped, 1 failed (README known-stale
  only). Lint clean. **The cache_dir fix unblocked the real-model semantic test** — the
  charter's first "known-stale" (test_real_model_semantic_neighbors onnxruntime) now PASSES
  standalone (15s real load); the ephemeral /tmp cache was its actual cause too, confirming the
  charter's "this is the actual unblock." Edits:
  - embed.py: NEW `_cache_root()` (factored) + `_weights_dir()` (`<XDG>/monition/fastembed`);
    `_embed_raw` passes `cache_dir=_weights_dir()` (+ makedirs) to TextEmbedding — was bare
    `TextEmbedding(model_name=...)` defaulting to ephemeral /tmp/fastembed_cache. NEW `warm()`:
    fail-open on missing extra (returns "skipped"), else stages weights + returns path.
  - cli.py: `embed-warm` verb registered + dispatched (`embed.warm()`).
  - Tests: test_embed_cache.py (fake fastembed → asserts managed cache_dir passed + created;
    warm stages; warm fail-open without fastembed). No real download needed in tests.
  DESIGN CALL: did NOT auto-wire warm into `init` (charter offered "init/sync OR embed-warm
  verb"). Reasons: (1) ~100MB surprise download inside `monition init`; (2) it would fire during
  test_init_sync (fastembed installed here) and hit the onnxruntime env path. Per the CLAUDE.md
  seam "deployment is CMS's; machinery is monition's," CMS's bootstrap calls `monition embed-warm`
  during setup. Monition exposes the verb.
  NOTE (out of scope): the remaining README failure is real drift — test asserts "uv tool install",
  README_LINE says "pip install git+..."; pre-existing, not v6. Leave for a separate fix.
  Handoff: B05 (warm daemon) is the only remaining runnable bucket (B04 fold still CMS-gated).
  B05 depends on this managed cache (daemon loads weights from _weights_dir()).
