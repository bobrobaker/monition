"""Write-capable store surface — the ported takeaway.py command set.

A characterization port of CMS `tools/takeaway.py` (the oracle until the B06
cutover): same SQL, same matching semantics, same output strings. Contract
sections binding this module: `trigger_spec` coordinate systems (per-pattern
comma split + strip + fnmatch against the repo-relative path) and Dedup
semantics (at most one disclosure per takeaway per session, deduped by
querying `firings`).

All writes flow through WriteStore, which inherits the reader's fingerprint
validation — no write happens against a store that fails the v2 contract.
"""
import fnmatch
import json
import os
import re
import subprocess

from .store import Store, StoreContractError


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


def reach_clause(repo):
    """SQL predicate gating *where* a row fires: `general` reach fires in any repo,
    `project` only where `origin_repo` equals the current repo.

    `repo is None` means the caller has no repo context — the reach filter is then
    **not applied** (fail-open, legacy behavior). Every auto-injection hot path (the
    hooks) supplies its repo, so the gate is live where leakage would be silent; the
    only callers that can pass None are explicit pulls (cli `query`, mcp
    `match_gotchas`) with no detectable repo, where returning the unfiltered set is
    a transparent "you asked, here's everything."
    """
    if repo is None:
        return ""
    # `origin_repo IS NULL` fires anywhere: a project row that never declared its
    # repo is under-specified, so fail-open rather than silently suppress (the
    # store's NULL-is-missing stance). Real v6 project rows always carry origin_repo
    # (add() stamps the current repo; migrate backfills it), so isolation holds for
    # every properly-specified row — only malformed/legacy NULLs fire broadly.
    return (f" AND (reach = 'general' OR origin_repo IS NULL"
            f" OR origin_repo = {val(repo)})")


def esc(s):
    return s.replace("\\", "\\\\").replace("'", "\\'")


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


def _content_tokens(text):
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) >= 4}


def _jaccard(a, b):
    ta, tb = _content_tokens(a), _content_tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


class WriteStore(Store):
    """Store opened for the lifecycle commands; contract-validated like the reader."""

    def add(self, kind, trigger_kind, one_liner, trigger_spec=None,
            full_content=None, scope=None, source=None, reach="project",
            origin_repo=None):
        # A project row with no origin_repo can never fire (origin_repo = NULL
        # never matches the reach predicate), so stamp the current repo. general
        # rows fire anywhere and need no origin.
        if reach == "project" and origin_repo is None:
            origin_repo = current_repo()
        self._sql(
            "INSERT INTO takeaways (created, kind, scope, trigger_kind, trigger_spec,"
            " one_liner, full_content, source, reach, origin_repo) VALUES (NOW(), "
            f"{val(kind)}, {val(scope)}, {val(trigger_kind)}, {val(trigger_spec)},"
            f" {val(one_liner)}, {val(full_content)}, {val(source)}, {val(reach)},"
            f" {val(origin_repo)})"
        )
        # each `dolt sql -q` is its own connection, so LAST_INSERT_ID() is useless here
        row = self._sql("SELECT MAX(id) AS id FROM takeaways")
        return f"added takeaway {row[0]['id']}"

    def list_rows(self, status="active"):
        rows = self._sql(
            "SELECT id, kind, trigger_kind, trigger_spec, status, reach, one_liner"
            f" FROM takeaways WHERE status = {val(status)} ORDER BY id"
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
        fired = self._sql(
            "SELECT DISTINCT takeaway_id FROM firings"
            f" WHERE session_id = {val(session)}"
        )
        fired_ids = {r["takeaway_id"] for r in fired}
        return [r for r in rows if r["id"] not in fired_ids]

    def match(self, path, session=None, current_repo=None):
        rows = self._sql(
            "SELECT id, one_liner, trigger_spec FROM takeaways"
            " WHERE status = 'active' AND trigger_kind = 'edit_path'"
            + reach_clause(current_repo)
        )
        hits = [
            r for r in rows
            if any(fnmatch.fnmatch(path, g.strip())
                   for g in (r["trigger_spec"] or "").split(","))
        ]
        return json.dumps(self._not_yet_fired(hits, session))

    def on_demand_match(self, query, session=None, current_repo=None):
        rows = self._sql(
            "SELECT id, one_liner, trigger_spec FROM takeaways"
            " WHERE status = 'active' AND trigger_kind = 'on_demand'"
            + reach_clause(current_repo)
        )
        q = query.lower()

        def lex_hit(r):
            return any(kw.strip().lower() in q
                       for kw in (r.get("trigger_spec") or "").split(",")
                       if kw.strip())

        lexical = [r for r in rows if lex_hit(r)]
        hits = [{"id": r["id"], "one_liner": r["one_liner"]} for r in lexical]
        rest = [r for r in rows if not lex_hit(r)]
        if rest:
            # fail-open: embeddings absent/broken → lexical-only is a valid result
            try:
                from . import embed
                texts = [f'{r["one_liner"]} {r.get("trigger_spec") or ""}'
                         for r in rest]
                sims = embed.semantic_scores(query, texts)
                ranked = sorted(
                    (p for p in zip(sims, rest) if p[0] >= embed.SIM_THRESHOLD),
                    key=lambda p: p[0], reverse=True,
                )
                hits += [{"id": r["id"], "one_liner": r["one_liner"]}
                         for _, r in ranked]
            except Exception:
                pass
        return json.dumps(self._not_yet_fired(hits, session))

    def session_start(self, session=None, current_repo=None):
        rows = self._sql(
            "SELECT id, one_liner FROM takeaways"
            " WHERE status = 'active' AND trigger_kind = 'session_start'"
            + reach_clause(current_repo)
        )
        return json.dumps(self._not_yet_fired(rows, session))

    def fire(self, takeaway_id, trigger_kind, session=None, context=None,
             model=None, situation=None, current_repo=None):
        # v4 provenance: git state of the *host repo* (current_repo), not the store
        # dir — under a v6 hub `os.path.dirname(self.path)` is the hub, not the repo.
        # current_repo is None only for mine-time self-calls (recurrence logging),
        # where there is no host-repo disclosure context; fall back to the store dir
        # for best-effort provenance there and record repo = NULL (honestly unknown).
        # v6 `repo`: the host repo at fire time — capture-or-lose, recovers per-repo
        # precision for general-reach rows. v5 `situation`: the executor's excerpt.
        provenance_root = current_repo or os.path.dirname(self.path)
        git_sha, git_dirty = _git_provenance(provenance_root)
        self._sql(
            "INSERT INTO firings (takeaway_id, fired_at, session_id, trigger_kind,"
            " trigger_context, git_sha, git_dirty, model, monition_version, situation,"
            " repo)"
            f" VALUES ({iid(takeaway_id)}, NOW(), {val(session)},"
            f" {val(trigger_kind)}, {val(context)}, {val(git_sha)},"
            f" {bval(git_dirty)}, {val(model)}, {val(_monition_version())}, {val(situation)},"
            f" {val(current_repo)})"
        )
        row = self._sql("SELECT MAX(id) AS id FROM firings")
        return f"firing {row[0]['id']}"

    def rate(self, firing_id, outcome):
        self._sql(f"UPDATE firings SET outcome = {val(outcome)} WHERE id = {iid(firing_id)}")
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

    @staticmethod
    def _decision_values(takeaway_id, session_id, decision,
                         evidence_count, cold_start, ev_score):
        ev_val = val(f"{ev_score:.4f}") if ev_score is not None else "NULL"
        return (f"({iid(takeaway_id)}, {val(session_id)}, NOW(), {val(decision)},"
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
        return matches

    def _content_similarity(self, query, texts):
        """(scores, threshold): embedding cosine when the embed extra is present,
        fail-open to lexical Jaccard otherwise — mirrors on_demand_match."""
        try:
            from . import embed
            return embed.semantic_scores(query, texts), embed.SIM_THRESHOLD
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
            f"UPDATE takeaways SET full_content = {val(merged)}"
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
