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

from .hooks import guarded_hook_command
from .storage_backends import DoltBackend, SqliteBackend, StorageBackendError, _dolt_bin
from .store import Store, StoreContractError

VERSION = "0.3.0"

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

# SQLite DDL — used by `monition init` (the default backend). SQLite types:
# TEXT for varchar/datetime/enum; INTEGER for int/tinyint; NUMERIC for decimal.
# Enum domains enforced via CHECK constraints at write time.
V5_SCHEMA_SQLITE = """
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
  mirror TEXT NOT NULL DEFAULT 'none' CHECK(mirror IN ('none','candidate','mirrored'))
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
  situation TEXT
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

_V1_STATUS = "enum('active','retired','upstream_candidate','mirrored')"
_V2_STATUS = "enum('active','retired')"

SKILL_MINE_SESSION = """\
---
name: mine-session
description: End-of-session mining pass — review this session for reusable lessons and house them in the Monition store with explicit triggers. Use when the user invokes /mine-session, says "mine this session" / "save the takeaways", or is wrapping up a session that hit gotchas worth keeping. NOT for mid-session one-offs the user wants codified immediately.
---

# mine-session

You are mining this session for takeaways. The store's semantics live in the
Monition store contract (`docs/contracts/takeaway-store.md` in the monition
repo) — read it before your first run in a session.

0. **Rate what fired (the eval pass) — run this first, before mining.** The store's
   fire/suppress gate trains on rated firings, and fire-time rating collects ~none (a
   session mid-task won't stop to grade an injection). So rate here, **warm**, with the
   session still in context — LLM-auto, evidence-gated, bulk-confirmed.
   - **Pull the worklist, highest-value first:**
     `monition export-firings --unrated-only --session "$CLAUDE_CODE_SESSION_ID" --order-by priority`.
     `--order-by priority` ranks by `rating_priority` (traffic × distance-to-fire/suppress
     boundary; cold-start rows rank high) — monition owns the math, you only consume the
     order. If `$CLAUDE_CODE_SESSION_ID` is unset, scope with `--since <today>` instead.
     **Fail open:** if the `monition` CLI or live store is absent, skip the pass entirely.
   - **Walk the top N** (a budget — ~15; head, not tail; stop when `rating_priority` drops
     off or evidence runs out). For each firing, look in the session for evidence the
     injected `one_liner` (it fired at `trigger_context` / `situation`) actually mattered:
     it **changed an action**, was **visibly ignored**, or was **contradicted** by what
     you did.
   - **Propose a rating ONLY where the session evidences it**, with a mandatory one-line
     citation of *what in this session* shows it. **No evidence → no rating** — never pad
     to hit coverage; an unsupported `helpful` is directional bias in the eval set, worse
     than a label missing at random. (A cold mine — rating a session you didn't live
     through — evidences little and correctly proposes ~0.)
   - **Present ONE batch for bulk confirm:** all proposed ratings at once, each line
     `<firing_id> helpful|noise — <one-line evidence>`; the user accepts the batch in a
     single gesture with per-line veto/flip. A rating is reversible eval data, so this is
     a **lighter gate** than proposing a new row.
   - **Apply the accepted lines:** `monition rate <firing_id> helpful|noise` for each.
     These ride into the `monition commit` at step 5.

   Then mine for new lessons:

1. Review the session for lessons that are **reusable** (would recur) and
   **non-obvious** (a future session wouldn't rediscover them cheaply). Mistakes,
   gotchas, corrections, and confirmed preferences all qualify; routine work does not.
2. **Route each candidate before drafting** (routing v1 — from CMS
   `method/lesson-routing.md`; run in order, first decisive test wins; under
   uncertainty prefer the row — it is the only tier with an eval loop and it
   retires cleanly):
   - *Behavior test:* can't state it as "in situation S, do/avoid X" with a
     nameable S → not routable; leave it in session notes.
   - *Owning surface:* an artifact that already fires at S (a skill that runs
     then, a hook on that event, a prompt for that task, a linter on those files,
     or a governance surface named in this repo's CLAUDE.md) gets the edit
     directly — a parallel row duplicates its trigger with worse precision.
     Procedure changes always land here. Destinations with their own admission
     rules keep them.
   - *Describable trigger, no owner:* takeaway row (`monition add`) — also the
     default when evidence is thin.
   - *Every session:* a CLAUDE.md line, only if it earns being paid every
     session forever.
   - *Mechanical shadow:* checkable-and-unambiguous violations also get a linter
     check alongside whatever prose landed above; for semantic artifacts the
     host's eval suite plays that role — the lesson must pass it before consent
     closes.

   Every landing goes through the consent gate; the proposal names the deciding test.
3. For each candidate routed to a row, draft the full row: `kind`
   (gotcha/rule/preference), `trigger_kind` + `trigger_spec` (*when should this
   fire?* — the design decision; edit_path glob, session_start, or on_demand),
   `one_liner` (what gets injected — make it a trap-warning, not a description),
   `full_content` (the why + the workaround), `source` (session/commit).
4. **Show the proposed landings and get acceptance before applying** (consent gate).
5. Insert accepted rows (`monition add …`), then snapshot the store:
   `monition commit -m "mine: <session topic>"`.
6. If a takeaway is domain-free enough to apply beyond this repo, add it with
   `--mirror candidate` — the mirror-back sweep picks those up. It keeps firing
   locally while queued; mirror state never affects firing.
"""

SKILLS = {"mine-session": SKILL_MINE_SESSION}

README_LINE = (
    "Takeaway capture/disclosure via [Monition](https://github.com/bobrobaker/monition): "
    "`pip install git+https://github.com/bobrobaker/monition.git` (hooks fail open if absent).\n"
)

DUMP_HOOK_SNIPPET = (
    "command -v monition >/dev/null 2>&1 && "
    "monition dump >/dev/null && git add monition/dump.sql || true\n"
)

_STAMP_RE = re.compile(r"^<!-- monition-skill v(\S+) sha256:([0-9a-f]{64}) -->\n")


def _stamp(body):
    digest = hashlib.sha256(body.encode()).hexdigest()
    return f"<!-- monition-skill v{VERSION} sha256:{digest} -->\n"


def _skill_state(path, body):
    """One of: absent, untouched (stamp matches content), edited, current."""
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
    """Add monition's guarded hook entries; never touch unrelated ones."""
    added = []
    hooks = settings.setdefault("hooks", {})
    wanted = [
        ("PreToolUse", "Write|Edit", guarded_hook_command("fire-hook")),
        ("SessionStart", None, guarded_hook_command("session-brief")),
        ("UserPromptSubmit", None, guarded_hook_command("prompt-hook")),
    ]
    for event, matcher, cmd in wanted:
        entries = hooks.setdefault(event, [])
        present = any(
            h.get("command") == cmd
            for entry in entries for h in entry.get("hooks", [])
        )
        if not present:
            entry = {"hooks": [{"type": "command", "command": cmd}]}
            if matcher:
                entry = {"matcher": matcher, "hooks": entry["hooks"]}
            entries.append(entry)
            added.append(event)
    return added


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
        yield name, path, body, _skill_state(path, body)


def _write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


def init(root, dry_run=False, with_dump_hook=False, dolt=False):
    """Returns the list of change lines (already executed unless dry_run).

    `dolt=True` uses the Dolt backend (requires dolt binary); the default
    is SQLite (stdlib, zero install).
    """
    changes = []

    def act(desc, fn):
        changes.append(("would " + desc) if dry_run else desc)
        if not dry_run:
            fn()

    store = os.path.join(root, "monition")
    dolt_store = os.path.isdir(os.path.join(store, ".dolt"))
    sqlite_store = os.path.exists(os.path.join(store, "store.db"))

    if dolt_store or sqlite_store:
        pass  # store exists — idempotent
    elif dolt:
        if _dolt_bin() is None:
            raise StoreContractError(
                "dolt binary not found on PATH or ~/.local/bin — install dolt "
                "or omit --dolt to use the SQLite backend (zero install)"
            )
        def make_dolt_store():
            os.makedirs(store, exist_ok=True)
            try:
                DoltBackend(store).init(V5_SCHEMA)
            except StorageBackendError as e:
                raise StoreContractError(str(e)) from e
        act(f"create Monition store at {store} (v5 schema, dolt)", make_dolt_store)
    else:
        def make_sqlite_store():
            os.makedirs(store, exist_ok=True)
            SqliteBackend(os.path.join(store, "store.db")).init(V5_SCHEMA_SQLITE)
        act(f"create Monition store at {store} (v5 schema, sqlite)", make_sqlite_store)

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
            if state == "untouched":
                act(f"upgrade skill {name} ({path})",
                    lambda p=path, b=body: _write(p, _stamp(b) + b))
            else:
                act(f"install skill {name} ({path})",
                    lambda p=path, b=body: _write(p, _stamp(b) + b))
        elif state == "edited":
            changes.append(f"WARN: skill {name} locally edited — left alone ({path})")

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


def migrate(store_path):
    """Bring a store up to the current schema (v5). Cumulative — an older store
    traverses every step it is missing:

    - v1 → v2: split the overloaded status domain into status + mirror axes
    - v2 → v3: add the decisions table
    - v3 → v4: add fire-time provenance columns to firings
    - v4 → v5: add the situational-excerpt column to firings
    """
    if _dolt_bin() is None:
        raise StoreContractError("dolt binary not found on PATH or ~/.local/bin")
    if not os.path.isdir(os.path.join(store_path, ".dolt")):
        raise StoreContractError(f"{store_path} is not a Dolt database")

    firing_cols = {r["Field"] for r in _raw_sql(store_path, "DESCRIBE `firings`")}
    has_provenance = "git_sha" in firing_cols
    has_situation = "situation" in firing_cols
    try:
        _raw_sql(store_path, "DESCRIBE `decisions`")
        decisions_exist = True
    except StoreContractError:
        decisions_exist = False

    if decisions_exist and has_provenance and has_situation:
        raise StoreContractError("store is already v5 — nothing to migrate")

    cols = {r["Field"]: r["Type"] for r in _raw_sql(store_path, "DESCRIBE `takeaways`")}
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

    Store(store_path)  # the reader's fingerprint check is the success gate
    return f"migrated {store_path} to v5"
