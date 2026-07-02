"""`monition export-firings` — the tier-3 eval read-verb (P2).

One JSONL object per firing, denormalized with the parent takeaway's
`one_liner`+`kind`. Pins the record shape, the export `schema_version` stamp
(distinct from store v4), NULL provenance/outcome preserved (never coerced),
`--since`/`--rated-only`/`--unrated-only`/`--session` filtering (incl. the
rated/unrated complement and mutual-exclusivity), the `decisions` table staying
out, a `resurrection` firing surfacing honestly, and empty-stream fail-open.
"""
import json
from datetime import datetime

import pytest

from monition.cli import main
from monition.export import (
    EXPORT_SCHEMA_VERSION,
    _rating_priority,
    export_records,
    render_jsonl,
)
from monition.store import Store

from .conftest import SCHEMA, build_store

# Ground truth: 2 takeaways, 5 firings.
#   f1 t1 helpful, full provenance (git_dirty=0)
#   f2 t1 noise,   full provenance (git_dirty=1)   -- 2026-03-01
#   f3 t1 UNRATED, all provenance NULL (pre-v4 firing), session_id "unknown"
#   f4 t2 helpful, trigger_kind='resurrection' (injected counterfactual) -- 2026-03-15
#   f5 t2 noise,   full provenance
# d1 decisions row exists -- must NOT leak into the export.
A, B, C, D = "a" * 40, "b" * 40, "c" * 40, "d" * 40
ROWS = f"""
INSERT INTO takeaways (id, created, kind, trigger_kind, trigger_spec, one_liner, status, reach) VALUES
  (1, '2026-01-01 10:00:00', 'gotcha', 'edit_path', 'src/*', 'use parametrized queries', 'active', 'project'),
  (2, '2026-01-01 10:00:00', 'rule', 'session_start', NULL, 'follow the commit format', 'active', 'project');
INSERT INTO firings (id, takeaway_id, fired_at, session_id, trigger_kind, trigger_context, outcome, git_sha, git_dirty, model, monition_version) VALUES
  (1, 1, '2026-02-01 10:00:00', 's1', 'edit_path', 'src/a.py', 'helpful', '{A}', 0, 'claude-opus-4-8', '0.4.0'),
  (2, 1, '2026-03-01 09:00:00', 's2', 'edit_path', 'src/b.py', 'noise', '{B}', 1, 'claude-sonnet-4-6', '0.4.0'),
  (3, 1, '2026-01-15 08:00:00', 'unknown', 'edit_path', 'src/c.py', NULL, NULL, NULL, NULL, NULL),
  (4, 2, '2026-03-15 12:00:00', 's3', 'resurrection', 'relearned: commit format', 'helpful', '{C}', 0, 'claude-opus-4-8', '0.4.0'),
  (5, 2, '2026-02-10 11:00:00', 's1', 'session_start', NULL, 'noise', '{D}', 0, 'claude-opus-4-8', '0.4.0');
INSERT INTO decisions (id, takeaway_id, session_id, decided_at, decision, evidence_count, cold_start, ev_score) VALUES
  (1, 1, 's2', '2026-03-01 09:00:00', 'suppress', 2, 0, 0.0000);
"""

EXPECTED_KEYS = {
    "schema_version", "firing_id", "takeaway_id", "one_liner", "kind",
    "outcome", "fired_at", "session_id", "trigger_kind", "trigger_context",
    "situation", "git_sha", "git_dirty", "model", "monition_version",
    # head-not-tail rating-value signals (additive, no schema_version bump)
    "fire_count", "rated_count", "precision", "rating_priority",
    # v7 lossless match evidence (additive, no schema_version bump)
    "match_evidence",
}
DECISIONS_KEYS = {"decision", "ev_score", "cold_start", "evidence_count", "decided_at"}


# --- fixtures (read-only -> built once per session) ------------------------


@pytest.fixture(scope="session")
def export_store(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("export") / "store")
    return build_store(path, [SCHEMA, ROWS])


@pytest.fixture(scope="session")
def empty_store(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("export_empty") / "store")
    return build_store(path, [SCHEMA])


def _by_firing(records):
    return {r["firing_id"]: r for r in records}


# --- record shape ----------------------------------------------------------

def test_one_record_per_firing_with_exact_keys(export_store):
    records = export_records(Store(export_store))
    assert len(records) == 5
    for r in records:
        assert set(r) == EXPECTED_KEYS


def test_schema_version_stamp_is_export_contract_version(export_store):
    # still 1 (`situation` is additive -> no bump), not the store schema version (v5).
    records = export_records(Store(export_store))
    assert EXPORT_SCHEMA_VERSION == 1
    assert all(r["schema_version"] == 1 for r in records)


def test_fired_at_is_iso8601(export_store):
    for r in export_records(Store(export_store)):
        # parses back without raising
        datetime.fromisoformat(r["fired_at"])


# --- denormalization -------------------------------------------------------

def test_denormalized_takeaway_fields(export_store):
    recs = _by_firing(export_records(Store(export_store)))
    assert recs[1]["one_liner"] == "use parametrized queries"
    assert recs[1]["kind"] == "gotcha"
    assert recs[4]["one_liner"] == "follow the commit format"
    assert recs[4]["kind"] == "rule"


# --- NULL handling: never coerced ------------------------------------------

def test_null_provenance_and_outcome_preserved(export_store):
    f3 = _by_firing(export_records(Store(export_store)))[3]
    assert f3["outcome"] is None  # unrated, not "noise"
    assert f3["git_sha"] is None
    assert f3["git_dirty"] is None
    assert f3["model"] is None
    assert f3["monition_version"] is None
    assert f3["session_id"] == "unknown"  # anonymous bucket, a real value


def test_present_provenance_typed(export_store):
    recs = _by_firing(export_records(Store(export_store)))
    assert recs[1]["git_sha"] == A
    assert recs[1]["git_dirty"] is False  # 0 -> bool False, not 0
    assert recs[2]["git_dirty"] is True   # 1 -> bool True
    assert recs[2]["model"] == "claude-sonnet-4-6"
    assert recs[1]["monition_version"] == "0.4.0"


# --- decisions table excluded ----------------------------------------------

def test_decisions_fields_absent(export_store):
    for r in export_records(Store(export_store)):
        assert DECISIONS_KEYS.isdisjoint(r)


# --- filters ---------------------------------------------------------------

def test_rated_only_excludes_unrated(export_store):
    records = export_records(Store(export_store), rated_only=True)
    assert {r["firing_id"] for r in records} == {1, 2, 4, 5}  # f3 dropped
    assert all(r["outcome"] is not None for r in records)


def test_unrated_only_is_the_complement_of_rated_only(export_store):
    records = export_records(Store(export_store), unrated_only=True)
    assert {r["firing_id"] for r in records} == {3}  # only the rating worklist
    assert all(r["outcome"] is None for r in records)
    # exact complement: rated ∪ unrated == all, rated ∩ unrated == ∅
    rated = {r["firing_id"] for r in export_records(Store(export_store), rated_only=True)}
    unrated = {r["firing_id"] for r in records}
    allf = {r["firing_id"] for r in export_records(Store(export_store))}
    assert rated | unrated == allf
    assert rated & unrated == set()


def test_session_scopes_to_one_session(export_store):
    records = export_records(Store(export_store), session="s1")
    assert {r["firing_id"] for r in records} == {1, 5}  # f1, f5 fired in s1
    assert all(r["session_id"] == "s1" for r in records)


def test_session_composes_with_unrated_only(export_store):
    # f3 is the only unrated firing and it lives in the "unknown" bucket.
    records = export_records(Store(export_store), session="unknown", unrated_only=True)
    assert {r["firing_id"] for r in records} == {3}


def test_unknown_session_is_a_real_filterable_value(export_store):
    records = export_records(Store(export_store), session="unknown")
    assert {r["firing_id"] for r in records} == {3}  # anonymous bucket, not skipped


# --- head-not-tail rating-value metric -------------------------------------

def test_rating_priority_cold_start_is_pure_traffic():
    # rated < N_COLD_START(3): closeness = 1.0, so priority == fire_count.
    assert _rating_priority(10, 0, 0) == 10.0   # never rated
    assert _rating_priority(5, 2, 2) == 5.0     # 2 rated, still cold-start


def test_rating_priority_peaks_at_the_decision_boundary():
    # evidence-based: closeness peaks at precision == EV_THRESHOLD (0.5).
    assert _rating_priority(10, 4, 2) == 10.0   # precision 0.5 -> closeness 1.0


def test_rating_priority_is_zero_for_settled_rows():
    assert _rating_priority(40, 4, 4) == 0.0    # 100% helpful -> settled
    assert _rating_priority(40, 4, 0) == 0.0    # 0% helpful -> settled


def test_rating_priority_scales_with_traffic_and_closeness():
    # precision 0.75 -> |0.75-0.5|/0.5 = 0.5 -> closeness 0.5.
    assert _rating_priority(20, 4, 3) == 10.0
    # same closeness, 10x traffic -> 10x priority (head beats tail).
    assert _rating_priority(200, 4, 3) == 100.0


def test_per_record_stats_are_parent_row_aggregates(export_store):
    recs = _by_firing(export_records(Store(export_store)))
    # t1: f1 helpful, f2 noise, f3 unrated -> fire 3, rated 2, precision 0.5
    assert recs[1]["fire_count"] == 3
    assert recs[1]["rated_count"] == 2
    assert recs[1]["precision"] == 0.5
    assert recs[1]["rating_priority"] == 3.0  # cold-start (2<3) -> traffic
    # the *unrated* firing carries the same parent-row stats, not per-firing.
    assert recs[3]["fire_count"] == 3
    assert recs[3]["precision"] == 0.5
    # t2: f4 helpful, f5 noise -> fire 2, rated 2, precision 0.5
    assert recs[4]["fire_count"] == 2
    assert recs[4]["rating_priority"] == 2.0


def test_stats_are_store_wide_not_filtered_slice(export_store):
    # filtering to f3 alone must still report t1's full traffic (3), not 1.
    f3 = export_records(Store(export_store), session="unknown")[0]
    assert f3["fire_count"] == 3
    assert f3["rated_count"] == 2


def test_order_by_priority_is_non_increasing(export_store):
    records = export_records(Store(export_store), order_by="priority")
    prios = [r["rating_priority"] for r in records]
    assert prios == sorted(prios, reverse=True)
    assert records[0]["takeaway_id"] == 1  # t1 (3.0) outranks t2 (2.0)


def test_default_order_is_unsorted_by_priority(export_store):
    # default keeps store/insertion order; all 5 still present.
    records = export_records(Store(export_store))
    assert len(records) == 5


def test_cli_order_by_priority_flag(export_store, capsys):
    rc = main(["export-firings", "--store", export_store, "--order-by", "priority"])
    assert rc == 0
    prios = [json.loads(l)["rating_priority"]
             for l in capsys.readouterr().out.splitlines() if l]
    assert prios == sorted(prios, reverse=True)


def test_since_is_inclusive_of_date(export_store):
    records = export_records(Store(export_store), since="2026-03-01")
    assert {r["firing_id"] for r in records} == {2, 4}  # 03-01 09:00 included


def test_since_and_rated_only_compose(export_store):
    records = export_records(Store(export_store), since="2026-01-01", rated_only=True)
    assert {r["firing_id"] for r in records} == {1, 2, 4, 5}


def test_bad_since_is_contract_violation(export_store):
    from monition.store import StoreContractError
    with pytest.raises(StoreContractError):
        export_records(Store(export_store), since="03/01/2026")


# --- resurrection firings surface honestly ---------------------------------

def test_resurrection_firing_exported_as_synthetic_helpful(export_store):
    f4 = _by_firing(export_records(Store(export_store)))[4]
    assert f4["trigger_kind"] == "resurrection"
    assert f4["outcome"] == "helpful"  # injected counterfactual, flagged by trigger_kind


# --- rendering + fail-open -------------------------------------------------

def test_render_jsonl_one_object_per_line(export_store):
    out = render_jsonl(export_records(Store(export_store)))
    lines = out.splitlines()
    assert len(lines) == 5
    for line in lines:
        json.loads(line)  # each line is a standalone object


def test_empty_store_yields_empty_stream(empty_store):
    assert export_records(Store(empty_store)) == []
    assert render_jsonl([]) == ""


# --- CLI surface -----------------------------------------------------------

def test_cli_emits_jsonl(export_store, capsys):
    rc = main(["export-firings", "--store", export_store])
    assert rc == 0
    lines = [l for l in capsys.readouterr().out.splitlines() if l]
    assert len(lines) == 5
    assert set(json.loads(lines[0])) == EXPECTED_KEYS


def test_cli_rated_only_flag(export_store, capsys):
    rc = main(["export-firings", "--store", export_store, "--rated-only"])
    assert rc == 0
    lines = [l for l in capsys.readouterr().out.splitlines() if l]
    assert len(lines) == 4
    assert all(json.loads(l)["outcome"] is not None for l in lines)


def test_cli_unrated_only_flag(export_store, capsys):
    rc = main(["export-firings", "--store", export_store, "--unrated-only"])
    assert rc == 0
    lines = [l for l in capsys.readouterr().out.splitlines() if l]
    assert len(lines) == 1
    assert json.loads(lines[0])["firing_id"] == 3


def test_cli_session_flag(export_store, capsys):
    rc = main(["export-firings", "--store", export_store, "--session", "s1"])
    assert rc == 0
    lines = [l for l in capsys.readouterr().out.splitlines() if l]
    assert {json.loads(l)["firing_id"] for l in lines} == {1, 5}


def test_cli_rated_and_unrated_are_mutually_exclusive(export_store):
    # argparse rejects the conflicting pair before any store read.
    with pytest.raises(SystemExit):
        main(["export-firings", "--store", export_store,
              "--rated-only", "--unrated-only"])


def test_cli_empty_store_prints_nothing(empty_store, capsys):
    rc = main(["export-firings", "--store", empty_store])
    assert rc == 0
    assert capsys.readouterr().out == ""
