"""Tier-0 lessons-file importer — `monition adopt` / `monition init --adopt`.

The format is owned by the contract (§Tier-0 interchange format); this module
is its importing consumer. Parsing is deliberately line-oriented and dumb —
the same dialect a frozen tier-0 executor reads — and every parsed block is
either imported or rejected with a counted reason, never silently skipped.
"""
from .store_write import WriteStore

KINDS = ("gotcha", "rule", "preference")
TRIGGER_KINDS = ("edit_path", "session_start", "on_demand")
KEYS = ("kind", "trigger_kind", "trigger_spec", "one_liner", "scope", "source")
REQUIRED = ("kind", "trigger_kind", "one_liner")


def parse_blocks(text):
    """Returns a list of dicts, one per `## takeaway` block, in file order."""
    blocks = []
    fields = None
    content_lines = None
    for line in text.splitlines():
        if line == "## takeaway":
            if fields is not None:
                blocks.append(_finish(fields, content_lines))
            fields, content_lines = {}, None
            continue
        if fields is None:
            continue  # prose outside any block
        if content_lines is not None:
            content_lines.append(line)
        elif line == "full_content:":
            content_lines = []
        elif ":" in line:
            key, value = line.split(":", 1)
            if key in KEYS:
                fields[key] = value.strip()
            # unknown keys tolerated and ignored
    if fields is not None:
        blocks.append(_finish(fields, content_lines))
    return blocks


def _finish(fields, content_lines):
    if content_lines is not None:
        body = "\n".join(content_lines).strip("\n")
        if body:
            fields["full_content"] = body
    return fields


def check_block(fields):
    """Returns a rejection reason (stable string) or None if valid."""
    for key in REQUIRED:
        if not fields.get(key):
            return f"missing required field: {key}"
    if fields["kind"] not in KINDS:
        return f"invalid kind: {fields['kind']}"
    if fields["trigger_kind"] not in TRIGGER_KINDS:
        return f"invalid trigger_kind: {fields['trigger_kind']}"
    return None


def adopt(store_path, lessons_file):
    """Import a tier-0 lessons file. Returns the report lines."""
    with open(lessons_file) as f:
        blocks = parse_blocks(f.read())
    store = WriteStore(store_path)
    imported, rejections = 0, []
    for n, fields in enumerate(blocks, 1):
        reason = check_block(fields)
        if reason:
            rejections.append(f"block {n}: {reason}")
            continue
        store.add(
            kind=fields["kind"],
            trigger_kind=fields["trigger_kind"],
            one_liner=fields["one_liner"],
            trigger_spec=fields.get("trigger_spec"),
            full_content=fields.get("full_content"),
            scope=fields.get("scope"),
            source=fields.get("source"),
        )
        imported += 1
    assert imported + len(rejections) == len(blocks)  # conservation
    lines = [f"imported {imported} takeaway(s), rejected {len(rejections)} "
             f"of {len(blocks)} block(s) from {lessons_file}"]
    lines += rejections
    return lines
