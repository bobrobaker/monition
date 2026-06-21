#!/usr/bin/env python3
"""Build the relevance-cascade label dataset (contract §1) from the hub.

One record per *firing*: a (prompt context, takeaway row) pair that fired
`on_demand` and was human-rated helpful/noise. The dataset trains and evaluates
the L2' relevance head (B02); the held-out `test` split is human-labeled ONLY.

Reuses the single approved store reader (`monition.export.export_records` ->
`Store`) — no direct store access. Regenerates from the hub; the output contains
real session prompts and is gitignored, never committed.

    python tools/build_relevance_labels.py [--store DIR] [--out PATH]

Two leakage axes, fixed after the B01 red-team (2026-06-21):

1. **Prompt field (parity, was C2).** The runtime embeds the FULL live prompt at
   inference (`on_demand_match(prompt)` -> `embed.semantic_scores`). So we train on
   the full prompt too: `situation` (= `prompt[:SITUATION_CHARS]`, ~4000) when
   present, else the lossy `trigger_context` (≤200-char preview). The earlier
   version trained on `trigger_context`, a ≤200 preview the runtime never embeds —
   a silent train/infer mismatch. `prompt_source`/`prompt_chars` record which field
   each row used so B02 can exclude or down-weight the 17 fallbacks.

2. **Split axis (was C1).** The head embeds prompt⊕ROW and there are only ~46
   distinct rows, so a *prompt*-grouped split leaks row identity: a prompt-ignoring
   per-row prior scored AUC 0.77 on the prompt-grouped test ≈ the headline number.
   The split is therefore **row-disjoint** (group by `takeaway_id`): test rows are
   unseen in train, so the per-row prior collapses to ~0.5 and any AUC the head
   earns is real prompt×row signal. We also emit `prompt_group` so B02 can do
   doubly-disjoint or leave-row-out CV (see the contract — a single row-disjoint
   split is tiny/imbalanced at 46 rows; CV is the honest gate).
"""
import argparse
import hashlib
import json
import os
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from monition.export import export_records
from monition.store import Store, StoreContractError
from monition.store_write import resolve_store_path

DEFAULT_OUT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "data", "relevance-cascade", "labels.jsonl"
)


# Spike leakage guard, reproduced exactly (spike/embed_classifier.py:86). Used as
# the prompt-GROUP key (emitted for B02's CV), NOT the split axis.
def norm_prompt(s):
    return re.sub(r"\s+", " ", (s or "").lower()).strip()[:120]


def best_prompt(r):
    """The prompt text to train on = what the runtime embeds at inference: the full
    prompt. `situation` (= prompt[:4000]) is the lossless proxy; fall back to the
    ≤200 `trigger_context` preview only when situation is absent (older firings)."""
    if r.get("situation"):
        return r["situation"], "situation"
    return (r.get("trigger_context") or ""), "trigger_context"


def split_of(takeaway_id, test_fraction_inverse=5):
    """ROW-disjoint grouping: every firing of a given row lands in the same split,
    so test rows are unseen in train (closes the row-identity leak). Deterministic
    hash (no RNG) -> ~1/5 of rows to test."""
    h = int(hashlib.sha256(str(takeaway_id).encode("utf-8")).hexdigest(), 16)
    return "test" if h % test_fraction_inverse == 0 else "train"


def build(store_path):
    """-> (records, skipped_tally). One record per rated on_demand firing with a
    usable prompt; everything excluded is counted with a reason."""
    records = []
    skipped = Counter()
    for r in export_records(Store(store_path), rated_only=True):
        if r.get("trigger_kind") != "on_demand":
            skipped["not_on_demand"] += 1
            continue
        prompt, source = best_prompt(r)
        if not prompt:
            skipped["no_prompt_text"] += 1
            continue
        if r.get("outcome") not in ("helpful", "noise"):
            skipped["outcome_not_binary"] += 1
            continue
        records.append({
            "takeaway_id": r["takeaway_id"],
            "prompt": prompt,                       # full prompt (matches inference)
            "prompt_source": source,                # situation | trigger_context
            "prompt_chars": len(prompt),
            "prompt_group": norm_prompt(prompt),    # for B02 CV / doubly-disjoint eval
            "label": r["outcome"],                  # helpful | noise (human rating)
            "label_source": "human",                # oracle rows (later) would set "oracle"
            "split": split_of(r["takeaway_id"]),    # ROW-disjoint
        })
    return records, skipped


def _row_prior_auc(records):
    """Sanity gate: a prompt-IGNORING per-row prior (learned on train) scored on
    test. Under a row-disjoint split this MUST be ~0.5 — test rows are unseen, so
    the prior has no per-row signal to exploit. A value materially above 0.5 means
    the split leaks row identity and the eval is invalid (the B01 red-team failure)."""
    tr = [r for r in records if r["split"] == "train"]
    te = [r for r in records if r["split"] == "test"]
    if not tr or not te:
        return None
    pos, tot = defaultdict(int), defaultdict(int)
    for r in tr:
        tot[r["takeaway_id"]] += 1
        pos[r["takeaway_id"]] += 1 if r["label"] == "helpful" else 0
    glob = sum(1 for r in tr if r["label"] == "helpful") / len(tr)
    score = lambda tid: pos[tid] / tot[tid] if tot[tid] else glob
    pred = [score(r["takeaway_id"]) for r in te]
    y = [1 if r["label"] == "helpful" else 0 for r in te]
    P = [s for s, yy in zip(pred, y) if yy == 1]
    N = [s for s, yy in zip(pred, y) if yy == 0]
    if not P or not N:
        return None
    return sum((a > b) + 0.5 * (a == b) for a in P for b in N) / (len(P) * len(N))


def validate(records):
    """Contract §1 invariants. Raises AssertionError on any breach."""
    by_split = defaultdict(list)
    for rec in records:
        by_split[rec["split"]].append(rec)
    # ROW-disjoint: no takeaway_id straddles train/test (closes the C1 row leak)
    rows = {s: {rec["takeaway_id"] for rec in recs} for s, recs in by_split.items()}
    overlap = rows.get("train", set()) & rows.get("test", set())
    assert not overlap, f"row leakage across splits: {len(overlap)} shared takeaway_ids"
    # test is human-only (the gate is measured on human labels)
    bad = [rec for rec in by_split.get("test", []) if rec["label_source"] != "human"]
    assert not bad, f"{len(bad)} non-human rows in test split"
    # the row-identity shortcut must be closed
    auc = _row_prior_auc(records)
    assert auc is None or auc <= 0.6, (
        f"per-row-prior AUC {auc:.3f} > 0.6 on test — split still leaks row identity"
    )


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--store", help="store directory (default: MONITION_STORE / repo convention)")
    ap.add_argument("--out", default=DEFAULT_OUT, help=f"output JSONL (default: {DEFAULT_OUT})")
    args = ap.parse_args(argv)

    store_path = args.store or resolve_store_path()
    if not store_path:
        raise StoreContractError("no store path: pass --store or set MONITION_STORE")

    records, skipped = build(store_path)
    validate(records)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")

    # Conservation tally: every rated firing is in the dataset or skipped-with-reason.
    total_rated = len(records) + sum(skipped.values())
    by_split = Counter(rec["split"] for rec in records)
    by_label = Counter((rec["split"], rec["label"]) for rec in records)
    by_source = Counter(rec["prompt_source"] for rec in records)
    n_rows = len({rec["takeaway_id"] for rec in records})
    print(f"wrote {len(records)} records -> {args.out}")
    print(f"conservation: total rated firings = {total_rated} "
          f"= in_dataset {len(records)} + skipped {sum(skipped.values())}")
    for reason, n in sorted(skipped.items()):
        print(f"  skipped[{reason}] = {n}")
    print(f"distinct rows (takeaway_ids): {n_rows}")
    print(f"prompt_source:   {dict(by_source)}")
    print(f"split (firings): {dict(by_split)}  [ROW-disjoint]")
    print(f"label balance:   {{{', '.join(f'{k}: {v}' for k, v in sorted(by_label.items()))}}}")
    auc = _row_prior_auc(records)
    print(f"per-row-prior AUC on test: {auc:.3f} (≈0.5 ⇒ row-identity leak closed)"
          if auc is not None else "per-row-prior AUC: n/a")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
