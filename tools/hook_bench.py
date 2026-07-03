#!/usr/bin/env python3
"""Hook hot-path bench: measure warm per-hook latency on a scratch copy of a store.

Copies the source store (default: $MONITION_STORE) to a tmp scratch dir, pipes N
synthetic prompt/tool events through `monition prompt-hook` / `fire-hook` with
MONITION_TRACE, prints per-phase medians, and tears everything down — including
any resident dolt sql-server the scratch store spawned.

The scratch copy is the point: piping fabricated events into an executor IS
instrumentation, and instrumentation writes never touch the hub (CLAUDE.md).

Usage: tools/hook_bench.py [--store PATH] [--runs N] [--cold]
  --cold  unset MONITION_SQL_SERVER/MONITION_EMBED_DAEMON for the runs
          (default is warm: inherit the machine's daemon flags).
"""
import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile

PROMPT_EVENT = {
    "prompt": "why does the test suite fail in a fresh worktree without a venv?",
    "session_id": "hook-bench",
}
TOOL_EVENT = {
    "tool_name": "Bash",
    "tool_input": {"command": "git status"},
    "session_id": "hook-bench",
}


def run_hook(subcommand, event, env, cwd):
    subprocess.run(
        ["monition", subcommand],
        input=json.dumps(event), text=True, capture_output=True,
        env=env, cwd=cwd, timeout=60,
    )


def summarize(trace_path):
    by_event = {}
    with open(trace_path) as f:
        for line in f:
            rec = json.loads(line)
            ev = by_event.setdefault(rec["event"], {"total": [], "phases": {}})
            ev["total"].append(rec["total_ms"])
            for p in rec["phases"]:
                ev["phases"].setdefault(p["phase"], []).append(p["ms"])
    for event, data in by_event.items():
        med = statistics.median(data["total"])
        print(f"\n{event}: n={len(data['total'])} median_total={med:.0f}ms")
        for phase, vals in data["phases"].items():
            pm = statistics.median(vals)
            if pm >= 5:
                print(f"  {phase:<28} {pm:>7.0f}ms")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default=os.environ.get("MONITION_STORE"))
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--cold", action="store_true")
    args = ap.parse_args()
    if not args.store or not os.path.isdir(args.store):
        sys.exit("no source store: pass --store or set MONITION_STORE")

    scratch_root = tempfile.mkdtemp(prefix="monition-hook-bench-")
    scratch = os.path.join(scratch_root, "store")
    print(f"copying {args.store} -> {scratch}")
    shutil.copytree(args.store, scratch)

    env = dict(os.environ)
    env["MONITION_STORE"] = scratch
    trace_path = os.path.join(scratch_root, "trace.jsonl")
    env["MONITION_TRACE"] = trace_path
    env.pop("MONITION_FIRING_OBSERVER", None)  # observer is machine UI, not hook cost
    if args.cold:
        env.pop("MONITION_SQL_SERVER", None)
        env.pop("MONITION_EMBED_DAEMON", None)

    # Hooks derive the repo from cwd; run from this repo's root.
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        # One unmeasured warm-up event so daemon spawn/cache costs don't skew run 1.
        run_hook("prompt-hook", PROMPT_EVENT, {**env, "MONITION_TRACE": ""}, repo_root)
        for _ in range(args.runs):
            run_hook("prompt-hook", PROMPT_EVENT, env, repo_root)
            run_hook("fire-hook", TOOL_EVENT, env, repo_root)
        summarize(trace_path)
    finally:
        subprocess.run(
            ["monition", "sql-server-stop", "--store", scratch],
            capture_output=True, timeout=30,
        )
        shutil.rmtree(scratch_root, ignore_errors=True)
        print(f"\nscratch removed; sql-server-stop issued for {scratch}")


if __name__ == "__main__":
    main()
