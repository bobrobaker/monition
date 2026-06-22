"""L2' relevance head: a learned logistic over L2-normalized prompt-row embeddings.

This is the serialized production artifact the cascade runtime (B03/B04) loads. Pure
numpy — no sklearn — so the shipped module carries no extra training dependency. The
feature is the elementwise PRODUCT of the L2-normalized prompt and row embeddings (its
sum is plain cosine; the head learns the per-dimension weights cosine throws away).

Parity invariant (contract §2, B01 red-team C2): the INPUT STRINGS are pinned —
  prompt half = the full prompt (train: the firing's `situation` ≈ prompt[:SITUATION_CHARS];
                infer: the live prompt, truncated to the same cap in B04);
  row half    = f"{one_liner} {trigger_spec}" exactly as `on_demand_match` builds `texts`.
A field/truncation mismatch silently destroys the AUC, so build_features is the single
shared definition for train and inference — the runtime MUST score through it.
"""
import json

import numpy as np

from monition import embed

ARTIFACT_VERSION = 1
FEATURE_KIND = "l2norm_product"  # elementwise product of L2-normalized prompt,row vectors


def _l2norm(matrix):
    m = np.asarray(matrix, dtype=float)
    return m / (np.linalg.norm(m, axis=1, keepdims=True) + 1e-9)


def build_features(prompts, rowtexts):
    """(prompts, rowtexts) -> raw product feature matrix (n x d). Embeds once.

    Pinned to embed._embed_raw + L2-normalize + elementwise product — the single feature
    definition shared by train and inference. NOT standardized here; standardization lives
    in the fitted head so train and infer apply the SAME shift/scale.
    """
    prompt_vecs = _l2norm(embed._embed_raw(list(prompts)))
    row_vecs = _l2norm(embed._embed_raw(list(rowtexts)))
    if prompt_vecs.shape != row_vecs.shape:
        raise ValueError(
            f"prompt/row embedding shape mismatch: {prompt_vecs.shape} vs {row_vecs.shape}"
        )
    return prompt_vecs * row_vecs


def _sigmoid(z):
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))


def _fit_logreg(features, labels, l2, iters=800, lr=0.5):
    """L2-regularized logistic via plain gradient descent (spike's recipe — pure numpy,
    no sklearn dependency to ship). Heavy l2 is the overfit defense at this n."""
    n, d = features.shape
    weights = np.zeros(d)
    bias = 0.0
    labels = np.asarray(labels, dtype=float)
    for _ in range(iters):
        pred = _sigmoid(features @ weights + bias)
        grad = pred - labels
        weights -= lr * (features.T @ grad / n + l2 * weights / n)
        bias -= lr * grad.mean()
    return weights, bias


class RelevanceHead:
    """Fitted head: standardization (mean/std) + logistic weights, bound to the embedding
    model id it was trained on. predict_proba_raw consumes RAW product features and applies
    the stored standardization, so callers never re-derive the transform — that keeps the
    train/infer feature path identical."""

    def __init__(self, weights, bias, mean, std, l2, model_name,
                 version=ARTIFACT_VERSION, feature_kind=FEATURE_KIND,
                 train_auc=None, cv_auc=None, cv_ci=None):
        self.weights = np.asarray(weights, dtype=float)
        self.bias = float(bias)
        self.mean = np.asarray(mean, dtype=float)
        self.std = np.asarray(std, dtype=float)
        self.l2 = float(l2)
        self.model_name = model_name
        self.version = version
        self.feature_kind = feature_kind
        self.train_auc = train_auc
        self.cv_auc = cv_auc
        self.cv_ci = cv_ci

    @classmethod
    def fit(cls, raw_features, labels, l2, model_name=None, **meta):
        raw_features = np.asarray(raw_features, dtype=float)
        mean = raw_features.mean(0)
        std = raw_features.std(0) + 1e-9
        standardized = (raw_features - mean) / std
        weights, bias = _fit_logreg(standardized, labels, l2)
        return cls(weights, bias, mean, std, l2,
                   model_name or embed.MODEL_NAME, **meta)

    def predict_proba_raw(self, raw_features):
        standardized = (np.asarray(raw_features, dtype=float) - self.mean) / self.std
        return _sigmoid(standardized @ self.weights + self.bias)

    def score(self, prompts, rowtexts):
        """End-to-end P(helpful) for (prompt, rowtext) pairs — the runtime entrypoint."""
        return self.predict_proba_raw(build_features(prompts, rowtexts))

    def save(self, path):
        with open(path, "w") as fh:
            json.dump({
                "version": self.version,
                "feature_kind": self.feature_kind,
                "model_name": self.model_name,
                "dim": int(self.weights.shape[0]),
                "l2": self.l2,
                "weights": self.weights.tolist(),
                "bias": self.bias,
                "mean": self.mean.tolist(),
                "std": self.std.tolist(),
                "train_auc": self.train_auc,
                "cv_auc": self.cv_auc,
                "cv_ci": self.cv_ci,
            }, fh, indent=2)

    @classmethod
    def load(cls, path, live_model_name=None):
        with open(path) as fh:
            data = json.load(fh)
        live = live_model_name or embed.MODEL_NAME
        if data["model_name"] != live:
            raise ValueError(
                f"relevance head trained on embedding model {data['model_name']!r} "
                f"but live model is {live!r}; refusing to load "
                "(embedding-version coupling, contract §2)"
            )
        if data.get("feature_kind") != FEATURE_KIND:
            raise ValueError(
                f"unknown feature_kind {data.get('feature_kind')!r}; "
                f"this build only knows {FEATURE_KIND!r}"
            )
        return cls(
            data["weights"], data["bias"], data["mean"], data["std"], data["l2"],
            data["model_name"], version=data["version"],
            feature_kind=data["feature_kind"], train_auc=data.get("train_auc"),
            cv_auc=data.get("cv_auc"), cv_ci=data.get("cv_ci"),
        )
