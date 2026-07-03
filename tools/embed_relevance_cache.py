#!/usr/bin/env python3
"""Precompute the B06 embedding cache: every unique text the relevance tooling
needs (distinct dataset prompts + distinct row texts), embedded once and stored
on disk. Downstream tools (train_relevance_head --embed-cache, the metamatch
eval) then run in seconds with no model in memory.

Deliberately separate from embed.py's hook-path cache (`_load_cache`) — that
JSON is loaded on every hook call and must stay small; 4000-char prompt entries
do not belong in it.

Resumable: vectors append to the JSONL as they are computed, keyed by
sha256(text); a killed run loses at most one chunk. Chunked small so peak
memory stays low regardless of fastembed internals.

    .venv/bin/python tools/embed_relevance_cache.py [--store DIR] [--dataset PATH]
"""
import argparse
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from monition import embed
from monition.store import Store
from monition.store_write import resolve_store_path

DEFAULT_DATASET = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "data", "relevance-cascade", "labels.jsonl"
)
DEFAULT_CACHE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "data", "relevance-cascade", "embed_cache.jsonl"
)
CHUNK = 8  # texts per _embed_raw call — small keeps peak memory low


def text_key(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_cache(path):
    cache = {}
    if os.path.exists(path):
        with open(path) as fh:
            for line in fh:
                if line.strip():
                    rec = json.loads(line)
                    cache[rec["k"]] = rec["v"]
    return cache


def unique_texts(dataset_path, store_path):
    with open(dataset_path) as fh:
        prompts = {json.loads(l)["prompt"] for l in fh if l.strip()}
    store = Store(store_path)
    rowtexts = {f"{t.one_liner} {t.trigger_spec or ''}".strip() for t in store.takeaways()}
    return sorted(prompts | rowtexts)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--store", help="store directory (default: MONITION_STORE / convention)")
    ap.add_argument("--dataset", default=DEFAULT_DATASET)
    ap.add_argument("--cache", default=DEFAULT_CACHE)
    args = ap.parse_args(argv)

    texts = unique_texts(args.dataset, args.store or resolve_store_path())
    cache = load_cache(args.cache)
    todo = [t for t in texts if text_key(t) not in cache]
    print(f"unique texts: {len(texts)}  cached: {len(texts) - len(todo)}  to embed: {len(todo)}",
          flush=True)

    os.makedirs(os.path.dirname(os.path.abspath(args.cache)), exist_ok=True)
    with open(args.cache, "a") as out:
        for i in range(0, len(todo), CHUNK):
            chunk = todo[i:i + CHUNK]
            for text, vec in zip(chunk, embed._embed_raw(chunk)):
                out.write(json.dumps({"k": text_key(text), "v": vec}) + "\n")
            out.flush()
            print(f"embedded {min(i + CHUNK, len(todo))}/{len(todo)}", flush=True)
    print(f"cache complete -> {args.cache}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
