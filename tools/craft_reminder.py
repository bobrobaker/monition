#!/usr/bin/env python3
"""PreToolUse hook: one-line reminder before edits to governed material.

Tier 2 of the enforcement split: the harness guarantees firing, the agent supplies
the judgment. Three properties are load-bearing — fires once per session *per pointer*
(a reminder that repeats becomes noise; distinct pointers are distinct reminders),
never blocks, and fails open (malformed input exits silently; a reminder has no
business stopping work).

Wire in .claude/settings.json:

    {"hooks": {"PreToolUse": [{"matcher": "Write|Edit",
        "hooks": [{"type": "command", "command": "python3 tools/craft_reminder.py"}]}]}}
"""
import json
import os
import sys

# Configure per project: (key, path fragment, pointer), most-specific first. The
# first rule whose fragment is in the path wins, so a more-specific governed surface
# (e.g. docs/decisions/) gets its own pointer instead of the generic one. `key` scopes
# the once-per-session marker, so distinct pointers fire independently.
RULES = [
    ("decision", "docs/decisions/",
     "Authoring a decision? Audit docs/decisions/ + road.md §2 for what this "
     "supersedes or contradicts; cite the contract section it affirms; mark any "
     "superseded doc Status: superseded-by …."),
    ("governed", "docs/",
     "Editing governed material — contracts bind consumers: check "
     "docs/contracts/ and docs/road.md before changing docs/."),
]


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return  # fail open

    fp = (data.get("tool_input") or {}).get("file_path", "") or ""
    sid = str(data.get("session_id", "unknown"))
    for key, fragment, pointer in RULES:  # most-specific first; first match wins
        if fragment not in fp:
            continue
        marker = "/tmp/craft_reminder_" + sid + "_" + key
        if os.path.exists(marker):
            return  # this pointer already shown this session
        open(marker, "w").close()
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": pointer}}))
        return  # one reminder per write: most-specific rule fired


if __name__ == "__main__":
    main()
