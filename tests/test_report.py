"""Report rendering + CLI, including the read-only guarantee."""
import hashlib
import os
import sqlite3

from monition.cli import main
from monition.report import render
from monition.store import Store


def test_report_contents(canonical_store):
    text = render(Store(canonical_store))
    assert "7 takeaways" in text and "8 firings, 5 rated" in text
    assert "1 from anonymous sessions" in text  # session_id == "unknown"
    assert "1 mirror-back candidate(s) queued" in text
    assert "t1: all rated firings were noise" in text
    assert "noise on: docs/a.md" in text


def test_cli_exit_codes(canonical_store, tmp_path, capsys):
    assert main(["report", canonical_store]) == 0
    assert main(["report", str(tmp_path)]) == 2
    assert "contract violation" in capsys.readouterr().err


def _db_hash(path):
    """SHA-256 of all table rows — proves the working set is unmodified."""
    db = os.path.join(path, "store.db")
    h = hashlib.sha256()
    with sqlite3.connect(db) as conn:
        for table in ("takeaways", "firings", "decisions"):
            for row in conn.execute(f"SELECT * FROM {table} ORDER BY id"):
                h.update(str(row).encode())
    return h.hexdigest()


def test_report_is_read_only(canonical_store):
    before = _db_hash(canonical_store)
    render(Store(canonical_store))
    assert _db_hash(canonical_store) == before
