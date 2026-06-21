# Workstream: Relevance Cascade (Phase 5)

Progress: B01/label-foundation next
Blocked: none

## Objective

Ship the spike-validated relevance filter: a cost-ordered, certainty-gated **cascade** of
relevance **Layers** on the passive `on_demand` fire path, whose decisive layer `L2′` is a
**learned head over full embeddings** (0.78 grouped-CV AUC vs cosine 0.63 — no inline LLM).
The LLM is an offline label oracle only. B01–B02 firm up the data and **gate** on a
usefulness bar before any runtime integration; B03–B05 build and roll out the runtime.

## Execution Protocol (do not change)

1. Read this workstream first. For B01, read the full file. For B02+, do NOT use `cat` — run `grep -n "^##" workstream.md` first to get section line anchors, then use bounded reads for only: Objective, Execution Protocol, Bucket Index, and Cross-Bucket Invariants — skip Deferred/Non-Goals, Estimate, and any lower boilerplate sections.
2. Use `Progress` and `Bucket Index` to select the active bucket; if none is active, select the next bucket.
2a. If the index references a bucket file that does not exist yet, read `## Bucket template` in the generator prompt before creating it.
3. Open only the selected bucket file. If its `State` is not `active`, update it to `active` before reading touchpoints.
4. Read only that bucket's required touchpoints before reporting.
5. Report first: selected bucket, required touchpoints read, current behavior, proposed edits, validation plan, and extra touchpoints if needed.
6. Only edit after the plan is clear.
7. Run the bucket's validation.
8. Update the bucket file's `Updates` section with completed tasks, discoveries, gotchas, test results, and handoff notes.
9. Update this workstream's `Progress`, `Bucket Index`, and `Updates` only for progress, sequencing changes, cross-bucket discoveries, and cross-bucket gotchas. Also update the next bucket file's `State` from `later` to `next`. Use the Read tool (not Bash `cat`) to open workstream.md before editing it — Edit requires a prior Read call.
10. Keep only one bucket active at a time unless the user explicitly authorizes parallel execution.

## Bucket Index

| B | State | File | Goal | Depends |
|---|---|---|---|---|
| B01 | next | buckets/B01_label-foundation.md | Build the (prompt,row)→label dataset + held-out split | — |
| B02 | later | buckets/B02_learned-head-gate.md | Train L2′ head, at-scale eval, GO/NO-GO gate, serialize | B01 |
| B03 | later | buckets/B03_cascade-runtime.md | Layer interface + orchestrator + L0 + L2′ layer in src | B02 |
| B04 | later | buckets/B04_hook-integration.md | Wire L0+L2′ into the passive on_demand path only | B03 |
| B05 | later | buckets/B05_operating-point-rollout.md | Pick operating point, dogfood, measure, ship | B04 |

States: `next`, `active`, `blocked`, `done`, `deferred`, `later`.

## Cross-Bucket Invariants

- **GO/NO-GO gate (B02):** if the head does not clear the usefulness bar on the
  **human-only** test split, the workstream **pauses** — B03+ do not start. Integration is
  gated on proven separation, not on the spike's n=102 number.
- **Data/model contract:** preserve `docs/contracts/relevance-cascade.md`; buckets that
  touch the label dataset, the head artifact, or per-firing score logging must read the
  relevant section before editing.
- **Train/infer feature parity:** the feature construction for `L2′` (L2-normalized
  prompt⊕row embeddings from `embed._embed_raw`) MUST be identical at training and
  inference. A mismatch silently destroys the AUC. Named invariant, owned across B02↔B03.
- **Embedding-version coupling:** a head is valid only for the `embed.MODEL_NAME` it was
  trained on; the runtime refuses a head whose stored model id ≠ the live model id.
- **Passive-path only:** the cascade gates the auto-fire path (`prompt_hook`) ONLY.
  Explicit pulls (`mcp_server`, `cli query`) stay ungated — the user asked for those.
- **No inline LLM on the hook path.** The LLM appears only offline (label oracle). Ever.
- **Per-session dedup preserved:** a row fired once in a session is not re-fired (current
  `_not_yet_fired` semantics survive integration).

## Deferred / Non-Goals

- Per-context Gate / `score.py` changes — the Gate stays last-resort, untouched here.
- More trigger *kinds* (breadth) — orthogonal; not this workstream.
- Retraining automation / online learning — B05 may log data for it; building it is later.
- `edit_path` filtering — the noise is `on_demand`; leave `edit_path` matching alone.

## Global Implementation Notes

- Spike reference (methodology to graduate, not copy blindly): branch
  `spike/relevance-cascade` — `cascade.py`, `layer_eval.py`, `embed_classifier.py`.
- n=102 overfits (train AUC 1.00). B01 exists because the spike number is not trustworthy
  without more labels.
- Dolt omits NULL columns from JSON → use `row.get("col")`, never `row["col"]`.
- Hook window assumed 30 s for `TIME_BUDGET`; B03 must confirm the real value.

## Updates

- 2026-06-21 Initial plan created (dispatched from the spike-validated decision doc). Next: B01/label-foundation.
