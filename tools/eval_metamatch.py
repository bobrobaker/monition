#!/usr/bin/env python3
"""B06 metamatch gate: honest re-test of the spike's buried negative.

metamatch(firing) = +conf_row·conf_prompt if metaness(row) == metaness(prompt)
                    else −conf_row·conf_prompt        (spike/run_eval_metamatch.py)

Training-free (~1 parameter: the sign convention), so the gate is simply the
pooled AUC of the raw signal against human labels with the same row-cluster
bootstrap CI the head used — no LORO needed (nothing is fit). Bar: identical to
B02 (95% CI lower bound > 0.60), judged per layer.

Also reports what B03 needs to choose the scorer-slot shape:
  - Spearman redundancy vs the head's LORO predictions and vs cosine
    (rank-normalized — t94: never rank raw confidence curves);
  - conditional lift: LORO-CV AUC of a 2-feature logistic [head_pred, metamatch]
    vs the head alone (both rank-normalized), CI'd the same way.

Inputs: data/relevance-cascade/labels.jsonl (B01 builder),
        data/relevance-cascade/metaness_out.json (oracle pass),
        data/relevance-cascade/embed_cache.jsonl (for head preds, model-free).

    .venv/bin/python tools/eval_metamatch.py [--store DIR]
"""
import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from monition.store import Store  # noqa: E402
from monition.store_write import resolve_store_path  # noqa: E402
from monition.relevance import eval as rce  # noqa: E402
from monition.relevance.head import build_features  # noqa: E402
from train_relevance_head import cached_embed_fn, load_dataset, rowtext_map  # noqa: E402
from embed_relevance_cache import DEFAULT_CACHE  # noqa: E402

DATASET = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                       "data", "relevance-cascade", "labels.jsonl")
METANESS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                        "data", "relevance-cascade", "metaness_out.json")
GATE_CI_LOWER_BOUND = 0.60
DEFAULT_L2 = 8.0


def rank_normalize(x):
    """Values -> average ranks scaled to [0,1] (ties averaged)."""
    x = np.asarray(x, dtype=float)
    order = np.argsort(x, kind="mergesort")
    ranks = np.empty(len(x))
    ranks[order] = np.arange(len(x), dtype=float)
    # average tied ranks
    for v in np.unique(x):
        m = x == v
        ranks[m] = ranks[m].mean()
    return ranks / max(len(x) - 1, 1)


def spearman(a, b):
    ra, rb = rank_normalize(a), rank_normalize(b)
    ra, rb = ra - ra.mean(), rb - rb.mean()
    d = np.sqrt((ra * ra).sum() * (rb * rb).sum())
    return float((ra * rb).sum() / d) if d else 0.0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--store")
    ap.add_argument("--metaness", default=METANESS)
    args = ap.parse_args(argv)

    recs = load_dataset(DATASET)
    meta = json.load(open(args.metaness))
    prompt_meta = {p["text_key"]: p for p in meta["prompts"]}
    row_meta = {r["takeaway_id"]: r for r in meta["rows"]}

    store = Store(args.store or resolve_store_path())
    row_text = rowtext_map(store)

    from embed_relevance_cache import text_key
    labels, groups, mm, prompts, rowtexts = [], [], [], [], []
    missing = {"prompt_label": 0, "row_label": 0, "row_text": 0}
    for r in recs:
        tid = r["takeaway_id"]
        pk = text_key(r["prompt"][:2000])  # oracle labeled the ≤2000-char text
        if tid not in row_text:
            missing["row_text"] += 1
            continue
        if pk not in prompt_meta:
            missing["prompt_label"] += 1
            continue
        if tid not in row_meta:
            missing["row_label"] += 1
            continue
        pm, rm = prompt_meta[pk], row_meta[tid]
        agree = pm["meta"] == rm["meta"]
        strength = float(pm["confidence"]) * float(rm["confidence"])
        mm.append(strength if agree else -strength)
        labels.append(1 if r["label"] == "helpful" else 0)
        groups.append(tid)
        prompts.append(r["prompt"])
        rowtexts.append(row_text[tid])
    labels = np.array(labels)
    groups = np.array(groups)
    mm = np.array(mm, dtype=float)
    if any(missing.values()):
        print(f"WARN coverage gaps (excluded firings): {missing}")
    print(f"firings={len(labels)}  rows={len(set(groups.tolist()))}  "
          f"helpful={int(labels.sum())}  noise={int((labels == 0).sum())}")

    # --- metamatch alone: training-free -> pooled AUC + row-cluster bootstrap CI ---
    mm_auc = rce.auc(mm, labels)
    lo, hi, boot = rce.cluster_bootstrap_ci(mm, labels, groups)
    print(f"\nmetamatch AUC  = {mm_auc:.3f}")
    print(f"95% CI (rows)  = [{lo:.3f}, {hi:.3f}]   (bootstrap mean {boot:.3f})")
    verdict = "PASS" if lo > GATE_CI_LOWER_BOUND else "FAIL"
    print(f"GATE [{verdict}]: CI lower bound {lo:.3f} "
          f"{'>' if lo > GATE_CI_LOWER_BOUND else '<='} {GATE_CI_LOWER_BOUND}")

    # cell-rate view (the spike's Finding-3 framing, now on honest data)
    match = mm > 0
    for name, m in (("metaness-match", match), ("metaness-MISmatch", ~match)):
        if m.any():
            print(f"P(noise | {name}) = {1 - labels[m].mean():.2f}  (n={int(m.sum())})")

    # --- redundancy + conditional lift vs the head (model-free via embed cache) ----
    embed_fn = cached_embed_fn(DEFAULT_CACHE) if os.path.exists(DEFAULT_CACHE) else None
    features = build_features(prompts, rowtexts, embed_fn=embed_fn)
    head_preds = rce.leave_row_out_cv(features, labels, groups, DEFAULT_L2)
    cosine = features.sum(axis=1)  # sum of the l2norm product = plain cosine
    print(f"\nSpearman(metamatch, head LORO preds) = {spearman(mm, head_preds):+.3f}")
    print(f"Spearman(metamatch, cosine)          = {spearman(mm, cosine):+.3f}")

    head_auc = rce.auc(head_preds, labels)
    combo_feats = np.column_stack([rank_normalize(head_preds), rank_normalize(mm)])
    combo_preds = rce.leave_row_out_cv(combo_feats, labels, groups, l2=1.0)
    combo_auc = rce.auc(combo_preds, labels)
    clo, chi, cboot = rce.cluster_bootstrap_ci(combo_preds, labels, groups)
    print(f"\nhead alone LORO AUC          = {head_auc:.3f}")
    print(f"head+metamatch LORO AUC      = {combo_auc:.3f}   (lift {combo_auc - head_auc:+.3f})")
    print(f"combo 95% CI (rows)          = [{clo:.3f}, {chi:.3f}]")
    print(f"combo GATE [{'PASS' if clo > GATE_CI_LOWER_BOUND else 'FAIL'}]: "
          f"CI lower bound {clo:.3f} vs {GATE_CI_LOWER_BOUND}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
