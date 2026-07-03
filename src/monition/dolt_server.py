"""Resident `dolt sql-server` lifecycle (opt-in via MONITION_SQL_SERVER).

Why this exists: concurrent `dolt sql -q` writes to one Dolt store contend on the
file/manifest lock — under load most are bounced ("cannot update manifest:
database is read only"), and a bounced firing is a lost firing. A running
`dolt sql-server` serializes writes in-process, and the dolt CLI auto-detects it
(via `.dolt/sql-server.info`) and routes every `dolt sql -q` through it — so the
existing subprocess write path becomes contention-free with *no* client change.
This module ensures such a server is running and, via address(), tells the
optional wire client (storage_backends, `[wire]` extra, Phase 8) where to
connect so queries skip the CLI spawn entirely.

Opt-in, off by default (mirrors the embed warm daemon): default behaviour is the
per-call subprocess path, byte-for-byte unchanged. Fail-open is absolute — a
spawn or probe failure must never block a write; the caller proceeds on the plain
subprocess path (lossy-under-contention, exactly as before).

Auto-routing means whoever spawns the server fixes the whole fleet: even a session
that never sets MONITION_SQL_SERVER routes its `dolt sql -q` through a server
another session started. The flag is set machine-wide in the same hand-maintained
settings env block as MONITION_STORE (a step CMS documents and `--doctor`s, not
bootstrap automation — see the 2026-07-02 correction in
docs/decisions/2026-06-19-dolt-sql-server-write-path.md), so every session's
writes serialize through the shared server.
"""
import errno
import fcntl
import hashlib
import os
import signal
import socket
import subprocess
import time

# Cold-spawn readiness budget. Server bind is ~0.2s empirically; poll up to this
# long for it to accept, then fail-open. Well under the 30s hook timeout.
_READY_TIMEOUT = 5.0
_POLL_INTERVAL = 0.05
_PORT_PROBE_TIMEOUT = 0.5  # a wedged server must not stall a write
_STOP_GRACE = 2.0  # SIGTERM grace before escalating to SIGKILL on stop()


def enabled():
    return bool(os.environ.get("MONITION_SQL_SERVER"))


def _info_path(store_path):
    return os.path.join(store_path, ".dolt", "sql-server.info")


def _lock_path(store_path):
    return os.path.join(store_path, ".dolt", "monition-sqlserver.lock")


def _port_for(store_path):
    """A deterministic, per-store port so distinct Dolt stores on one machine
    never collide on dolt's default 3306. The bound port is recorded in `.info`
    and the co-located CLI reads it from there, so the exact value is transparent
    to readers — it only needs to be stable per store and free of the default.
    sha256 (not the salted builtin hash) keeps it stable across processes."""
    h = int(hashlib.sha256(os.path.abspath(store_path).encode()).hexdigest(), 16)
    return 10000 + (h % 50000)


def _read_info(store_path):
    """Parse `.dolt/sql-server.info` (`PID:PORT:UUID`) → (pid, port), or None when
    absent/malformed. dolt writes this when a server binds and reads it to route
    CLI calls; a stale file from a dead owner is detected via the PID liveness
    check, never here."""
    try:
        with open(_info_path(store_path)) as f:
            parts = f.read().strip().split(":")
        return int(parts[0]), int(parts[1])
    except (OSError, ValueError, IndexError):
        return None


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
    except OSError as e:
        return e.errno != errno.ESRCH  # EPERM still means the pid is live
    return True


def _port_open(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(_PORT_PROBE_TIMEOUT)
    try:
        s.connect(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def running(store_path):
    """A server is *accepting* on this store — info file + live PID + open port.
    The gate must require accepting, not just a live PID: a server that has bound
    the store lock but isn't yet listening would let a racing `dolt sql -q` fall
    through to direct access and hit the read-only lock. Cheap when healthy (a
    localhost connect is instant); only a wedged server pays the probe timeout."""
    info = _read_info(store_path)
    return bool(info and _pid_alive(info[0]) and _port_open(info[1]))


def address(store_path):
    """('127.0.0.1', port) when a server is accepting on this store, else None.
    The wire client (storage_backends, `[wire]` extra) connects here instead of
    spawning the dolt CLI per query; same accepting-gate as running()."""
    info = _read_info(store_path)
    if info and _pid_alive(info[0]) and _port_open(info[1]):
        return ("127.0.0.1", info[1])
    return None


def ensure_running(store_path, dolt_bin):
    """Best-effort: guarantee a `dolt sql-server` is *accepting* on `store_path`
    before the caller's `dolt sql -q` runs, so concurrent writes serialize through
    it instead of contending on the manifest lock. No-op when disabled or already
    serving. Fail-open: any spawn/probe error returns silently and the caller falls
    back to the plain subprocess path."""
    if not enabled() or dolt_bin is None:
        return
    if running(store_path):  # steady state: no lock taken once the server is up
        return
    # Serialize the *spawn* across racing callers (threads and separate session
    # processes alike) with a file lock. A thundering herd of `dolt sql-server`
    # spawns on one port churns the .info file — losers' processes write-then-
    # remove it — so some callers never see a stable "accepting" state and fall
    # through to a contended write. Only the lock holder spawns; the rest block
    # here, then re-check and return the moment the server is accepting.
    try:
        lock_fd = os.open(_lock_path(store_path), os.O_CREAT | os.O_RDWR, 0o644)
    except OSError:
        return  # can't open the lock (read-only FS, perms) — fail-open
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        if running(store_path):
            return  # another holder already started it
        try:
            subprocess.Popen(
                [dolt_bin, "sql-server", "--port", str(_port_for(store_path))],
                cwd=store_path, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, start_new_session=True,
            )
        except Exception:
            return  # spawn failed — fail-open onto the subprocess path
        deadline = time.monotonic() + _READY_TIMEOUT
        while time.monotonic() < deadline:
            if running(store_path):
                return
            time.sleep(_POLL_INTERVAL)
        # not accepting in budget — fail-open; the write proceeds on subprocess
    finally:
        os.close(lock_fd)  # also releases the flock


def status(store_path):
    """Human-readable line for the `sql-server-status` verb."""
    info = _read_info(store_path)
    if info and running(store_path):
        return f"running (pid {info[0]}, port {info[1]})"
    return "not running"


def stop(store_path):
    """Terminate the server owning `store_path`, if any. Returns a status string.
    For explicit teardown (CMS bootstrap shutdown, tests); not on any hook path."""
    info = _read_info(store_path)
    if not info or not _pid_alive(info[0]):
        return "no running sql-server for this store"
    pid = info[0]
    # SIGTERM clears .info early but the dolt process can linger many seconds; a
    # lingering process still holds the store lock, so a half-dead server would
    # bounce the next direct write. Escalate to SIGKILL to guarantee the lock is
    # released. (Not on any hook path — explicit teardown only.)
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.kill(pid, sig)
        except OSError:
            break  # already gone
        deadline = time.monotonic() + _STOP_GRACE
        while time.monotonic() < deadline and _pid_alive(pid):
            time.sleep(_POLL_INTERVAL)
        if not _pid_alive(pid):
            break
    return f"stopped sql-server (pid {pid})"
