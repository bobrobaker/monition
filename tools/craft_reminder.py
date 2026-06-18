#!/usr/bin/env python3
"""PreToolUse hook: one-line reminder before edits to governed material.

Tier 2 of the enforcement split: the harness guarantees firing, the agent supplies
the judgment. Three properties are load-bearing — fires once per session (a reminder
that repeats becomes noise), never blocks, and fails open (malformed input exits
silently; a reminder has no business stopping work).

Wire in .claude/settings.json:

    {"hooks": {"PreToolUse": [{"matcher": "Write|Edit",
        "hooks": [{"type": "command", "command": "python3 tools/craft_reminder.py"}]}]}}
"""
import json
import os
import sys

# Configure per project: path fragments that mark governed material, and the pointer.
GOVERNED_PATHS = ["docs/"]
POINTER = ("Editing governed material — contracts bind consumers: check "
           "docs/contracts/ and docs/road.md before changing docs/.")


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return  # fail open

    fp = (data.get("tool_input") or {}).get("file_path", "") or ""
    if not any(p in fp for p in GOVERNED_PATHS):
        return  # not our corpus: stay silent

    marker = "/tmp/craft_reminder_" + str(data.get("session_id", "unknown"))
    if os.path.exists(marker):
        return  # already reminded this session
    open(marker, "w").close()

    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "additionalContext": POINTER}}))


if __name__ == "__main__":
    main()
