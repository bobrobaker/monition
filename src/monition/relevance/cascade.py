"""Cascade runtime: the typed relevance-filter skeleton (B03).

Three stage kinds, in pipeline order (wired to the passive on_demand path in B04):

  Gate      — prompt-level, PRE-MATCH: one verdict skips matching entirely. This
              preserves the boilerplate decision's "prefix skip, not a
              candidate-level filter" position (2026-07-02 doc; named invariant in
              the workstream's amended gate invariant): a gated prompt costs no
              lexical/semantic work and creates no firing rows to mis-rate later.
  Transform — rewrites the MATCH INPUT: the matcher sees the transformed text;
              the original prompt is untouched everywhere else (stored firings,
              the user's context).
  Scorer    — pair-level: (context, candidates) → per-candidate
              (category, certainty), ABSTAIN first-class. Scorers run
              cheapest-first on the unsettled residual under a time budget
              (pre-emptive: a scorer that cannot be afforded is never started).

Standalone by design: this module imports `embed` and `head` only — never hooks,
never the store. Integration (B04) composes these stages inside `prompt_hook`.
"""
import re
import time

# The heavy dependencies (numpy via .head, the embedding stack via embed) are
# imported lazily inside the pieces that need them: hooks.py imports this module
# on the UserPromptSubmit hot path for the gate/transform residents alone, and a
# module-level numpy import would tax every hook invocation (B04).

RELEVANT = "relevant"
NOT_RELEVANT = "not_relevant"
ABSTAIN = "abstain"

# --- knobs -------------------------------------------------------------------
# UserPromptSubmit command hooks default to a 30s window — confirmed against the
# hooks doc 2026-07-03 (code.claude.com/docs/en/hooks.md: 30s for UserPromptSubmit
# vs 600s for other events; neither settings.json sets an explicit override).
HOOK_WINDOW_S = 30.0
BUDGET_FRACTION = 0.10          # scorers may spend at most 10% of the window
TIME_BUDGET_MS = BUDGET_FRACTION * HOOK_WINDOW_S * 1000
TARGET_CERTAINTY = 0.80         # stop scoring a candidate once this certain
FIRE_FLOOR = 0.60               # certainty a verdict needs to count at commit
# FALLBACK suppress threshold, for artifacts that predate the B05 operating
# point field. The live value ships INSIDE the head artifact
# (`operating_point.suppress_threshold` — chosen with the user 2026-07-03:
# 0.0139 → 23% noise blocked @ 10% helpful lost, LORO n=594); a retrain
# re-selects it there, never here.
OP_SUPPRESS_THRESHOLD = 0.0139


# --- stage kinds ---------------------------------------------------------------
class Gate:
    """Prompt-level pre-match stage: True = skip matching entirely."""
    name = "gate"

    def should_skip(self, prompt):
        raise NotImplementedError


class Transform:
    """Match-input rewrite: returns the text the matcher should see."""
    name = "transform"

    def apply(self, text):
        raise NotImplementedError


class Scorer:
    """Pair-level relevance estimator with a known cost.

    evaluate(context, candidates) -> {id: (category, certainty)}; candidates are
    matcher-shaped rows ({id, one_liner, trigger_spec, ...}). ABSTAIN when the
    scorer has no signal for a candidate."""
    name = "scorer"
    cost_estimate = 0.0  # ms — used ONLY for ordering + pre-emptive budgeting

    def evaluate(self, context, candidates):
        raise NotImplementedError


# --- residents -----------------------------------------------------------------
# Source of truth moved from hooks.py (B03). hooks.py keeps a duplicate until B04
# rewires it to import from here — tests/test_cascade.py asserts the two stay
# identical so the duplication cannot drift silently. Provenance and the
# add-only-with-evidence bar: docs/decisions/2026-07-02-boilerplate-prompt-gate.md.
BOILERPLATE_PREFIXES = (
    "<task-notification>",
)


class BoilerplateGate(Gate):
    """Harness-generated prompts (never typed by anyone) skip matching entirely.
    A prefix check, not a contains check: a human prompt that merely mentions a
    task-notification mid-text is real content and must still be matched."""
    name = "boilerplate_gate"

    def should_skip(self, prompt):
        return (prompt or "").startswith(BOILERPLATE_PREFIXES)


class SpanSanitizer(Transform):
    """Strip quoted machinery spans from the match input — text that *mentions*
    rows must not fire rows (the use/mention split, B06 discussion 2026-07-02).

    Deliberately line-shaped and conservative: it removes only the hook's own
    injected-context shapes and inline row/firing id markers, never free prose.
    """
    name = "span_sanitizer"

    # whole lines: injected headers, injected row lines, the cap notice
    _LINES = re.compile(
        r"^[ \t]*(?:"
        r"\[t\d+(?:/f\d+)?\].*"                       # "[t123/f4567] one-liner…"
        r"|Takeaways for this prompt \(full text:.*"  # prompt-hook header
        r"|Session-start takeaways \(full text:.*"    # session-brief header
        r"|\(\+\d+ more suppressed by cap.*"          # cap notice
        r")$",
        re.MULTILINE,
    )
    _INLINE_ID = re.compile(r"\[t\d+(?:/f\d+)?\]")
    _BLANK_RUN = re.compile(r"\n{3,}")

    def apply(self, text):
        out = self._LINES.sub("", text or "")
        out = self._INLINE_ID.sub("", out)
        return self._BLANK_RUN.sub("\n\n", out).strip()


def default_artifact_path():
    """Contract §2 candidate location: a versioned file near the managed weights
    cache (~/.cache/monition/relevance/head-v1.json), never the Dolt store."""
    import os

    from monition import embed
    return os.path.join(os.path.dirname(embed._weights_dir()),
                        "relevance", "head-v1.json")


def _memoized(embed_fn):
    """Per-call memo so build_features([context]*n, rows) embeds the repeated
    context once. Value-identical to the wrapped fn — parity is preserved."""
    if embed_fn is None:
        from monition import embed
        embed_fn = embed._embed_raw
    base = embed_fn
    cache = {}

    def fn(texts):
        missing = [t for t in texts if t not in cache]
        if missing:
            for t, v in zip(missing, base(missing)):
                cache[t] = v
        return [cache[t] for t in texts]

    return fn


class L2HeadScorer(Scorer):
    """The B06-accepted head (LORO 0.657, CI [0.598, 0.715]; user-ratified bar
    amendment 2026-07-03). Emits confident NOT_RELEVANT only below the suppress
    threshold — matching the accepted operating point's polarity — and a
    proportionate RELEVANT above it. Refuses an artifact trained on a different
    embedding model (contract §2 coupling; enforced in RelevanceHead.load)."""
    name = "L2_head"
    cost_estimate = 40.0  # ms: one prompt embed (memoized) + row embeds + numpy

    def __init__(self, artifact_path=None, embed_fn=None,
                 suppress_threshold=None):
        from .head import RelevanceHead
        self.head = RelevanceHead.load(artifact_path or default_artifact_path())
        self._embed_fn = embed_fn
        # resolution order: explicit arg → the artifact's own operating point
        # (B05: a property of the head version) → the module fallback constant
        if suppress_threshold is None:
            op = self.head.operating_point or {}
            suppress_threshold = op.get("suppress_threshold",
                                        OP_SUPPRESS_THRESHOLD)
        self.suppress_threshold = suppress_threshold
        # raw P(helpful) per candidate id from the LAST evaluate() call — the
        # scalar the score-logging contract (§3) records, which the
        # (category, certainty) belief tuple deliberately does not carry
        self.last_probs = {}

    def evaluate(self, context, candidates):
        from .head import build_features
        rowtexts = [
            f"{c.get('one_liner') or ''} {c.get('trigger_spec') or ''}".strip()
            for c in candidates
        ]
        feats = build_features([context or ""] * len(candidates), rowtexts,
                               embed_fn=_memoized(self._embed_fn))
        probs = self.head.predict_proba_raw(feats)
        self.last_probs = {c["id"]: float(p) for c, p in zip(candidates, probs)}
        out = {}
        for c, p in zip(candidates, probs):
            if p < self.suppress_threshold:
                out[c["id"]] = (NOT_RELEVANT, 0.95)
            else:
                # certainty grows with distance from the decision boundary,
                # capped below 1.0 — the head is marginal and must say so
                out[c["id"]] = (RELEVANT, min(0.9, 0.5 + abs(p - 0.5)))
        return out


# --- orchestrator ----------------------------------------------------------------
def combine(prev, new):
    """Belief update: a non-abstaining verdict wins iff at least as certain as the
    current one; ABSTAIN never lowers belief."""
    ncat, ncert = new
    if ncat == ABSTAIN:
        return prev
    return new if ncert >= prev[1] else prev


def run_scorers(context, candidates, scorers,
                target=TARGET_CERTAINTY, budget_ms=TIME_BUDGET_MS):
    """Cost-ordered, certainty-gated scoring. Returns belief + accounting; the
    fire/suppress decision is a separate commit policy (see below)."""
    scorers = sorted(scorers, key=lambda s: s.cost_estimate)
    belief = {c["id"]: (ABSTAIN, 0.0) for c in candidates}
    by_id = {c["id"]: c for c in candidates}
    spent = 0.0
    settled_by = {}
    trace = []
    for scorer in scorers:
        unsettled = [by_id[i] for i, b in belief.items() if b[1] < target]
        if not unsettled:
            trace.append(("stop:certainty-reached", scorer.name))
            break
        if spent + scorer.cost_estimate > budget_ms:
            trace.append(("stop:out-of-budget", scorer.name))
            break
        t = time.perf_counter()
        try:
            out = scorer.evaluate(context, unsettled)
        except Exception as e:
            # fail-open for availability: a broken scorer is an ABSTAIN, never a
            # crashed hook — but never a SILENT one: the error rides the trace
            # so the integration layer can log it (this module owns no logger).
            out = {}
            trace.append((f"error:{scorer.name}", repr(e)))
        spent += (time.perf_counter() - t) * 1000
        for i, verdict in out.items():
            before = belief[i]
            belief[i] = combine(before, verdict)
            if belief[i][1] >= target and before[1] < target:
                settled_by[i] = scorer.name
        trace.append((scorer.name, len(unsettled)))
    return {"belief": belief, "spent_ms": spent,
            "settled_by": settled_by, "trace": trace}


def commit_fail_closed(belief, floor=FIRE_FLOOR):
    """Fire only proven-relevant (the spike's policy). Right for a strong scorer;
    with the B06 marginal head it would suppress most unsettled candidates."""
    return {i for i, (cat, cert) in belief.items()
            if cat == RELEVANT and cert >= floor}


def commit_suppress_only(belief, floor=FIRE_FLOOR):
    """Fire everything except confident noise — the polarity of the B06-accepted
    operating point (suppress when P(helpful) < threshold). Default for B04;
    B05's measured rollout finalizes the choice."""
    return {i for i, (cat, cert) in belief.items()
            if not (cat == NOT_RELEVANT and cert >= floor)}


def cascade(prompt, candidates, gates=(), transforms=(), scorers=(),
            commit=commit_suppress_only, target=TARGET_CERTAINTY,
            budget_ms=TIME_BUDGET_MS):
    """Full pipeline convenience: gates → transforms → scorers → commit.
    Returns {skipped, gate, match_input, fired, belief, spent_ms, trace}."""
    for g in gates:
        if g.should_skip(prompt):
            return {"skipped": True, "gate": g.name, "match_input": None,
                    "fired": set(), "belief": {}, "spent_ms": 0.0, "trace": []}
    text = prompt
    for t in transforms:
        text = t.apply(text)
    scored = run_scorers(text, candidates, scorers,
                         target=target, budget_ms=budget_ms)
    return {"skipped": False, "gate": None, "match_input": text,
            "fired": commit(scored["belief"]), **scored}
