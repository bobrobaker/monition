"""Warm embed daemon (B05): opt-in, fail-open. Tested with a fake `_embed_raw`
(no real model) and an in-thread daemon (no subprocess). Two layers:
  - dispatch logic of `_embed` (stub `_daemon_embed`/`_spawn_daemon`);
  - socket protocol + lifecycle of `run_daemon`/`_daemon_embed` (real thread).
"""
import os
import socket
import threading
import time

import monition.embed as me


def _fake_embed_raw(texts):
    return [[float(len(t)), 1.0] for t in texts]


def _wait_socket(path, timeout=3):
    end = time.time() + timeout
    while time.time() < end:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            s.connect(path)
            return True
        except OSError:
            time.sleep(0.02)
        finally:
            s.close()
    return False


# ---- dispatch logic -------------------------------------------------------

def test_embed_default_is_in_process(monkeypatch):
    """Daemon off (default) → never touches the socket, pure in-process."""
    monkeypatch.delenv("MONITION_EMBED_DAEMON", raising=False)
    monkeypatch.setattr(me, "_embed_raw", _fake_embed_raw)
    monkeypatch.setattr(me, "_daemon_embed",
                        lambda t: (_ for _ in ()).throw(AssertionError("touched daemon")))
    assert me._embed(["abc"]) == _fake_embed_raw(["abc"])


def test_embed_uses_daemon_when_up(monkeypatch):
    """Opt-in + daemon answers → use its result, no fallback, no spawn."""
    monkeypatch.setenv("MONITION_EMBED_DAEMON", "1")
    sentinel = [[9.0, 9.0]]
    monkeypatch.setattr(me, "_daemon_embed", lambda t: sentinel)
    monkeypatch.setattr(me, "_embed_raw",
                        lambda t: (_ for _ in ()).throw(AssertionError("fell back")))
    monkeypatch.setattr(me, "_spawn_daemon",
                        lambda: (_ for _ in ()).throw(AssertionError("spawned")))
    assert me._embed(["abc"]) is sentinel


def test_embed_falls_back_and_spawns_when_daemon_down(monkeypatch):
    """Opt-in but daemon unreachable → serve in-process now, spawn one for later."""
    monkeypatch.setenv("MONITION_EMBED_DAEMON", "1")
    monkeypatch.setattr(me, "_daemon_embed",
                        lambda t: (_ for _ in ()).throw(OSError("no daemon")))
    monkeypatch.setattr(me, "_embed_raw", _fake_embed_raw)
    spawned = []
    monkeypatch.setattr(me, "_spawn_daemon", lambda: spawned.append(True))
    assert me._embed(["abc"]) == _fake_embed_raw(["abc"])
    assert spawned == [True]


# ---- socket protocol + lifecycle ------------------------------------------

def test_daemon_roundtrip_and_idle_exit(monkeypatch, tmp_path):
    sock = str(tmp_path / "d.sock")
    monkeypatch.setattr(me, "_socket_path", lambda: sock)
    monkeypatch.setattr(me, "_embed_raw", _fake_embed_raw)
    t = threading.Thread(target=me.run_daemon, kwargs={"idle_timeout": 1}, daemon=True)
    t.start()
    assert _wait_socket(sock)
    assert me._daemon_embed(["hello", "x"]) == _fake_embed_raw(["hello", "x"])
    t.join(timeout=4)
    assert not t.is_alive()            # idle-exited
    assert not os.path.exists(sock)    # cleaned up its socket


def test_second_daemon_exits_if_one_is_live(monkeypatch, tmp_path):
    sock = str(tmp_path / "d.sock")
    monkeypatch.setattr(me, "_socket_path", lambda: sock)
    monkeypatch.setattr(me, "_embed_raw", _fake_embed_raw)
    t = threading.Thread(target=me.run_daemon, kwargs={"idle_timeout": 2}, daemon=True)
    t.start()
    assert _wait_socket(sock)
    start = time.time()
    me.run_daemon(idle_timeout=2)      # a live daemon owns the socket → return now
    assert time.time() - start < 1.5
    t.join(timeout=5)


def test_daemon_reclaims_stale_socket(monkeypatch, tmp_path):
    sock = str(tmp_path / "d.sock")
    monkeypatch.setattr(me, "_socket_path", lambda: sock)
    monkeypatch.setattr(me, "_embed_raw", _fake_embed_raw)
    # leave a stale socket file: bound then closed, no listener.
    stale = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    stale.bind(sock)
    stale.close()
    assert os.path.exists(sock)
    t = threading.Thread(target=me.run_daemon, kwargs={"idle_timeout": 1}, daemon=True)
    t.start()
    assert _wait_socket(sock)          # reclaimed the stale path and now serves
    assert me._daemon_embed(["y"]) == _fake_embed_raw(["y"])
    t.join(timeout=4)
