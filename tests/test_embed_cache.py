"""v6 embed-cache unblock: model weights must land in a managed, persistent dir
(not ephemeral /tmp, which never survives a cold blocking hook). Uses a fake
fastembed so no real ~100MB download / onnxruntime runtime is needed."""
import os
import sys
import types

import monition.embed as me


def _fake_fastembed(captured):
    class FakeModel:
        def __init__(self, model_name, cache_dir):
            captured["model_name"] = model_name
            captured["cache_dir"] = cache_dir

        def embed(self, texts, batch_size=256):
            return [[0.1, 0.2] for _ in texts]

    mod = types.ModuleType("fastembed")
    mod.TextEmbedding = FakeModel
    return mod


def test_embed_raw_passes_managed_cache_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    captured = {}
    monkeypatch.setitem(sys.modules, "fastembed", _fake_fastembed(captured))
    monkeypatch.setattr(me, "_model", None)

    me._embed_raw(["hello"])

    expected = str(tmp_path / "monition" / "fastembed")
    assert captured["cache_dir"] == expected  # managed, not /tmp/fastembed_cache
    assert captured["model_name"] == me.MODEL_NAME
    assert os.path.isdir(expected)  # created before use


def test_warm_stages_weights(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setitem(sys.modules, "fastembed", _fake_fastembed({}))
    monkeypatch.setattr(me, "_model", None)

    msg = me.warm()
    assert str(tmp_path / "monition" / "fastembed") in msg


def test_warm_fails_open_without_fastembed(monkeypatch):
    # sys.modules[name] = None makes `import name` raise ImportError.
    monkeypatch.setitem(sys.modules, "fastembed", None)
    msg = me.warm()
    assert "not installed" in msg and "skipped" in msg
