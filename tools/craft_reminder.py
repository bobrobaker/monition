#!/usr/bin/env python3
"""PreToolUse hook: one-line reminder before edits to governed material.

Tier 2 of the enforcement split: the harness guarantees firing, the agent supplies
the judgment. Three properties are load-bearing — each pointer fires once per session
(a reminder that repeats becomes noise), never blocks, and fails open (malformed
input exits silently; a reminder has no business stopping work).

`RULES` maps path fragments to pointers; the most specific match wins. The defaults
here are doc-agnostic so a bare fork's reminders fire out of the box. A fork
overrides or adds rows in `tools/craft_reminder_local.py` (a module-level `RULES`
list of the same shape), merged by `key` — local wins. That file is not a managed
tool, so `--update` re-vendoring never touches it and per-project pointer text
survives an upgrade.

Wire in .claude/settings.json:

    {"hooks": {"PreToolUse": [{"matcher": "Write|Edit",
        "hooks": [{"type": "command", "command": "python3 tools/craft_reminder.py"}]}]}}
"""
import json
import os
import sys

# Doc-agnostic defaults. Each rule: `key` (a short filename-safe id — it names the
# per-session firing marker and is the merge handle), `path` (fragment matched against
# the edited file path), `pointer` (the one line injected). Override or add per
# project in tools/craft_reminder_local.py, never here (this file is managed —
# `--update` replaces it).
RULES = [
    {"key": "decisions", "path": "docs/decisions/",
     "pointer": "New decision doc — authoring one is a backward-looking act: audit "
                "docs/decisions/ (and the roadmap) for calls this supersedes or "
                "contradicts, and mark those `status: superseded`."},
    {"key": "docs", "path": "docs/",
     "pointer": "Editing governed material — first consult the craft rules in docs/."},
]


def merge_rules(defaults, local):
    """Merge local rules over defaults by `key` (local wins), most-specific path
    first — so a `docs/decisions/` row outranks a `docs/` row regardless of order."""
    merged = {r["key"]: r for r in defaults}
    for r in local:
        merged[r["key"]] = r
    return sorted(merged.values(), key=lambda r: len(r["path"]), reverse=True)


def load_rules():
    """Defaults merged with the optional fork-local craft_reminder_local.RULES."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import craft_reminder_local
        local = list(getattr(craft_reminder_local, "RULES", []))
    except Exception:
        local = []  # absent or broken local file must not block an edit: fail open
    return merge_rules(RULES, local)


def match(fp, rules):
    """First (most-specific, given merge_rules ordering) rule whose path fragment
    occurs in fp, or None."""
    for rule in rules:
        if rule["path"] in fp:
            return rule
    return None


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return  # fail open

    fp = (data.get("tool_input") or {}).get("file_path", "") or ""
    rule = match(fp, load_rules())
    if rule is None:
        return  # not governed material: stay silent

    # Once per session PER POINTER: each rule key gets its own marker.
    marker = "/tmp/craft_reminder_{}_{}".format(
        data.get("session_id", "unknown"), rule["key"])
    if os.path.exists(marker):
        return  # this pointer already fired this session
    try:
        open(marker, "w").close()
    except OSError:
        pass  # an unwritable /tmp may cause a repeat firing; still better than a crash

    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "additionalContext": rule["pointer"]}}))


if __name__ == "__main__":
    main()
