"""B04: shared-cause batch attribution — read-side only. One 6-row batch and
two individually-rated noise firings assert the exact split (bucket
validation), plus the export annotation and the report line."""
import json

from monition.export import export_records
from monition.metrics import audit, batch_sizes
from monition.report import render
from monition.store import Store

from .conftest import sqlite_exec

DUMP_CTX = "one meta prompt lighting a band of rows"


def _seed_batch(store):
    """Six on_demand rows (t10-t15) each fired once by the same prompt moment
    and rated noise (the 6-row batch), plus two individually-rated noise
    firings on t10 and t11 with distinct moments."""
    rows = ",".join(
        f"({tid}, '2026-01-01 10:00:00', 'gotcha', 'on_demand', 'kw{tid}',"
        f" 'row {tid}', 'active', 'project')"
        for tid in range(10, 16))
    sqlite_exec(store, (
        "INSERT INTO takeaways (id, created, kind, trigger_kind, trigger_spec,"
        f" one_liner, status, reach) VALUES {rows};"))
    batch = ",".join(
        f"({tid}, '2026-02-01 09:00:00', 's_dump', 'on_demand',"
        f" '{DUMP_CTX}', 'noise')"
        for tid in range(10, 16))
    sqlite_exec(store, (
        "INSERT INTO firings (takeaway_id, fired_at, session_id, trigger_kind,"
        f" trigger_context, outcome) VALUES {batch},"
        " (10, '2026-02-02 09:00:00', 's_solo_a', 'on_demand', 'a lone prompt', 'noise'),"
        " (11, '2026-02-03 09:00:00', 's_solo_b', 'on_demand', 'another lone prompt', 'noise');"))


def test_exact_split_batch_vs_individual(store_copy):
    _seed_batch(store_copy)
    s = Store(store_copy)
    audits = {a.takeaway_id: a for a in audit(s.takeaways(), s.firings())}

    # t10/t11: one batch noise + one individual noise each
    for tid in (10, 11):
        assert audits[tid].noise == 2 and audits[tid].noise_batch == 1
    # t12-t15: batch noise only
    for tid in (12, 13, 14, 15):
        assert audits[tid].noise == 1 and audits[tid].noise_batch == 1
    # pre-existing fixture rows are untouched: t1's two noise firings have
    # distinct (session, context) moments — individual, not batch
    assert audits[1].noise == 2 and audits[1].noise_batch == 0


def test_all_batch_noise_changes_recommendation(store_copy):
    _seed_batch(store_copy)
    s = Store(store_copy)
    audits = {a.takeaway_id: a for a in audit(s.takeaways(), s.firings())}
    # all-noise all-batch: attribute to breadth, not the row
    assert "shared-cause batch dumps" in audits[12].recommendation
    # all-noise with individual evidence keeps the per-row recommendation
    assert "narrow trigger_spec or retire" in audits[1].recommendation


def test_batch_sizes_null_keys_ungroupable(store_copy):
    sqlite_exec(store_copy, (
        "INSERT INTO firings (takeaway_id, fired_at, session_id, trigger_kind,"
        " trigger_context, outcome) VALUES"
        " (7, '2026-02-01 09:00:00', NULL, 'on_demand', 'same ctx', 'noise'),"
        " (7, '2026-02-01 09:01:00', NULL, 'on_demand', 'same ctx', 'noise'),"
        " (4, '2026-02-01 09:00:00', 's_x', 'session_start', NULL, NULL),"
        " (6, '2026-02-01 09:00:00', 's_x', 'session_start', NULL, NULL);"))
    s = Store(store_copy)
    sizes = batch_sizes(s.firings())
    new = [f for f in s.firings() if f.fired_at.year == 2026 and f.session_id in (None, "s_x")]
    assert all(sizes[f.id] == 1 for f in new)  # NULL is not a shared cause


def test_export_carries_batch_size(store_copy):
    _seed_batch(store_copy)
    records = export_records(Store(store_copy), session="s_dump")
    assert len(records) == 6
    assert all(r["batch_size"] == 6 for r in records)
    solo = export_records(Store(store_copy), session="s_solo_a")
    assert len(solo) == 1 and solo[0]["batch_size"] == 1


def test_report_shows_batch_split(store_copy):
    _seed_batch(store_copy)
    out = render(Store(store_copy))
    assert "2 noise (1 in batch dumps — shared cause)" in out
