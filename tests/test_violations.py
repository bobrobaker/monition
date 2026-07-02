"""Phase 6 recall column: violation signatures, the offline evaluator, and the
violations write path (contract §Violation signatures / §Violation semantics /
§validation requirements)."""
import json

import pytest

from monition.evaluate import evaluate_session, extract_transcript_text
from monition.store import StoreContractError
from monition.store_write import WriteStore, validate_signature

from .conftest import sqlite_exec

SIG = json.dumps({"kind": "transcript_regex",
                  "pattern": r"error: manifest lock held"})


@pytest.fixture
def transcript(tmp_path):
    """A JSONL transcript whose tool_result carries the failure text — the
    signature must match extracted string leaves, never raw JSON framing."""
    path = tmp_path / "sess-abc.jsonl"
    lines = [
        {"type": "user", "message": {"content": "please fold the store"}},
        {"type": "tool_result",
         "content": [{"type": "text",
                      "text": "dolt sql failed\nerror: manifest lock held"}]},
        {"type": "assistant", "message": {"content": "that failed, retrying"}},
    ]
    path.write_text("\n".join(json.dumps(l) for l in lines) + "\n")
    return str(path)


def test_validate_signature_write_gate():
    assert json.loads(validate_signature(SIG))["kind"] == "transcript_regex"
    with pytest.raises(StoreContractError, match="not valid JSON"):
        validate_signature("{nope")
    with pytest.raises(StoreContractError, match="unknown signature kind"):
        validate_signature(json.dumps({"kind": "diff_regex", "pattern": "x"}))
    with pytest.raises(StoreContractError, match="does not compile"):
        validate_signature(json.dumps({"kind": "transcript_regex",
                                       "pattern": "[unclosed"}))
    with pytest.raises(StoreContractError, match="pattern"):
        validate_signature(json.dumps({"kind": "transcript_regex"}))


def test_set_signature_and_clear(store_copy):
    ws = WriteStore(store_copy)
    assert "set violation signature" in ws.set_signature("1", SIG)
    assert ws.takeaways()[0].violation_signature == SIG
    assert "cleared" in ws.set_signature("1", None)
    assert ws.takeaways()[0].violation_signature is None
    with pytest.raises(StoreContractError, match="no takeaway"):
        ws.set_signature("999", SIG)


def test_add_with_signature(store_copy):
    ws = WriteStore(store_copy)
    out = ws.add("gotcha", "on_demand", "watch the manifest lock",
                 trigger_spec="dolt", violation_signature=SIG)
    tid = int(out.split()[-1])
    row = {t.id: t for t in ws.takeaways()}[tid]
    assert row.violation_signature == SIG
    with pytest.raises(StoreContractError, match="not valid JSON"):
        ws.add("gotcha", "on_demand", "bad sig", violation_signature="{nope")


def test_log_violation_idempotent(store_copy):
    ws = WriteStore(store_copy)
    first = ws.log_violation("1", "sess-abc", evidence="boom", repo="/r")
    again = ws.log_violation("1", "sess-abc", evidence="boom", repo="/r")
    assert "already logged" in again
    vs = ws.violations()
    assert len(vs) == 1
    assert first.endswith(str(vs[0].id))
    assert vs[0].evidence == "boom" and vs[0].session_id == "sess-abc"
    with pytest.raises(StoreContractError, match="requires a session_id"):
        ws.log_violation("1", None)
    with pytest.raises(StoreContractError, match="no takeaway"):
        ws.log_violation("999", "sess-abc")


def test_extract_transcript_text_uses_leaves_not_framing(transcript):
    text = extract_transcript_text(transcript)
    assert "error: manifest lock held" in text
    assert '"tool_result"' not in text  # framing never leaks into match text


def test_evaluator_three_cells(store_copy, transcript):
    """t1 hit+not-fired → violation; t2 hit+fired → fired∧hit, no violation;
    t3 fired+no-hit → fired∧avoided."""
    ws = WriteStore(store_copy)
    ws.set_signature("1", SIG)
    ws.set_signature("2", SIG)
    ws.set_signature("3", json.dumps(
        {"kind": "transcript_regex", "pattern": "phrase-not-in-transcript"}))
    ws.fire("2", "on_demand", "sess-abc", "ctx")
    ws.fire("3", "on_demand", "sess-abc", "ctx")

    report = evaluate_session(ws, transcript, "sess-abc")
    assert report["fired_hit"] == [2]
    assert report["fired_avoided"] == [3]
    assert [tid for tid, _ in report["not_fired_hit"]] == [1]
    vs = ws.violations()
    assert [v.takeaway_id for v in vs] == [1]
    assert "manifest lock held" in vs[0].evidence

    # idempotent: a re-run classifies identically and adds nothing
    report2 = evaluate_session(ws, transcript, "sess-abc")
    assert "already logged" in report2["not_fired_hit"][0][1]
    assert len(ws.violations()) == 1


def test_evaluator_skips_broken_and_unknown_signatures(store_copy, transcript):
    ws = WriteStore(store_copy)
    # bypass the write gate to simulate a legacy/newer-version row
    sqlite_exec(store_copy,
                "UPDATE takeaways SET violation_signature ="
                " '{\"kind\": \"diff_regex\", \"pattern\": \"x\"}' WHERE id = 1")
    sqlite_exec(store_copy,
                "UPDATE takeaways SET violation_signature = '{nope' WHERE id = 2")
    report = evaluate_session(ws, transcript, "sess-abc")
    assert len(report["skipped"]) == 2
    assert report["not_fired_hit"] == [] and ws.violations() == []


def test_evaluator_respects_reach(store_copy, transcript):
    """A project row from another repo is not this session's business."""
    ws = WriteStore(store_copy)
    ws.set_signature("1", SIG)   # project row; fixture origin_repo is NULL
    sqlite_exec(store_copy,
                "UPDATE takeaways SET origin_repo = '/elsewhere' WHERE id = 1")
    report = evaluate_session(ws, transcript, "sess-abc", repo="/here")
    assert report["rows"] == 0 and ws.violations() == []
    # same row, evaluated in its own repo, is in scope
    report = evaluate_session(ws, transcript, "sess-abc", repo="/elsewhere")
    assert report["rows"] == 1


def test_report_surfaces_false_negatives(store_copy):
    from monition.report import render
    ws = WriteStore(store_copy)
    ws.set_signature("1", SIG)
    ws.log_violation("1", "sess-abc", evidence="boom")
    out = render(ws)
    assert "False negatives" in out
    assert "t1: 1 missed session(s)" in out


def test_eval_session_cli(store_copy, transcript, capsys):
    """CLI wiring: session id defaults to the transcript filename stem."""
    from monition.cli import main
    ws = WriteStore(store_copy)
    ws.set_signature("1", SIG)
    rc = main(["eval-session", "--store", store_copy,
               "--transcript", transcript])
    out = capsys.readouterr().out
    assert rc == 0
    assert "not-fired∧hit: 1" in out
    assert ws.violations()[0].session_id == "sess-abc"
