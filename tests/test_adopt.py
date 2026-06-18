"""Tier-0 interchange round-trip (contract §Tier-0 interchange format)."""
import os

import pytest

from monition.adopt import adopt, check_block, parse_blocks
from monition.store import Store
from monition.init_sync import init

FIXTURE = """\
# Lessons from incubation

Free prose up here is ignored entirely.
kind: this-looks-like-a-header but is outside any block

## takeaway
kind: gotcha
trigger_kind: edit_path
trigger_spec: payload/*, schema/*
one_liner: payload edits must keep the frozen executor untouched
scope: payload
source: session 2026-06-09
custom_key: tolerated and ignored
full_content:
The why lives here.

Multi-paragraph, blank interior line preserved.

## takeaway
kind: rule
trigger_kind: session_start
one_liner: minimal block, optional fields absent

## takeaway
trigger_kind: edit_path
one_liner: missing kind

## takeaway
kind: epiphany
trigger_kind: edit_path
one_liner: bad kind domain

## takeaway
kind: gotcha
trigger_kind: on_commit
one_liner: bad trigger_kind domain
"""


def test_parse_blocks_shapes():
    blocks = parse_blocks(FIXTURE)
    assert len(blocks) == 5
    b = blocks[0]
    assert b["kind"] == "gotcha"
    assert b["trigger_spec"] == "payload/*, schema/*"
    assert "custom_key" not in b
    assert b["full_content"] == (
        "The why lives here.\n\n"
        "Multi-paragraph, blank interior line preserved."
    )
    assert blocks[1] == {"kind": "rule", "trigger_kind": "session_start",
                         "one_liner": "minimal block, optional fields absent"}


def test_check_block_reasons():
    blocks = parse_blocks(FIXTURE)
    assert check_block(blocks[0]) is None
    assert check_block(blocks[1]) is None
    assert check_block(blocks[2]) == "missing required field: kind"
    assert check_block(blocks[3]) == "invalid kind: epiphany"
    assert check_block(blocks[4]) == "invalid trigger_kind: on_commit"


@pytest.fixture
def fresh_store(tmp_path):
    root = str(tmp_path / "host")
    os.makedirs(root)
    init(root)
    return os.path.join(root, "monition")


def test_adopt_round_trip(fresh_store, tmp_path):
    lessons = tmp_path / "lessons.md"
    lessons.write_text(FIXTURE)
    lines = adopt(fresh_store, str(lessons))

    # conservation + per-rejection reasons, stable strings
    assert lines[0] == (f"imported 2 takeaway(s), rejected 3 of 5 block(s) "
                        f"from {lessons}")
    assert lines[1:] == [
        "block 3: missing required field: kind",
        "block 4: invalid kind: epiphany",
        "block 5: invalid trigger_kind: on_commit",
    ]

    rows = Store(fresh_store).takeaways()
    assert len(rows) == 2
    t1, t2 = rows
    assert (t1.kind, t1.trigger_kind, t1.trigger_spec, t1.scope, t1.source) == (
        "gotcha", "edit_path", "payload/*, schema/*", "payload",
        "session 2026-06-09")
    assert t1.one_liner == "payload edits must keep the frozen executor untouched"
    assert t1.full_content == (
        "The why lives here.\n\n"
        "Multi-paragraph, blank interior line preserved.")
    assert (t1.status, t1.mirror) == ("active", "none")  # defaults applied
    assert (t2.kind, t2.trigger_kind, t2.trigger_spec, t2.full_content,
            t2.scope, t2.source) == (
        "rule", "session_start", None, None, None, None)


def test_adopted_rows_fire(fresh_store, tmp_path):
    """Imported edit_path rows are live: same fnmatch dialect end-to-end."""
    from monition.store_write import WriteStore
    lessons = tmp_path / "lessons.md"
    lessons.write_text(FIXTURE)
    adopt(fresh_store, str(lessons))
    ws = WriteStore(fresh_store)
    import json
    hits = json.loads(ws.match("payload/deep/nested.py", "s1"))
    assert [h["id"] for h in hits] == [1]  # * crosses separators
