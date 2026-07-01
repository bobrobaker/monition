"""B04 fold: consolidate per-repo v6 Dolt stores into the Dolt hub. Dolt-only —
skipped when the dolt binary is absent."""
import json
import os
import shutil

import pytest

from monition import init_sync as ins
from monition.store import Store, StoreContractError
from monition.store_write import WriteStore
from .conftest import build_dolt_store, build_store, SCHEMA

dolt_only = pytest.mark.skipif(
    not (shutil.which("dolt") or os.path.exists(os.path.expanduser("~/.local/bin/dolt"))),
    reason="dolt binary not available",
)


def _seed_source(tmp_path, name, proj, gen):
    """A v6 Dolt source store at <tmp>/<name>/monition with project + general rows
    (origin_repo = the source's repo root, as a real v6 migration would set it)."""
    store = str(tmp_path / name / "monition")
    build_dolt_store(store, [ins.V6_SCHEMA])
    origin = os.path.dirname(os.path.abspath(store))
    for ol in proj:
        ins._raw_sql(store, "INSERT INTO takeaways (created, kind, trigger_kind, trigger_spec,"
                     f" one_liner, status, reach, origin_repo) VALUES (NOW(),'gotcha','on_demand',"
                     f"'x','{ol}','active','project','{origin}')")
    for ol in gen:
        ins._raw_sql(store, "INSERT INTO takeaways (created, kind, trigger_kind, trigger_spec,"
                     f" one_liner, status, reach, origin_repo) VALUES (NOW(),'rule','on_demand',"
                     f"'x','{ol}','active','general','{origin}')")
    return store, origin


@dolt_only
def test_fold_two_sources_conserves_and_remaps_fks(tmp_path):
    hub = str(tmp_path / "hub" / "monition")
    build_dolt_store(hub, [ins.V6_SCHEMA])
    a, origin_a = _seed_source(tmp_path, "repoA", ["a-proj"], ["a-gen"])
    b, origin_b = _seed_source(tmp_path, "repoB", ["b-proj"], [])
    # a firing in A referencing its project takeaway (source id 1)
    ins._raw_sql(a, "INSERT INTO firings (takeaway_id, fired_at, session_id) VALUES (1, NOW(), 's1')")

    assert "folded" in ins.fold_store(a, hub)
    assert "folded" in ins.fold_store(b, hub)

    s = Store(hub)
    tk = {t.one_liner: t for t in s.takeaways()}
    assert set(tk) == {"a-proj", "a-gen", "b-proj"}            # every source row present
    assert tk["a-proj"].origin_repo == origin_a and tk["a-proj"].reach == "project"
    assert tk["a-gen"].reach == "general"
    assert tk["b-proj"].origin_repo == origin_b
    firings = s.firings()
    assert len(firings) == 1
    assert firings[0].takeaway_id == tk["a-proj"].id          # FK remapped to the hub id


@dolt_only
def test_fold_is_idempotency_guarded(tmp_path):
    hub = str(tmp_path / "hub" / "monition")
    build_dolt_store(hub, [ins.V6_SCHEMA])
    a, _ = _seed_source(tmp_path, "repoA", ["a"], [])
    ins.fold_store(a, hub)
    with pytest.raises(StoreContractError, match="already"):
        ins.fold_store(a, hub)


@dolt_only
def test_fold_refuses_non_v6_source(tmp_path):
    hub = str(tmp_path / "hub" / "monition")
    build_dolt_store(hub, [ins.V6_SCHEMA])
    v5 = str(tmp_path / "old" / "monition")
    build_dolt_store(v5, [ins.V5_SCHEMA])
    with pytest.raises(StoreContractError, match="not v6"):
        ins.fold_store(v5, hub)


@dolt_only
def test_fold_refuses_sqlite_source(tmp_path):
    hub = str(tmp_path / "hub" / "monition")
    build_dolt_store(hub, [ins.V6_SCHEMA])
    sqlite_src = build_store(str(tmp_path / "lite"), [SCHEMA])
    with pytest.raises(StoreContractError, match="Dolt"):
        ins.fold_store(sqlite_src, hub)


@dolt_only
def test_folded_hub_respects_reach_filter(tmp_path):
    hub = str(tmp_path / "hub" / "monition")
    build_dolt_store(hub, [ins.V6_SCHEMA])
    a, origin_a = _seed_source(tmp_path, "repoA", ["a-proj"], ["shared-gen"])
    b, origin_b = _seed_source(tmp_path, "repoB", ["b-proj"], [])
    ins.fold_store(a, hub)
    ins.fold_store(b, hub)
    ws = WriteStore(hub)
    from_a = {h["one_liner"] for h in
              json.loads(ws.on_demand_match("x", current_repo=origin_a))["hits"]}
    assert from_a == {"a-proj", "shared-gen"}                 # A's project + general; not b-proj
    from_b = {h["one_liner"] for h in
              json.loads(ws.on_demand_match("x", current_repo=origin_b))["hits"]}
    assert from_b == {"b-proj", "shared-gen"}                 # B's project + general; not a-proj
