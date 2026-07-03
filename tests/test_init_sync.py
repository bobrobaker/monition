"""init / sync / migrate (spec decisions 5–6, 9).

Everything runs against throwaway tmp host repos; no test touches a real repo.
Core invariant: init's DDL passes the reader's own fingerprint check.

Dolt-specific tests (migrate, v1 dialect) are skipped when dolt is unavailable.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess

import pytest

import monition.init_sync as ins
from monition.hooks import guarded_hook_command
from monition.init_sync import init, migrate, sync
from monition.store import Store, StoreContractError

from .conftest import build_dolt_store, build_store

dolt_only = pytest.mark.skipif(
    not (shutil.which("dolt") or os.path.exists(os.path.expanduser("~/.local/bin/dolt"))),
    reason="dolt binary not available",
)


@pytest.fixture
def host(tmp_path):
    root = tmp_path / "host"
    os.makedirs(root / ".git" / "hooks")  # enough git-ness for the dump hook
    (root / "README.md").write_text("# host project\n")
    return str(root)


def tree_digest(root):
    """Stable digest of every file under root (paths + contents)."""
    h = hashlib.sha256()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            p = os.path.join(dirpath, name)
            h.update(os.path.relpath(p, root).encode())
            with open(p, "rb") as f:
                h.update(f.read())
    return h.hexdigest()


def test_init_creates_working_store_and_wiring(host):
    changes = init(host)
    assert any("create Monition store" in c for c in changes)

    Store(os.path.join(host, "monition"))  # reader fingerprint check passes

    with open(os.path.join(host, ".claude", "settings.json")) as f:
        settings = json.load(f)
    commands = [h["command"]
                for event in ("PreToolUse", "SessionStart", "UserPromptSubmit")
                for entry in settings["hooks"][event]
                for h in entry["hooks"]]
    assert guarded_hook_command("fire-hook") in commands
    assert guarded_hook_command("session-brief") in commands
    assert guarded_hook_command("prompt-hook") in commands
    pre = settings["hooks"]["PreToolUse"][0]
    assert pre["matcher"] == "Write|Edit|Bash"

    with open(os.path.join(host, ".mcp.json")) as f:
        mcp = json.load(f)
    assert mcp["mcpServers"]["monition"] == {
        "command": "monition", "args": ["mcp-serve"]}

    skill = os.path.join(host, ".claude", "skills", "mine-session", "SKILL.md")
    with open(skill) as f:
        content = f.read()
    assert ins._STAMP_RE.match(content)
    assert "monition add" in content

    with open(os.path.join(host, "README.md")) as f:
        assert "uv tool install" in f.read()

    # hook offered, not installed
    assert any(c.startswith("offer: pre-commit") for c in changes)
    assert not os.path.exists(os.path.join(host, ".git", "hooks", "pre-commit"))


def test_init_idempotent(host):
    init(host)
    digest = tree_digest(host)
    changes = init(host)
    assert changes[0] == "no changes (already initialized)"
    assert tree_digest(host) == digest


def test_dry_run_writes_nothing(host):
    digest = tree_digest(host)
    changes = init(host, dry_run=True)
    assert tree_digest(host) == digest
    assert not os.path.exists(os.path.join(host, "monition"))
    assert any(c.startswith("would create Monition store") for c in changes)
    assert any(c.startswith("would merge guarded hooks") for c in changes)


def test_init_sqlite_does_not_require_dolt(host, monkeypatch):
    """SQLite default: init succeeds even when dolt binary is absent."""
    monkeypatch.setattr(ins, "_dolt_bin", lambda: None)
    changes = init(host)
    assert any("sqlite" in c for c in changes)
    Store(os.path.join(host, "monition"))  # fingerprint check passes


def test_init_dolt_fails_clearly_without_dolt(host, monkeypatch):
    monkeypatch.setattr(ins, "_dolt_bin", lambda: None)
    with pytest.raises(StoreContractError, match="dolt binary not found"):
        init(host, dolt=True)
    assert not os.path.exists(os.path.join(host, "monition"))
    assert not os.path.exists(os.path.join(host, ".claude"))


def test_init_preserves_unrelated_settings(host):
    spath = os.path.join(host, ".claude", "settings.json")
    os.makedirs(os.path.dirname(spath))
    existing = {
        "permissions": {"allow": ["Bash(ls:*)"]},
        "hooks": {"PreToolUse": [
            {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo hi"}]}
        ]},
    }
    with open(spath, "w") as f:
        json.dump(existing, f)
    init(host)
    with open(spath) as f:
        merged = json.load(f)
    assert merged["permissions"] == existing["permissions"]
    pre = merged["hooks"]["PreToolUse"]
    assert pre[0] == existing["hooks"]["PreToolUse"][0]  # untouched, still first
    assert pre[1]["hooks"][0]["command"] == guarded_hook_command("fire-hook")


def test_init_preserves_unrelated_mcp_servers(host):
    mpath = os.path.join(host, ".mcp.json")
    existing = {"mcpServers": {"other": {"command": "other-server"}}}
    with open(mpath, "w") as f:
        json.dump(existing, f)
    init(host)
    with open(mpath) as f:
        merged = json.load(f)
    assert merged["mcpServers"]["other"] == existing["mcpServers"]["other"]
    assert merged["mcpServers"]["monition"]["command"] == "monition"


def _hook_commands(host, event, token):
    with open(os.path.join(host, ".claude", "settings.json")) as f:
        settings = json.load(f)
    return [h["command"] for entry in settings["hooks"].get(event, [])
            for h in entry.get("hooks", []) if token in h.get("command", "")]


def test_stale_hook_command_is_replaced_not_appended(host):
    """A monition hook entry is identified by its subcommand token: when the
    guarded command changes between versions, sync replaces the stale entry
    instead of appending the new one beside it."""
    init(host)
    spath = os.path.join(host, ".claude", "settings.json")
    with open(spath) as f:
        settings = json.load(f)
    for entry in settings["hooks"]["UserPromptSubmit"]:
        for h in entry["hooks"]:
            if "monition prompt-hook" in h["command"]:
                h["command"] = "monition prompt-hook || true"  # older guard
    with open(spath, "w") as f:
        json.dump(settings, f)

    changes = sync(host)
    assert any("UserPromptSubmit (replaced)" in c for c in changes)
    assert (_hook_commands(host, "UserPromptSubmit", "monition prompt-hook")
            == [guarded_hook_command("prompt-hook")])


def test_accumulated_stale_duplicates_collapse_to_one(host):
    """Pre-fix repos may carry a stale entry beside a current one; the merge
    collapses them to exactly one current entry and touches nothing else."""
    init(host)
    spath = os.path.join(host, ".claude", "settings.json")
    with open(spath) as f:
        settings = json.load(f)
    foreign = {"hooks": [{"type": "command", "command": "echo unrelated"}]}
    settings["hooks"]["SessionStart"] = [
        {"hooks": [{"type": "command", "command": "monition session-brief"}]},
        foreign,
        {"hooks": [{"type": "command",
                    "command": guarded_hook_command("session-brief")}]},
    ]
    with open(spath, "w") as f:
        json.dump(settings, f)

    sync(host)
    assert (_hook_commands(host, "SessionStart", "monition session-brief")
            == [guarded_hook_command("session-brief")])
    with open(spath) as f:
        merged = json.load(f)
    assert foreign in merged["hooks"]["SessionStart"]  # unrelated untouched


def test_current_hooks_are_left_alone(host):
    """Idempotence survives the replace logic: a second sync changes nothing."""
    init(host)
    spath = os.path.join(host, ".claude", "settings.json")
    before = open(spath).read()
    changes = sync(host)
    assert not any("hook" in c for c in changes if not c.startswith("no changes"))
    assert open(spath).read() == before


def test_with_dump_hook_installs_pre_commit(host):
    init(host, with_dump_hook=True)
    hook = os.path.join(host, ".git", "hooks", "pre-commit")
    with open(hook) as f:
        content = f.read()
    assert "monition dump" in content
    assert os.access(hook, os.X_OK)
    # existing hook is never overwritten
    changes = init(host, with_dump_hook=True)
    assert any("exists — dump hook not installed" in c for c in changes)


def test_sync_upgrades_untouched_warns_on_edited(host):
    init(host)
    skill = os.path.join(host, ".claude", "skills", "mine-session", "SKILL.md")

    # untouched: simulate an older generation by re-stamping different body
    old_body = "old template body\n"
    with open(skill, "w") as f:
        f.write(ins._stamp(old_body) + old_body)
    changes = sync(host)
    assert any(c.startswith("upgraded skill mine-session") for c in changes)
    with open(skill) as f:
        assert "monition add" in f.read()

    # edited: body no longer matches its stamp
    with open(skill, "a") as f:
        f.write("\nlocal note\n")
    edited = open(skill).read()
    changes = sync(host)
    assert any(c.startswith("WARN: skill mine-session locally edited") for c in changes)
    assert open(skill).read() == edited  # left alone

    # nothing else to do
    spath = os.path.join(host, ".claude", "settings.json")
    before = open(spath).read()
    sync(host)
    assert open(spath).read() == before


def test_sync_ships_bundled_doc(host):
    """The bundled method/lesson-routing.md follows the same stamp + hash-check
    contract as skills: installed on init, upgraded when untouched, left with a
    WARN when locally edited."""
    init(host)
    doc = os.path.join(host, "method", "lesson-routing.md")
    with open(doc) as f:
        content = f.read()
    assert ins._STAMP_RE.match(content)
    assert "Lesson routing" in content  # the bundled doc body shipped

    # untouched: an older generation re-stamped onto a different body -> upgrade
    old_body = "# old routing doc\n"
    with open(doc, "w") as f:
        f.write(ins._stamp(old_body, "doc") + old_body)
    changes = sync(host)
    assert any(c.startswith("upgraded doc method/lesson-routing.md") for c in changes)
    assert "Lesson routing" in open(doc).read()

    # edited: body no longer matches its stamp -> WARN-and-leave
    with open(doc, "a") as f:
        f.write("\nlocal note\n")
    edited = open(doc).read()
    changes = sync(host)
    assert any(c.startswith("WARN: doc method/lesson-routing.md locally edited") for c in changes)
    assert open(doc).read() == edited


_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_routing_label_matches_routing_version():
    """ROUTING_VERSION (the human-readable legend in init_sync) must equal the
    `**Version:** routing vN` header of the bundled METHOD_LESSON_ROUTING doc, so
    the constant can't drift from the generated content. Always-on — runs on
    forks/CI too, since it reads only committed monition state."""
    m = re.search(r"(?m)^\*\*Version:\*\* routing v(\d+)", ins.METHOD_LESSON_ROUTING)
    assert m, "no `**Version:** routing vN` header in METHOD_LESSON_ROUTING"
    assert int(m.group(1)) == ins.ROUTING_VERSION, (
        f"doc header is routing v{m.group(1)} but ROUTING_VERSION is "
        f"{ins.ROUTING_VERSION} — bump ROUTING_VERSION when re-running regen"
    )


def _load_regen():
    """Import tools/regen_from_cms.py by path (tools/ isn't a package)."""
    import importlib.util
    path = os.path.join(_REPO_ROOT, "tools", "regen_from_cms.py")
    spec = importlib.util.spec_from_file_location("regen_from_cms", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_regen = _load_regen()


@pytest.mark.skipif(not os.path.isdir(_regen.cms_root()), reason="CMS not present (fork/CI)")
def test_generated_matches_cms_regen():
    """Dev-only anti-drift guarantee: re-run the CMS->monition transform in memory
    and assert it byte-matches the committed generated constants. When CMS is on
    this machine, an un-regenerated edit to CMS canonical (skill, fork-overrides,
    or lesson-routing.md) fails here. Subsumes the old CMS-version parity check:
    METHOD_LESSON_ROUTING is the verbatim CMS doc, so matching it == matching the
    CMS `**Version:** routing vN` header, which the label test ties to
    ROUTING_VERSION. No-ops on forks/CI (skipped)."""
    consts = _regen.build()
    assert consts["SKILL_MINE_SESSION"] == ins.SKILL_MINE_SESSION, (
        "SKILL_MINE_SESSION is stale — run `python tools/regen_from_cms.py`")
    assert consts["METHOD_LESSON_ROUTING"] == ins.METHOD_LESSON_ROUTING, (
        "METHOD_LESSON_ROUTING is stale — run `python tools/regen_from_cms.py`")


V1_SCHEMA = ins.V2_SCHEMA.replace(  # V1 uses the v2 base (no decisions)
    "status enum('active','retired') NOT NULL DEFAULT 'active',\n"
    "  mirror enum('none','candidate','mirrored') NOT NULL DEFAULT 'none',",
    "status enum('active','retired','upstream_candidate','mirrored')"
    " NOT NULL DEFAULT 'active',",
)

V1_ROWS = """
INSERT INTO takeaways (id, created, kind, trigger_kind, trigger_spec, one_liner, status) VALUES
  (1, '2026-01-01 10:00:00', 'gotcha', 'edit_path', 'a/*', 'plain active', 'active'),
  (2, '2026-01-01 10:00:00', 'rule', 'edit_path', 'b/*', 'was candidate', 'upstream_candidate'),
  (3, '2026-01-01 10:00:00', 'rule', 'session_start', NULL, 'was mirrored', 'mirrored'),
  (4, '2026-01-01 10:00:00', 'gotcha', 'edit_path', 'c/*', 'plain retired', 'retired');
"""


@dolt_only
def test_migrate_v1_to_v8(tmp_path):
    assert "upstream_candidate" in V1_SCHEMA  # the replace actually took
    store = str(tmp_path / "v1store")
    build_dolt_store(store, [V1_SCHEMA, V1_ROWS])
    with pytest.raises(StoreContractError, match="v1-dialect"):
        Store(store)

    msg = migrate(store)  # cumulative: v1 -> v2 -> ... -> v8
    assert "to v9" in msg

    s = Store(store)  # v8 fingerprint check passes post-migration
    rows = {t.id: t for t in s.takeaways()}
    # status split preserved; mirror retired at v6 (the candidate/mirrored
    # distinction is dropped — uniform reach='project' backfill, origin_repo from
    # the store's repo root).
    assert rows[1].status == "active"
    assert rows[2].status == "active"
    assert rows[3].status == "active"
    assert rows[4].status == "retired"
    origin = os.path.dirname(os.path.abspath(store))
    assert all(t.reach == "project" and t.origin_repo == origin for t in rows.values())


@dolt_only
def test_migrate_v3_to_v8_adds_provenance(tmp_path):
    store = str(tmp_path / "v3store")
    build_dolt_store(store, [ins.V3_SCHEMA])  # decisions present, firings lack provenance
    with pytest.raises(StoreContractError, match="upgrade to v4"):
        Store(store)

    msg = migrate(store)
    assert "to v9" in msg

    s = Store(store)  # v8 fingerprint passes; provenance + situation now present
    assert s.firings() == []  # empty store reads cleanly post-migration


@dolt_only
def test_migrate_v4_to_v8_adds_situation(tmp_path):
    store = str(tmp_path / "v4store")
    build_dolt_store(store, [ins.V4_SCHEMA])  # provenance present, firings lack situation
    with pytest.raises(StoreContractError, match="upgrade to v5"):
        Store(store)

    msg = migrate(store)
    assert "to v9" in msg

    s = Store(store)  # v8 fingerprint passes; situation column now present
    assert s.firings() == []


@dolt_only
def test_migrate_v5_to_v8_then_refuses(tmp_path):
    store = str(tmp_path / "v5store")
    build_dolt_store(store, [ins.V5_SCHEMA])  # situation present, takeaways lack reach
    with pytest.raises(StoreContractError, match="upgrade to v6"):
        Store(store)

    msg = migrate(store)
    assert "to v9" in msg
    Store(store)  # v8 fingerprint passes

    with pytest.raises(StoreContractError, match="already v9"):
        migrate(store)


@dolt_only
def test_migrate_v6_to_v8_adds_recall_column(tmp_path):
    store = str(tmp_path / "v6store")
    build_dolt_store(store, [ins.V6_SCHEMA])  # reach present, no violation_signature
    with pytest.raises(StoreContractError, match="upgrade to v7"):
        Store(store)

    msg = migrate(store)
    assert "to v9" in msg

    s = Store(store)  # v8 fingerprint passes; violations table reads cleanly
    assert s.violations() == []


def test_migrate_sqlite_v6_to_v8(tmp_path):
    """The SQLite ladder: a v6 SQLite store (created before the recall
    column shipped) gains the v7 + v8 pieces in place."""
    import sqlite3

    store = tmp_path / "sqlstore"
    store.mkdir()
    conn = sqlite3.connect(store / "store.db")
    conn.executescript(ins.V6_SCHEMA_SQLITE)
    conn.close()
    with pytest.raises(StoreContractError, match="upgrade to v7"):
        Store(str(store))

    msg = migrate(str(store))
    assert "to v9" in msg

    s = Store(str(store))  # v8 fingerprint passes
    assert s.violations() == []
    with pytest.raises(StoreContractError, match="already v9"):
        migrate(str(store))


def test_migrate_sqlite_v7_to_v8_rebuild_preserves_rows(tmp_path):
    """v7→v8 on SQLite is a takeaways table rebuild (the CHECK constraint
    cannot be ALTERed): rows survive byte-identical, sem_threshold arrives
    NULL, the widened CHECK accepts tool_call, and AUTOINCREMENT continues
    past the copied max id."""
    import sqlite3

    from .conftest import ROWS

    store = tmp_path / "sqlstore"
    store.mkdir()
    conn = sqlite3.connect(store / "store.db")
    conn.executescript(ins.V7_SCHEMA_SQLITE)
    conn.executescript(ROWS)
    conn.close()
    with pytest.raises(StoreContractError, match="upgrade to v8"):
        Store(str(store))

    msg = migrate(str(store))
    assert "to v9" in msg

    s = Store(str(store))
    rows = {t.id: t for t in s.takeaways()}
    assert len(rows) == 7
    assert rows[7].one_liner == "on_demand: migration gotcha"
    assert rows[5].status == "retired"
    assert all(t.sem_threshold is None for t in rows.values())

    conn = sqlite3.connect(store / "store.db")
    conn.execute(
        "INSERT INTO takeaways (created, kind, trigger_kind, one_liner,"
        " status, reach) VALUES (datetime('now'), 'gotcha', 'tool_call',"
        " 'tc row', 'active', 'project')")
    conn.commit()
    new_id = conn.execute("SELECT MAX(id) FROM takeaways").fetchone()[0]
    conn.close()
    assert new_id == 8  # sequence continued, no id reuse


def test_init_cli_end_to_end(host):
    """The CLI path: init via subprocess, then a lifecycle command works."""
    import sys
    src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
    env = {**os.environ, "PYTHONPATH": src}
    out = subprocess.run(
        [sys.executable, "-m", "monition.cli", "init", "--root", host],
        capture_output=True, text=True, env=env)
    assert out.returncode == 0, out.stderr
    out = subprocess.run(
        [sys.executable, "-m", "monition.cli", "list",
         "--store", os.path.join(host, "monition")],
        capture_output=True, text=True, env=env)
    assert out.returncode == 0, out.stderr
    assert out.stdout == "(no takeaways with status active)\n"
