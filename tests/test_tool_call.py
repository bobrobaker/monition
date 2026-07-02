"""B05: the tool_call module — execution-moment matching. Module unit
behavior, the store matcher, the fire-hook flow (a tool_call row fires on a
matching Bash input and not on a non-matching one), the set_trigger ladder
verb with provenance, and the settings-matcher replacement on sync."""
import io
import json
import os
import shutil

import pytest

from monition.hooks import fire_hook
from monition.init_sync import _merge_hook_entries, guarded_hook_command
from monition.modules import tool_call_match
from monition.store import Store, StoreContractError
from monition.store_write import WriteStore

SPEC = json.dumps({"tool": "Bash", "field": "command",
                   "contains": ["git push"]})


@pytest.fixture
def host_repo(store_copy, tmp_path, monkeypatch):
    root = tmp_path / "hostrepo"
    os.makedirs(root)
    shutil.move(str(store_copy), str(root / "monition"))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    ws = WriteStore(os.path.join(root, "monition"))
    ws.add("gotcha", "tool_call", "check push scope first",
           trigger_spec=SPEC, reach="general")
    return str(root)


def _run_fire_hook(monkeypatch, capsys, payload):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    fire_hook()
    return capsys.readouterr().out


# --- module unit ------------------------------------------------------------

def test_module_matches_and_carries_lossless_evidence():
    ev = tool_call_match(SPEC, "Bash", {"command": "cd x && git push origin"})
    assert ev == {"module": "tool_call", "tool": "Bash",
                  "pattern": "git push", "matched": "cd x && git push origin"}


def test_module_no_match_cases():
    assert tool_call_match(SPEC, "Bash", {"command": "git status"}) is None
    assert tool_call_match(SPEC, "Write", {"command": "git push"}) is None
    assert tool_call_match(SPEC, "Bash", {}) is None
    assert tool_call_match(SPEC, "Bash", {"command": 42}) is None
    assert tool_call_match(SPEC, "Bash", None) is None
    # fail-open on malformed spec, never an exception
    assert tool_call_match("not json", "Bash", {"command": "git push"}) is None
    assert tool_call_match(None, "Bash", {"command": "git push"}) is None


def test_matching_is_case_sensitive():
    assert tool_call_match(SPEC, "Bash", {"command": "GIT PUSH"}) is None


# --- store matcher + hook flow ----------------------------------------------

def test_fire_hook_fires_on_matching_bash_input(host_repo, monkeypatch, capsys):
    out = _run_fire_hook(monkeypatch, capsys, {
        "session_id": "tc1", "tool_name": "Bash",
        "tool_input": {"command": "git push origin main"},
    })
    assert "check push scope first" in out
    f = next(x for x in Store(os.path.join(host_repo, "monition")).firings()
             if x.session_id == "tc1")
    assert f.trigger_kind == "tool_call"
    ev = json.loads(f.match_evidence)
    assert ev["pattern"] == "git push"
    assert ev["matched"] == "git push origin main"  # lossless
    assert f.situation == "git push origin main"
    assert f.trigger_context == "Bash: git push origin main"


def test_fire_hook_silent_on_non_matching_bash(host_repo, monkeypatch, capsys):
    out = _run_fire_hook(monkeypatch, capsys, {
        "session_id": "tc2", "tool_name": "Bash",
        "tool_input": {"command": "git status"},
    })
    assert out == ""


def test_fire_hook_session_dedup_applies(host_repo, monkeypatch, capsys):
    payload = {"session_id": "tc3", "tool_name": "Bash",
               "tool_input": {"command": "git push"}}
    assert "check push scope" in _run_fire_hook(monkeypatch, capsys, payload)
    assert _run_fire_hook(monkeypatch, capsys, payload) == ""


def test_fire_hook_both_flows_one_call(host_repo, monkeypatch, capsys):
    """A Write under the repo can light edit_path AND tool_call rows."""
    ws = WriteStore(os.path.join(host_repo, "monition"))
    ws.add("gotcha", "tool_call", "careful with that content",
           trigger_spec=json.dumps({"tool": "Write", "field": "content",
                                    "contains": ["DROP TABLE"]}),
           reach="general")
    out = _run_fire_hook(monkeypatch, capsys, {
        "session_id": "tc4", "tool_name": "Write",
        "tool_input": {"file_path": os.path.join(host_repo, "docs/x.md"),
                       "content": "DROP TABLE users"},
    })
    assert "all noise" in out                  # edit_path row t1 (docs/*)
    assert "careful with that content" in out  # tool_call row


def test_add_validates_tool_call_spec(host_repo):
    ws = WriteStore(os.path.join(host_repo, "monition"))
    with pytest.raises(StoreContractError, match="tool_call trigger_spec"):
        ws.add("gotcha", "tool_call", "bad spec row", trigger_spec="not json")


# --- set_trigger (the migrate_kind verb) --------------------------------------

def test_set_trigger_migrates_with_provenance(store_copy):
    ws = WriteStore(store_copy)
    msg = ws.set_trigger(7, "tool_call", SPEC, source="B05 exemplar")
    assert "on_demand -> tool_call" in msg
    t = {x.id: x for x in ws.takeaways()}[7]
    assert t.trigger_kind == "tool_call"
    assert json.loads(t.trigger_spec) == json.loads(SPEC)
    m = ws.mutations()[-1]
    assert m.verb == "migrate_kind" and m.source == "B05 exemplar"
    changes = json.loads(m.changes)
    assert changes["trigger_kind"] == {"old": "on_demand", "new": "tool_call"}
    assert changes["trigger_spec"]["old"] == "migration, schema"


def test_set_trigger_guards(store_copy):
    ws = WriteStore(store_copy)
    with pytest.raises(StoreContractError, match="unknown trigger_kind"):
        ws.set_trigger(7, "telepathy", "spec")
    with pytest.raises(StoreContractError, match="no trigger_spec"):
        ws.set_trigger(7, "session_start", "dead spec")
    with pytest.raises(StoreContractError, match="tool_call trigger_spec"):
        ws.set_trigger(7, "tool_call", '{"tool": "Bash"}')  # no field/contains
    with pytest.raises(StoreContractError, match="non-empty trigger_spec"):
        ws.set_trigger(7, "edit_path", None)
    with pytest.raises(StoreContractError, match="no takeaway"):
        ws.set_trigger(999, "on_demand", "kw")
    assert ws.mutations() == []  # refused migrations leave no provenance


# --- dialect quoting regression (surfaced by JSON-in-JSON mutations) ---------

def test_sqlite_roundtrips_backslashes_and_quotes(store_copy):
    """MySQL-style escaping corrupts SQLite values (backslashes are literal
    there): a firing context with an apostrophe used to break the INSERT and
    a JSON value gained spurious backslashes. Round-trip both."""
    ws = WriteStore(store_copy)
    gnarly = "it's a \\\"quoted\\\" backslash-y 'context'"
    ws.fire("7", "on_demand", "q1", gnarly, situation=gnarly)
    f = next(x for x in Store(store_copy).firings() if x.session_id == "q1")
    assert f.trigger_context == gnarly
    assert f.situation == gnarly


# --- instrument: matcher-only change must replace the entry -------------------

def test_merge_hook_entries_replaces_stale_matcher():
    settings = {"hooks": {"PreToolUse": [
        {"matcher": "Write|Edit",
         "hooks": [{"type": "command",
                    "command": guarded_hook_command("fire-hook")}]},
    ]}}
    changed = _merge_hook_entries(settings)
    assert any("PreToolUse" in c for c in changed)
    pre = settings["hooks"]["PreToolUse"]
    ours = [e for e in pre
            if any("monition fire-hook" in h["command"] for h in e["hooks"])]
    assert len(ours) == 1 and ours[0]["matcher"] == "Write|Edit|Bash"
