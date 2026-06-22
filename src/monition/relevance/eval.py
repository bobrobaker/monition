"""Calibration-invariant evaluation for the relevance head — graduated from the spike's
`layer_eval`. The decisive measurement is **leave-row-out CV**: every `takeaway_id` is held
out once, so all firings get an unseen-ROW prediction. This is mandatory because the head
embeds prompt-ROW over only ~46 distinct rows; a prompt-grouped split leaks row identity and
a prompt-ignoring per-row prior then scores ≈ the headline AUC (B01 red-team C1).

The CI is a **cluster bootstrap over rows**, not firings: within-row firings are correlated,
so a firing-level bootstrap reports a falsely tight interval (B01 red-team M1).
"""
import numpy as np

from monition.relevance.head import RelevanceHead


def auc(scores, labels):
    """Rank AUC with tie credit. NaN if a class is absent."""
    scores = np.asarray(scores, dtype=float)
    labels = np.asarray(labels)
    pos = scores[labels == 1]
    neg = scores[labels == 0]
    if len(pos) == 0 or len(neg) == 0:
        return float("nan")
    greater = (pos[:, None] > neg[None, :]).sum()
    equal = (pos[:, None] == neg[None, :]).sum()
    return float((greater + 0.5 * equal) / (len(pos) * len(neg)))


def leave_row_out_cv(raw_features, labels, groups, l2):
    """Hold out each unique group (takeaway_id) once; predict its firings from a head
    trained on every OTHER row. Returns pooled out-of-fold predictions aligned to inputs."""
    raw_features = np.asarray(raw_features, dtype=float)
    labels = np.asarray(labels)
    groups = np.asarray(groups)
    preds = np.full(len(labels), np.nan)
    for g in np.unique(groups):
        test = groups == g
        train = ~test
        head = RelevanceHead.fit(raw_features[train], labels[train], l2)
        preds[test] = head.predict_proba_raw(raw_features[test])
    return preds


def per_row_prior_auc(labels, groups):
    """Leak sanity (C1): a row-identity-only predictor under LORO cannot see the held-out
    row's own label rate, so it predicts the train base rate (constant per fold) -> AUC≈0.5.
    A high value means the split still leaks row identity."""
    labels = np.asarray(labels, dtype=float)
    groups = np.asarray(groups)
    preds = np.full(len(labels), np.nan)
    for g in np.unique(groups):
        test = groups == g
        preds[test] = labels[~test].mean()
    return auc(preds, labels)


def cluster_bootstrap_ci(preds, labels, groups, n_boot=2000, alpha=0.05, seed=0):
    """95% CI for the pooled LORO AUC by resampling GROUPS (rows) with replacement —
    honest under within-row correlation, unlike a firing-level bootstrap. Returns
    (lo, hi, bootstrap_mean)."""
    preds = np.asarray(preds, dtype=float)
    labels = np.asarray(labels)
    groups = np.asarray(groups)
    uniq = np.unique(groups)
    idx_by_group = {g: np.where(groups == g)[0] for g in uniq}
    rng = np.random.default_rng(seed)
    boot_aucs = []
    for _ in range(n_boot):
        picked = rng.choice(uniq, size=len(uniq), replace=True)
        idx = np.concatenate([idx_by_group[g] for g in picked])
        a = auc(preds[idx], labels[idx])
        if not np.isnan(a):
            boot_aucs.append(a)
    lo = float(np.percentile(boot_aucs, 100 * alpha / 2))
    hi = float(np.percentile(boot_aucs, 100 * (1 - alpha / 2)))
    return lo, hi, float(np.mean(boot_aucs))


def suppression_curve(preds, labels):
    """For the noise FILTER framing: score = P(helpful), suppress when score < threshold.
    Sweeps thresholds and returns (threshold, noise_suppressed_frac, helpful_lost_frac) so
    B02 can confirm a usable operating point EXISTS (B05 picks the exact one)."""
    preds = np.asarray(preds, dtype=float)
    labels = np.asarray(labels)
    n_noise = int((labels == 0).sum())
    n_helpful = int((labels == 1).sum())
    out = []
    for t in sorted(set(preds.tolist())):
        suppressed = preds < t
        noise_supp = int(((labels == 0) & suppressed).sum())
        helpful_lost = int(((labels == 1) & suppressed).sum())
        out.append((
            float(t),
            noise_supp / n_noise if n_noise else 0.0,
            helpful_lost / n_helpful if n_helpful else 0.0,
        ))
    return out
