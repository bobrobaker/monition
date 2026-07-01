#!/usr/bin/env python3
"""Render a one-page exploratory dashboard of a Monition store.

Monition's premise is *lessons as rows, triggers as data, firings as eval data*:
mined takeaways fire into sessions, and the firing log is the substrate an
EV-scored firing engine trains against. This utility reads that log and asks the
questions the premise makes interesting:

  - Signal quality   — which rows are gold and which are noise generators?
  - The eval gap      — what share of firings ever get a helpful/noise label?
  - Concentration     — do a few rows dominate all firing traffic? (Gini/Lorenz)
  - Cross-repo lift    — does the shared hub actually carry `general` rows across repos?
  - The firing gate   — where does the EV score draw the fire/suppress line?
  - Durability        — how fast do mined rows start firing, and do they keep firing?

It is backend-agnostic: it pulls the three raw tables (Dolt via the `dolt` CLI, or
a SQLite file via stdlib) and does every aggregate in Python, so no SQL dialect
leaks in. Output is a single PNG.

Dependencies: numpy and matplotlib (beyond the stdlib) — install both before running.

Usage:
    python3 tools/monition_dashboard.py [--store PATH] [--out FILE] [--days N]

Store resolution: --store, else $MONITION_STORE, else $CMS_LANDING_ZONE/monition,
else ./monition. Output defaults to ~/.local/state/monition/dashboard.png (outside
any repo working tree) — override with --out.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec

# ── palette ────────────────────────────────────────────────────────────────
BG = "#0e1117"
PANEL = "#161b22"
GRID = "#2a313c"
FG = "#c9d1d9"
MUTE = "#8b949e"
ACCENT = "#58a6ff"
GOOD = "#3fb950"
BAD = "#f85149"
WARN = "#d29922"
PURPLE = "#bc8cff"
TEAL = "#39c5cf"

TS_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S.%f")


# ── store access ───────────────────────────────────────────────────────────
def resolve_store(arg: str | None) -> Path:
    cand = arg or os.environ.get("MONITION_STORE")
    if not cand:
        lz = os.environ.get("CMS_LANDING_ZONE")
        cand = str(Path(lz) / "monition") if lz else "monition"
    p = Path(cand).expanduser()
    if not p.exists():
        sys.exit(f"store not found: {p}")
    return p


def _fetch_dolt(store: Path, table: str, cols: list[str]) -> list[dict]:
    q = f"SELECT {', '.join(cols)} FROM {table}"
    out = subprocess.run(
        ["dolt", "sql", "-q", q, "-r", "json"],
        cwd=store, capture_output=True, text=True, check=True,
    ).stdout
    return json.loads(out).get("rows", [])


def _fetch_sqlite(dbfile: Path, table: str, cols: list[str]) -> list[dict]:
    import sqlite3

    con = sqlite3.connect(str(dbfile))
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(f"SELECT {', '.join(cols)} FROM {table}").fetchall()
    finally:
        con.close()
    return [dict(r) for r in rows]


def load(store: Path):
    """Return (takeaways, firings, decisions, backend_name)."""
    tk_cols = ["id", "created", "kind", "scope", "trigger_kind", "status",
               "reach", "origin_repo", "one_liner"]
    fr_cols = ["id", "takeaway_id", "fired_at", "session_id", "trigger_kind",
               "outcome", "model", "repo"]
    dc_cols = ["id", "takeaway_id", "decided_at", "decision", "evidence_count",
               "cold_start", "ev_score"]

    if (store / ".dolt").exists():
        f = lambda t, c: _fetch_dolt(store, t, c)
        backend = "dolt"
    else:
        dbs = [p for p in store.iterdir()
               if p.suffix in (".db", ".sqlite", ".sqlite3")] if store.is_dir() else []
        if store.is_file():
            dbs = [store]
        if not dbs:
            sys.exit(f"no .dolt dir and no sqlite file under {store}")
        f = lambda t, c: _fetch_sqlite(dbs[0], t, c)
        backend = "sqlite"

    return f("takeaways", tk_cols), f("firings", fr_cols), f("decisions", dc_cols), backend


# ── normalization ──────────────────────────────────────────────────────────
def parse_ts(v):
    if not v:
        return None
    s = str(v)
    for fmt in TS_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def norm_outcome(v):
    if v in ("helpful", 1, "1"):
        return "helpful"
    if v in ("noise", 2, "2"):
        return "noise"
    return None


def short_repo(r):
    if not r:
        return "(none)"
    name = Path(r).name
    if ".cache/agent-spawn/worktrees" in r:
        return f"⌥{name}"
    return name


# ── stats helpers ──────────────────────────────────────────────────────────
def gini(values):
    a = np.sort(np.asarray([v for v in values if v > 0], dtype=float))
    if a.size == 0:
        return 0.0
    n = a.size
    cum = np.cumsum(a)
    return (n + 1 - 2 * np.sum(cum) / cum[-1]) / n


def lorenz(values):
    a = np.sort(np.asarray([v for v in values if v > 0], dtype=float))
    if a.size == 0:
        return np.array([0, 1]), np.array([0, 1])
    cum = np.cumsum(a) / a.sum()
    x = np.linspace(0, 1, a.size + 1)
    y = np.concatenate([[0], cum])
    return x, y


# ── panel styling ──────────────────────────────────────────────────────────
def style(ax, title=None, subtitle=None):
    ax.set_facecolor(PANEL)
    for s in ax.spines.values():
        s.set_color(GRID)
    ax.tick_params(colors=MUTE, labelsize=8)
    ax.grid(True, color=GRID, lw=0.5, alpha=0.5)
    if title:
        ax.set_title(title, color=FG, fontsize=11, fontweight="bold",
                     loc="left", pad=22 if subtitle else 6)
    if subtitle:
        ax.text(0, 1.03, subtitle, transform=ax.transAxes, color=MUTE,
                fontsize=8, va="bottom")


def kpi(ax, value, label, sub=None, color=ACCENT):
    ax.set_facecolor(PANEL)
    ax.axis("off")
    for s in ax.spines.values():
        s.set_visible(False)
    ax.add_patch(plt.Rectangle((0, 0), 1, 1, transform=ax.transAxes,
                               facecolor=PANEL, edgecolor=GRID, lw=1))
    ax.text(0.5, 0.62, value, transform=ax.transAxes, ha="center", va="center",
            color=color, fontsize=26, fontweight="bold")
    ax.text(0.5, 0.27, label.upper(), transform=ax.transAxes, ha="center",
            va="center", color=FG, fontsize=9.5, fontweight="bold")
    if sub:
        ax.text(0.5, 0.11, sub, transform=ax.transAxes, ha="center",
                va="center", color=MUTE, fontsize=7.5)


# ── main render ────────────────────────────────────────────────────────────
def render(store: Path, out: Path, days: int | None):
    tks, frs, dcs, backend = load(store)

    # index takeaways
    tk = {t["id"]: t for t in tks}
    for f in frs:
        f["_ts"] = parse_ts(f.get("fired_at"))
        f["_out"] = norm_outcome(f.get("outcome"))
    for t in tks:
        t["_created"] = parse_ts(t.get("created"))
    for d in dcs:
        d["_ev"] = None if d.get("ev_score") in (None, "") else float(d["ev_score"])
        d["_cold"] = str(d.get("cold_start")) in ("1", "True", "true")

    frs_dated = [f for f in frs if f["_ts"]]
    horizon = None
    if days:
        latest = max(f["_ts"] for f in frs_dated)
        horizon = latest - timedelta(days=days)
        frs_dated = [f for f in frs_dated if f["_ts"] >= horizon]

    # ── aggregates ──
    active = [t for t in tks if t.get("status") == "active"]
    retired = [t for t in tks if t.get("status") == "retired"]
    total_fires = len(frs_dated)
    rated = [f for f in frs_dated if f["_out"]]
    helpful = sum(1 for f in rated if f["_out"] == "helpful")
    noise = sum(1 for f in rated if f["_out"] == "noise")
    rated_pct = 100 * len(rated) / total_fires if total_fires else 0
    precision = 100 * helpful / (helpful + noise) if rated else 0
    repos = {short_repo(f.get("repo")) for f in frs_dated if f.get("repo")}

    # per-row firing stats
    per_row = defaultdict(lambda: {"n": 0, "h": 0, "x": 0, "repos": set()})
    for f in frs_dated:
        r = per_row[f["takeaway_id"]]
        r["n"] += 1
        if f["_out"] == "helpful":
            r["h"] += 1
        elif f["_out"] == "noise":
            r["x"] += 1
        if f.get("repo"):
            r["repos"].add(short_repo(f["repo"]))

    # ── figure scaffold ──
    fig = plt.figure(figsize=(20, 30), facecolor=BG)
    gs = GridSpec(7, 4, figure=fig, hspace=0.85, wspace=0.28,
                  height_ratios=[0.5, 0.7, 1.0, 1.0, 1.0, 1.0, 1.0],
                  left=0.05, right=0.97, top=0.95, bottom=0.035)

    # header
    hax = fig.add_subplot(gs[0, :])
    hax.axis("off")
    span = ""
    if frs_dated:
        lo = min(f["_ts"] for f in frs_dated).date()
        hi = max(f["_ts"] for f in frs_dated).date()
        span = f"{lo} → {hi}"
    hax.text(0, 0.6, "MONITION  ·  firing-store telemetry",
             color=FG, fontsize=26, fontweight="bold", va="center")
    scope = f"last {days} days" if days else "all time"
    hax.text(0, 0.05, f"{store}  ·  {backend}  ·  {scope}  ·  {span}",
             color=MUTE, fontsize=11, va="center")

    # KPI row
    kpis = [
        (str(len(active)), "active rows", f"+{len(retired)} retired", ACCENT),
        (f"{total_fires:,}", "firings", f"across {len(repos)} repos", TEAL),
        (f"{rated_pct:.0f}%", "rated", f"{len(rated):,} of {total_fires:,} labelled", WARN),
        (f"{precision:.0f}%", "precision", f"{helpful} helpful / {noise} noise", GOOD if precision >= 60 else BAD),
        (f"{len(repos)}", "repos reached", "firing surface", PURPLE),
    ]
    # five cards over a 4-col grid: use a dedicated 1x5 inset
    krow = gs[1, :].subgridspec(1, 5, wspace=0.18)
    for i, (val, lab, sub, col) in enumerate(kpis):
        kpi(fig.add_subplot(krow[0, i]), val, lab, sub, col)

    # ── 1. firing volume over time + cumulative corpus growth ──
    ax = fig.add_subplot(gs[2, :2])
    style(ax, "Firing volume & corpus growth",
          "daily firings (bars) vs. cumulative active rows (line)")
    by_day = Counter(f["_ts"].date() for f in frs_dated)
    rated_by_day = Counter(f["_ts"].date() for f in rated)
    if by_day:
        days_sorted = sorted(by_day)
        xs = [datetime.combine(d, datetime.min.time()) for d in days_sorted]
        ax.bar(xs, [by_day[d] for d in days_sorted], width=0.8, color=ACCENT,
               alpha=0.55, label="firings/day")
        ax.bar(xs, [rated_by_day.get(d, 0) for d in days_sorted], width=0.8,
               color=WARN, alpha=0.95, label="rated/day")
        ax.set_ylabel("firings / day", color=MUTE, fontsize=9)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
        ax.tick_params(axis="x", rotation=0)
        # cumulative corpus
        created = sorted(t["_created"] for t in tks if t["_created"]
                         and (not horizon or t["_created"] >= horizon))
        ax2 = ax.twinx()
        ax2.set_facecolor("none")
        for s in ax2.spines.values():
            s.set_color(GRID)
        ax2.tick_params(colors=PURPLE, labelsize=8)
        if created:
            ax2.plot(created, np.arange(1, len(created) + 1), color=PURPLE,
                     lw=2.2, label="cumulative rows")
            ax2.set_ylabel("cumulative rows", color=PURPLE, fontsize=9)
        ax.legend(loc="upper left", facecolor=PANEL, edgecolor=GRID,
                  labelcolor=FG, fontsize=8)

    # ── 2. signal-quality scatter: traffic vs precision ──
    ax = fig.add_subplot(gs[2, 2:])
    style(ax, "Signal quality — traffic vs. precision",
          "each dot a row; x=fires, y=helpful share of its rated firings; size=fires")
    xs, ys, sz, cs, labels = [], [], [], [], []
    for tid, r in per_row.items():
        labelled = r["h"] + r["x"]
        if labelled == 0 or tid not in tk:
            continue
        prec = r["h"] / labelled
        xs.append(r["n"])
        ys.append(prec * 100)
        sz.append(30 + r["n"] * 4)
        cs.append(GOOD if prec >= 0.66 else (WARN if prec >= 0.33 else BAD))
        labels.append((r["n"], prec, tid, tk.get(tid, {}).get("one_liner", "")))
    if xs:
        ax.scatter(xs, ys, s=sz, c=cs, alpha=0.75, edgecolors=BG, linewidths=0.6)
        ax.axhspan(0, 33, color=BAD, alpha=0.06)
        ax.axhline(50, color=MUTE, lw=0.8, ls="--")
        ax.set_xlabel("total firings", color=MUTE, fontsize=9)
        ax.set_ylabel("precision (% helpful of rated)", color=MUTE, fontsize=9)
        ax.set_ylim(-5, 108)
        # annotate the high-traffic low-precision retire candidates
        flagged = sorted([l for l in labels if l[0] >= 20 and l[1] < 0.5],
                         key=lambda l: (l[1], -l[0]))[:3]
        for n, prec, tid, ol in flagged:
            ax.annotate(f"#{tid}", (n, prec * 100), color=BAD, fontsize=8,
                        fontweight="bold", xytext=(4, 4), textcoords="offset points")
        ax.text(0.99, 0.03, "red band = retire/narrow candidates",
                transform=ax.transAxes, ha="right", color=BAD, fontsize=8)

    # ── 3. firing concentration: Lorenz + Gini ──
    ax = fig.add_subplot(gs[3, 0])
    counts = [r["n"] for r in per_row.values()]
    g = gini(counts)
    style(ax, "Firing concentration", f"Lorenz curve · Gini = {g:.2f}")
    lx, ly = lorenz(counts)
    ax.plot([0, 1], [0, 1], color=MUTE, ls="--", lw=1)
    ax.plot(lx, ly, color=TEAL, lw=2.4)
    ax.fill_between(lx, ly, lx, color=TEAL, alpha=0.15)
    ax.set_xlabel("share of rows (low→high traffic)", color=MUTE, fontsize=8)
    ax.set_ylabel("share of firings", color=MUTE, fontsize=8)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    # top-decile share callout
    if counts:
        srt = sorted(counts, reverse=True)
        top10 = sum(srt[:max(1, len(srt) // 10)]) / sum(srt) * 100
        ax.text(0.04, 0.92, f"top 10% of rows\n= {top10:.0f}% of firings",
                transform=ax.transAxes, color=FG, fontsize=8.5, va="top")

    # ── 4. the firing gate: ev_score operating point ──
    ax = fig.add_subplot(gs[3, 1])
    style(ax, "The firing gate", "EV score by decision (warm decisions only)")
    fire_ev = [d["_ev"] for d in dcs if d["_ev"] is not None and d.get("decision") == "fire"]
    sup_ev = [d["_ev"] for d in dcs if d["_ev"] is not None and d.get("decision") == "suppress"]
    bins = np.linspace(0, 1, 21)
    if sup_ev:
        ax.hist(sup_ev, bins=bins, color=BAD, alpha=0.65, label=f"suppress ({len(sup_ev)})")
    if fire_ev:
        ax.hist(fire_ev, bins=bins, color=GOOD, alpha=0.65, label=f"fire ({len(fire_ev)})")
    cold = sum(1 for d in dcs if d["_cold"] and d.get("decision") == "fire")
    ax.set_xlabel("EV score", color=MUTE, fontsize=8)
    ax.set_ylabel("decisions", color=MUTE, fontsize=8)
    ax.legend(facecolor=PANEL, edgecolor=GRID, labelcolor=FG, fontsize=8, loc="upper center")
    ax.text(0.5, 0.02, f"+{cold} cold-start fires (no score)", transform=ax.transAxes,
            ha="center", color=MUTE, fontsize=7.5)

    # ── 5. time-to-first-fire ──
    ax = fig.add_subplot(gs[3, 2])
    style(ax, "Time to first fire", "hours from a row's creation to its first firing")
    first_fire = {}
    for f in frs:
        if not f["_ts"]:
            continue
        tid = f["takeaway_id"]
        if tid not in first_fire or f["_ts"] < first_fire[tid]:
            first_fire[tid] = f["_ts"]
    ttf = []
    for tid, ts in first_fire.items():
        c = tk.get(tid, {}).get("_created")
        if c:
            h = (ts - c).total_seconds() / 3600
            if h >= 0:
                ttf.append(h)
    if ttf:
        ax.hist(ttf, bins=np.linspace(0, max(ttf), 25), color=PURPLE, alpha=0.8)
        med = float(np.median(ttf))
        ax.axvline(med, color=ACCENT, lw=1.6, ls="--")
        ax.text(0.96, 0.9, f"median\n{med:.0f}h", transform=ax.transAxes,
                ha="right", va="top", color=ACCENT, fontsize=9, fontweight="bold")
        ax.set_xlabel("hours to first fire", color=MUTE, fontsize=8)
        ax.set_ylabel("rows", color=MUTE, fontsize=8)

    # ── 6. composition: kind × reach ──
    ax = fig.add_subplot(gs[3, 3])
    style(ax, "Corpus composition", "active rows by kind & reach")
    kinds = ["gotcha", "rule", "preference"]
    reaches = ["general", "project"]
    rcolor = {"general": ACCENT, "project": PURPLE}
    bottoms = np.zeros(len(kinds))
    for reach in reaches:
        vals = [sum(1 for t in active if t.get("kind") == k and t.get("reach") == reach)
                for k in kinds]
        ax.bar(kinds, vals, bottom=bottoms, color=rcolor[reach], alpha=0.85,
               label=reach, width=0.6)
        bottoms += np.array(vals)
    ax.set_ylabel("rows", color=MUTE, fontsize=8)
    ax.legend(facecolor=PANEL, edgecolor=GRID, labelcolor=FG, fontsize=8)

    # ── 7. cross-repo transfer: top repos ──
    ax = fig.add_subplot(gs[4, :2])
    style(ax, "Where lessons land — top repos by firings",
          "general rows fire anywhere; project rows only in their origin")
    repo_counts = Counter(short_repo(f.get("repo")) for f in frs_dated if f.get("repo"))
    top = repo_counts.most_common(12)
    if top:
        names = [t[0] for t in top][::-1]
        vals = [t[1] for t in top][::-1]
        # split each repo's firings by reach of the row
        gen = []
        for name in names:
            g_ = sum(1 for f in frs_dated
                     if short_repo(f.get("repo")) == name
                     and tk.get(f["takeaway_id"], {}).get("reach") == "general")
            gen.append(g_)
        ax.barh(names, vals, color=PURPLE, alpha=0.5, label="project rows")
        ax.barh(names, gen, color=ACCENT, alpha=0.9, label="general rows")
        ax.set_xlabel("firings", color=MUTE, fontsize=9)
        ax.legend(facecolor=PANEL, edgecolor=GRID, labelcolor=FG, fontsize=8, loc="lower right")

    # ── 8. cross-repo reach of general rows ──
    ax = fig.add_subplot(gs[4, 2])
    style(ax, "Hub payoff", "# of distinct repos each general row reaches")
    gen_reach = [len(per_row[t["id"]]["repos"]) for t in active
                 if t.get("reach") == "general" and t["id"] in per_row]
    proj_reach = [len(per_row[t["id"]]["repos"]) for t in active
                  if t.get("reach") == "project" and t["id"] in per_row]
    if gen_reach:
        mx = max(gen_reach + proj_reach + [1])
        bins = np.arange(0.5, mx + 1.5, 1)
        ax.hist([gen_reach, proj_reach], bins=bins, color=[ACCENT, PURPLE],
                label=["general", "project"], alpha=0.85)
        ax.set_xlabel("# repos reached", color=MUTE, fontsize=8)
        ax.set_ylabel("rows", color=MUTE, fontsize=8)
        ax.legend(facecolor=PANEL, edgecolor=GRID, labelcolor=FG, fontsize=8,
                  loc="upper right")
        ax.text(0.96, 0.60, f"general rows reach\na median of "
                f"{int(np.median(gen_reach))} repos", transform=ax.transAxes,
                ha="right", va="top", color=ACCENT, fontsize=8.5, fontweight="bold")

    # ── 9. trigger-kind economics ──
    ax = fig.add_subplot(gs[4, 3])
    style(ax, "How rows reach a session", "firings by trigger kind")
    tkk = Counter(f.get("trigger_kind") or "(none)" for f in frs_dated)
    items = tkk.most_common()
    tcolors = {"on_demand": ACCENT, "session_start": TEAL, "edit_path": WARN,
               "recurrence": PURPLE, "resurrection": BAD}
    if items:
        labels_ = [i[0] for i in items]
        vals = [i[1] for i in items]
        ax.pie(vals, labels=labels_, colors=[tcolors.get(l, MUTE) for l in labels_],
               autopct=lambda p: f"{p:.0f}%" if p > 4 else "",
               textprops={"color": FG, "fontsize": 8.5},
               wedgeprops={"edgecolor": BG, "linewidth": 1.5})

    # ════ forward-looking band: readiness of the labeled-evidence substrate ════
    # ── 11. labeled-evidence volume funnel ──
    ax = fig.add_subplot(gs[5, 0])
    band_top = ax.get_position().y1
    fig.text(0.05, band_top + 0.030, "EVAL-SUBSTRATE READINESS", color=WARN,
             fontsize=14, fontweight="bold", va="bottom")
    fig.text(0.05, band_top + 0.020,
             "learned firing decisions train on labeled evidence — these panels "
             "track its volume and coverage",
             color=MUTE, fontsize=9.5, va="bottom")
    style(ax, "Labeled-evidence funnel", "distinct rows by depth of rated evidence")
    depth = Counter()
    for f in frs_dated:
        if f["_out"] and f["takeaway_id"] in tk:
            depth[f["takeaway_id"]] += 1
    ever = len({f["takeaway_id"] for f in frs_dated if f["takeaway_id"] in tk})
    ge1 = sum(1 for v in depth.values() if v >= 1)
    ge3 = sum(1 for v in depth.values() if v >= 3)
    ge5 = sum(1 for v in depth.values() if v >= 5)
    funnel = [("fired ≥1×", ever, MUTE), ("≥1 rating", ge1, ACCENT),
              ("≥3 ratings", ge3, GOOD), ("≥5 ratings", ge5, PURPLE)]
    ypos = range(len(funnel))[::-1]
    ax.barh(list(ypos), [f[1] for f in funnel], color=[f[2] for f in funnel],
            alpha=0.85, height=0.62)
    ax.set_yticks(list(ypos))
    ax.set_yticklabels([f[0] for f in funnel], fontsize=9)
    for y, (_, v, _) in zip(ypos, funnel):
        ax.text(v + ever * 0.02, y, str(v), va="center", color=FG,
                fontsize=9, fontweight="bold")
    ax.set_xlabel("rows", color=MUTE, fontsize=8)
    ax.set_xlim(0, ever * 1.18)
    ax.text(0.5, -0.30, f"≥3 ratings ({ge3} rows) = cold-start evidence threshold",
            transform=ax.transAxes, ha="center", color=GOOD, fontsize=8)

    # ── 12. noise lives in on_demand (the filter's target) ──
    ax = fig.add_subplot(gs[5, 1])
    style(ax, "Where the noise is", "rated firings by trigger kind; red = noise")
    tk_rate = defaultdict(lambda: {"h": 0, "x": 0})
    for f in frs_dated:
        if f["_out"]:
            tk_rate[f.get("trigger_kind") or "(none)"][
                "h" if f["_out"] == "helpful" else "x"] += 1
    order = sorted(tk_rate, key=lambda k: -(tk_rate[k]["h"] + tk_rate[k]["x"]))
    hvals = [tk_rate[k]["h"] for k in order]
    xvals = [tk_rate[k]["x"] for k in order]
    ax.bar(order, hvals, color=GOOD, alpha=0.8, label="helpful", width=0.6)
    ax.bar(order, xvals, bottom=hvals, color=BAD, alpha=0.85, label="noise", width=0.6)
    for i, k in enumerate(order):
        tot = tk_rate[k]["h"] + tk_rate[k]["x"]
        if tot:
            ax.text(i, tot + 1, f"{100*tk_rate[k]['x']/tot:.0f}% noise",
                    ha="center", color=BAD, fontsize=8)
    ax.set_ylabel("rated firings", color=MUTE, fontsize=8)
    ax.tick_params(axis="x", labelsize=8)
    ax.legend(facecolor=PANEL, edgecolor=GRID, labelcolor=FG, fontsize=8, loc="upper right")
    od_noise = tk_rate["on_demand"]["x"]
    tot_noise = sum(v["x"] for v in tk_rate.values())
    ax.text(0.5, -0.28, f"on_demand = {od_noise}/{tot_noise} of all noise — "
            f"the passive fire path\na learned noise filter targets",
            transform=ax.transAxes, ha="center", color=MUTE, fontsize=8)

    # ── 13. rating coverage by repo (the starved substrate) ──
    ax = fig.add_subplot(gs[5, 2:])
    style(ax, "Eval substrate coverage by repo",
          "the gate trains on ratings — % of each repo's firings that carry a label")
    repo_tot = Counter()
    repo_rat = Counter()
    for f in frs_dated:
        if f.get("repo"):
            r = short_repo(f["repo"])
            repo_tot[r] += 1
            if f["_out"]:
                repo_rat[r] += 1
    top_repos = [r for r, _ in repo_tot.most_common(10)][::-1]
    pct = [100 * repo_rat[r] / repo_tot[r] for r in top_repos]
    bars = ax.barh(top_repos, pct, color=[GOOD if p >= 15 else (WARN if p >= 5 else BAD)
                                          for p in pct], alpha=0.85)
    for r, p, b in zip(top_repos, pct, bars):
        ax.text(p + 0.4, b.get_y() + b.get_height() / 2,
                f"{p:.0f}%  ({repo_rat[r]}/{repo_tot[r]})", va="center",
                color=FG, fontsize=8)
    ax.set_xlabel("% of firings rated", color=MUTE, fontsize=9)
    ax.set_xlim(0, max(pct + [1]) * 1.25)
    ax.text(0.99, 0.04, "rating discipline lives in mine-session; "
            "host-repo coverage still thin", transform=ax.transAxes,
            ha="right", color=MUTE, fontsize=8)

    # ── 14. activity heatmap day-of-week × hour ──
    ax = fig.add_subplot(gs[6, :])
    style(ax, "When the store is busy", "firings by weekday × hour (UTC of fired_at)")
    grid = np.zeros((7, 24))
    for f in frs_dated:
        grid[f["_ts"].weekday(), f["_ts"].hour] += 1
    im = ax.imshow(grid, aspect="auto", cmap="magma",
                   extent=[0, 24, 6.5, -0.5])
    ax.set_yticks(range(7))
    ax.set_yticklabels(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"], fontsize=8)
    ax.set_xticks(range(0, 25, 3))
    ax.set_xlabel("hour of day", color=MUTE, fontsize=9)
    ax.grid(False)
    cb = fig.colorbar(im, ax=ax, fraction=0.025, pad=0.01)
    cb.ax.tick_params(colors=MUTE, labelsize=7)
    cb.outline.set_edgecolor(GRID)

    fig.text(0.05, 0.012,
             "monition_dashboard.py · stats computed in-process from raw rows",
             color=MUTE, fontsize=8)

    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, facecolor=BG, dpi=110, bbox_inches="tight")
    plt.close(fig)
    return out, dict(rows=len(tks), firings=total_fires, rated=len(rated),
                     precision=precision, gini=g, repos=len(repos))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--store", help="store dir (Dolt) or sqlite file")
    ap.add_argument("--out", default="~/.local/state/monition/dashboard.png",
                    help="output PNG path (default kept outside any repo working tree)")
    ap.add_argument("--days", type=int, help="limit to the last N days of firings")
    args = ap.parse_args()

    store = resolve_store(args.store)
    out, summary = render(store, Path(args.out).expanduser(), args.days)
    print(f"wrote {out}")
    print("  " + "  ".join(f"{k}={v:.0f}" if isinstance(v, float) else f"{k}={v}"
                           for k, v in summary.items()))


if __name__ == "__main__":
    main()
