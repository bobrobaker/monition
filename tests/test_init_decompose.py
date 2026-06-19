"""init decomposition (2026-06-19 decision): `init` = `init_store` + `instrument`.
Store-creation and instrumentation are now separable, in both directions."""
import json
import os

from monition.init_sync import init, init_store, instrument


def _read(path):
    with open(path) as f:
        return json.load(f)


def test_init_store_creates_store_no_instrumentation(tmp_path):
    store = str(tmp_path / "hub" / "monition")
    init_store(store)                                   # default SQLite
    assert os.path.exists(os.path.join(store, "store.db"))
    # pure store creation: no .claude wiring anywhere under the store's parent repo
    assert not os.path.exists(str(tmp_path / "hub" / ".claude"))


def test_instrument_wires_hooks_and_points_at_hub_no_store(tmp_path):
    root = str(tmp_path / "host")
    os.makedirs(root)
    hub = str(tmp_path / "hub" / "monition")
    instrument(root, store=hub)

    settings = _read(os.path.join(root, ".claude", "settings.json"))
    cmds = [h.get("command", "")
            for entries in settings["hooks"].values()
            for e in entries for h in e.get("hooks", [])]
    assert any("fire-hook" in c for c in cmds)          # hooks wired
    assert _read(os.path.join(root, ".mcp.json"))["mcpServers"]["monition"]
    # MONITION_STORE pointed at the hub, in the GITIGNORED local settings only
    local = _read(os.path.join(root, ".claude", "settings.local.json"))
    assert local["env"]["MONITION_STORE"] == os.path.abspath(hub)
    # and NO store was created in the instrumented repo
    assert not os.path.exists(os.path.join(root, "monition"))


def test_instrument_convention_store_writes_no_env(tmp_path):
    root = str(tmp_path / "host")
    os.makedirs(root)
    instrument(root, store=os.path.join(root, "monition"))   # the convention path
    local = os.path.join(root, ".claude", "settings.local.json")
    # convention resolves via the unset-MONITION_STORE fallback → no env baked
    assert not os.path.exists(local) or "MONITION_STORE" not in _read(local).get("env", {})


def test_init_is_composition(tmp_path):
    root = str(tmp_path / "host")
    os.makedirs(root)
    init(root)
    assert os.path.exists(os.path.join(root, "monition", "store.db"))      # init-store half
    assert "fire-hook" in open(os.path.join(root, ".claude", "settings.json")).read()  # instrument half
    # convention store → no MONITION_STORE env (preserves no-hub mode)
    local = os.path.join(root, ".claude", "settings.local.json")
    assert not os.path.exists(local) or "MONITION_STORE" not in _read(local).get("env", {})


def test_instrument_idempotent_repoint(tmp_path):
    root = str(tmp_path / "host")
    os.makedirs(root)
    a, b = str(tmp_path / "hubA"), str(tmp_path / "hubB")
    instrument(root, store=a)
    instrument(root, store=b)                            # re-point a clean re-join
    local = _read(os.path.join(root, ".claude", "settings.local.json"))
    assert local["env"]["MONITION_STORE"] == os.path.abspath(b)
