"""v6 reach filter + firing provenance under a relocated (hub) store.

Ground truth for the reach store: one general row, two project rows in distinct
origin repos, and one under-specified project row (NULL origin_repo).
"""
import json
import os

from monition.store_write import WriteStore
from .conftest import build_store, SCHEMA

REPO_A = "/repos/alpha"
REPO_B = "/repos/beta"

ROWS = f"""
INSERT INTO takeaways (id, created, kind, trigger_kind, trigger_spec, one_liner, status, reach, origin_repo) VALUES
  (1, '2026-01-01 10:00:00', 'rule', 'on_demand', 'deploy', 'general deploy rule', 'active', 'general', NULL),
  (2, '2026-01-01 10:00:00', 'gotcha', 'on_demand', 'deploy', 'alpha-only deploy gotcha', 'active', 'project', '{REPO_A}'),
  (3, '2026-01-01 10:00:00', 'gotcha', 'on_demand', 'deploy', 'beta-only deploy gotcha', 'active', 'project', '{REPO_B}'),
  (4, '2026-01-01 10:00:00', 'gotcha', 'on_demand', 'deploy', 'unscoped deploy gotcha', 'active', 'project', NULL);
"""


def _ids(ws, repo):
    return {h["id"] for h in json.loads(ws.on_demand_match("deploy plan", current_repo=repo))}


def test_project_rows_isolate_by_origin_repo(tmp_path):
    ws = WriteStore(build_store(str(tmp_path / "reach"), [SCHEMA, ROWS]))
    # In repo A: general (1) + A's project (2) + NULL-origin fail-open (4); never B's (3).
    assert _ids(ws, REPO_A) == {1, 2, 4}
    # In repo B: general (1) + B's project (3) + NULL-origin (4); never A's (2).
    assert _ids(ws, REPO_B) == {1, 3, 4}
    # No repo context → filter not applied (all four).
    assert _ids(ws, None) == {1, 2, 3, 4}


def test_add_stamps_origin_repo_for_project_rows(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", REPO_A)
    ws = WriteStore(build_store(str(tmp_path / "add"), [SCHEMA]))
    ws.add("gotcha", "on_demand", "stamped row", "deploy")           # default reach=project
    ws.add("rule", "on_demand", "anywhere row", "deploy", reach="general")
    by_one = {t.one_liner: t for t in ws.takeaways()}
    assert by_one["stamped row"].origin_repo == REPO_A  # project stamped current repo
    assert by_one["anywhere row"].origin_repo is None   # general needs no origin


def test_firing_repo_is_host_not_store_dir(tmp_path):
    """fire() records firings.repo from current_repo, not os.path.dirname(store) —
    the hub bug: under a relocated store the store dir is not the host repo."""
    store = build_store(str(tmp_path / "hub"), [SCHEMA, ROWS])
    ws = WriteStore(store)
    ws.fire("1", "on_demand", session="s1", current_repo=REPO_A)
    rows = ws._sql("SELECT repo FROM firings ORDER BY id")
    assert rows[-1]["repo"] == REPO_A
    # No current_repo → repo honestly NULL (not the store dir).
    ws.fire("1", "on_demand", session="s2")
    nullrow = ws._sql("SELECT repo FROM firings ORDER BY id")[-1]
    assert nullrow.get("repo") is None
