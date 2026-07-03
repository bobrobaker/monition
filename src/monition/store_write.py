"""Write-capable store surface — the ported takeaway.py command set.

A characterization port of CMS `tools/takeaway.py` (the oracle until the B06
cutover): same SQL, same matching semantics, same output strings. Contract
sections binding this module: `trigger_spec` coordinate systems (the matching
itself is executed by the trigger modules in `modules.py` — the matchers here
own row selection, hit assembly, dedup, and the cap) and Dedup semantics (at
most one disclosure per takeaway per session, deduped by querying `firings`).

All writes flow through WriteStore, which inherits the reader's fingerprint
validation — no write happens against a store that fails the v2 contract.
"""
import json
import os
import re
import subprocess

from . import modules, session_state
from .store import Store, StoreContractError

# Injection cap: unbounded semantic matching injected 41-75 rows (~6k tokens)
# on broad "meta" prompts. Lexical hits are user-designed deterministic
# triggers and are ALWAYS kept; semantic-only hits are capped to the top
# SEMANTIC_TOP_K by cosine score, then the combined one-liner budget
# INJECTION_CHAR_BUDGET drops the lowest-scoring semantic hits first. Dropping
# is never silent: `on_demand_match` reports the count and the executors
# render a "+N suppressed" trailer.
SEMANTIC_TOP_K = 5
INJECTION_CHAR_BUDGET = 6000

# Dedup at birth: `find_resurrection` checks only currently-suppressed rows, so
# an active near-duplicate used to insert silently (the store grew several
# multi-copy clone groups). An exact one_liner match, or embedding cosine >=
# DUPLICATE_COSINE, against an active non-suppressed row refuses the add
# (`--force` overrides). Deliberately stricter than embed.SIM_THRESHOLD: at 0.9
# two one-liners say the same thing, not merely the same topic.
DUPLICATE_COSINE = 0.9

# `monition add` rejects a longer one_liner (without --force): every char of a
# one_liner is injected into context on every fire, so length is a per-fire
# recurring cost. Detail belongs in full_content (pulled on demand, free).
ONE_LINER_MAX_CHARS = 250

# v7 violation-signature kinds this writer can author. Read-side (the offline
# evaluator) additionally tolerates unknown kinds — rows written by a newer
# monition — by skipping them with a note; the write-side gate is strict.
SIGNATURE_KINDS = ("transcript_regex",)


def validate_signature(raw):
    """Authoring gate (contract §Violation signatures): shape-check the JSON
    and compile the pattern at write time, so read-side skipping stays the
    exception path. Returns the normalized JSON string; raises
    StoreContractError on any defect."""
    try:
        spec = json.loads(raw)
    except (TypeError, ValueError) as e:
        raise StoreContractError(f"violation signature is not valid JSON: {e}")
    if not isinstance(spec, dict) or not spec.get("kind"):
        raise StoreContractError(
            'violation signature must be a JSON object with a "kind"')
    if spec["kind"] not in SIGNATURE_KINDS:
        raise StoreContractError(
            f"unknown signature kind {spec['kind']!r} — this monition can "
            f"author: {', '.join(SIGNATURE_KINDS)}")
    pattern = spec.get("pattern")
    if not pattern or not isinstance(pattern, str):
        raise StoreContractError(
            'a transcript_regex signature needs a non-empty "pattern" string')
    try:
        re.compile(pattern)
    except re.error as e:
        raise StoreContractError(f"signature pattern does not compile: {e}")
    return json.dumps(spec)


TRIGGER_KINDS = ("edit_path", "session_start", "on_demand", "tool_call")


def validate_tool_call_spec(raw):
    """Authoring gate for the v8 tool_call spec (contract §trigger_spec
    coordinate systems): one JSON object with a non-empty "tool", a non-empty
    "field", and a non-empty "contains" list of non-empty strings. Validated
    at write time so the module's read-side fail-open stays the exception
    path. Returns the normalized JSON string."""
    try:
        spec = json.loads(raw)
    except (TypeError, ValueError) as e:
        raise StoreContractError(f"tool_call trigger_spec is not valid JSON: {e}")
    if not isinstance(spec, dict):
        raise StoreContractError("tool_call trigger_spec must be a JSON object")
    for key in ("tool", "field"):
        if not spec.get(key) or not isinstance(spec[key], str):
            raise StoreContractError(
                f'tool_call trigger_spec needs a non-empty "{key}" string')
    contains = spec.get("contains")
    if (not contains or not isinstance(contains, list)
            or not all(isinstance(n, str) and n for n in contains)):
        raise StoreContractError(
            'tool_call trigger_spec needs a non-empty "contains" list of '
            'non-empty strings')
    return json.dumps(spec)


def current_repo():
    """Absolute host repo root: $CLAUDE_PROJECT_DIR (set for hook commands),
    falling back to `git rev-parse --show-toplevel` from cwd. None when neither
    resolves. **Independent of store location** — the store may be a shared hub
    elsewhere (v6); this is always the repo the work is happening in, and it is
    what the reach filter and firing provenance key on.
    """
    root = os.environ.get("CLAUDE_PROJECT_DIR")
    if not root:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True,
        )
        root = out.stdout.strip() if out.returncode == 0 else None
    return root


def resolve_store_path():
    """Store directory. $MONITION_STORE (the v6 hub, if set) wins; otherwise the
    convention path <host-repo-root>/monition/. Unset $MONITION_STORE with no
    detectable repo = no store (standalone/no-hub).
    """
    store = os.environ.get("MONITION_STORE")
    if store:
        return store
    root = current_repo()
    return os.path.join(root, "monition") if root else None


def esc(s):
    """MySQL/Dolt-DIALECT escaping — for Dolt-only paths (init_sync's fold).
    Store methods must use self._val instead: SQLite treats backslashes
    literally, so this corrupts values on SQLite stores."""
    return s.replace("\\", "\\\\").replace("'", "''")


def val(s):
    return "NULL" if s is None else f"'{esc(s)}'"


def iid(s):
    # injection labels render ids as t3/f4; accept those forms everywhere an id is taken
    return int(str(s).lstrip("tf"))


def bval(b):
    """SQL literal for a nullable boolean column: None -> NULL, else 0/1."""
    return "NULL" if b is None else str(int(b))


def _git_provenance(repo_root):
    """(git_sha, git_dirty) for the host repo at fire time. Fail-open — returns
    (None, None) on any error so a firing is never blocked by provenance capture.
    git_sha alone is misleading under uncommitted changes, hence the dirty flag.
    """
    try:
        sha = subprocess.run(["git", "-C", repo_root, "rev-parse", "HEAD"],
                             capture_output=True, text=True)
        if sha.returncode != 0:
            return None, None
        dirty = subprocess.run(["git", "-C", repo_root, "status", "--porcelain"],
                               capture_output=True, text=True)
        is_dirty = bool(dirty.stdout.strip()) if dirty.returncode == 0 else None
        return sha.stdout.strip() or None, is_dirty
    except Exception:
        return None, None


def _monition_version():
    """The installed monition version, or None if undeterminable. Records which
    module build logged/scored the firing — distinct from the host repo's sha."""
    try:
        from importlib.metadata import version, PackageNotFoundError
        try:
            return version("monition")
        except PackageNotFoundError:
            return None
    except Exception:
        return None


# Resurrection detection (Phase 4): when the embed extra is absent, fall back to
# Jaccard overlap of significant (len>=4) content tokens. Strict by design — a
# false "resurrection" needlessly blocks an add, so prefer misses to noise.
_RESURRECTION_LEX_JACCARD = 0.4

# Same-lesson bar for the embedding path, and a cap on how many candidates the
# consent gate shows — resurrection asks "is this THE suppressed lesson,
# re-learned?", a much stricter question than firing relevance.
RESURRECTION_COSINE = 0.8
RESURRECTION_MAX_CANDIDATES = 3


def _content_tokens(text):
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) >= 4}


def _jaccard(a, b):
    ta, tb = _content_tokens(a), _content_tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _cap_hits(lexical, semantic):
    """(kept_hits, capped_count) — apply the injection cap. `semantic` must be
    sorted by score descending; lexical hits are never dropped, even when they
    alone exceed the budget (the cap bounds semantic noise, not the triggers a
    user designed to fire)."""
    kept = list(semantic[:SEMANTIC_TOP_K])
    lexical_chars = sum(len(h["one_liner"]) for h in lexical)
    while kept and (lexical_chars + sum(len(h["one_liner"]) for h in kept)
                    > INJECTION_CHAR_BUDGET):
        kept.pop()  # lowest-scoring semantic hit goes first
    return lexical + kept, len(semantic) - len(kept)


class WriteStore(Store):
    """Store opened for the lifecycle commands; contract-validated like the reader."""

    def _reach_clause(self, repo):
        """SQL predicate gating *where* a row fires: `general` reach fires in
        any repo, `project` only where `origin_repo` equals the current repo.

        `repo is None` means the caller has no repo context — the reach filter
        is then **not applied** (fail-open, legacy behavior). Every
        auto-injection hot path (the hooks) supplies its repo, so the gate is
        live where leakage would be silent; the only callers that can pass
        None are explicit pulls (cli `query`, mcp `match_gotchas`) with no
        detectable repo, where returning the unfiltered set is a transparent
        "you asked, here's everything."
        """
        if repo is None:
            return ""
        # `origin_repo IS NULL` fires anywhere: a project row that never
        # declared its repo is under-specified, so fail-open rather than
        # silently suppress (the store's NULL-is-missing stance). Real v6
        # project rows always carry origin_repo (add() stamps the current
        # repo; migrate backfills it), so isolation holds for every
        # properly-specified row — only malformed/legacy NULLs fire broadly.
        return (f" AND (reach = 'general' OR origin_repo IS NULL"
                f" OR origin_repo = {self._val(repo)})")

    def add(self, kind, trigger_kind, one_liner, trigger_spec=None,
            full_content=None, scope=None, source=None, reach="project",
            origin_repo=None, violation_signature=None):
        # A project row with no origin_repo can never fire (origin_repo = NULL
        # never matches the reach predicate), so stamp the current repo. general
        # rows fire anywhere and need no origin.
        if reach == "project" and origin_repo is None:
            origin_repo = current_repo()
        if violation_signature is not None:
            violation_signature = validate_signature(violation_signature)
        if trigger_kind == "tool_call":
            trigger_spec = validate_tool_call_spec(trigger_spec)
        self._sql(
            "INSERT INTO takeaways (created, kind, scope, trigger_kind, trigger_spec,"
            " one_liner, full_content, source, reach, origin_repo,"
            " violation_signature) VALUES (NOW(), "
            f"{self._val(kind)}, {self._val(scope)}, {self._val(trigger_kind)}, {self._val(trigger_spec)},"
            f" {self._val(one_liner)}, {self._val(full_content)}, {self._val(source)}, {self._val(reach)},"
            f" {self._val(origin_repo)}, {self._val(violation_signature)})"
        )
        # each `dolt sql -q` is its own connection, so LAST_INSERT_ID() is useless here
        row = self._sql("SELECT MAX(id) AS id FROM takeaways")
        return f"added takeaway {row[0]['id']}"

    def set_signature(self, id_, signature):
        """Set or clear (signature=None) a row's violation signature. A narrow,
        purpose-specific mutator in the retire/rate pattern — decision
        2026-06-21 rejects a generic column setter, not verbs like this."""
        rows = self._sql(f"SELECT id FROM takeaways WHERE id = {iid(id_)}")
        if not rows:
            raise StoreContractError(f"no takeaway with id {id_}")
        if signature is None:
            self._sql("UPDATE takeaways SET violation_signature = NULL"
                      f" WHERE id = {iid(id_)}")
            return f"cleared violation signature on takeaway {rows[0]['id']}"
        normalized = validate_signature(signature)
        self._sql(f"UPDATE takeaways SET violation_signature = {self._val(normalized)}"
                  f" WHERE id = {iid(id_)}")
        return f"set violation signature on takeaway {rows[0]['id']}"

    def set_trigger(self, id_, trigger_kind, trigger_spec=None, source=None):
        """Migrate a row along the determinism ladder — the `migrate_kind`
        mutation verb (contract §Trigger modules / §mutations). A narrow,
        consented actuator: rewrites trigger_kind + trigger_spec atomically,
        recording both old values in one event-grain `mutations` row before
        the write. Never called automatically — every use is a human-accepted
        proposal (B01: no auto-apply anywhere)."""
        if trigger_kind not in TRIGGER_KINDS:
            raise StoreContractError(
                f"unknown trigger_kind {trigger_kind!r} — one of: "
                + ", ".join(TRIGGER_KINDS))
        if trigger_kind == "session_start":
            if trigger_spec:
                raise StoreContractError(
                    "session_start takes no trigger_spec (spec is ignored by "
                    "contract — refuse rather than store dead data)")
        elif trigger_kind == "tool_call":
            trigger_spec = validate_tool_call_spec(trigger_spec)
        elif not trigger_spec:
            raise StoreContractError(
                f"{trigger_kind} requires a non-empty trigger_spec")
        rows = self._sql(
            "SELECT id, trigger_kind, trigger_spec FROM takeaways"
            f" WHERE id = {iid(id_)}")
        if not rows:
            raise StoreContractError(f"no takeaway with id {id_}")
        old_kind = rows[0]["trigger_kind"]
        old_spec = rows[0].get("trigger_spec")
        changes = json.dumps({
            "trigger_kind": {"old": old_kind, "new": trigger_kind},
            "trigger_spec": {"old": old_spec, "new": trigger_spec},
        })
        self._sql(
            f"UPDATE takeaways SET trigger_kind = {self._val(trigger_kind)},"
            f" trigger_spec = {self._val(trigger_spec)} WHERE id = {iid(id_)}")
        self._sql(
            "INSERT INTO mutations (takeaway_id, mutated_at, verb, changes,"
            f" source) VALUES ({iid(id_)}, NOW(), 'migrate_kind',"
            f" {self._val(changes)}, {self._val(source)})"
        )
        return (f"takeaway {rows[0]['id']} migrated {old_kind} -> "
                f"{trigger_kind} — mutation logged")

    def retarget(self, id_, trigger_spec, source=None):
        """Rewrite a row's trigger_spec within its current kind — the
        `retarget` mutation verb (contract §mutations, initial vocabulary).
        The narrow actuator behind tighten/broaden/migrate-keyword proposals:
        same-kind spec edit, old spec recorded in an event-grain `mutations`
        row before the write. Never called automatically — every use is a
        human-accepted proposal (no auto-apply anywhere)."""
        rows = self._sql(
            "SELECT id, trigger_kind, trigger_spec FROM takeaways"
            f" WHERE id = {iid(id_)}")
        if not rows:
            raise StoreContractError(f"no takeaway with id {id_}")
        kind = rows[0]["trigger_kind"]
        if kind == "session_start":
            raise StoreContractError(
                "session_start has no trigger_spec to retarget — migrating "
                "the kind is set_trigger's job")
        if kind == "tool_call":
            trigger_spec = validate_tool_call_spec(trigger_spec)
        elif not trigger_spec:
            raise StoreContractError(
                f"{kind} requires a non-empty trigger_spec")
        old_spec = rows[0].get("trigger_spec")
        if trigger_spec == old_spec:
            raise StoreContractError(
                f"retarget is a no-op: takeaway {rows[0]['id']} already has "
                "that trigger_spec")
        changes = json.dumps(
            {"trigger_spec": {"old": old_spec, "new": trigger_spec}})
        self._sql(f"UPDATE takeaways SET trigger_spec = {self._val(trigger_spec)}"
                  f" WHERE id = {iid(id_)}")
        self._sql(
            "INSERT INTO mutations (takeaway_id, mutated_at, verb, changes,"
            f" source) VALUES ({iid(id_)}, NOW(), 'retarget',"
            f" {self._val(changes)}, {self._val(source)})"
        )
        return (f"takeaway {rows[0]['id']} retargeted "
                f"({old_spec!r} -> {trigger_spec!r}) — mutation logged")

    def set_threshold(self, id_, value, source=None):
        """Set or clear (value=None) a row's per-row semantic threshold — the
        `tune` mutation verb (contract §Trigger modules / §mutations). A
        narrow, consented actuator in the set_signature pattern; every call
        writes an event-grain `mutations` row with the old value captured
        BEFORE the update, so replay can reconstruct the prior spec. Domain
        [0,1] (contract; NULL = global SIM_THRESHOLD). The row must be
        on_demand — no other kind has a semantic module to tune."""
        if value is not None:
            value = float(value)
            if not 0.0 <= value <= 1.0:
                raise StoreContractError(
                    f"sem_threshold must be in [0,1], got {value}")
        rows = self._sql(
            "SELECT id, trigger_kind, sem_threshold FROM takeaways"
            f" WHERE id = {iid(id_)}")
        if not rows:
            raise StoreContractError(f"no takeaway with id {id_}")
        if rows[0]["trigger_kind"] != "on_demand":
            raise StoreContractError(
                f"takeaway {rows[0]['id']} is {rows[0]['trigger_kind']!r} — "
                "sem_threshold tunes the on_demand semantic module only")
        old = rows[0].get("sem_threshold")
        old = float(old) if old is not None else None
        changes = json.dumps({"sem_threshold": {"old": old, "new": value}})
        new_sql = "NULL" if value is None else repr(value)
        self._sql(f"UPDATE takeaways SET sem_threshold = {new_sql}"
                  f" WHERE id = {iid(id_)}")
        self._sql(
            "INSERT INTO mutations (takeaway_id, mutated_at, verb, changes,"
            f" source) VALUES ({iid(id_)}, NOW(), 'tune', {self._val(changes)},"
            f" {self._val(source)})"
        )
        what = "cleared" if value is None else f"set to {value}"
        return (f"sem_threshold on takeaway {rows[0]['id']} {what} "
                f"(was {old}) — mutation logged")

    def log_violation(self, takeaway_id, session_id, evidence=None, repo=None):
        """One observed not-fired∧hit event. Idempotent per
        (takeaway, session) — contract §Violation semantics — so re-running
        the evaluator over a session never double-logs."""
        if not session_id:
            raise StoreContractError("a violation requires a session_id")
        rows = self._sql(f"SELECT id FROM takeaways WHERE id = {iid(takeaway_id)}")
        if not rows:
            raise StoreContractError(f"no takeaway with id {takeaway_id}")
        existing = self._sql(
            f"SELECT id FROM violations WHERE takeaway_id = {iid(takeaway_id)}"
            f" AND session_id = {self._val(session_id)}"
        )
        if existing:
            return f"violation {existing[0]['id']} (already logged)"
        self._sql(
            "INSERT INTO violations (takeaway_id, detected_at, session_id,"
            f" evidence, repo) VALUES ({iid(takeaway_id)}, NOW(),"
            f" {self._val(session_id)}, {self._val(evidence)}, {self._val(repo)})"
        )
        row = self._sql("SELECT MAX(id) AS id FROM violations")
        return f"violation {row[0]['id']}"

    def list_rows(self, status="active"):
        rows = self._sql(
            "SELECT id, kind, trigger_kind, trigger_spec, status, reach, one_liner"
            f" FROM takeaways WHERE status = {self._val(status)} ORDER BY id"
        )
        lines = []
        for r in rows:
            spec = r.get("trigger_spec") or "-"
            reach = f" [{r['reach']}]" if r.get("reach") == "general" else ""
            lines.append(f"[{r['id']}] {r['kind']}/{r['trigger_kind']}({spec}){reach} {r['one_liner']}")
        if not rows:
            lines.append(f"(no takeaways with status {status})")
        return "\n".join(lines)

    def show(self, id_):
        rows = self._sql(f"SELECT * FROM takeaways WHERE id = {iid(id_)}")
        return json.dumps(rows[0] if rows else None, indent=2)

    def _not_yet_fired(self, rows, session):
        if not session:
            return rows
        # Compaction re-arm: firings at or before the session's latest
        # compaction marker were wiped from the context window along with the
        # rest of it, so they no longer count as disclosed (see the
        # session_state module docstring).
        floor = session_state.compaction_floor(session)
        fired = self._sql(
            "SELECT DISTINCT takeaway_id FROM firings"
            f" WHERE session_id = {self._val(session)} AND id > {int(floor)}"
        )
        fired_ids = {r["takeaway_id"] for r in fired}
        return [r for r in rows if r["id"] not in fired_ids]

    def match(self, path, session=None, current_repo=None):
        rows = self._sql(
            "SELECT id, one_liner, trigger_spec FROM takeaways"
            " WHERE status = 'active' AND trigger_kind = 'edit_path'"
            + self._reach_clause(current_repo)
        )
        hits = []
        for r in rows:
            evidence = modules.glob_match(r["trigger_spec"], path)
            if evidence is not None:
                hits.append({
                    "id": r["id"], "one_liner": r["one_liner"],
                    "trigger_spec": r.get("trigger_spec"),
                    "evidence": evidence,
                })
        return json.dumps(self._not_yet_fired(hits, session))

    def on_demand_match(self, query, session=None, current_repo=None, cap=True):
        """Hybrid on_demand retrieval. Returns a JSON object
        `{"hits": [...], "capped": N}`: `hits` are `{id, one_liner}` dicts —
        every lexical hit first, then semantic hits by cosine descending —
        after the per-session dedup and (with `cap=True`) the injection cap;
        `capped` is how many above-threshold semantic hits the cap dropped.
        `cap=False` is the explicit-pull escape hatch (`monition query`):
        everything is returned and `capped` is 0."""
        rows = self._sql(
            "SELECT id, one_liner, trigger_spec, sem_threshold FROM takeaways"
            " WHERE status = 'active' AND trigger_kind = 'on_demand'"
            + self._reach_clause(current_repo)
        )
        from . import trace
        trace.mark("match:sql_done")
        lexical, rest = [], []
        for r in rows:
            evidence = modules.lexical_match(r.get("trigger_spec"), query)
            if evidence is not None:
                lexical.append({
                    "id": r["id"], "one_liner": r["one_liner"],
                    "evidence": evidence,
                })
            else:
                rest.append(r)
        trace.mark("match:lexical_done")
        semantic = [{"id": r["id"], "one_liner": r["one_liner"], "evidence": ev}
                    for r, ev in modules.semantic_rank(rest, query)]
        # dedup before capping so already-disclosed hits don't consume cap slots
        lexical = self._not_yet_fired(lexical, session)
        semantic = self._not_yet_fired(semantic, session)
        if cap:
            hits, capped = _cap_hits(lexical, semantic)
        else:
            hits, capped = lexical + semantic, 0
        return json.dumps({"hits": hits, "capped": capped})

    def match_tool_call(self, tool_name, tool_input, session=None,
                        current_repo=None):
        """tool_call rows matching this execution moment (v8). Same shape as
        match(): a JSON list of hit dicts with lossless evidence, per-session
        dedup applied."""
        rows = self._sql(
            "SELECT id, one_liner, trigger_spec FROM takeaways"
            " WHERE status = 'active' AND trigger_kind = 'tool_call'"
            + self._reach_clause(current_repo)
        )
        hits = []
        for r in rows:
            evidence = modules.tool_call_match(
                r.get("trigger_spec"), tool_name, tool_input)
            if evidence is not None:
                hits.append({
                    "id": r["id"], "one_liner": r["one_liner"],
                    "evidence": evidence,
                })
        return json.dumps(self._not_yet_fired(hits, session))

    def session_start(self, session=None, current_repo=None):
        rows = self._sql(
            "SELECT id, one_liner FROM takeaways"
            " WHERE status = 'active' AND trigger_kind = 'session_start'"
            + self._reach_clause(current_repo)
        )
        return json.dumps(self._not_yet_fired(rows, session))

    def fire(self, takeaway_id, trigger_kind, session=None, context=None,
             model=None, situation=None, current_repo=None, evidence=None):
        # v4 provenance: git state of the *host repo* (current_repo), not the store
        # dir — under a v6 hub `os.path.dirname(self.path)` is the hub, not the repo.
        # current_repo is None only for mine-time self-calls (recurrence logging),
        # where there is no host-repo disclosure context; fall back to the store dir
        # for best-effort provenance there and record repo = NULL (honestly unknown).
        # v6 `repo`: the host repo at fire time — capture-or-lose, recovers per-repo
        # precision for general-reach rows. v5 `situation`: the executor's excerpt.
        provenance_root = current_repo or os.path.dirname(self.path)
        git_sha, git_dirty = _git_provenance(provenance_root)
        self._sql(self._FIRINGS_INSERT + self._firing_values(
            takeaway_id, trigger_kind, session, context, git_sha, git_dirty,
            model, situation, current_repo, evidence))
        row = self._sql("SELECT MAX(id) AS id FROM firings")
        return f"firing {row[0]['id']}"

    _FIRINGS_INSERT = (
        "INSERT INTO firings (takeaway_id, fired_at, session_id, trigger_kind,"
        " trigger_context, git_sha, git_dirty, model, monition_version, situation,"
        " repo, match_evidence) VALUES "
    )

    def _firing_values(self, takeaway_id, trigger_kind, session, context,
                       git_sha, git_dirty, model, situation, current_repo,
                       evidence):
        # v7 match evidence: the full, lossless record of what the trigger
        # matched on (dict from the matcher), serialized here. None for fires
        # logged outside the matchers (manual fire, log-recurrence).
        evidence_json = json.dumps(evidence) if evidence is not None else None
        return (
            f"({iid(takeaway_id)}, NOW(), {self._val(session)},"
            f" {self._val(trigger_kind)}, {self._val(context)}, {self._val(git_sha)},"
            f" {bval(git_dirty)}, {self._val(model)}, {self._val(_monition_version())}, {self._val(situation)},"
            f" {self._val(current_repo)}, {self._val(evidence_json)})"
        )

    def fire_batch(self, hits, trigger_kind, session=None, context=None,
                   model=None, situation=None, current_repo=None):
        """Fire every hit of one prompt in ONE INSERT (hook hot path, Phase 8 —
        `fire()` costs two subprocess spawns per hit plus a git-provenance
        subprocess each; a multi-hit prompt paid all of it per hit).
        `hits`: [(takeaway_id, evidence_or_None), ...]. Returns the firing ids
        aligned with `hits` order.

        Id recovery does NOT assume batch ids are consecutive: it re-reads the
        newest rows for THIS session and matches them back by takeaway_id.
        Sessions write one prompt at a time, so our own rows can't interleave;
        other sessions' concurrent rows are excluded by the session filter.
        Per-row SQL is single-sourced with fire() via _firing_values."""
        hits = list(hits)
        if not hits:
            return []
        provenance_root = current_repo or os.path.dirname(self.path)
        git_sha, git_dirty = _git_provenance(provenance_root)
        self._sql(self._FIRINGS_INSERT + ", ".join(
            self._firing_values(tid, trigger_kind, session, context, git_sha,
                                git_dirty, model, situation, current_repo, ev)
            for tid, ev in hits))
        rows = self._sql(
            "SELECT id, takeaway_id FROM firings"
            f" WHERE session_id = {self._val(session)}"
            f" ORDER BY id DESC LIMIT {len(hits)}"
        )
        if len(rows) != len(hits):
            raise StoreContractError(
                f"fire_batch wrote {len(hits)} firings but read back {len(rows)}"
            )
        # rows are newest-first == reverse of VALUES order; assign per
        # takeaway_id so the [tX/fY] line names the row actually written.
        by_takeaway = {}
        for r in reversed(rows):
            by_takeaway.setdefault(int(r["takeaway_id"]), []).append(int(r["id"]))
        ids = []
        for tid, _ in hits:
            pool = by_takeaway.get(int(tid))
            if not pool:
                raise StoreContractError(
                    f"fire_batch read-back is missing takeaway {tid}"
                )
            ids.append(pool.pop(0))
        return ids

    def rate(self, firing_id, outcome):
        self._sql(f"UPDATE firings SET outcome = {self._val(outcome)} WHERE id = {iid(firing_id)}")
        return f"firing {firing_id} rated {outcome}"

    def retire(self, id_):
        self._sql(f"UPDATE takeaways SET status = 'retired' WHERE id = {iid(id_)}")
        return f"takeaway {id_} retired"

    def dump(self):
        target = self._backend.dump(self.path)
        return f"wrote {os.path.relpath(target, os.path.dirname(self.path))}"

    _DECISIONS_INSERT = (
        "INSERT INTO decisions (takeaway_id, session_id, decided_at, decision,"
        " evidence_count, cold_start, ev_score) VALUES "
    )

    def _decision_values(self, takeaway_id, session_id, decision,
                         evidence_count, cold_start, ev_score):
        ev_val = self._val(f"{ev_score:.4f}") if ev_score is not None else "NULL"
        return (f"({iid(takeaway_id)}, {self._val(session_id)}, NOW(), {self._val(decision)},"
                f" {int(evidence_count)}, {1 if cold_start else 0}, {ev_val})")

    def write_decision(self, takeaway_id, session_id, decision,
                       evidence_count, cold_start, ev_score):
        self._sql(self._DECISIONS_INSERT + self._decision_values(
            takeaway_id, session_id, decision, evidence_count, cold_start, ev_score))

    def write_decisions(self, rows):
        """Batch-insert decision rows in ONE INSERT (one Dolt write per prompt
        instead of one per hit). `rows`: iterable of
        (takeaway_id, session_id, decision, evidence_count, cold_start, ev_score).
        Identical per-row SQL to write_decision — single-sourced via _decision_values."""
        rows = list(rows)
        if not rows:
            return
        self._sql(self._DECISIONS_INSERT
                  + ", ".join(self._decision_values(*r) for r in rows))

    # --- Suppression resurrection (Phase 4) ---------------------------------
    # `add` runs find_resurrection before inserting: a near-match to a row the EV
    # scorer is currently suppressing is the harvested natural counterfactual —
    # near-direct evidence the suppression was wrong (the lesson is being
    # re-learned). The consent gate resolves it instead of silently duplicating.

    def _latest_decisions(self):
        """{takeaway_id: Decision} keyed to each row's most recent decision.
        Suppression is computed, not a status — this reads it back."""
        latest = {}
        for d in self.decisions():       # reader yields rows in ascending id order
            latest[d.takeaway_id] = d
        return latest

    def find_resurrection(self, one_liner, full_content=None):
        """Currently-suppressed takeaways whose content near-matches the new
        lesson. Hybrid lexical+embedding over the suppressed candidate set,
        fail-open to lexical-only. Returns match dicts (highest similarity
        first) carrying the suppression evidence, for the consent gate."""
        latest = self._latest_decisions()
        suppressed = {tid for tid, d in latest.items() if d.decision == "suppress"}
        if not suppressed:
            return []
        rows = [t for t in self.takeaways()
                if t.id in suppressed and t.status == "active"]
        if not rows:
            return []
        query = f"{one_liner} {full_content or ''}".strip()
        texts = [f"{t.one_liner} {t.full_content or ''}".strip() for t in rows]
        scores, threshold = self._content_similarity(query, texts)
        matches = []
        for t, score in zip(rows, scores):
            if score >= threshold:
                d = latest[t.id]
                matches.append({
                    "id": t.id, "one_liner": t.one_liner,
                    "similarity": round(float(score), 3),
                    "evidence_count": d.evidence_count, "ev_score": d.ev_score,
                    "decided_at": d.decided_at.strftime("%Y-%m-%d"),
                })
        matches.sort(key=lambda m: m["similarity"], reverse=True)
        return matches[:RESURRECTION_MAX_CANDIDATES]

    def find_active_duplicate(self, one_liner):
        """Active, non-suppressed takeaways that near-duplicate `one_liner`:
        an exact (stripped) string match always counts; with the embed extra
        present, embedding cosine >= DUPLICATE_COSINE also counts. Fail-open
        to exact-only when embeddings are unavailable — Jaccard is too coarse
        for duplicate-grade similarity, and a false positive blocks an add.
        Suppressed rows are find_resurrection's candidates, not ours, so the
        two birth gates stay disjoint. Returns matches, highest similarity
        first, for the consent gate (`--force` overrides)."""
        latest = self._latest_decisions()
        suppressed = {tid for tid, d in latest.items()
                      if d.decision == "suppress"}
        rows = [t for t in self.takeaways()
                if t.status == "active" and t.id not in suppressed]
        if not rows:
            return []
        needle = one_liner.strip()
        scores = [1.0 if t.one_liner.strip() == needle else 0.0 for t in rows]
        try:
            from . import embed
            sims = embed.semantic_scores(needle, [t.one_liner for t in rows])
            scores = [max(s, float(c)) for s, c in zip(scores, sims)]
        except Exception:
            pass  # fail-open: exact-match-only
        matches = [{"id": t.id, "one_liner": t.one_liner,
                    "similarity": round(float(s), 3)}
                   for t, s in zip(rows, scores) if s >= DUPLICATE_COSINE]
        matches.sort(key=lambda m: m["similarity"], reverse=True)
        return matches

    def _content_similarity(self, query, texts):
        """(scores, threshold): embedding cosine when the embed extra is present,
        fail-open to lexical Jaccard otherwise. The embedding threshold is
        same-lesson grade (RESURRECTION_COSINE), NOT the firing-relevance
        SIM_THRESHOLD — at 0.6, a store with many suppressed rows lists a wall
        of unrelated candidates on every add."""
        try:
            from . import embed
            return embed.semantic_scores(query, texts), RESURRECTION_COSINE
        except Exception:
            return [_jaccard(query, t) for t in texts], _RESURRECTION_LEX_JACCARD

    def resolve_add(self, resolve, kind, trigger_kind, one_liner,
                    trigger_spec=None, full_content=None, scope=None,
                    source=None, reach="project", origin_repo=None):
        """Apply a consent-gate resolution to a detected resurrection:
        new (override-create) | merge:ID (fold the wording in) | log-helpful:ID
        (revive by recording the recurrence as helpful-equivalent)."""
        choice, _, target = resolve.partition(":")
        if choice == "new":
            return self.add(kind, trigger_kind, one_liner, trigger_spec,
                            full_content, scope, source, reach, origin_repo)
        if not target:
            raise StoreContractError(
                f"--resolve {choice} needs a target id, e.g. {choice}:t12")
        if choice == "merge":
            return self.merge_resurrection(target, one_liner, full_content)
        if choice == "log-helpful":
            fid = self.log_helpful_equivalent(target, context=one_liner)
            return f"revived takeaway {target} (helpful-equivalent firing {fid})"
        raise StoreContractError(
            f"unknown --resolve {choice!r}: use new | merge:ID | log-helpful:ID")

    def merge_resurrection(self, takeaway_id, one_liner, full_content=None):
        """Fold a re-learned lesson's wording into the suppressed row instead of
        creating a duplicate. Content-only — orthogonal to the revive (use
        log-helpful for that)."""
        rows = self._sql(
            f"SELECT full_content FROM takeaways WHERE id = {iid(takeaway_id)}")
        if not rows:
            raise StoreContractError(f"no takeaway {takeaway_id} to merge into")
        existing = rows[0].get("full_content") or ""
        addition = one_liner if not full_content else f"{one_liner}\n{full_content}"
        merged = f"{existing}\n\n[re-learned] {addition}".strip()
        self._sql(
            f"UPDATE takeaways SET full_content = {self._val(merged)}"
            f" WHERE id = {iid(takeaway_id)}")
        return f"merged into takeaway {takeaway_id}"

    def log_helpful_equivalent(self, takeaway_id, context=None, session=None,
                               trigger_kind="resurrection", current_repo=None):
        """Record a recurrence as a helpful firing (fire + rate-helpful in one
        step). Used two ways, kept separable by trigger_kind for honest
        provenance: 'resurrection' (revive a suppressed row — the only
        'un-suppress' when suppression is computed from ratings) and 'recurrence'
        (a mine-time already-covered hit on an active row; see log_recurrence)."""
        fid = iid(self.fire(takeaway_id, trigger_kind, session=session,
                            context=context, current_repo=current_repo).split()[-1])
        self.rate(fid, "helpful")
        return fid

    def log_recurrence(self, takeaway_id, context=None, session=None,
                       current_repo=None):
        """Log a mine-time 'already covered by this row' recurrence as a helpful
        firing against an *active* row — evidence the row is load-bearing that
        would otherwise evaporate, and the accelerant that grows rated firings
        toward the tune gate. No consent gate (unlike resurrection): an active
        row needs no revival. Tagged trigger_kind='recurrence', distinct from
        'resurrection', so the two provenance stories stay separable in
        export-firings / tier-3 eval.

        Intended caller: CMS's mine-session, on an already-covered skip where the
        covering row is a *low-firing on_demand* row (high-firing / session_start
        rows stay with the fire+rate loop — the double-count guard). Enforcing
        that scope is CMS's mine-session discipline, not this verb's job."""
        return self.log_helpful_equivalent(takeaway_id, context=context,
                                           session=session,
                                           trigger_kind="recurrence",
                                           current_repo=current_repo)

    def commit(self, message):
        return self._backend.snapshot(message)
