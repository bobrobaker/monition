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
import socket
import subprocess
import sys

MODEL_NAME = "BAAI/bge-small-en-v1.5"
SIM_THRESHOLD = 0.6

# Warm daemon (opt-in): a long-lived process holds the model in memory so cold
# hooks pay the ~1s load once instead of every fire. Off by default — the in-process
# path is unchanged. Fail-open is absolute: a missing/wedged daemon must never block.
DAEMON_IDLE_TIMEOUT = 300  # seconds with no connection → the daemon exits
_DAEMON_CONNECT_TIMEOUT = 5  # a wedged daemon must not stall a prompt
# ONNX runtime's arena allocator grows but never shrinks, so one large request
# permanently inflates the daemon (observed: 106MB → 1.8GB, 2026-07-03). Above this
# RSS the daemon exits after serving; callers fall back in-process and respawn a
# fresh one, so the ceiling costs at most one warm-up.
DAEMON_RSS_MAX_MB = 600

_model = None


def _cache_root():
    return os.environ.get("XDG_CACHE_HOME") or os.path.join(
        os.path.expanduser("~"), ".cache"
    )


def _cache_file():
    return os.path.join(_cache_root(), "monition", "embed-cache.json")


def _weights_dir():
    """Managed, persistent home for the fastembed model weights. Without an
    explicit cache_dir fastembed downloads into an ephemeral /tmp dir, which never
    survives a cold blocking hook under the 30s timeout — semantic matching then
    silently never works. Staging weights here (once, off the hook path) is the
    actual unblock."""
    return os.path.join(_cache_root(), "monition", "fastembed")


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
        cache_dir = _weights_dir()
        os.makedirs(cache_dir, exist_ok=True)
        _model = TextEmbedding(model_name=MODEL_NAME, cache_dir=cache_dir)
    # batch_size caps ONNX attention memory (batch × seq_len² × heads): fastembed's
    # default 256 is fine for short row texts but spikes to multi-GB on batches of
    # 512-token prompts (full `situation` texts) — 16 keeps peak ~hundreds of MB.
    return [[float(x) for x in v] for v in _model.embed(texts, batch_size=16)]


def warm():
    """Pre-fetch the model weights into the managed cache, off any hook path.
    Returns a status string. Fail-open on a missing extra: the embed layer is
    optional and callers degrade to lexical, so an absent fastembed is "skipped",
    not an error. A genuine download failure propagates (the caller surfaces it)."""
    try:
        import fastembed  # noqa: F401
    except ImportError:
        return "fastembed not installed (pip install 'monition[embed]') — semantic matching disabled, skipped"
    _embed_raw(["warm"])  # forces the weight download into _weights_dir()
    return f"embedding weights staged at {_weights_dir()}"


def _rss_mb():
    """Own resident set size in MB via /proc (Linux-only, like the socket path).
    0 on any read problem — fail-open: an unreadable statm must not kill the daemon."""
    try:
        with open("/proc/self/statm") as f:
            return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") // (1024 * 1024)
    except Exception:
        return 0


def _daemon_enabled():
    return bool(os.environ.get("MONITION_EMBED_DAEMON"))


def _socket_path():
    root = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
    return os.path.join(root, "monition-embed.sock")


def _daemon_embed(texts):
    """Client: ask the warm daemon to embed `texts`. Raises on any socket problem
    so the caller falls back — a short timeout guarantees a wedged daemon can never
    stall a prompt. Protocol: one newline-framed JSON request/response per call."""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(_DAEMON_CONNECT_TIMEOUT)
    try:
        s.connect(_socket_path())
        f = s.makefile("rwb")
        f.write((json.dumps({"texts": list(texts)}) + "\n").encode())
        f.flush()
        line = f.readline()
        if not line:
            raise OSError("daemon closed the connection")
        return json.loads(line)["vecs"]
    finally:
        s.close()


def _spawn_daemon():
    """Fire-and-forget: start the warm daemon detached. Never waits, never raises
    into the caller — a spawn failure just means we stay on the in-process path."""
    try:
        subprocess.Popen(
            [sys.executable, "-c", "import monition.embed as e; e.run_daemon()"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True,
        )
    except Exception:
        pass


def _embed(texts):
    """Daemon-aware embed dispatcher. Opt-in via MONITION_EMBED_DAEMON; fail-open
    chain: daemon socket → spawn-and-serve-in-process → (caller) lexical. Default
    off = the in-process primitive only, behaviourally identical to pre-daemon."""
    if not _daemon_enabled():
        return _embed_raw(texts)
    try:
        return _daemon_embed(texts)
    except Exception:
        _spawn_daemon()           # warm one for next time
        return _embed_raw(texts)  # serve this call now — never block on warm-up


def _serve_one(conn):
    """Answer one embed request. A bad/short request is swallowed, never fatal to
    the daemon."""
    try:
        f = conn.makefile("rwb")
        line = f.readline()
        if not line:
            return
        texts = json.loads(line)["texts"]
        vecs = _embed_raw(texts)
        f.write((json.dumps({"vecs": vecs}) + "\n").encode())
        f.flush()
    except Exception:
        pass


def run_daemon(idle_timeout=DAEMON_IDLE_TIMEOUT):
    """Warm embed daemon: hold the model in memory, answer embed requests over a
    unix socket, idle-exit after `idle_timeout` seconds with no connection. One per
    machine — if a live daemon already owns the socket we exit immediately; a stale
    socket (owner died) is reclaimed. Fail-open: any error ends the daemon cleanly,
    callers just fall back to in-process."""
    path = _socket_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            probe.connect(path)
            return  # a live daemon already serves — we're redundant
        except OSError:
            os.unlink(path)  # stale socket from a dead owner — reclaim it
        finally:
            probe.close()
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        srv.bind(path)
    except OSError:
        return  # lost a bind race to another daemon
    srv.listen(8)
    srv.settimeout(idle_timeout)
    try:
        _embed_raw(["warm"])  # load the model once, here, off any hook path
    except Exception:
        pass
    try:
        while True:
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                return  # idle → exit
            with conn:
                _serve_one(conn)
            if _rss_mb() > DAEMON_RSS_MAX_MB:
                return  # arena bloated past the ceiling → exit; next caller respawns fresh
    finally:
        srv.close()
        try:
            os.unlink(path)
        except OSError:
            pass


def embed_texts(texts):
    from . import trace
    cache = _load_cache()
    trace.mark("embed:cache_loaded")
    missing = [t for t in texts if _key(t) not in cache]
    if missing:
        for t, v in zip(missing, _embed(missing)):
            cache[_key(t)] = v
        trace.mark(f"embed:vectorized({len(missing)} miss)")
        _save_cache(cache)
        trace.mark("embed:cache_saved")
    return [cache[_key(t)] for t in texts]


def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return 0.0 if na == 0.0 or nb == 0.0 else dot / (na * nb)


def semantic_scores(query, texts):
    """Cosine similarity of each text to the query, in input order."""
    from . import trace
    vecs = embed_texts([query] + list(texts))
    q = vecs[0]
    scores = [cosine(q, v) for v in vecs[1:]]
    trace.mark(f"embed:cosine({len(texts)} vecs)")
    return scores
