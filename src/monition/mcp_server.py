"""MCP server exposing on_demand retrieval as an explicit, Claude-initiated tool.

Wraps `WriteStore.on_demand_match()` (B03 lexical + B04 embeddings) behind a
single `match_gotchas` tool. The MCP surface is never the backbone: the
`edit_path` / `session_start` / `on_demand` hook executors are unaffected.
Unlike the hooks, an explicit query is a pull, not unsolicited injection, so
hits are NOT gated by the EV scorer — but each disclosure still logs a firing
so `monition rate` works on the result.

The `mcp` dependency (install via `monition[mcp]`) is imported lazily inside
`serve()`; the handler logic below is plain Python so it tests without it.
Tool errors never propagate: the handler returns a message string on any
failure (same fail-open posture as the hooks).
"""
from .store_write import WriteStore, resolve_store_path, current_repo


def match_gotchas_impl(query, store_path=None):
    """Returns the disclosure text for a free-text query. Fail-open."""
    import json
    try:
        path = store_path or resolve_store_path()
        if not path:
            return "No Monition store found (not in an initialized repo)."
        repo = current_repo()
        store = WriteStore(path)
        hits = json.loads(store.on_demand_match(query, current_repo=repo))
        lines = []
        for h in hits:
            firing = store.fire(str(h["id"]), "on_demand", None, query[:200],
                                current_repo=repo)
            fid = (firing or "").split()[-1] if firing else "?"
            lines.append(f"[t{h['id']}/f{fid}] {h['one_liner']}")
        if not lines:
            return "No matching gotchas."
        return (
            "Matching gotchas (full text: monition show <t-id>; "
            "rate: monition rate <f-id> helpful|noise):\n" + "\n".join(lines)
        )
    except Exception as e:
        return f"Gotcha lookup unavailable: {e}"


def serve():
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        import sys
        print("mcp extra not installed: pip install 'monition[mcp]'",
              file=sys.stderr)
        return 1

    server = FastMCP("monition")

    @server.tool()
    def match_gotchas(query: str) -> str:
        """Look up stored gotchas/takeaways relevant to a free-text query.

        Use when starting work on a topic (e.g. "database migration",
        "auth flow") to surface lessons this repo has already learned.
        """
        return match_gotchas_impl(query)

    server.run()
    return 0
