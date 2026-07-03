"""B06: the audit-cadence proposal engine — one known-good proposal per class
on a synthetic store with ground truth, thin-evidence silence, the B04 batch
discount, and the narrow `retarget` apply verb (mutations provenance)."""
import json

import pytest

from monition.proposals import propose, render
from monition.store import Store, StoreContractError
from monition.store_write import WriteStore

from .conftest import SCHEMA, build_store

# Ground truth by class:
#   t10 tighten  — keyword 'beta' has 2 solo-noise lexical firings, 0 helpful;
#                  'alpha' has a helpful firing (kept under replay).
#   t11 broaden  — 2 violations sharing the literal 'doltserver'.
#   t12 broaden  — 1 violation only: below the exemplar floor -> note, no prop.
#   t13 migrate  — 2 helpful semantic firings sharing the literal 'worktree'.
#   t14+t15 merge — co-fire on the same delivery moment in 3 sessions.
#   t16 graduate — session_start, fires helpful in every store session.
#   t17 stale    — edit_path glob matches nothing in its (injected) repo;
#   t18 not stale — same repo, glob matches; t19 — origin unresolvable -> note.
#   t20+t21      — 2 noise lexical firings each, but batch-borne (shared
#                  moment) -> B04 discount, no tighten proposal.
#   t22 no migrate — helpful semantic literal 'deploy' also hits solo noise.
#   t23          — tool_call row for retarget validation.
ROWS = """
INSERT INTO takeaways (id, created, kind, trigger_kind, trigger_spec, one_liner, status, reach, origin_repo) VALUES
  (10, '2026-01-01 10:00:00', 'gotcha', 'on_demand', 'alpha,beta', 'tighten target', 'active', 'project', NULL),
  (11, '2026-01-01 10:00:00', 'gotcha', 'on_demand', 'gamma', 'broaden target', 'active', 'project', NULL),
  (12, '2026-01-01 10:00:00', 'gotcha', 'on_demand', 'delta', 'thin broaden', 'active', 'project', NULL),
  (13, '2026-01-01 10:00:00', 'gotcha', 'on_demand', 'epsilon', 'migrate target', 'active', 'project', NULL),
  (14, '2026-01-01 10:00:00', 'gotcha', 'on_demand', 'zeta', 'merge twin A', 'active', 'project', NULL),
  (15, '2026-01-01 10:00:00', 'gotcha', 'on_demand', 'zeta topic', 'merge twin B', 'active', 'project', NULL),
  (16, '2026-01-01 10:00:00', 'rule', 'session_start', NULL, 'graduate target', 'active', 'general', NULL),
  (17, '2026-01-01 10:00:00', 'gotcha', 'edit_path', 'vanished/*', 'stale target', 'active', 'project', '/repo/x'),
  (18, '2026-01-01 10:00:00', 'gotcha', 'edit_path', 'src/*', 'not stale', 'active', 'project', '/repo/x'),
  (19, '2026-01-01 10:00:00', 'gotcha', 'edit_path', 'foo/*', 'unresolvable', 'active', 'project', NULL),
  (20, '2026-01-01 10:00:00', 'gotcha', 'on_demand', 'eta,theta', 'batch noise A', 'active', 'project', NULL),
  (21, '2026-01-01 10:00:00', 'gotcha', 'on_demand', 'iota,kappa', 'batch noise B', 'active', 'project', NULL),
  (22, '2026-01-01 10:00:00', 'gotcha', 'on_demand', 'lambda', 'noisy migrate', 'active', 'project', NULL),
  (23, '2026-01-01 10:00:00', 'gotcha', 'tool_call', '{"tool": "Bash", "field": "command", "contains": ["git push"]}', 'tool row', 'active', 'project', NULL);
INSERT INTO firings (id, takeaway_id, fired_at, session_id, trigger_kind, trigger_context, outcome, match_evidence) VALUES
  (101, 10, '2026-01-02 10:00:00', 's1', 'on_demand', 'q beta one', 'noise',
   '{"module": "lexical", "keyword": "beta", "query": "beta thing one"}'),
  (102, 10, '2026-01-03 10:00:00', 's2', 'on_demand', 'q beta two', 'noise',
   '{"module": "lexical", "keyword": "beta", "query": "beta thing two"}'),
  (103, 10, '2026-01-04 10:00:00', 's3', 'on_demand', 'q alpha', 'helpful',
   '{"module": "lexical", "keyword": "alpha", "query": "alpha question"}'),
  (104, 13, '2026-01-02 10:00:00', 's4', 'on_demand', 'q wt one', 'helpful',
   '{"module": "semantic", "score": 0.71, "query": "cleanup the worktree please"}'),
  (105, 13, '2026-01-03 10:00:00', 's5', 'on_demand', 'q wt two', 'helpful',
   '{"module": "semantic", "score": 0.68, "query": "worktree removal step"}'),
  (106, 14, '2026-01-02 10:00:00', 'sm1', 'on_demand', 'merge ctx', NULL, NULL),
  (107, 15, '2026-01-02 10:00:00', 'sm1', 'on_demand', 'merge ctx', NULL, NULL),
  (108, 14, '2026-01-03 10:00:00', 'sm2', 'on_demand', 'merge ctx', NULL, NULL),
  (109, 15, '2026-01-03 10:00:00', 'sm2', 'on_demand', 'merge ctx', NULL, NULL),
  (110, 14, '2026-01-04 10:00:00', 'sm3', 'on_demand', 'merge ctx', NULL, NULL),
  (111, 15, '2026-01-04 10:00:00', 'sm3', 'on_demand', 'merge ctx', NULL, NULL),
  (112, 16, '2026-01-02 10:00:00', 's1', 'session_start', NULL, 'helpful', NULL),
  (113, 16, '2026-01-02 10:00:00', 's2', 'session_start', NULL, 'helpful', NULL),
  (114, 16, '2026-01-02 10:00:00', 's3', 'session_start', NULL, 'helpful', NULL),
  (115, 16, '2026-01-02 10:00:00', 's4', 'session_start', NULL, 'helpful', NULL),
  (116, 16, '2026-01-02 10:00:00', 's5', 'session_start', NULL, 'helpful', NULL),
  (117, 16, '2026-01-02 10:00:00', 'sm1', 'session_start', NULL, 'helpful', NULL),
  (118, 16, '2026-01-02 10:00:00', 'sm2', 'session_start', NULL, 'helpful', NULL),
  (119, 16, '2026-01-02 10:00:00', 'sm3', 'session_start', NULL, 'helpful', NULL),
  (120, 20, '2026-01-02 11:00:00', 's1', 'on_demand', 'batch ctx', 'noise',
   '{"module": "lexical", "keyword": "eta", "query": "eta and iota dump"}'),
  (121, 21, '2026-01-02 11:00:00', 's1', 'on_demand', 'batch ctx', 'noise',
   '{"module": "lexical", "keyword": "iota", "query": "eta and iota dump"}'),
  (122, 20, '2026-01-03 11:00:00', 's2', 'on_demand', 'batch ctx 2', 'noise',
   '{"module": "lexical", "keyword": "eta", "query": "eta iota again"}'),
  (123, 21, '2026-01-03 11:00:00', 's2', 'on_demand', 'batch ctx 2', 'noise',
   '{"module": "lexical", "keyword": "iota", "query": "eta iota again"}'),
  (124, 22, '2026-01-02 10:00:00', 's4', 'on_demand', 'q dep one', 'helpful',
   '{"module": "semantic", "score": 0.70, "query": "deploy the staging build"}'),
  (125, 22, '2026-01-03 10:00:00', 's5', 'on_demand', 'q dep two', 'helpful',
   '{"module": "semantic", "score": 0.69, "query": "deploy checklist step"}'),
  (126, 22, '2026-01-04 10:00:00', 's3', 'on_demand', 'q dep noise', 'noise',
   '{"module": "lexical", "keyword": "lambda", "query": "lambda deploy chatter"}');
INSERT INTO violations (id, takeaway_id, session_id, detected_at, evidence, repo) VALUES
  (1, 11, 'sv1', '2026-01-05 10:00:00', 'the doltserver refused the connection', NULL),
  (2, 11, 'sv2', '2026-01-06 10:00:00', 'doltserver lock held by stale pid', NULL),
  (3, 12, 'sv3', '2026-01-05 10:00:00', 'single exemplar text', NULL);
"""

REPO_FILES = {"/repo/x": ["src/a.py", "README.md"]}


def fake_git_files(repo):
    return REPO_FILES.get(repo)


@pytest.fixture()
def prop_store(tmp_path):
    return build_store(str(tmp_path / "props"), [SCHEMA, ROWS])


@pytest.fixture()
def result(prop_store):
    return propose(Store(prop_store), git_files=fake_git_files)


def by_class(result, cls):
    return [p for p in result["proposals"] if p["class"] == cls]


def test_tighten_drops_solo_noise_keyword(result):
    props = by_class(result, "tighten")
    assert [p["takeaway_id"] for p in props] == [10]
    p = props[0]
    assert p["proposed_spec"] == "alpha"
    assert p["verb"] == "retarget"
    assert "monition retarget 10 'alpha'" in p["apply"]
    assert any("f101" in e for e in p["evidence"])
    assert any("helpful lost 0" in e for e in p["evidence"])


def test_batch_borne_noise_never_tightens(result):
    # t20/t21: all their noise shares a delivery moment -> B04 attributes it
    # to the breadth layer, not the rows
    assert not [p for p in by_class(result, "tighten")
                if p["takeaway_id"] in (20, 21)]


def test_broaden_needs_two_exemplars(result):
    props = by_class(result, "broaden")
    assert [p["takeaway_id"] for p in props] == [11]
    p = props[0]
    assert p["candidates"][0] == "doltserver"
    assert p["proposed_spec"] == "gamma,doltserver"
    assert "v1" in p["apply"] and "v2" in p["apply"]
    # t12 (one exemplar) is a note, never a proposal
    assert any("t12" in n and "floor" in n for n in result["notes"])


def test_migrate_finds_stable_literal(result):
    props = by_class(result, "migrate")
    assert [p["takeaway_id"] for p in props] == [13]
    p = props[0]
    assert p["proposed_spec"] == "epsilon,worktree"
    assert any("f104" in e for e in p["evidence"])


def test_migrate_rejects_literal_that_hits_solo_noise(result):
    # t22: 'deploy' covers both helpful semantic queries but also solo noise
    assert not [p for p in by_class(result, "migrate")
                if p["takeaway_id"] == 22]


def test_merge_pairs_by_cofiring_sessions(result):
    props = by_class(result, "merge")
    assert len(props) == 1
    p = props[0]
    assert {p["takeaway_id"], p["other_id"]} == {14, 15}
    assert any("3 distinct sessions" in e for e in p["evidence"])


def test_graduate_names_surface_writes_nothing(result):
    props = by_class(result, "graduate")
    assert [p["takeaway_id"] for p in props] == [16]
    p = props[0]
    assert "CLAUDE.md" in p["target_surface"]
    assert "retire 16" in p["apply"]


def test_stale_glob_against_origin_repo(result):
    props = by_class(result, "stale")
    assert [p["takeaway_id"] for p in props] == [17]
    assert "monition retire 17" == props[0]["apply"]
    assert any("t19" in n and "unresolvable" in n for n in result["notes"])


def test_thin_store_proposes_nothing(tmp_path):
    path = build_store(str(tmp_path / "thin"), [SCHEMA])
    result = propose(Store(path), git_files=fake_git_files)
    assert result["proposals"] == []


def test_render_cites_and_points_at_calibrate(result):
    text = render(result)
    assert "TIGHTEN" in text and "STALE" in text
    assert "monition calibrate" in text  # semantic θ stays B03's
    assert "f101" in text


# ---- the narrow retarget apply verb ----------------------------------------


def test_retarget_writes_spec_and_provenance(prop_store):
    ws = WriteStore(prop_store)
    out = ws.retarget(10, "alpha", source="propose:tighten f101,f102")
    assert "mutation logged" in out
    s = Store(prop_store)
    row = {t.id: t for t in s.takeaways()}[10]
    assert row.trigger_spec == "alpha"
    m = [m for m in s.mutations() if m.takeaway_id == 10]
    assert len(m) == 1 and m[0].verb == "retarget"
    changes = json.loads(m[0].changes)
    assert changes["trigger_spec"] == {"old": "alpha,beta", "new": "alpha"}
    assert m[0].source == "propose:tighten f101,f102"


def test_retarget_refusals(prop_store):
    ws = WriteStore(prop_store)
    with pytest.raises(StoreContractError):  # unknown id
        ws.retarget(999, "x")
    with pytest.raises(StoreContractError):  # session_start has no spec
        ws.retarget(16, "x")
    with pytest.raises(StoreContractError):  # empty spec
        ws.retarget(10, "")
    with pytest.raises(StoreContractError):  # no-op
        ws.retarget(10, "alpha,beta")
    with pytest.raises(StoreContractError):  # malformed tool_call spec
        ws.retarget(23, "not json")
    assert not list(Store(prop_store).mutations())  # refusals write nothing


def test_propose_cli_end_to_end(prop_store, capsys):
    from monition.cli import main
    assert main(["propose", "--store", prop_store]) == 0
    out = capsys.readouterr().out
    assert "monition propose" in out and "TIGHTEN" in out
    assert main(["propose", "--store", prop_store, "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["summary"]["proposals"] == len(data["proposals"])
