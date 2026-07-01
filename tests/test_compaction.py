"""Compaction re-arms per-session dedup.

Claude Code can compact a session (SessionStart `source: "compact"`), wiping
previously injected takeaway text from the context window while the
per-session dedup would still block a re-fire. The session-brief executor
records a compaction marker (the store's MAX(firings.id), in a per-machine
state file — markers are session state, not store data); `_not_yet_fired`
then counts only firings after the latest marker.
"""
import io
import json
import os
import shutil

import pytest

import monition.embed as me
import monition.session_state as ss
from monition.hooks import prompt_hook, session_brief
from monition.store_write import WriteStore


@pytest.fixture(autouse=True)
def isolated_state(monkeypatch, tmp_path_factory):
    """Markers live under XDG_STATE_HOME — isolate every test from the real one."""
    monkeypatch.setenv(
        "XDG_STATE_HOME", str(tmp_path_factory.mktemp("state")))


@pytest.fixture(autouse=True)
def lexical_only(monkeypatch):
    monkeypatch.setattr(me, "semantic_scores",
                        lambda q, texts: [0.0] * len(texts))


# ---- session_state unit -----------------------------------------------------


def test_marker_roundtrip_latest_wins():
    assert ss.compaction_floor("s1") == 0  # never compacted
    ss.record_compaction("s1", 42)
    assert ss.compaction_floor("s1") == 42
    ss.record_compaction("s1", 50)  # a later compaction supersedes
    assert ss.compaction_floor("s1") == 50
    assert ss.compaction_floor("other") == 0  # per-session, not global


def test_corrupt_marker_file_fails_open():
    ss.record_compaction("s1", 7)
    with open(ss._marker_file(), "w") as f:
        f.write("not json")
    assert ss.compaction_floor("s1") == 0


# ---- dedup floor ------------------------------------------------------------


def test_not_yet_fired_counts_only_post_marker_firings(store_copy):
    ws = WriteStore(store_copy)
    ws.fire("7", "on_demand", session="cmp1", context="migration")
    hits = json.loads(ws.on_demand_match("migration", session="cmp1"))["hits"]
    assert not any(h["id"] == 7 for h in hits)  # deduped as usual

    ss.record_compaction("cmp1", max(f.id for f in ws.firings()))
    hits = json.loads(ws.on_demand_match("migration", session="cmp1"))["hits"]
    assert any(h["id"] == 7 for h in hits)  # re-armed after compaction

    ws.fire("7", "on_demand", session="cmp1", context="migration")
    hits = json.loads(ws.on_demand_match("migration", session="cmp1"))["hits"]
    assert not any(h["id"] == 7 for h in hits)  # post-marker firing dedups again


# ---- hook end-to-end --------------------------------------------------------


@pytest.fixture
def host_repo(store_copy, tmp_path, monkeypatch):
    root = tmp_path / "hostrepo"
    os.makedirs(root)
    shutil.move(str(store_copy), str(root / "monition"))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    return str(root)


def _prompt(monkeypatch, capsys, session, prompt):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(
        {"session_id": session, "prompt": prompt})))
    prompt_hook()
    return capsys.readouterr().out


def _brief(monkeypatch, capsys, session, source):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(
        {"session_id": session, "source": source})))
    session_brief()
    return capsys.readouterr().out


def test_compact_brief_rearms_prompt_disclosure(host_repo, monkeypatch, capsys):
    assert "[t7/f" in _prompt(monkeypatch, capsys, "cc1", "migration plan")
    assert _prompt(monkeypatch, capsys, "cc1", "migration again") == ""

    _brief(monkeypatch, capsys, "cc1", "compact")

    # the compaction wiped the earlier disclosure from context -> re-fire
    assert "[t7/f" in _prompt(monkeypatch, capsys, "cc1", "migration once more")


def test_startup_brief_does_not_rearm(host_repo, monkeypatch, capsys):
    assert "[t7/f" in _prompt(monkeypatch, capsys, "cc2", "migration plan")
    _brief(monkeypatch, capsys, "cc2", "startup")
    assert _prompt(monkeypatch, capsys, "cc2", "migration again") == ""


def test_compact_rearms_session_start_rows_too(host_repo, monkeypatch, capsys):
    """The brief that carries source=compact re-discloses session_start rows
    it had already disclosed earlier in the session (t4/t6 in the fixture)."""
    first = _brief(monkeypatch, capsys, "cc3", "startup")
    assert "[t4/f" in first or "[t6/f" in first
    assert _brief(monkeypatch, capsys, "cc3", "resume") == ""  # deduped
    compacted = _brief(monkeypatch, capsys, "cc3", "compact")
    assert "[t4/f" in compacted or "[t6/f" in compacted
