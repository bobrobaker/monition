---
status: decided
---
# 2026-06-18 · Warm daemon for semantic `on_demand` matching (host the embedding model out of the hook)

**Status.** Design decision, **investigation-backed this session, not implemented.**
Project-internal (pure machinery — no cross-repo confer needed; embedding is
monition's per the eval/deployment seams). Prerequisite cache-location fix is
separable and lower-risk than the daemon; see Decision.

## Question

`on_demand` rows match user prompts in two stages: a fast lexical pass, then a
semantic (cosine) pass over the rows lexical missed (`store_write.on_demand_match`,
`:159`). The semantic pass runs inside the `prompt-hook` executor, which fires on
**every** `UserPromptSubmit` and is a **fresh, blocking subprocess** with a 30 s
timeout. How do we run semantic matching without (a) paying a cold model-load tax
on every turn and (b) the download-in-hook failure that left it silently dead?

Two problems were found, one structural, one latent:

1. **The model was never reachable.** Weights download lazily on first semantic
   fire, *inside* the 30 s hook, into fastembed's default `/tmp/fastembed_cache`.
   The `.onnx` (largest file) was left as an `.incomplete` blob — consistent with
   the 30 s timeout killing the download mid-flight, and self-perpetuating (a
   download can never finish if it only ever runs inside a 30 s-capped hook). With
   the `.onnx` missing, `semantic_scores` throws, hits the bare `except` at
   `store_write.py:187`, and **silently degrades to lexical-only** — correct
   fail-open, but invisible: you cannot tell from behavior that semantic is off.
2. **Cold per-fire load is ~1 s**, intrinsic to a fresh Python process loading any
   HF model — too much to pay on every semantic-eligible prompt on the blocking
   path.

## Measurements (offline, fresh process — this session)

| model | import | load | encode | **cold total** | related-disjoint cos | unrelated cos | 1-time download |
|---|---|---|---|---|---|---|---|
| **bge-small** (onnx, current) | 0.63 | 0.38 | 0.02 | **1.03 s** | **0.677** ✓ | 0.408 | 14.7 s |
| potion-retrieval-32M (static) | 0.20 | 0.61 | 0.002 | **0.81 s** | **0.089** ✗ | −0.005 | 49 s |

- **Warm encode is 2–19 ms** — the prize: a resident model answers in ~ms + IPC.
- The "related-disjoint" query shares **zero keywords** with the row (`"my unit
  checks sometimes pass and sometimes fail at random"` vs row `"Quarantine
  intermittent tests before they block the merge pipeline"`) — it is exactly the
  case semantic exists for (catching what lexical misses). Verified end-to-end
  through the real `on_demand_match`: the row fired on bge-small (0.677 ≥ 0.6
  threshold).

## Decision

**Keep bge-small** (the quality winner) and remove the cold-start tax with two
separable changes:

**1. Managed cache + pre-fetch (prerequisite — do regardless of the daemon).**
Point fastembed at a monition-managed `cache_dir` (XDG, e.g.
`~/.cache/monition/fastembed`) via `FASTEMBED_CACHE_PATH` or an explicit
`cache_dir=` at the `TextEmbedding(...)` call (`embed.py:49`), and **pre-download
weights at `monition init`/`sync`** (or an explicit `monition embed-warm` verb) so
the hook only ever *loads*, never *fetches*. This kills both the `/tmp`
ephemerality and the download-in-hook timeout trap, and extends the existing
"deleting the cache is always safe" XDG discipline (today applied to *vectors*) to
the *weights*.

**2. Session-scoped warm daemon for the per-fire load.** Since ~1 s cold is
intrinsic to a fresh Python process (confirmed below — not onnx-specific), host
the loaded model in a persistent process:

- **Lifecycle bounded to the session**: lazy-spawn (first fire, or `SessionStart`),
  unix socket at a session-scoped path, idle-timeout + session-end shutdown. Not a
  free-floating always-on process.
- **Fail-open preserved**: the hook tries the socket; if it's absent (first-prompt
  race, crash) it falls back to in-process embed → which itself falls back to
  lexical. Absence of the daemon never blocks a prompt — same degradation as today.
- **Call site unchanged**: `embed.py` tries the socket first, falls back to its
  current in-process path. No API churn for callers; the daemon is a clean later
  upgrade decoupled from change 1.

## Options considered and why the rejected ones lost

- **A — accept ~1 s/fire, load per subprocess (no daemon).** Simplest; zero new
  machinery; just ship change 1. Rejected: ~1 s on *every* semantic-eligible
  prompt, on the blocking 30 s hook — judged too heavy this session. Remains the
  fallback if the daemon proves not worth its lifecycle cost.
- **B — swap to a cheaper/static model (model2vec potion-retrieval-32M).** The
  hoped-for escape: "the cost is onnxruntime, drop it." **Rejected on both axes**
  (numbers above): speed barely moved (0.81 s — the load tax is the HF tokenizer +
  matrix, *intrinsic to cold-Python model load*, not onnx-specific), and quality
  collapsed (0.089 vs 0.677 on the case semantic is *for*). The retrieval-tuned
  static model is the best static option and isn't close. (model2vec + potion
  weights left installed — may be reused for a different purpose later.)
- **C — reuse the existing MCP server as the warm host.** It is already long-lived
  (`mcp_server.py`, FastMCP, per-session). Rejected: `server.run()` is **stdio**
  transport — only Claude Code talks to it; the sibling `prompt-hook` subprocess
  can't reach it. Adding an HTTP/socket transport to reach it *is* building a
  daemon, with extra steps.
- **D — compiled (Rust/C++) embedder binary.** Cuts the Python import. Rejected:
  keeps model session-init (~0.3–0.5 s), never near the daemon's ~0.01 s, and adds
  a native build dependency for a partial win.

## Anti-goals

- Do **not** download weights inside the hook path (the original bug) or store
  them in `/tmp`/any unmanaged location — extend the XDG "safe to delete" cache
  discipline to weights.
- Do **not** make the daemon a hard dependency. Semantic must stay fail-open to
  lexical; a missing/crashed daemon must never block a prompt.
- Do **not** trade bge-small for a faster-but-weaker model — quality on the
  lexical-disjoint case is the whole point of the semantic stage.
- Do **not** leave the daemon free-floating/always-on. Bound its lifecycle to the
  session + idle timeout.

## Seams this touches (from the code, not the docs)

1. `embed.py:49` `_embed_raw` — `TextEmbedding(model_name=MODEL_NAME)`, no
   `cache_dir` → must take the managed path. `_model` global is the per-process
   warm cache that dies with the subprocess (the thing the daemon makes durable).
2. `store_write.py:159` `on_demand_match` — lexical-first, semantic on `rest`,
   fail-open `except` at `:187`. Unchanged in behavior; just faster underneath.
3. `hooks.py` executors run as fresh subprocesses via `guarded_hook_command`
   (`monition prompt-hook`). Daemon-spawn would hook `SessionStart`
   (`session-brief`) or lazy-spawn from the first `prompt-hook`.
4. `init_sync.py` — add the weights pre-fetch step (and any daemon registration).

## Follow-ups

- Frames the session's **Trigger → Filter → Gate** pipeline: the semantic *filter*
  is the slow stage; the daemon is how it stays on the hot path within the hook's
  latency budget. Trigger = `trigger_kind` hook dispatch (fast); Gate = `score.py`
  EV (cheap, non-LLM).
- Benchmark the warm-daemon IPC roundtrip once built (expect ~ms) to confirm the
  ~1 s → ~0.01 s win and validate it's worth the lifecycle cost vs Option A.
- `road.md §2` backlink pending (this decision is investigation-backed, not yet
  ratified/implemented).
- **Parked:** skill-invocation as a new `trigger_kind` (the question that started
  the session) — separate from this latency work.
