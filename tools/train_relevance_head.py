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
EMBED_CACHE = "data/relevance-cascade/embed_cache.jsonl"
ARTIFACT = "src/monition/relevance/artifacts/head-v1.json"


def cached_embed_fn(cache_path):
    """Disk-cached, value-identical stand-in for embed._embed_raw (B06: the model
    never loads when the cache covers the corpus — see tools/embed_relevance_cache.py).
    Misses fall through to the real embedding and are appended to the cache."""
    from embed_relevance_cache import load_cache, text_key
    cache = load_cache(cache_path)

    def fn(texts):
        missing = [t for t in texts if text_key(t) not in cache]
        if missing:
            print(f"embed cache: {len(missing)}/{len(texts)} misses (loading model)")
            with open(cache_path, "a") as out:
                for t, v in zip(missing, embed._embed_raw(missing)):
                    cache[text_key(t)] = v
                    out.write(json.dumps({"k": text_key(t), "v": v}) + "\n")
        return [cache[text_key(t)] for t in texts]

    return fn


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
    ap.add_argument("--embed-cache", default=EMBED_CACHE,
                    help="JSONL embedding cache (tools/embed_relevance_cache.py); "
                         "misses fall through to the live model")
    ap.add_argument("--l2", type=float, default=DEFAULT_L2)
    ap.add_argument("--out", default=ARTIFACT)
    ap.add_argument("--write", action="store_true", help="serialize the artifact on PASS")
    ap.add_argument("--accept-marginal", action="store_true",
                    help="serialize despite a gate FAIL — an explicit, user-ratified bar "
                         "amendment (B06, 2026-07-03: CI-LB 0.598 accepted; see the bucket "
                         "Updates). The gate verdict still prints FAIL; this only unlocks "
                         "--write.")
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

    cache_path = args.embed_cache if os.path.isabs(args.embed_cache) else _repo_path(args.embed_cache)
    embed_fn = cached_embed_fn(cache_path) if os.path.exists(cache_path) else None
    print(f"embed cache: {'ON (' + cache_path + ')' if embed_fn else 'absent — embedding live'}")
    features = build_features(prompts, rowtexts, embed_fn=embed_fn)  # embeds once

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

    if not passed and not args.accept_marginal:
        print("\nNO-GO: the artifact does not ship on this evidence. Record the finding "
              "(per-layer verdict — workstream sequencing is B03's own call since the "
              "2026-07-02 gate-invariant amendment).")
        return 1
    if not passed:
        print("\ngate FAIL overridden by --accept-marginal (user-ratified bar amendment, "
              "B06 2026-07-03) — serializing anyway.")

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
