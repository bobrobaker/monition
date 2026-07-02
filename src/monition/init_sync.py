"""monition init / sync / migrate — the host-repo mutation surface.

Spec decision 6: init is invasive but idempotent and transparent — it merges
its own hook entries into .claude/settings.json (never touching others),
materializes skills with a version stamp, prints exactly what changed, and
`--dry-run` shows the would-be changes without writing. Decision 5: skills are
materialized full-text; `sync` hash-checks the stamp — untouched skills
upgrade silently, locally-edited ones warn and are left alone.

`migrate` is the repair path the contract's fingerprint check points to:
v1-dialect stores (mirror-back state overloaded onto `status`) are rewritten
onto the v2 axes.
"""
import hashlib
import json
import os
import re
import subprocess

from ._generated_cms import METHOD_LESSON_ROUTING, SKILL_MINE_SESSION
from .hooks import guarded_hook_command
from .storage_backends import DoltBackend, SqliteBackend, StorageBackendError, _dolt_bin
from .store import Store, StoreContractError
from .store_write import val

VERSION = "0.4.0"

# v2 DDL (takeaways + firings) — used to construct V1 test fixtures and as the
# base for V3_SCHEMA. The contract's field tables are the source of truth.
V2_SCHEMA = """
CREATE TABLE takeaways (
  id int NOT NULL AUTO_INCREMENT,
  created datetime NOT NULL,
  kind enum('gotcha','rule','preference') NOT NULL,
  scope varchar(255),
  trigger_kind enum('edit_path','session_start','on_demand') NOT NULL,
  trigger_spec varchar(255),
  one_liner varchar(500) NOT NULL,
  full_content text,
  source varchar(255),
  status enum('active','retired') NOT NULL DEFAULT 'active',
  mirror enum('none','candidate','mirrored') NOT NULL DEFAULT 'none',
  PRIMARY KEY (id)
);
CREATE TABLE firings (
  id int NOT NULL AUTO_INCREMENT,
  takeaway_id int NOT NULL,
  fired_at datetime NOT NULL,
  session_id varchar(64),
  trigger_kind varchar(32),
  trigger_context varchar(512),
  outcome enum('helpful','noise'),
  PRIMARY KEY (id)
);
"""

_DECISIONS_DDL = """\
CREATE TABLE decisions (
  id int NOT NULL AUTO_INCREMENT,
  takeaway_id int NOT NULL,
  session_id varchar(64),
  decided_at datetime NOT NULL,
  decision enum('fire','suppress') NOT NULL,
  evidence_count int NOT NULL,
  cold_start tinyint(1) NOT NULL DEFAULT 0,
  ev_score decimal(5,4),
  PRIMARY KEY (id)
);"""

V3_SCHEMA = V2_SCHEMA + _DECISIONS_DDL

# v4: fire-time provenance on firings — the git state, model, and monition
# version in effect at disclosure. These are impossible to backfill (every
# firing logged without them loses those eval dimensions for good), so they are
# captured at every fire. The same ALTER is the v3→v4 migration step; appended
# to V3_SCHEMA it builds a fresh v4 store (CREATE firings, then ADD the columns).
_FIRINGS_PROVENANCE_DDL = (
    "ALTER TABLE firings"
    " ADD COLUMN git_sha varchar(40),"
    " ADD COLUMN git_dirty tinyint(1),"
    " ADD COLUMN model varchar(64),"
    " ADD COLUMN monition_version varchar(32);"
)

V4_SCHEMA = V3_SCHEMA + _FIRINGS_PROVENANCE_DDL

# v5: a short situational excerpt at fire time — the (un-truncated) user prompt for
# on_demand, an excerpt of the edited content for edit_path; NULL when the executor
# has none (e.g. session_start). This is firing-grain decision context the
# session-archive join recovers only at session grain (confer 2026-06-14); like v4
# provenance it is impossible to backfill, so it is captured at every fire.
_FIRINGS_SITUATION_DDL = "ALTER TABLE firings ADD COLUMN situation text;"

V5_SCHEMA = V4_SCHEMA + _FIRINGS_SITUATION_DDL

# v6: collapse per-repo stores into one hub. `reach`+`origin_repo` carry the
# general/project distinction as columns (no physical store boundary); `general`
# fires anywhere, `project` only where origin_repo == current repo. `firings.repo`
# captures the host repo at fire time (capture-or-lose, like git_sha/situation).
# `mirror` is retired (vestigial; its "applies beyond this repo" intent is now
# reach='general'). The ALTERs build a fresh v6 store on top of v5 (CREATE with
# mirror, then ADD reach/origin_repo/repo and DROP mirror) and are also the
# v5→v6 migration steps. origin_repo/repo are absolute repo roots.
_TAKEAWAYS_REACH_DDL = (
    "ALTER TABLE takeaways"
    " ADD COLUMN reach enum('general','project') NOT NULL DEFAULT 'project',"
    " ADD COLUMN origin_repo varchar(512);"
)
_FIRINGS_REPO_DDL = "ALTER TABLE firings ADD COLUMN repo varchar(512);"
_TAKEAWAYS_DROP_MIRROR_DDL = "ALTER TABLE takeaways DROP COLUMN mirror;"

V6_SCHEMA = (
    V5_SCHEMA + _TAKEAWAYS_REACH_DDL + _FIRINGS_REPO_DDL + _TAKEAWAYS_DROP_MIRROR_DDL
)

# v7: the recall column (Phase 6, decision 2026-07-01-row-lifecycle-pr-framing-
# and-mutation-track). `violation_signature` is an optional machine-checkable
# probe for the failure a row warns about, interpreted only by the offline
# evaluator; `match_evidence` is the full, lossless record of what the trigger
# matched on (`trigger_context` stays the bounded human preview); `violations`
# holds observed not-fired∧hit events — the false-negative cell ratings cannot
# produce. The ALTERs + CREATE are also the v6→v7 migration steps.
_TAKEAWAYS_SIGNATURE_DDL = "ALTER TABLE takeaways ADD COLUMN violation_signature text;"
_FIRINGS_EVIDENCE_DDL = "ALTER TABLE firings ADD COLUMN match_evidence text;"
_VIOLATIONS_DDL = """\
CREATE TABLE violations (
  id int NOT NULL AUTO_INCREMENT,
  takeaway_id int NOT NULL,
  session_id varchar(64) NOT NULL,
  detected_at datetime NOT NULL,
  evidence text,
  repo varchar(512),
  PRIMARY KEY (id)
);"""

V7_SCHEMA = (
    V6_SCHEMA + _TAKEAWAYS_SIGNATURE_DDL + _FIRINGS_EVIDENCE_DDL + _VIOLATIONS_DDL
)

# SQLite DDL — used by `monition init` (the default backend). SQLite types:
# TEXT for varchar/datetime/enum; INTEGER for int/tinyint; NUMERIC for decimal.
# Enum domains enforced via CHECK constraints at write time.
V6_SCHEMA_SQLITE = """
CREATE TABLE takeaways (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('gotcha','rule','preference')),
  scope TEXT,
  trigger_kind TEXT NOT NULL CHECK(trigger_kind IN ('edit_path','session_start','on_demand')),
  trigger_spec TEXT,
  one_liner TEXT NOT NULL,
  full_content TEXT,
  source TEXT,
  status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','retired')),
  reach TEXT NOT NULL DEFAULT 'project' CHECK(reach IN ('general','project')),
  origin_repo TEXT
);
CREATE TABLE firings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  takeaway_id INTEGER NOT NULL,
  fired_at TEXT NOT NULL,
  session_id TEXT,
  trigger_kind TEXT,
  trigger_context TEXT,
  outcome TEXT CHECK(outcome IN ('helpful','noise')),
  git_sha TEXT,
  git_dirty INTEGER,
  model TEXT,
  monition_version TEXT,
  situation TEXT,
  repo TEXT
);
CREATE TABLE decisions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  takeaway_id INTEGER NOT NULL,
  session_id TEXT,
  decided_at TEXT NOT NULL,
  decision TEXT NOT NULL CHECK(decision IN ('fire','suppress')),
  evidence_count INTEGER NOT NULL,
  cold_start INTEGER NOT NULL DEFAULT 0,
  ev_score NUMERIC
);
"""

# The SQLite v6→v7 steps, individually executable (the SQLite backend shipped
# at v6, so this is the only rung its migration ladder needs).
_V7_STEPS_SQLITE = [
    "ALTER TABLE takeaways ADD COLUMN violation_signature TEXT",
    "ALTER TABLE firings ADD COLUMN match_evidence TEXT",
    """CREATE TABLE violations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  takeaway_id INTEGER NOT NULL,
  session_id TEXT NOT NULL,
  detected_at TEXT NOT NULL,
  evidence TEXT,
  repo TEXT
)""",
]

V7_SCHEMA_SQLITE = V6_SCHEMA_SQLITE + ";\n".join(_V7_STEPS_SQLITE) + ";\n"

# v8: the mutation track (Phase 7, decision 2026-07-01-trigger-module-
# representation). Three pieces, migrated ATOMICALLY (partial migration makes
# the version ladder ambiguous — the v7 lesson): `sem_threshold` — the semantic
# module's per-row parameter (NULL = global SIM_THRESHOLD); `trigger_kind`
# widened with 'tool_call' (first post-v7 kind; JSON spec, executor lands B05);
# `mutations` — event-grain provenance for every consented trigger mutation.
_TAKEAWAYS_THRESHOLD_DDL = "ALTER TABLE takeaways ADD COLUMN sem_threshold decimal(5,4);"
_TAKEAWAYS_TOOLCALL_DDL = (
    "ALTER TABLE takeaways MODIFY COLUMN trigger_kind"
    " enum('edit_path','session_start','on_demand','tool_call') NOT NULL;"
)
_MUTATIONS_DDL = """\
CREATE TABLE mutations (
  id int NOT NULL AUTO_INCREMENT,
  takeaway_id int NOT NULL,
  mutated_at datetime NOT NULL,
  verb varchar(32) NOT NULL,
  changes text NOT NULL,
  source varchar(512),
  PRIMARY KEY (id)
);"""

V8_SCHEMA = (
    V7_SCHEMA + _TAKEAWAYS_THRESHOLD_DDL + _TAKEAWAYS_TOOLCALL_DDL + _MUTATIONS_DDL
)

# SQLite cannot ALTER a CHECK constraint, so widening the trigger_kind domain
# is a table rebuild; the rebuilt table carries sem_threshold too, keeping the
# v8 pieces atomic. Explicit ids in the copy keep sqlite_sequence correct
# (AUTOINCREMENT updates it to the max inserted id).
_V8_TAKEAWAYS_REBUILD_SQLITE = [
    """CREATE TABLE takeaways_v8 (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('gotcha','rule','preference')),
  scope TEXT,
  trigger_kind TEXT NOT NULL CHECK(trigger_kind IN ('edit_path','session_start','on_demand','tool_call')),
  trigger_spec TEXT,
  one_liner TEXT NOT NULL,
  full_content TEXT,
  source TEXT,
  status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','retired')),
  reach TEXT NOT NULL DEFAULT 'project' CHECK(reach IN ('general','project')),
  origin_repo TEXT,
  violation_signature TEXT,
  sem_threshold NUMERIC
)""",
    "INSERT INTO takeaways_v8 (id, created, kind, scope, trigger_kind,"
    " trigger_spec, one_liner, full_content, source, status, reach,"
    " origin_repo, violation_signature)"
    " SELECT id, created, kind, scope, trigger_kind, trigger_spec, one_liner,"
    " full_content, source, status, reach, origin_repo, violation_signature"
    " FROM takeaways",
    "DROP TABLE takeaways",
    "ALTER TABLE takeaways_v8 RENAME TO takeaways",
]
_MUTATIONS_DDL_SQLITE = """CREATE TABLE mutations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  takeaway_id INTEGER NOT NULL,
  mutated_at TEXT NOT NULL,
  verb TEXT NOT NULL,
  changes TEXT NOT NULL,
  source TEXT
)"""
_V8_STEPS_SQLITE = _V8_TAKEAWAYS_REBUILD_SQLITE + [_MUTATIONS_DDL_SQLITE]

V8_SCHEMA_SQLITE = V7_SCHEMA_SQLITE + ";\n".join(_V8_STEPS_SQLITE) + ";\n"

_V1_STATUS = "enum('active','retired','upstream_candidate','mirrored')"
_V2_STATUS = "enum('active','retired')"

# Routing-tests version mirrored from CMS method/lesson-routing.md. The
# `**Version:** routing v{N}` header in the bundled METHOD_LESSON_ROUTING doc must
# equal this; a test enforces it so the human-readable legend can't drift from the
# generated content (see the v1/v2 mix-up that motivated this guard). Bump when
# re-stripping a CMS routing change, alongside re-running tools/regen_from_cms.py.
ROUTING_VERSION = 5

# SKILL_MINE_SESSION and METHOD_LESSON_ROUTING are GENERATED from CMS canonical by
# tools/regen_from_cms.py and imported at the top of this module — do not hand-edit;
# edit the CMS sources and re-run regen.

SKILLS = {"mine-session": SKILL_MINE_SESSION}
DOCS = {"method/lesson-routing.md": METHOD_LESSON_ROUTING}

README_LINE = (
    "Takeaway capture/disclosure via [Monition](https://github.com/bobrobaker/monition): "
    "`uv tool install git+https://github.com/bobrobaker/monition.git` (hooks fail open if absent).\n"
)

DUMP_HOOK_SNIPPET = (
    "command -v monition >/dev/null 2>&1 && "
    "monition dump >/dev/null && git add monition/dump.sql || true\n"
)

_STAMP_RE = re.compile(r"^<!-- monition-(?:skill|doc) v(\S+) sha256:([0-9a-f]{64}) -->\n")


def _stamp(body, kind="skill"):
    digest = hashlib.sha256(body.encode()).hexdigest()
    return f"<!-- monition-{kind} v{VERSION} sha256:{digest} -->\n"


def _managed_state(path, body):
    """One of: absent, untouched (stamp matches content), edited, current.

    Shared by packaged skills and bundled docs — both carry a stamp comment and
    follow the same untouched→upgrade / edited→leave hash-check."""
    if not os.path.exists(path):
        return "absent"
    with open(path) as f:
        installed = f.read()
    m = _STAMP_RE.match(installed)
    if not m:
        return "edited"  # no stamp: treat as user-owned
    installed_body = installed[m.end():]
    if hashlib.sha256(installed_body.encode()).hexdigest() != m.group(2):
        return "edited"
    return "current" if installed_body == body else "untouched"


def _merge_hook_entries(settings):
    """Add or refresh monition's guarded hook entries; never touch unrelated
    ones. A monition entry is identified by its subcommand token (e.g.
    "monition prompt-hook"), not the exact command string — so when the
    guarded command changes between versions, the stale entry is REPLACED
    (and accumulated duplicates collapsed) instead of a new one appending
    beside it."""
    changed = []
    hooks = settings.setdefault("hooks", {})
    wanted = [
        # Write|Edit serves edit_path; Bash serves tool_call (v8). Every
        # matcher widening costs a cold subprocess per matched call — widen
        # only when a module consumes the tool.
        ("PreToolUse", "Write|Edit|Bash", "fire-hook"),
        ("SessionStart", None, "session-brief"),
        ("UserPromptSubmit", None, "prompt-hook"),
    ]
    for event, matcher, subcommand in wanted:
        cmd = guarded_hook_command(subcommand)
        token = f"monition {subcommand}"
        entries = hooks.setdefault(event, [])
        # (entry, hook) pairs so staleness sees the entry's matcher too — a
        # matcher-only change (e.g. Write|Edit -> Write|Edit|Bash at v8) must
        # replace the entry, not silently pass the command-equality check
        ours = [(entry, h) for entry in entries
                for h in entry.get("hooks", [])
                if token in (h.get("command") or "")]
        if (len(ours) == 1 and ours[0][1].get("command") == cmd
                and ours[0][0].get("matcher") == matcher):
            continue  # current — nothing to do
        ours = [h for _, h in ours]
        if ours:
            # stale command and/or duplicates: remove every hook carrying our
            # subcommand token, dropping only entries *we* emptied
            emptied = []
            for entry in entries:
                hs = entry.get("hooks", [])
                if any(token in (h.get("command") or "") for h in hs):
                    entry["hooks"] = [
                        h for h in hs
                        if token not in (h.get("command") or "")
                    ]
                    if not entry["hooks"]:
                        emptied.append(entry)
            for entry in emptied:
                entries.remove(entry)
            changed.append(f"{event} (replaced)")
        else:
            changed.append(event)
        entry = {"hooks": [{"type": "command", "command": cmd}]}
        if matcher:
            entry = {"matcher": matcher, "hooks": entry["hooks"]}
        entries.append(entry)
    return changed


def _plan_settings(root):
    path = os.path.join(root, ".claude", "settings.json")
    settings = {}
    if os.path.exists(path):
        with open(path) as f:
            settings = json.load(f)
    added = _merge_hook_entries(settings)
    return path, settings, added


def _plan_mcp(root):
    """Register the monition MCP server in <root>/.mcp.json (merge, idempotent)."""
    path = os.path.join(root, ".mcp.json")
    cfg = {}
    if os.path.exists(path):
        with open(path) as f:
            cfg = json.load(f)
    servers = cfg.setdefault("mcpServers", {})
    if "monition" in servers:
        return path, cfg, False
    servers["monition"] = {"command": "monition", "args": ["mcp-serve"]}
    return path, cfg, True


def _plan_skills(root):
    """Yields (name, path, body, state) for each packaged skill."""
    for name, body in SKILLS.items():
        path = os.path.join(root, ".claude", "skills", name, "SKILL.md")
        yield name, path, body, _managed_state(path, body)


def _plan_docs(root):
    """Yields (relpath, path, body, state) for each bundled doc — same stamp /
    hash-check contract as skills, written under <root>/<relpath>."""
    for relpath, body in DOCS.items():
        path = os.path.join(root, *relpath.split("/"))
        yield relpath, path, body, _managed_state(path, body)


def _write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


def _actor(changes, dry_run):
    def act(desc, fn):
        changes.append(("would " + desc) if dry_run else desc)
        if not dry_run:
            fn()
    return act


def init_store(store, dolt=False, dry_run=False):
    """Pure store creation — the hub, or a standalone `<repo>/monition`. Touches only
    the store dir; no instrumentation. Idempotent (a present store is a no-op).
    `dolt=True` uses Dolt (requires the binary); default is SQLite (zero install)."""
    changes = []
    act = _actor(changes, dry_run)
    if (os.path.isdir(os.path.join(store, ".dolt"))
            or os.path.exists(os.path.join(store, "store.db"))):
        return changes  # store exists — idempotent no-op
    if dolt:
        if _dolt_bin() is None:
            raise StoreContractError(
                "dolt binary not found on PATH or ~/.local/bin — install dolt "
                "or omit --dolt to use the SQLite backend (zero install)")
        def make():
            os.makedirs(store, exist_ok=True)
            try:
                DoltBackend(store).init(V8_SCHEMA)
            except StorageBackendError as e:
                raise StoreContractError(str(e)) from e
        act(f"create Monition store at {store} (v8 schema, dolt)", make)
    else:
        def make():
            os.makedirs(store, exist_ok=True)
            SqliteBackend(os.path.join(store, "store.db")).init(V8_SCHEMA_SQLITE)
        act(f"create Monition store at {store} (v8 schema, sqlite)", make)
    return changes


def _plan_store_env(root, store):
    """Plan `env.MONITION_STORE` → abspath(store) in the GITIGNORED local settings
    (`settings.local.json`), never the committed `settings.json` — baking a
    machine-local path into the tree breaks the forkable-lock. Idempotent."""
    path = os.path.join(root, ".claude", "settings.local.json")
    cfg = {}
    if os.path.exists(path):
        with open(path) as f:
            cfg = json.load(f)
    target = os.path.abspath(store)
    env = cfg.setdefault("env", {})
    if env.get("MONITION_STORE") == target:
        return path, cfg, False
    env["MONITION_STORE"] = target
    return path, cfg, True


def instrument(root, store=None, dry_run=False, with_dump_hook=False):
    """Pure instrumentation: merge monition's hooks/MCP/skills into the repo at
    `root` and, when `store` is a hub/external store (not the `<root>/monition`
    convention), point `MONITION_STORE` at it via the gitignored local settings.
    Creates NO store. Idempotent — merges, never clobbers foreign entries, and a
    new `--store` re-points a clean re-join."""
    changes = []
    act = _actor(changes, dry_run)

    spath, settings, added = _plan_settings(root)
    if added:
        act(f"merge guarded hooks ({', '.join(added)}) into {spath}",
            lambda: _write(spath, json.dumps(settings, indent=2) + "\n"))

    mpath, mcfg, mcp_added = _plan_mcp(root)
    if mcp_added:
        act(f"register monition MCP server in {mpath}",
            lambda: _write(mpath, json.dumps(mcfg, indent=2) + "\n"))

    for name, path, body, state in _plan_skills(root):
        if state in ("absent", "untouched"):
            verb = "upgrade" if state == "untouched" else "install"
            act(f"{verb} skill {name} ({path})",
                lambda p=path, b=body: _write(p, _stamp(b) + b))
        elif state == "edited":
            changes.append(f"WARN: skill {name} locally edited — left alone ({path})")

    for relpath, path, body, state in _plan_docs(root):
        if state in ("absent", "untouched"):
            verb = "upgrade" if state == "untouched" else "install"
            act(f"{verb} doc {relpath} ({path})",
                lambda p=path, b=body: _write(p, _stamp(b, "doc") + b))
        elif state == "edited":
            changes.append(f"WARN: doc {relpath} locally edited — left alone ({path})")

    # Point MONITION_STORE at a hub/external store only — the <root>/monition
    # convention resolves via the unset-MONITION_STORE fallback, so the standalone
    # path writes no env (preserves "unset = no-hub").
    if (store is not None
            and os.path.abspath(store) != os.path.abspath(os.path.join(root, "monition"))):
        lpath, lcfg, changed = _plan_store_env(root, store)
        if changed:
            act(f"point MONITION_STORE → {store} in {lpath}",
                lambda: _write(lpath, json.dumps(lcfg, indent=2) + "\n"))

    readme = os.path.join(root, "README.md")
    if os.path.exists(readme):
        with open(readme) as f:
            text = f.read()
        if "monition" not in text.lower():
            act(f"append install line to {readme}",
                lambda: _write(readme, text + "\n" + README_LINE))

    if with_dump_hook:
        hook_path = os.path.join(root, ".git", "hooks", "pre-commit")
        if not os.path.isdir(os.path.join(root, ".git")):
            changes.append("WARN: no .git directory — dump hook not installed")
        elif os.path.exists(hook_path):
            changes.append(f"WARN: {hook_path} exists — dump hook not installed; "
                           f"add manually: {DUMP_HOOK_SNIPPET.strip()}")
        else:
            def install_hook():
                _write(hook_path, "#!/bin/sh\n" + DUMP_HOOK_SNIPPET)
                os.chmod(hook_path, 0o755)
            act(f"install pre-commit dump hook at {hook_path}", install_hook)
    else:
        changes.append("offer: pre-commit dump hook not installed (use "
                       f"--with-dump-hook); snippet: {DUMP_HOOK_SNIPPET.strip()}")

    return changes


def init(root, dry_run=False, with_dump_hook=False, dolt=False):
    """Standalone/forker one-command path — the composition of `init_store` +
    `instrument` over `<root>/monition`. Behaviour is unchanged from the
    pre-decomposition init; unset MONITION_STORE (no env written for the convention
    store) keeps no-hub mode."""
    store = os.path.join(root, "monition")
    changes = init_store(store, dolt=dolt, dry_run=dry_run)
    changes += instrument(root, store=store, dry_run=dry_run,
                          with_dump_hook=with_dump_hook)
    if not any(c for c in changes if not c.startswith(("offer:", "WARN:"))):
        changes.insert(0, "no changes (already initialized)")
    return changes


def sync(root):
    """Regenerate hook entries + skills; hash-check before overwriting skills."""
    changes = []
    spath, settings, added = _plan_settings(root)
    if added:
        _write(spath, json.dumps(settings, indent=2) + "\n")
        changes += [f"merged guarded {event} hook into {spath}" for event in added]
    mpath, mcfg, mcp_added = _plan_mcp(root)
    if mcp_added:
        _write(mpath, json.dumps(mcfg, indent=2) + "\n")
        changes.append(f"registered monition MCP server in {mpath}")
    for name, path, body, state in _plan_skills(root):
        if state in ("absent", "untouched"):
            _write(path, _stamp(body) + body)
            changes.append(f"{'installed' if state == 'absent' else 'upgraded'} skill {name}")
        elif state == "edited":
            changes.append(f"WARN: skill {name} locally edited — left alone ({path})")
    for relpath, path, body, state in _plan_docs(root):
        if state in ("absent", "untouched"):
            _write(path, _stamp(body, "doc") + body)
            changes.append(f"{'installed' if state == 'absent' else 'upgraded'} doc {relpath}")
        elif state == "edited":
            changes.append(f"WARN: doc {relpath} locally edited — left alone ({path})")
    if not changes:
        changes.append("no changes (everything current)")
    return changes


def _raw_sql(store_path, query):
    out = subprocess.run([_dolt_bin(), "sql", "-q", query, "-r", "json"],
                         cwd=store_path, capture_output=True, text=True)
    if out.returncode != 0:
        raise StoreContractError(out.stderr.strip() or out.stdout.strip())
    text = out.stdout.strip()
    return json.loads(text).get("rows", []) if text else []


def _migrate_sqlite(store_path, db_path):
    """The SQLite migration ladder starts at v6 (the SQLite backend shipped at
    v6, so no older SQLite store exists to migrate): v6→v7→v8."""
    backend = SqliteBackend(db_path)
    t_cols = {r["Field"] for r in backend.describe("takeaways")}
    if not t_cols:
        raise StoreContractError(f"{store_path} has no takeaways table")
    if "reach" not in t_cols:
        raise StoreContractError(
            f"{store_path} is a pre-v6 SQLite store — the SQLite backend shipped "
            "at v6, so this store was not created by `monition init`; no "
            "migration path exists")
    f_cols = {r["Field"] for r in backend.describe("firings")}
    steps = []
    if "violation_signature" not in t_cols:
        steps.append(_V7_STEPS_SQLITE[0])
    if "match_evidence" not in f_cols:
        steps.append(_V7_STEPS_SQLITE[1])
    if not backend.describe("violations"):
        steps.append(_V7_STEPS_SQLITE[2])
    # v7 → v8: the takeaways rebuild carries sem_threshold + the widened
    # trigger_kind CHECK together (SQLite cannot ALTER a CHECK constraint).
    if "sem_threshold" not in t_cols:
        steps.extend(_V8_TAKEAWAYS_REBUILD_SQLITE)
    if not backend.describe("mutations"):
        steps.append(_MUTATIONS_DDL_SQLITE)
    if not steps:
        raise StoreContractError("store is already v8 — nothing to migrate")
    try:
        for step in steps:
            backend.execute_sql(step)
    except StorageBackendError as e:
        raise StoreContractError(str(e)) from e
    Store(store_path)  # the reader's fingerprint check is the success gate
    return f"migrated {store_path} to v8"


def migrate(store_path):
    """Bring a store up to the current schema (v8). Cumulative — an older store
    traverses every step it is missing:

    - v1 → v2: split the overloaded status domain into status + mirror axes
    - v2 → v3: add the decisions table
    - v3 → v4: add fire-time provenance columns to firings
    - v4 → v5: add the situational-excerpt column to firings
    - v5 → v6: add reach/origin_repo to takeaways + repo to firings (backfilled
      from this store's repo root), then retire the vestigial mirror column
    - v6 → v7: add violation_signature to takeaways + match_evidence to firings,
      create the violations table (all additive; existing rows stay NULL)
    - v7 → v8: add sem_threshold to takeaways, widen trigger_kind with
      'tool_call', create the mutations table (atomic; existing rows stay NULL)
    """
    if (not os.path.isdir(os.path.join(store_path, ".dolt"))
            and os.path.exists(os.path.join(store_path, "store.db"))):
        return _migrate_sqlite(store_path, os.path.join(store_path, "store.db"))
    if _dolt_bin() is None:
        raise StoreContractError("dolt binary not found on PATH or ~/.local/bin")
    if not os.path.isdir(os.path.join(store_path, ".dolt")):
        raise StoreContractError(f"{store_path} is not a Dolt database")

    firing_cols = {r["Field"] for r in _raw_sql(store_path, "DESCRIBE `firings`")}
    has_provenance = "git_sha" in firing_cols
    has_situation = "situation" in firing_cols
    has_firing_repo = "repo" in firing_cols
    has_evidence = "match_evidence" in firing_cols
    try:
        _raw_sql(store_path, "DESCRIBE `decisions`")
        decisions_exist = True
    except StoreContractError:
        decisions_exist = False
    try:
        _raw_sql(store_path, "DESCRIBE `violations`")
        violations_exist = True
    except StoreContractError:
        violations_exist = False
    try:
        _raw_sql(store_path, "DESCRIBE `mutations`")
        mutations_exist = True
    except StoreContractError:
        mutations_exist = False

    cols = {r["Field"]: r["Type"] for r in _raw_sql(store_path, "DESCRIBE `takeaways`")}
    has_reach = "reach" in cols
    has_signature = "violation_signature" in cols
    has_threshold = "sem_threshold" in cols
    has_tool_call = "tool_call" in cols.get("trigger_kind", "")

    if (decisions_exist and has_provenance and has_situation
            and has_reach and has_firing_repo
            and has_signature and has_evidence and violations_exist
            and has_threshold and has_tool_call and mutations_exist):
        raise StoreContractError("store is already v8 — nothing to migrate")

    status = cols.get("status")
    if status == _V1_STATUS:
        # v1 -> v2 mapping: upstream_candidate -> (active, candidate);
        # mirrored -> (active, mirrored); active/retired -> (unchanged, none).
        if "mirror" not in cols:
            _raw_sql(store_path,
                     "ALTER TABLE takeaways ADD COLUMN mirror "
                     "enum('none','candidate','mirrored') NOT NULL DEFAULT 'none'")
        _raw_sql(store_path,
                 "UPDATE takeaways SET mirror = 'candidate' WHERE status = 'upstream_candidate'")
        _raw_sql(store_path,
                 "UPDATE takeaways SET mirror = 'mirrored' WHERE status = 'mirrored'")
        _raw_sql(store_path,
                 "UPDATE takeaways SET status = 'active' "
                 "WHERE status IN ('upstream_candidate','mirrored')")
        _raw_sql(store_path,
                 "ALTER TABLE takeaways MODIFY COLUMN status "
                 "enum('active','retired') NOT NULL DEFAULT 'active'")
    elif status != _V2_STATUS:
        raise StoreContractError(
            f"unrecognized status domain {status!r} — this migration maps only "
            "the v1 dialect or v2/v3 stores"
        )

    if not decisions_exist:
        _raw_sql(store_path, _DECISIONS_DDL)
    if not has_provenance:
        _raw_sql(store_path, _FIRINGS_PROVENANCE_DDL)
    if not has_situation:
        _raw_sql(store_path, _FIRINGS_SITUATION_DDL)

    # v5 -> v6: a per-repo store belongs to exactly one repo, so backfill
    # origin_repo/firings.repo from the store's repo root. Additive + backfill
    # first, then drop the vestigial mirror (checked against the LIVE column set —
    # a v1-origin store gains mirror during v1→v2 above, so the stale pre-migration
    # `cols` would miss it).
    repo_root = os.path.dirname(os.path.abspath(store_path))
    repo_sql = "'" + repo_root.replace("'", "''") + "'"
    if not has_reach:
        _raw_sql(store_path, _TAKEAWAYS_REACH_DDL)
        _raw_sql(store_path, f"UPDATE takeaways SET origin_repo = {repo_sql}")
    if not has_firing_repo:
        _raw_sql(store_path, _FIRINGS_REPO_DDL)
        _raw_sql(store_path, f"UPDATE firings SET repo = {repo_sql}")
    live_cols = {r["Field"] for r in _raw_sql(store_path, "DESCRIBE `takeaways`")}
    if "mirror" in live_cols:
        _raw_sql(store_path, _TAKEAWAYS_DROP_MIRROR_DDL)

    # v6 -> v7: all additive; existing rows' new columns stay NULL.
    if not has_signature:
        _raw_sql(store_path, _TAKEAWAYS_SIGNATURE_DDL)
    if not has_evidence:
        _raw_sql(store_path, _FIRINGS_EVIDENCE_DDL)
    if not violations_exist:
        _raw_sql(store_path, _VIOLATIONS_DDL)

    # v7 -> v8: the mutation track — per-indicator guards (the v7 lesson).
    if not has_threshold:
        _raw_sql(store_path, _TAKEAWAYS_THRESHOLD_DDL)
    if not has_tool_call:
        _raw_sql(store_path, _TAKEAWAYS_TOOLCALL_DDL)
    if not mutations_exist:
        _raw_sql(store_path, _MUTATIONS_DDL)

    Store(store_path)  # the reader's fingerprint check is the success gate
    return f"migrated {store_path} to v8"


# --- v6 fold: consolidate per-repo Dolt stores into the Dolt hub ----------

_TAKEAWAY_COLS = ["created", "kind", "scope", "trigger_kind", "trigger_spec",
                  "one_liner", "full_content", "source", "status", "reach", "origin_repo",
                  "violation_signature", "sem_threshold"]
_FIRING_COLS = ["fired_at", "session_id", "trigger_kind", "trigger_context", "outcome",
                "git_sha", "git_dirty", "model", "monition_version", "situation", "repo",
                "match_evidence"]
_FIRING_NUM = {"git_dirty"}
_DECISION_COLS = ["session_id", "decided_at", "decision", "evidence_count",
                  "cold_start", "ev_score"]
_DECISION_NUM = {"evidence_count", "cold_start", "ev_score"}
_VIOLATION_COLS = ["session_id", "detected_at", "evidence", "repo"]


def _numv(v):
    """SQL literal for a numeric/decimal column: None -> NULL (Dolt omits NULL keys
    from JSON, so a missing key reads as None via .get), else the value verbatim."""
    return "NULL" if v is None else str(v)


def _max_id(path, table):
    rows = _raw_sql(path, f"SELECT MAX(id) AS m FROM `{table}`")
    m = rows[0].get("m") if rows else None  # empty table → MAX is NULL → omitted key
    return int(m) if m is not None else 0


def _count(path, table):
    return int(_raw_sql(path, f"SELECT COUNT(*) AS n FROM `{table}`")[0]["n"])


def _row_values(r, columns, numeric, lead):
    """One `(...)` VALUES tuple: `lead` is the already-formatted id literals that
    prefix the data columns (the offset id, and FK takeaway_id for child tables)."""
    cells = list(lead)
    for c in columns:
        cells.append(_numv(r.get(c)) if c in numeric else val(r.get(c)))
    return "(" + ", ".join(cells) + ")"


def _insert_rows(path, table, full_columns, tuples, chunk=100):
    """`full_columns` is the complete ordered column list (id + any takeaway_id FK +
    data columns) matching each tuple produced by `_row_values`."""
    if not tuples:
        return
    cols = "(" + ", ".join(full_columns) + ")"
    for i in range(0, len(tuples), chunk):
        batch = ", ".join(tuples[i:i + chunk])
        _raw_sql(path, f"INSERT INTO `{table}` {cols} VALUES {batch}")


def fold_store(source_path, hub_path):
    """Fold a per-repo **v7** Dolt store's rows into the Dolt hub (Dolt→Dolt only).

    Non-destructive to the source — it is read, never modified. The source must
    already be v7 (run `monition migrate --store <source>` first) so reach/origin_repo
    /firings.repo are set; the fold preserves them. Source ids are offset by the hub's
    current MAX(id) per table so they never collide and the firings/decisions/
    violations → takeaways FK references stay intact. Idempotent guard: refuses if the
    hub already holds this source's origin_repo. Conservation-checked, then the hub is
    committed."""
    if _dolt_bin() is None:
        raise StoreContractError("dolt binary not found on PATH or ~/.local/bin")
    for label, path in (("source", source_path), ("hub", hub_path)):
        if not os.path.isdir(os.path.join(path, ".dolt")):
            raise StoreContractError(
                f"{label} {path} is not a Dolt database — the fold is Dolt→Dolt only")

    src_cols = {r["Field"] for r in _raw_sql(source_path, "DESCRIBE `takeaways`")}
    if "reach" not in src_cols or "violation_signature" not in src_cols:
        raise StoreContractError(
            f"source {source_path} is not v7 (missing `reach` or "
            f"`violation_signature`) — run "
            f"`monition migrate --store {source_path}` first, then fold")
    Store(hub_path)  # hub must pass the v7 fingerprint

    origin = os.path.dirname(os.path.abspath(source_path))
    already = int(_raw_sql(
        hub_path, f"SELECT COUNT(*) AS n FROM takeaways WHERE origin_repo = {val(origin)}"
    )[0]["n"])
    if already:
        raise StoreContractError(
            f"hub already holds {already} row(s) for origin_repo {origin} — already "
            "folded; refusing to double-insert")

    takeaways = _raw_sql(source_path, "SELECT * FROM takeaways ORDER BY id")
    firings = _raw_sql(source_path, "SELECT * FROM firings ORDER BY id")
    decisions = _raw_sql(source_path, "SELECT * FROM decisions ORDER BY id")
    violations = _raw_sql(source_path, "SELECT * FROM violations ORDER BY id")

    t_base, f_base, d_base, v_base = (
        _max_id(hub_path, t)
        for t in ("takeaways", "firings", "decisions", "violations"))
    before = tuple(_count(hub_path, t)
                   for t in ("takeaways", "firings", "decisions", "violations"))

    _insert_rows(hub_path, "takeaways", ["id"] + _TAKEAWAY_COLS, [
        _row_values(r, _TAKEAWAY_COLS, {"sem_threshold"}, [_numv(t_base + int(r["id"]))])
        for r in takeaways])
    _insert_rows(hub_path, "firings", ["id", "takeaway_id"] + _FIRING_COLS, [
        _row_values(r, _FIRING_COLS, _FIRING_NUM,
                    [_numv(f_base + int(r["id"])), _numv(t_base + int(r["takeaway_id"]))])
        for r in firings])
    _insert_rows(hub_path, "decisions", ["id", "takeaway_id"] + _DECISION_COLS, [
        _row_values(r, _DECISION_COLS, _DECISION_NUM,
                    [_numv(d_base + int(r["id"])), _numv(t_base + int(r["takeaway_id"]))])
        for r in decisions])
    _insert_rows(hub_path, "violations", ["id", "takeaway_id"] + _VIOLATION_COLS, [
        _row_values(r, _VIOLATION_COLS, set(),
                    [_numv(v_base + int(r["id"])), _numv(t_base + int(r["takeaway_id"]))])
        for r in violations])

    after = tuple(_count(hub_path, t)
                  for t in ("takeaways", "firings", "decisions", "violations"))
    expected = (before[0] + len(takeaways), before[1] + len(firings),
                before[2] + len(decisions), before[3] + len(violations))
    if after != expected:
        raise StoreContractError(
            f"fold conservation failed: hub counts {after} != expected {expected} "
            f"(source: {len(takeaways)} takeaways / {len(firings)} firings / "
            f"{len(decisions)} decisions / {len(violations)} violations)")

    DoltBackend(hub_path).snapshot(
        f"fold: {origin} into hub ({len(takeaways)} takeaways, {len(firings)} firings)")
    return (f"folded {len(takeaways)} takeaways, {len(firings)} firings, "
            f"{len(decisions)} decisions from {source_path} into {hub_path}")
