"""B02 trainer + GO/NO-GO gate for the relevance head `L2'`.

Graduates the spike's `embed_classifier.py` into a repeatable trainer. Reads the B01 label
dataset, re-derives the row half from the hub (parity: `f"{one_liner} {trigger_spec}"`, which
`export.py` does not expose — read the takeaway), runs **leave-row-out CV** with a
**cluster-bootstrap CI**, and applies the usefulness gate:

    PASS iff the 95% CI lower bound of LORO-CV AUC > 0.60  AND  a usable operating point exists.

The 0.60 bar was set with the user up front (2026-06-21) — before any number was seen — so it
cannot be rationalized after the fact. On PASS (`--write`) it serializes the production head
artifact (contract §2). On FAIL it prints the finding and exits non-zero; the workstream pauses
(B03+ do not run).

    .venv/bin/python tools/train_relevance_head.py --store "$MONITION_STORE" [--write]
"""
import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from monition import embed  # noqa: E402
from monition.store import Store  # noqa: E402
from monition.store_write import resolve_store_path  # noqa: E402
from monition.relevance import eval as rce  # noqa: E402
from monition.relevance.head import RelevanceHead, build_features  # noqa: E402

GATE_CI_LOWER_BOUND = 0.60  # B02 GO/NO-GO bar, set with the user up front (2026-06-21)
DEFAULT_L2 = 8.0            # spike: logistic-on-product L2=8 won; heavy reg is the overfit defense
DATASET = "data/relevance-cascade/labels.jsonl"
ARTIFACT = "src/monition/relevance/artifacts/head-v1.json"


def _repo_path(rel):
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", rel)


def load_dataset(path):
    with open(path) as fh:
        return [json.loads(line) for line in fh if line.strip()]


def rowtext_map(store):
    """takeaway_id -> the row half exactly as on_demand_match builds `texts`."""
    return {
        t.id: f"{t.one_liner} {t.trigger_spec or ''}".strip()
        for t in store.takeaways()
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--store", help="store path (default: resolve_store_path / MONITION_STORE)")
    ap.add_argument("--dataset", default=DATASET)
    ap.add_argument("--l2", type=float, default=DEFAULT_L2)
    ap.add_argument("--out", default=ARTIFACT)
    ap.add_argument("--write", action="store_true", help="serialize the artifact on PASS")
    args = ap.parse_args(argv)

    dataset_path = args.dataset if os.path.isabs(args.dataset) else _repo_path(args.dataset)
    rows = load_dataset(dataset_path)
    store = Store(args.store or resolve_store_path())
    row_text = rowtext_map(store)

    prompts, rowtexts, labels, groups = [], [], [], []
    missing = 0
    for r in rows:
        tid = r["takeaway_id"]
        if tid not in row_text:
            missing += 1
            continue
        prompts.append(r["prompt"])
        rowtexts.append(row_text[tid])
        labels.append(1 if r["label"] == "helpful" else 0)
        groups.append(tid)
    labels = np.array(labels)
    groups = np.array(groups)
    if missing:
        print(f"WARN: {missing} firings reference a takeaway_id absent from the hub (skipped)")

    print(f"embedding model: {embed.MODEL_NAME}")
    print(f"firings={len(labels)}  rows={len(set(groups.tolist()))}  "
          f"helpful={int(labels.sum())}  noise={int((labels == 0).sum())}  "
          f"base_rate={labels.mean():.3f}")

    features = build_features(prompts, rowtexts)  # embeds once

    # --- leak sanity (C1): per-row prior under LORO must be ~0.5 -----------------
    prior_auc = rce.per_row_prior_auc(labels, groups)
    print(f"per-row-prior AUC (leak check, want ~0.5): {prior_auc:.3f}")
    assert prior_auc <= 0.6, (
        f"row-identity leak: per-row-prior AUC {prior_auc:.3f} > 0.6 — the split is not row-disjoint"
    )

    # --- full-data fit: train AUC exposes overfit -------------------------------
    full = RelevanceHead.fit(features, labels, args.l2)
    train_auc = rce.auc(full.predict_proba_raw(features), labels)

    # --- the gate measurement: leave-row-out CV + cluster-bootstrap CI ----------
    preds = rce.leave_row_out_cv(features, labels, groups, args.l2)
    cv_auc = rce.auc(preds, labels)
    lo, hi, boot_mean = rce.cluster_bootstrap_ci(preds, labels, groups)
    print(f"\ntrain AUC      = {train_auc:.3f}")
    print(f"LORO-CV AUC    = {cv_auc:.3f}   (overfit gap = {train_auc - cv_auc:.3f})")
    print(f"95% CI (rows)  = [{lo:.3f}, {hi:.3f}]   (bootstrap mean {boot_mean:.3f}, baseline ~0.5)")

    # --- operating point existence (B05 picks the exact one) --------------------
    curve = rce.suppression_curve(preds, labels)
    best = max(curve, key=lambda c: c[1] if c[2] <= 0.10 else -1)  # max noise suppressed at <=10% helpful loss
    print("\noperating-point scan (suppress when P(helpful) < threshold):")
    print(f"  best @ <=10% helpful loss: threshold={best[0]:.3f}  "
          f"noise_suppressed={best[1]:.0%}  helpful_lost={best[2]:.0%}")
    usable = best[1] >= 0.20  # a usable point suppresses >=20% of noise while keeping >=90% helpful
    print(f"  usable operating point exists (>=20% noise @ <=10% loss): {usable}")

    # --- GATE --------------------------------------------------------------------
    passed = (lo > GATE_CI_LOWER_BOUND) and usable
    verdict = "PASS" if passed else "FAIL"
    print(f"\nGATE [{verdict}]: 95% CI lower bound {lo:.3f} "
          f"{'>' if lo > GATE_CI_LOWER_BOUND else '<='} {GATE_CI_LOWER_BOUND} "
          f"AND usable_point={usable}")

    if not passed:
        print("\nNO-GO: workstream pauses (B03+ do not start). Record the finding in a decision "
              "doc and set the workstream Blocked.")
        return 1

    if args.write:
        full.train_auc = train_auc
        full.cv_auc = cv_auc
        full.cv_ci = [lo, hi]
        out_path = args.out if os.path.isabs(args.out) else _repo_path(args.out)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        full.save(out_path)
        # round-trip + model-id refusal validation
        reloaded = RelevanceHead.load(out_path)
        rt_auc = rce.auc(reloaded.predict_proba_raw(features), labels)
        assert abs(rt_auc - train_auc) < 1e-9, f"round-trip drift: {rt_auc} vs {train_auc}"
        try:
            RelevanceHead.load(out_path, live_model_name="some/other-model")
            raise AssertionError("load did NOT refuse a mismatched embedding model id")
        except ValueError:
            pass
        print(f"\nserialized -> {out_path}  (round-trip AUC {rt_auc:.3f}; model-id refusal verified)")
    else:
        print("\nPASS (dry run). Re-run with --write to serialize the artifact.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
