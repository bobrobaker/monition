"""Optional embedding layer for on_demand retrieval.

Backend is fastembed (install via `monition[embed]`), imported lazily so the
module loads fine without it. Vectors live in a derivable JSON cache under
XDG_CACHE_HOME keyed by (model, text) hash — never in the Dolt store; deleting
the cache is always safe. Callers must treat any exception from this module as
"embeddings unavailable" and degrade to lexical matching.
"""
import hashlib
import json
import os

MODEL_NAME = "BAAI/bge-small-en-v1.5"
SIM_THRESHOLD = 0.6

_model = None


def _cache_file():
    root = os.environ.get("XDG_CACHE_HOME") or os.path.join(
        os.path.expanduser("~"), ".cache"
    )
    return os.path.join(root, "monition", "embed-cache.json")


def _key(text):
    return hashlib.sha256(f"{MODEL_NAME}::{text}".encode()).hexdigest()


def _load_cache():
    try:
        with open(_cache_file()) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_cache(cache):
    path = _cache_file()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(cache, f)


def _embed_raw(texts):
    global _model
    if _model is None:
        from fastembed import TextEmbedding
        _model = TextEmbedding(model_name=MODEL_NAME)
    return [[float(x) for x in v] for v in _model.embed(texts)]


def embed_texts(texts):
    cache = _load_cache()
    missing = [t for t in texts if _key(t) not in cache]
    if missing:
        for t, v in zip(missing, _embed_raw(missing)):
            cache[_key(t)] = v
        _save_cache(cache)
    return [cache[_key(t)] for t in texts]


def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return 0.0 if na == 0.0 or nb == 0.0 else dot / (na * nb)


def semantic_scores(query, texts):
    """Cosine similarity of each text to the query, in input order."""
    vecs = embed_texts([query] + list(texts))
    q = vecs[0]
    return [cosine(q, v) for v in vecs[1:]]
