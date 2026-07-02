"""The approved reader — the only module that touches a takeaway store.

Implements the column-fingerprint version check from
docs/contracts/takeaway-store.md §Versioning: verify tables, required columns,
and enum domains before reading a single row; raise StoreContractError on any
mismatch. Additive unknown columns are tolerated. All queries are reads.
"""
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from .storage_backends import StorageBackendError, open_backend


class StoreContractError(Exception):
    """The store at this path does not satisfy the takeaway-store contract."""


# Required columns and their type-pattern per backend dialect.
#
# Dolt patterns match MySQL DESCRIBE type strings (enum domains checked exactly).
# SQLite patterns match PRAGMA table_info type strings (enum domains can't be
# checked via type string — they are enforced at write time by CHECK constraints).
_REQUIRED = {
    "takeaways": {
        "id": r"^int",
        "created": r"^datetime",
        "kind": r"^enum\('gotcha','rule','preference'\)$",
        "scope": r"^varchar",
        "trigger_kind": r"^enum\('edit_path','session_start','on_demand','tool_call'\)$",
        "trigger_spec": r"^varchar",
        "one_liner": r"^varchar",
        "full_content": r"^text",
        "source": r"^varchar",
        "status": r"^enum\('active','retired'\)$",
        "reach": r"^enum\('general','project'\)$",
        "origin_repo": r"^varchar",
        "violation_signature": r"^text",
        "sem_threshold": r"^decimal",
    },
    "firings": {
        "id": r"^int",
        "takeaway_id": r"^int",
        "fired_at": r"^datetime",
        "session_id": r"^varchar",
        "trigger_kind": r"^varchar",
        "trigger_context": r"^varchar",
        "outcome": r"^enum\('helpful','noise'\)$",
        "git_sha": r"^varchar",
        "git_dirty": r"^tinyint",
        "model": r"^varchar",
        "monition_version": r"^varchar",
        "situation": r"^text",
        "repo": r"^varchar",
        "match_evidence": r"^text",
    },
    "decisions": {
        "id": r"^int",
        "takeaway_id": r"^int",
        "decided_at": r"^datetime",
        "decision": r"^enum\('fire','suppress'\)$",
        "evidence_count": r"^int",
        "cold_start": r"^tinyint",
        "ev_score": r"^decimal",
    },
    "violations": {
        "id": r"^int",
        "takeaway_id": r"^int",
        "session_id": r"^varchar",
        "detected_at": r"^datetime",
        "evidence": r"^text",
        "repo": r"^varchar",
    },
    "mutations": {
        "id": r"^int",
        "takeaway_id": r"^int",
        "mutated_at": r"^datetime",
        "verb": r"^varchar",
        "changes": r"^text",
        "source": r"^varchar",
    },
}

_REQUIRED_SQLITE = {
    "takeaways": {
        "id": r"^INTEGER$",
        "created": r"^TEXT$",
        "kind": r"^TEXT$",
        "scope": r"^TEXT$",
        "trigger_kind": r"^TEXT$",
        "trigger_spec": r"^TEXT$",
        "one_liner": r"^TEXT$",
        "full_content": r"^TEXT$",
        "source": r"^TEXT$",
        "status": r"^TEXT$",
        "reach": r"^TEXT$",
        "origin_repo": r"^TEXT$",
        "violation_signature": r"^TEXT$",
        "sem_threshold": r"^NUMERIC$",
    },
    "firings": {
        "id": r"^INTEGER$",
        "takeaway_id": r"^INTEGER$",
        "fired_at": r"^TEXT$",
        "session_id": r"^TEXT$",
        "trigger_kind": r"^TEXT$",
        "trigger_context": r"^TEXT$",
        "outcome": r"^TEXT$",
        "git_sha": r"^TEXT$",
        "git_dirty": r"^INTEGER$",
        "model": r"^TEXT$",
        "monition_version": r"^TEXT$",
        "situation": r"^TEXT$",
        "repo": r"^TEXT$",
        "match_evidence": r"^TEXT$",
    },
    "decisions": {
        "id": r"^INTEGER$",
        "takeaway_id": r"^INTEGER$",
        "decided_at": r"^TEXT$",
        "decision": r"^TEXT$",
        "evidence_count": r"^INTEGER$",
        "cold_start": r"^INTEGER$",
        "ev_score": r"^NUMERIC$",
    },
    "violations": {
        "id": r"^INTEGER$",
        "takeaway_id": r"^INTEGER$",
        "session_id": r"^TEXT$",
        "detected_at": r"^TEXT$",
        "evidence": r"^TEXT$",
        "repo": r"^TEXT$",
    },
    "mutations": {
        "id": r"^INTEGER$",
        "takeaway_id": r"^INTEGER$",
        "mutated_at": r"^TEXT$",
        "verb": r"^TEXT$",
        "changes": r"^TEXT$",
        "source": r"^TEXT$",
    },
}

FIRING_ELIGIBLE = ("active",)

# the v1 status domain carried mirror-back state; reject it by name, never coerce
_V1_STATUS = "enum('active','retired','upstream_candidate','mirrored')"


@dataclass(frozen=True)
class Takeaway:
    id: int
    created: datetime
    kind: str
    scope: Optional[str]
    trigger_kind: str
    trigger_spec: Optional[str]
    one_liner: str
    full_content: Optional[str]
    source: Optional[str]
    status: str
    reach: str
    origin_repo: Optional[str]
    # v7 violation signature — None = no probe; the row has no FN column
    violation_signature: Optional[str] = None
    # v8 per-row semantic threshold — None = global default (embed.SIM_THRESHOLD)
    sem_threshold: Optional[float] = None

    @property
    def firing_eligible(self):
        return self.status in FIRING_ELIGIBLE


@dataclass(frozen=True)
class Firing:
    id: int
    takeaway_id: int
    fired_at: datetime
    session_id: Optional[str]
    trigger_kind: Optional[str]
    trigger_context: Optional[str]
    outcome: Optional[str]  # None = unrated: missing data, never "noise"
    # v4 fire-time provenance — None = not captured (pre-v4 firing or unavailable)
    git_sha: Optional[str] = None
    git_dirty: Optional[bool] = None
    model: Optional[str] = None
    monition_version: Optional[str] = None
    # v5 firing-grain situational excerpt — None = not captured / executor had none
    situation: Optional[str] = None
    # v7 lossless match evidence — None = pre-v7 firing or a non-matcher fire
    match_evidence: Optional[str] = None


@dataclass(frozen=True)
class Decision:
    id: int
    takeaway_id: int
    session_id: Optional[str]
    decided_at: datetime
    decision: str
    evidence_count: int
    cold_start: bool
    ev_score: Optional[float]  # None when cold_start=True (Dolt omits NULL key)


@dataclass(frozen=True)
class Mutation:
    """One consented trigger-mutation event (v8). `changes` is the JSON
    `{field: {"old": ..., "new": ...}}` record, old values captured before the
    write. Never a firing and never rating evidence — consumers are the
    proposal engine's audit view, report, and replay."""
    id: int
    takeaway_id: int
    mutated_at: datetime
    verb: str
    changes: str
    source: Optional[str]


@dataclass(frozen=True)
class Violation:
    """One observed not-fired∧hit event: the failure a row warns about occurred
    in a session where the row never fired. Never a firing — excluded from
    precision, disclosure dedup, and scorer evidence by contract."""
    id: int
    takeaway_id: int
    session_id: str
    detected_at: datetime
    evidence: Optional[str]
    repo: Optional[str]


def _parse_dt(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")


class Store:
    """Read-only view of one takeaway store, contract-validated on open."""

    def __init__(self, path):
        import os
        self.path = os.path.abspath(os.path.expanduser(path))
        try:
            self._backend = open_backend(self.path)
        except StorageBackendError as e:
            raise StoreContractError(str(e)) from e
        self._validate_schema()

    def _sql(self, query):
        try:
            return self._backend.execute_sql(query)
        except StorageBackendError as e:
            raise StoreContractError(
                f"query failed against {self.path}: {e}"
            ) from e

    def _val(self, s):
        """Dialect-correct nullable string literal, bound to THIS store's
        backend. SQLite treats backslashes literally where MySQL escapes
        them, so a store method must never use the module-level `val()`
        (MySQL-dialect-only, kept for Dolt-only paths like the fold) — values
        containing backslashes or quotes corrupt on SQLite otherwise."""
        return "NULL" if s is None else self._backend.quote(s)

    def _detect_stale_schema(self):
        """Version-ladder detection, oldest→newest, so the migrate message names
        the *actual* gap. Runs before the per-table column checks (which assume v6
        columns). Missing-table cases fall through to those checks."""
        takeaway_cols = {r["Field"]: r["Type"]
                         for r in self._backend.describe("takeaways")}
        firing_cols = {r["Field"] for r in self._backend.describe("firings")}
        decisions_present = bool(self._backend.describe("decisions"))

        # v1 detection (Dolt only — SQLite stores are always fresh)
        if (self._backend.name == "dolt"
                and takeaway_cols.get("status") == _V1_STATUS):
            raise StoreContractError(
                "v1-dialect store: `status` still carries mirror-back state "
                "(upstream_candidate/mirrored) — run `monition migrate` to upgrade "
                "to the current schema before reading"
            )
        if takeaway_cols and not decisions_present:
            raise StoreContractError(
                "v2-schema store: missing `decisions` table — "
                "run `monition migrate` to upgrade to v3"
            )
        if firing_cols and "git_sha" not in firing_cols:
            raise StoreContractError(
                "v3-schema store: `firings` lacks fire-time provenance "
                "(git_sha/git_dirty/model/monition_version) — "
                "run `monition migrate` to upgrade to v4"
            )
        if "git_sha" in firing_cols and "situation" not in firing_cols:
            raise StoreContractError(
                "v4-schema store: `firings` lacks the `situation` column — "
                "run `monition migrate` to upgrade to v5"
            )
        if takeaway_cols and "reach" not in takeaway_cols:
            raise StoreContractError(
                "v5-schema store: `takeaways` lacks `reach`/`origin_repo` — "
                "run `monition migrate` to upgrade to v6"
            )
        # The three v7 pieces migrate atomically, so any one missing means v6 —
        # but a missing *table* is not a version signal; it falls through to the
        # per-table checks (hence the per-indicator table guards).
        violations_present = bool(self._backend.describe("violations"))
        if ((takeaway_cols and "violation_signature" not in takeaway_cols)
                or (firing_cols and "match_evidence" not in firing_cols)
                or (takeaway_cols and firing_cols and not violations_present)):
            raise StoreContractError(
                "v6-schema store: lacks `violation_signature`/`match_evidence`/"
                "`violations` (the recall column) — "
                "run `monition migrate` to upgrade to v7"
            )
        # The three v8 pieces migrate atomically too; a missing `mutations`
        # table alone is not a version signal (per-indicator table guards).
        mutations_present = bool(self._backend.describe("mutations"))
        if ((takeaway_cols and "sem_threshold" not in takeaway_cols)
                or (takeaway_cols and firing_cols and not mutations_present)):
            raise StoreContractError(
                "v7-schema store: lacks `sem_threshold`/`mutations` (the "
                "mutation track) — run `monition migrate` to upgrade to v8"
            )

    def _validate_schema(self):
        required = (
            _REQUIRED_SQLITE if self._backend.name == "sqlite" else _REQUIRED
        )
        self._detect_stale_schema()
        for table, cols_required in required.items():
            col_rows = self._backend.describe(table)
            if not col_rows:
                raise StoreContractError(
                    f"missing required table `{table}` in {self.path}"
                )
            cols = {r["Field"]: r["Type"] for r in col_rows}
            for name, pattern in cols_required.items():
                if name not in cols:
                    raise StoreContractError(
                        f"`{table}` is missing required column `{name}`"
                    )
                if not re.match(pattern, cols[name]):
                    raise StoreContractError(
                        f"`{table}.{name}` has type {cols[name]!r}, "
                        f"contract requires /{pattern}/"
                    )
            # additive unknown columns are tolerated by design

    def takeaways(self):
        rows = self._sql(
            "SELECT id, created, kind, scope, trigger_kind, trigger_spec,"
            " one_liner, full_content, source, status, reach, origin_repo,"
            " violation_signature, sem_threshold"
            " FROM takeaways ORDER BY id"
        )
        return [
            Takeaway(
                id=r["id"], created=_parse_dt(r["created"]), kind=r["kind"],
                scope=r.get("scope"), trigger_kind=r["trigger_kind"],
                trigger_spec=r.get("trigger_spec"), one_liner=r["one_liner"],
                full_content=r.get("full_content"), source=r.get("source"),
                status=r["status"], reach=r["reach"], origin_repo=r.get("origin_repo"),
                violation_signature=r.get("violation_signature"),
                sem_threshold=(float(r["sem_threshold"])
                               if r.get("sem_threshold") is not None else None),
            )
            for r in rows
        ]

    def firings(self):
        rows = self._sql(
            "SELECT id, takeaway_id, fired_at, session_id, trigger_kind,"
            " trigger_context, outcome, git_sha, git_dirty, model,"
            " monition_version, situation, match_evidence FROM firings ORDER BY id"
        )
        firings = [
            Firing(
                id=r["id"], takeaway_id=r["takeaway_id"],
                fired_at=_parse_dt(r["fired_at"]), session_id=r.get("session_id"),
                trigger_kind=r.get("trigger_kind"),
                trigger_context=r.get("trigger_context"), outcome=r.get("outcome"),
                git_sha=r.get("git_sha"),
                git_dirty=bool(r["git_dirty"]) if r.get("git_dirty") is not None else None,
                model=r.get("model"), monition_version=r.get("monition_version"),
                situation=r.get("situation"),
                match_evidence=r.get("match_evidence"),
            )
            for r in rows
        ]
        known = {t.id for t in self.takeaways()}
        orphans = [f.id for f in firings if f.takeaway_id not in known]
        if orphans:
            raise StoreContractError(
                f"firings reference missing takeaways (firing ids {orphans})"
            )
        return firings

    def decisions(self):
        rows = self._sql(
            "SELECT id, takeaway_id, session_id, decided_at, decision,"
            " evidence_count, cold_start, ev_score FROM decisions ORDER BY id"
        )
        decisions = [
            Decision(
                id=r["id"], takeaway_id=r["takeaway_id"],
                session_id=r.get("session_id"), decided_at=_parse_dt(r["decided_at"]),
                decision=r["decision"], evidence_count=r["evidence_count"],
                cold_start=bool(r["cold_start"]),
                ev_score=float(r["ev_score"]) if r.get("ev_score") is not None else None,
            )
            for r in rows
        ]
        known = {t.id for t in self.takeaways()}
        orphans = [d.id for d in decisions if d.takeaway_id not in known]
        if orphans:
            raise StoreContractError(
                f"decisions reference missing takeaways (decision ids {orphans})"
            )
        return decisions

    def mutations(self):
        rows = self._sql(
            "SELECT id, takeaway_id, mutated_at, verb, changes, source"
            " FROM mutations ORDER BY id"
        )
        mutations = [
            Mutation(
                id=r["id"], takeaway_id=r["takeaway_id"],
                mutated_at=_parse_dt(r["mutated_at"]), verb=r["verb"],
                changes=r["changes"], source=r.get("source"),
            )
            for r in rows
        ]
        known = {t.id for t in self.takeaways()}
        orphans = [m.id for m in mutations if m.takeaway_id not in known]
        if orphans:
            raise StoreContractError(
                f"mutations reference missing takeaways (mutation ids {orphans})"
            )
        return mutations

    def violations(self):
        rows = self._sql(
            "SELECT id, takeaway_id, session_id, detected_at, evidence, repo"
            " FROM violations ORDER BY id"
        )
        violations = [
            Violation(
                id=r["id"], takeaway_id=r["takeaway_id"],
                session_id=r["session_id"], detected_at=_parse_dt(r["detected_at"]),
                evidence=r.get("evidence"), repo=r.get("repo"),
            )
            for r in rows
        ]
        known = {t.id for t in self.takeaways()}
        orphans = [v.id for v in violations if v.takeaway_id not in known]
        if orphans:
            raise StoreContractError(
                f"violations reference missing takeaways (violation ids {orphans})"
            )
        return violations
