"""B04: the relevance cascade on the passive prompt-hook path.

Hermetic: the head artifact is staged at the conftest-isolated default path
with a tiny known-geometry head (dim 4, heavy weights so alignment saturates
P(helpful) toward 0/1 across the 0.014 suppress threshold), and the embedding
call is faked — vectors point positive unless the text contains "gotcha" (the
fixture row's one_liner), so prompt⊕row alignment is test-controlled.
"""
import io
import json
import os

import pytest

import monition.embed as me
import monition.relevance.cascade as csc
from monition.hooks import _log_path, prompt_hook
from monition.relevance.head import RelevanceHead
from monition.store_write import WriteStore

DIM = 4


@pytest.fixture(autouse=True)
def lexical_only(monkeypatch):
    monkeypatch.setattr(me, "semantic_scores", lambda q, texts: [0.0] * len(texts))


@pytest.fixture
def host_repo(store_copy, tmp_path, monkeypatch):
    import shutil
    root = tmp_path / "hostrepo"
    os.makedirs(root)
    shutil.move(str(store_copy), str(root / "monition"))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    return str(root)


def stage_artifact():
    """Write a dim-4 head at the (conftest-isolated) default path."""
    path = csc.default_artifact_path()
    RelevanceHead(weights=[10.0] * DIM, bias=0.0, mean=[0.0] * DIM,
                  std=[1.0] * DIM, l2=8.0, model_name=me.MODEL_NAME).save(path)
    return path


def fake_embed(sign_for_rows):
    """Prompt texts embed positive; row texts (contain 'gotcha') embed with
    `sign_for_rows` — +1.0 aligns them with the prompt (high P), -1.0 opposes
    (P ≈ 0 under the heavy weights, i.e. below the suppress threshold)."""
    def fn(texts):
        return [[sign_for_rows] * DIM if "gotcha" in t else [1.0] * DIM
                for t in texts]
    return fn


def run_hook(monkeypatch, capsys, prompt, session):
    monkeypatch.setattr(
        "sys.stdin", io.StringIO(json.dumps(
            {"session_id": session, "prompt": prompt})))
    prompt_hook()
    return capsys.readouterr().out


def firings(host_repo, session):
    return WriteStore(os.path.join(host_repo, "monition"))._sql(
        "SELECT takeaway_id, relevance_score, head_version FROM firings"
        f" WHERE session_id = '{session}'")


def test_confident_noise_suppressed_no_firing(host_repo, monkeypatch, capsys):
    stage_artifact()
    monkeypatch.setattr(me, "_embed", fake_embed(-1.0))
    out = run_hook(monkeypatch, capsys, "question about the migration", "cs1")
    assert out == ""                      # candidate suppressed, nothing injected
    assert firings(host_repo, "cs1") == []   # and no firing row to mis-rate
    with open(_log_path()) as f:
        log = f.read()
    # the line names the suppressed row + its score — the only audit trail,
    # since suppression writes no firing row
    assert "[cascade] suppressed 1 of 1 candidate(s): t7@0.0" in log
    assert "session=cs1" in log


def test_relevant_hit_fires_with_score_logged(host_repo, monkeypatch, capsys):
    stage_artifact()
    monkeypatch.setattr(me, "_embed", fake_embed(1.0))
    out = run_hook(monkeypatch, capsys, "question about the migration", "cs2")
    assert "[t7/f" in out
    rows = firings(host_repo, "cs2")
    assert len(rows) == 1
    assert float(rows[0]["relevance_score"]) > 0.9
    assert rows[0]["head_version"] == "head-v1"


def test_no_artifact_fires_ungated_null_score(host_repo, monkeypatch, capsys):
    # nothing staged at the isolated default path → scorer quietly skipped
    monkeypatch.setattr(me, "_embed", fake_embed(-1.0))  # would suppress if ran
    out = run_hook(monkeypatch, capsys, "question about the migration", "cs3")
    assert "[t7/f" in out
    rows = firings(host_repo, "cs3")
    assert len(rows) == 1
    assert rows[0]["relevance_score"] is None
    assert rows[0]["head_version"] is None


def test_kill_switch_restores_todays_behavior(host_repo, monkeypatch, capsys):
    stage_artifact()
    monkeypatch.setattr(me, "_embed", fake_embed(-1.0))  # would suppress
    monkeypatch.setenv("MONITION_CASCADE_DISABLE", "1")
    out = run_hook(monkeypatch, capsys, "question about the migration", "cs4")
    assert "[t7/f" in out                                # fired anyway
    assert firings(host_repo, "cs4")[0]["relevance_score"] is None


def test_scorer_error_fails_open_ungated(host_repo, monkeypatch, capsys):
    stage_artifact()
    def boom(texts):
        raise RuntimeError("embedding stack down")
    monkeypatch.setattr(me, "_embed", boom)
    out = run_hook(monkeypatch, capsys, "question about the migration", "cs5")
    assert "[t7/f" in out                                # fail-open: fires
    assert firings(host_repo, "cs5")[0]["relevance_score"] is None
    with open(_log_path()) as f:
        assert "[cascade-error]" in f.read()


def test_sanitizer_gates_matcher_on_quoted_rows(host_repo, monkeypatch, capsys):
    # The ONLY mention of the trigger keyword lives inside a quoted injected-row
    # line — sanitized away, so the matcher sees no keyword and stays silent.
    quoted = ("Takeaways for this prompt (full text: monition show <t-id>; "
              "rate: monition rate <f-id> helpful|noise):\n"
              "[t7/f123] on_demand: migration gotcha\n"
              "why was that injected here?")
    out = run_hook(monkeypatch, capsys, quoted, "cs6")
    assert out == ""
    assert firings(host_repo, "cs6") == []
    # control: the same keyword as real prose still matches (cs7)
    monkeypatch.setattr(me, "_embed", fake_embed(1.0))
    stage_artifact()
    out = run_hook(monkeypatch, capsys, "why was the migration row injected?",
                   "cs7")
    assert "[t7/f" in out
