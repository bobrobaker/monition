"""monition CLI.

`monition report <store-path>` — the offline audit (Phase 1).
Lifecycle commands (ported from CMS takeaway.py, behavior-identical):
add / list / show / match / session-start / fire / rate / log-recurrence /
retire / dump / commit. Each takes `--store <path>`; default is the convention path
`<repo-root>/monition/`.
"""
import argparse
import json
import os
import sys

from .adopt import adopt as adopt_file
from .backends import BackendError
from .export import export_records, render_jsonl
from .hooks import fire_hook, prompt_hook, session_brief
from .init_sync import (init as init_repo, migrate as migrate_store, sync as sync_repo,
                        fold_store, init_store, instrument)
from .replay import DEFAULT_CONDITION_CAP, DEFAULT_RUN_TIMEOUT, ReplayError, run_replay
from .report import render, render_tune
from .snapshot import SnapshotError, capture as capture_snapshot
from .store import Store, StoreContractError
from .score import score as run_score
from .store_write import WriteStore, iid, resolve_store_path, current_repo


def _git_root():
    import subprocess
    out = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                         capture_output=True, text=True)
    return out.stdout.strip() if out.returncode == 0 else None


def _open(args):
    path = args.store or resolve_store_path()
    if not path:
        raise StoreContractError(
            "no store path: pass --store or run inside a git repo "
            "(convention path <repo-root>/monition/)"
        )
    return WriteStore(path)


def _render_resurrection(matches):
    """The consent gate: a suppressed near-match refuses the silent insert."""
    out = [
        "RESURRECTION: this lesson near-matches a takeaway the scorer is suppressing.",
        "Re-learning a suppressed lesson is evidence the suppression was wrong.",
        "",
    ]
    for m in matches:
        ev = "cold-start" if m["ev_score"] is None else f"ev {m['ev_score']:.2f}"
        out.append(f"  t{m['id']}  sim {m['similarity']:.2f}  \"{m['one_liner']}\"")
        out.append(f"        suppressed {m['decided_at']}: "
                   f"{m['evidence_count']} rated, {ev}")
    top = matches[0]["id"]
    out += [
        "",
        "Re-run `monition add <same args> --resolve CHOICE`:",
        f"  --resolve log-helpful:t{top}   revive it (log this recurrence as helpful-equivalent)",
        f"  --resolve merge:t{top}         fold this lesson's wording into it (no duplicate)",
        "  --resolve new               create anyway (genuinely distinct)",
    ]
    return "\n".join(out)


def _run_add(ws, args):
    """`add` with Phase-4 suppression-resurrection detection. Without --resolve,
    a near-match to a currently-suppressed row refuses the insert and prints the
    consent gate (exit 3) for the caller to resolve; otherwise inserts normally.
    With --resolve, applies the chosen resolution."""
    if args.resolve:
        print(ws.resolve_add(args.resolve, args.kind, args.trigger_kind,
                             args.one_liner, args.trigger_spec, args.full_content,
                             args.scope, args.source, args.reach, args.origin_repo))
        return 0
    matches = ws.find_resurrection(args.one_liner, args.full_content)
    if matches:
        print(_render_resurrection(matches))
        return 3
    print(ws.add(args.kind, args.trigger_kind, args.one_liner, args.trigger_spec,
                 args.full_content, args.scope, args.source, args.reach, args.origin_repo))
    return 0


def main(argv=None):
    # crash-test seam: proves the guarded hook command keeps a session
    # unblocked when monition is present but failing (spec decision 14)
    if os.environ.get("MONITION_TEST_CRASH"):
        raise RuntimeError("induced crash (MONITION_TEST_CRASH)")
    p = argparse.ArgumentParser(prog="monition", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("report", help="audit a Monition store by path")
    s.add_argument("store_path", help="directory of the live Dolt store")

    def lifecycle(name, help=None):
        sp = sub.add_parser(name, help=help)
        sp.add_argument("--store", help="store directory (default: <repo-root>/monition/)")
        return sp

    s = lifecycle("add")
    s.add_argument("--kind", required=True, choices=["gotcha", "rule", "preference"])
    s.add_argument("--trigger-kind", required=True,
                   choices=["edit_path", "session_start", "on_demand"])
    s.add_argument("--trigger-spec")
    s.add_argument("--one-liner", required=True)
    s.add_argument("--full-content")
    s.add_argument("--scope")
    s.add_argument("--source")
    s.add_argument("--reach", default="project",
                   choices=["general", "project"],
                   help="general = fires in every repo; project = only where authored")
    s.add_argument("--origin-repo",
                   help="absolute repo root this row belongs to (default: current repo)")
    s.add_argument("--resolve", metavar="CHOICE",
                   help="resolve a suppressed near-match: new | merge:ID | log-helpful:ID")

    s = lifecycle("list")
    s.add_argument("--status", default="active")

    s = lifecycle("show")
    s.add_argument("id")

    s = lifecycle("match")
    s.add_argument("--path", required=True)
    s.add_argument("--session")

    s = lifecycle("session-start")
    s.add_argument("--session")

    s = lifecycle("fire")
    s.add_argument("takeaway_id")
    s.add_argument("--session")
    s.add_argument("--trigger-kind", required=True)
    s.add_argument("--context")

    s = lifecycle("rate")
    s.add_argument("firing_id")
    s.add_argument("outcome", choices=["helpful", "noise"])

    s = lifecycle("log-recurrence",
                  help="log a mine-time recurrence (helpful firing) on an active row")
    s.add_argument("takeaway_id")
    s.add_argument("--session")
    s.add_argument("--context")

    s = lifecycle("retire")
    s.add_argument("id")

    s = lifecycle("dump")

    s = lifecycle("commit")
    s.add_argument("-m", "--message", required=True)

    sub.add_parser("fire-hook", help="PreToolUse executor: stdin hook JSON")
    sub.add_parser("session-brief", help="SessionStart executor: stdin hook JSON")
    sub.add_parser("prompt-hook", help="UserPromptSubmit executor: stdin hook JSON")

    sub.add_parser("mcp-serve", help="run the MCP server (requires monition[mcp])")
    sub.add_parser("embed-warm",
                   help="pre-fetch the embedding model weights into the managed cache "
                        "(off the hook path; requires monition[embed])")
    sub.add_parser("embed-daemon",
                   help="run the warm embedding daemon (usually lazy-spawned; opt-in "
                        "via MONITION_EMBED_DAEMON)")

    s = sub.add_parser("init", help="adopt monition in a host repo (idempotent) "
                                    "= init-store <root>/monition + instrument")
    s.add_argument("--root", help="host repo root (default: git toplevel)")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--with-dump-hook", action="store_true")
    s.add_argument("--dolt", action="store_true",
                   help="use Dolt backend instead of SQLite (requires dolt binary)")
    s.add_argument("--adopt", metavar="FILE",
                   help="import a tier-0 lessons file after init")

    s = sub.add_parser("init-store",
                       help="create a Monition store with NO instrumentation (the hub, or a standalone store)")
    s.add_argument("store_path", help="directory for the store")
    s.add_argument("--dolt", action="store_true",
                   help="use the Dolt backend (requires dolt binary; default SQLite)")
    s.add_argument("--dry-run", action="store_true")

    s = sub.add_parser("instrument",
                       help="wire monition hooks/MCP/skills into a repo + point MONITION_STORE at a store; creates NO store")
    s.add_argument("--root", help="repo root to instrument (default: git toplevel)")
    s.add_argument("--store",
                   help="store to point MONITION_STORE at (a hub/external store); "
                        "omit for the <root>/monition convention (no env written)")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--with-dump-hook", action="store_true")

    s = sub.add_parser("adopt", help="import a tier-0 lessons file into a store")
    s.add_argument("file")
    s.add_argument("--store", help="store directory (default: <repo-root>/monition/)")

    s = sub.add_parser("sync", help="refresh hook entries + skills (hash-checked)")
    s.add_argument("--root", help="host repo root (default: git toplevel)")

    s = sub.add_parser("migrate", help="migrate a store up to the current schema (v6), cumulative")
    s.add_argument("--store", help="store directory (default: <repo-root>/monition/)")
    s.add_argument("--fold-into", metavar="HUB",
                   help="fold --store's rows into this Dolt hub (Dolt→Dolt) instead of "
                        "migrating in place; --store must already be v6")

    s = sub.add_parser("score", help="score a takeaway: fire or suppress decision")
    s.add_argument("takeaway_id", help="takeaway id (numeric or tN form)")
    s.add_argument("--session")
    s.add_argument("--store", help="store directory (default: <repo-root>/monition/)")

    s = sub.add_parser("tune", help="measure EV scorer quality vs always-fire baseline")
    s.add_argument("--store", help="store directory (default: <repo-root>/monition/)")

    s = sub.add_parser("query", help="match on_demand takeaways by keyword against query text")
    s.add_argument("query_text", metavar="query", help="free-text query string")
    s.add_argument("--session")
    s.add_argument("--store", help="store directory (default: <repo-root>/monition/)")

    s = sub.add_parser("export-firings",
                       help="export firings as JSONL for tier-3 eval (read-only)")
    s.add_argument("--store", help="store directory (default: <repo-root>/monition/)")
    s.add_argument("--since", metavar="DATE",
                   help="only firings on/after this date (YYYY-MM-DD)")
    rating_filter = s.add_mutually_exclusive_group()
    rating_filter.add_argument("--rated-only", action="store_true",
                               help="only firings with a non-NULL outcome")
    rating_filter.add_argument("--unrated-only", action="store_true",
                               help="only firings with a NULL outcome (the rating worklist)")
    s.add_argument("--session", metavar="ID",
                   help="only firings of this session_id (scope a rating pass)")
    s.add_argument("--order-by", choices=["fired_at", "priority"], default="fired_at",
                   help="emission order: fired_at (default) or priority "
                        "(head-not-tail rating worklist, highest-value first)")
    s.add_argument("--format", choices=["jsonl"], default="jsonl",
                   help="output format (v1: jsonl only)")

    s = sub.add_parser("snapshot",
                       help="capture a replay-ablation environment snapshot (side ref)")
    s.add_argument("--issue", help="short description of the flagged issue (derives the id)")
    s.add_argument("--firing",
                   help="originating firing id; stamps its sha+situation, derives the id")
    s.add_argument("--store", help="store directory (default: <repo-root>/monition/)")
    s.add_argument("--root", help="host repo root (default: git toplevel)")

    s = sub.add_parser("replay",
                       help="vary context conditions over a snapshot; emit per-condition artifacts")
    s.add_argument("--snapshot", required=True,
                   help="snapshot ref (e.g. refs/monition/snapshots/<id>)")
    s.add_argument("--manifest", required=True, help="YAML conditions manifest")
    s.add_argument("--out", help="output dir (default: <repo-root>/monition-replay/<run-id>/)")
    s.add_argument("--parallel", type=int, default=1,
                   help="run up to N conditions concurrently (bounded; default sequential)")
    s.add_argument("--dry-run", action="store_true",
                   help="list the worktrees/runs it would create without spawning agents")
    s.add_argument("--backend", default="tmux", help="execution backend (default: tmux)")
    s.add_argument("--max-conditions", type=int, default=DEFAULT_CONDITION_CAP,
                   help=f"hard cap on conditions per call (default {DEFAULT_CONDITION_CAP})")
    s.add_argument("--timeout", type=float, default=DEFAULT_RUN_TIMEOUT,
                   help=f"per-run wall-clock timeout in seconds (default {int(DEFAULT_RUN_TIMEOUT)})")
    s.add_argument("--root", help="host repo root (default: git toplevel)")

    args = p.parse_args(argv)
    if args.cmd == "fire-hook":
        fire_hook()
        return 0
    if args.cmd == "session-brief":
        session_brief()
        return 0
    if args.cmd == "prompt-hook":
        prompt_hook()
        return 0
    if args.cmd == "mcp-serve":
        from .mcp_server import serve
        return serve()
    try:
        if args.cmd == "init-store":
            lines = init_store(args.store_path, dolt=args.dolt, dry_run=args.dry_run)
            print("\n".join(lines or ["no changes (store already exists)"]))
            return 0
        if args.cmd == "instrument":
            root = args.root or _git_root()
            if not root:
                raise StoreContractError("not in a git repo: pass --root")
            lines = instrument(root, store=args.store, dry_run=args.dry_run,
                               with_dump_hook=args.with_dump_hook)
            print("\n".join(lines or ["no changes"]))
            return 0
        if args.cmd in ("init", "sync"):
            root = args.root or _git_root()
            if not root:
                raise StoreContractError("not in a git repo: pass --root")
            if args.cmd == "init":
                lines = init_repo(root, dry_run=args.dry_run,
                                  with_dump_hook=args.with_dump_hook,
                                  dolt=args.dolt)
                if args.adopt and not args.dry_run:
                    lines += adopt_file(os.path.join(root, "monition"), args.adopt)
                elif args.adopt:
                    lines.append(f"would adopt {args.adopt}")
            else:
                lines = sync_repo(root)
            print("\n".join(lines))
            return 0
        if args.cmd == "adopt":
            print("\n".join(adopt_file(
                args.store or resolve_store_path(), args.file)))
            return 0
        if args.cmd == "migrate":
            src = args.store or resolve_store_path()
            if args.fold_into:
                print(fold_store(src, args.fold_into))
            else:
                print(migrate_store(src))
            return 0
        if args.cmd == "embed-warm":
            from . import embed
            print(embed.warm())
            return 0
        if args.cmd == "embed-daemon":
            from . import embed
            embed.run_daemon()
            return 0
        if args.cmd == "score":
            path = args.store or resolve_store_path()
            if not path:
                raise StoreContractError(
                    "no store path: pass --store or run inside a git repo"
                )
            result = run_score(iid(args.takeaway_id), path,
                               session_id=getattr(args, "session", None))
            print(json.dumps(result, indent=2))
            return 0
        if args.cmd == "tune":
            path = args.store or resolve_store_path()
            if not path:
                raise StoreContractError(
                    "no store path: pass --store or run inside a git repo"
                )
            print(render_tune(Store(path)))
            return 0
        if args.cmd == "export-firings":
            path = args.store or resolve_store_path()
            if not path:
                raise StoreContractError(
                    "no store path: pass --store or run inside a git repo"
                )
            out = render_jsonl(export_records(
                Store(path), since=args.since, rated_only=args.rated_only,
                unrated_only=args.unrated_only, session=args.session,
                order_by=args.order_by))
            if out:
                print(out)
            return 0
        if args.cmd == "snapshot":
            root = args.root or _git_root()
            if not root:
                raise StoreContractError("not in a git repo: pass --root")
            store_path = None
            if args.firing:
                store_path = args.store or resolve_store_path()
                if not store_path:
                    raise StoreContractError(
                        "no store path for --firing: pass --store or run inside a git repo"
                    )
            print(json.dumps(
                capture_snapshot(root, issue=args.issue, firing_id=args.firing,
                                 store_path=store_path), indent=2))
            return 0
        if args.cmd == "replay":
            result = run_replay(
                args.snapshot, args.manifest, out_dir=args.out,
                parallel=args.parallel, dry_run=args.dry_run,
                backend_name=args.backend, repo_root=args.root or _git_root(),
                max_conditions=args.max_conditions, timeout=args.timeout)
            if result.get("dry_run"):
                print(json.dumps(result, indent=2))
                return 0
            print(json.dumps({
                "out_dir": result["out_dir"],
                "summary": result["summary"],
                "conditions": [
                    {"condition_id": r["condition_id"], "status": r["status"],
                     "completed_by": r["completed_by"],
                     "check_passed": (r["verdict"] or {}).get("passed")}
                    for r in result["records"]],
            }, indent=2))
            return 0
        if args.cmd == "query":
            path = args.store or resolve_store_path()
            if not path:
                raise StoreContractError(
                    "no store path: pass --store or run inside a git repo"
                )
            ws = WriteStore(path)
            print(ws.on_demand_match(args.query_text,
                                     session=getattr(args, "session", None),
                                     current_repo=current_repo()))
            return 0
        if args.cmd == "report":
            print(render(Store(args.store_path)))
        else:
            ws = _open(args)
            if args.cmd == "add":
                return _run_add(ws, args)
            cr = current_repo()  # host repo, independent of store location (hub-safe)
            out = {
                "list": lambda: ws.list_rows(args.status),
                "show": lambda: ws.show(args.id),
                "match": lambda: ws.match(args.path, args.session, current_repo=cr),
                "session-start": lambda: ws.session_start(args.session, current_repo=cr),
                "fire": lambda: ws.fire(args.takeaway_id, args.trigger_kind,
                                        args.session, args.context, current_repo=cr),
                "rate": lambda: ws.rate(args.firing_id, args.outcome),
                "log-recurrence": lambda: "takeaway {} recurrence logged (helpful firing {})".format(
                    args.takeaway_id,
                    ws.log_recurrence(args.takeaway_id, context=args.context,
                                      session=args.session, current_repo=cr)),
                "retire": lambda: ws.retire(args.id),
                "dump": lambda: ws.dump(),
                "commit": lambda: ws.commit(args.message),
            }[args.cmd]()
            print(out)
    except StoreContractError as e:
        print(f"contract violation: {e}", file=sys.stderr)
        return 2
    except (ReplayError, SnapshotError, BackendError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
