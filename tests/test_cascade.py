"""B03 cascade runtime: typed stages, orchestrator control flow, residents."""
import json

import numpy as np
import pytest

from monition import embed, hooks
from monition.relevance import cascade as csc
from monition.relevance.head import RelevanceHead


# --- residents: gate ----------------------------------------------------------
def test_boilerplate_gate_skips_prefix_and_passes_humans():
    g = csc.BoilerplateGate()
    assert g.should_skip("<task-notification>\n<task-id>x</task-id>")
    assert not g.should_skip("why did the <task-notification> firing get rated?")
    assert not g.should_skip("ordinary question about dolt")
    assert not g.should_skip("")


def test_hooks_boilerplate_delegates_to_cascade():
    # B04 rewired hooks to the cascade's constant — the old duplicate is gone
    # and the hooks-side check behaves identically to the gate resident.
    assert not hasattr(hooks, "_BOILERPLATE_PREFIXES")
    for p in ("<task-notification>x", "real prompt", ""):
        assert hooks._is_boilerplate(p) == csc.BoilerplateGate().should_skip(p)


# --- residents: transform -------------------------------------------------------
INJECTED = """real question about the store schema
Takeaways for this prompt (full text: monition show <t-id>; rate: monition rate <f-id> helpful|noise):
[t215/f6237] Ablation over monition's replay runner? Test FACT propagation.
[t181/f6238] monition's WARN 'skill X locally edited' = vendored-stamp mismatch.
(+59 more suppressed by cap — monition query "..." shows all)
and here is my actual follow-up about t190's advice"""


def test_sanitizer_strips_injected_block_keeps_prose():
    out = csc.SpanSanitizer().apply(INJECTED)
    assert "real question about the store schema" in out
    assert "actual follow-up" in out
    assert "Ablation over" not in out          # injected row line gone
    assert "Takeaways for this prompt" not in out
    assert "suppressed by cap" not in out
    assert "[t215/f6237]" not in out


def test_sanitizer_strips_inline_ids_and_is_idempotent():
    s = csc.SpanSanitizer()
    once = s.apply("see [t12/f34] and [t99] for context")
    assert once == "see  and  for context".strip() or "[t" not in once
    assert s.apply(once) == once
    assert s.apply("") == ""


# --- orchestrator control flow ----------------------------------------------------
class FakeScorer(csc.Scorer):
    def __init__(self, name, cost, verdicts, calls=None):
        self.name, self.cost_estimate = name, cost
        self._verdicts = verdicts
        self.calls = calls if calls is not None else []

    def evaluate(self, context, candidates):
        self.calls.append([c["id"] for c in candidates])
        return {c["id"]: self._verdicts[c["id"]]
                for c in candidates if c["id"] in self._verdicts}


CANDS = [{"id": 1, "one_liner": "a", "trigger_spec": "x"},
         {"id": 2, "one_liner": "b", "trigger_spec": "y"}]


def test_orchestrator_stops_when_certainty_reached():
    cheap = FakeScorer("cheap", 1, {1: (csc.RELEVANT, 0.9), 2: (csc.NOT_RELEVANT, 0.9)})
    dear = FakeScorer("dear", 5, {})
    res = csc.run_scorers("ctx", CANDS, [dear, cheap])  # order by cost, not list order
    assert cheap.calls and not dear.calls
    assert ("stop:certainty-reached", "dear") in res["trace"]
    assert res["settled_by"] == {1: "cheap", 2: "cheap"}


def test_orchestrator_preemptive_budget_never_starts_unaffordable():
    cheap = FakeScorer("cheap", 1, {1: (csc.RELEVANT, 0.3)})
    huge = FakeScorer("huge", 10_000_000, {1: (csc.RELEVANT, 0.99)})
    res = csc.run_scorers("ctx", CANDS, [cheap, huge], budget_ms=100)
    assert not huge.calls
    assert ("stop:out-of-budget", "huge") in res["trace"]


def test_orchestrator_runs_only_on_unsettled_residual():
    first = FakeScorer("first", 1, {1: (csc.RELEVANT, 0.95)})
    second = FakeScorer("second", 2, {2: (csc.RELEVANT, 0.7)})
    csc.run_scorers("ctx", CANDS, [first, second])
    assert second.calls == [[2]]  # candidate 1 was settled, not re-scored


def test_scorer_exception_is_abstain_not_crash():
    class Boom(csc.Scorer):
        name, cost_estimate = "boom", 1

        def evaluate(self, context, candidates):
            raise RuntimeError("scorer died")

    res = csc.run_scorers("ctx", CANDS, [Boom()])
    assert res["belief"][1] == (csc.ABSTAIN, 0.0)
    # the swallowed error must still be observable (integration layer logs it)
    assert any(tag == "error:boom" for tag, _ in res["trace"])


def test_combine_abstain_never_lowers_and_certainty_wins():
    assert csc.combine((csc.RELEVANT, 0.8), (csc.ABSTAIN, 0.0)) == (csc.RELEVANT, 0.8)
    assert csc.combine((csc.RELEVANT, 0.8), (csc.NOT_RELEVANT, 0.9)) == (csc.NOT_RELEVANT, 0.9)
    assert csc.combine((csc.RELEVANT, 0.8), (csc.NOT_RELEVANT, 0.7)) == (csc.RELEVANT, 0.8)


# --- commit polarity -----------------------------------------------------------------
def test_commit_policies_differ_on_unsettled():
    belief = {1: (csc.RELEVANT, 0.9),     # proven relevant
              2: (csc.NOT_RELEVANT, 0.9),  # proven noise
              3: (csc.ABSTAIN, 0.0)}       # unsettled
    assert csc.commit_fail_closed(belief) == {1}
    assert csc.commit_suppress_only(belief) == {1, 3}  # unsettled still fires


# --- L2 head scorer ---------------------------------------------------------------
DIM = 4


def _artifact(tmp_path, model_name=None):
    head = RelevanceHead(weights=[1.0] * DIM, bias=0.0, mean=[0.0] * DIM,
                         std=[1.0] * DIM, l2=8.0,
                         model_name=model_name or embed.MODEL_NAME)
    path = tmp_path / "head.json"
    head.save(str(path))
    return str(path)


def _fake_embed(texts):
    # deterministic per-text vectors; "hot" texts point positive, others negative
    return [[1.0] * DIM if "hot" in t else [-1.0] * DIM for t in texts]


def test_l2_head_refuses_wrong_model_id(tmp_path):
    path = _artifact(tmp_path, model_name="some/other-model")
    with pytest.raises(ValueError, match="refusing to load"):
        csc.L2HeadScorer(artifact_path=path)


def test_l2_head_scores_through_shared_feature_path(tmp_path):
    scorer = csc.L2HeadScorer(artifact_path=_artifact(tmp_path),
                              embed_fn=_fake_embed, suppress_threshold=0.5)
    out = scorer.evaluate("hot prompt", [
        {"id": 1, "one_liner": "hot row", "trigger_spec": ""},   # aligned -> P high
        {"id": 2, "one_liner": "cold row", "trigger_spec": ""},  # opposed -> P low
    ])
    assert out[1][0] == csc.RELEVANT
    assert out[2] == (csc.NOT_RELEVANT, 0.95)


# --- full pipeline -------------------------------------------------------------------
def test_cascade_gate_short_circuits_everything():
    scorer = FakeScorer("s", 1, {1: (csc.RELEVANT, 0.9)})
    res = csc.cascade("<task-notification>...", CANDS,
                      gates=[csc.BoilerplateGate()],
                      transforms=[csc.SpanSanitizer()], scorers=[scorer])
    assert res["skipped"] and res["gate"] == "boilerplate_gate"
    assert res["fired"] == set() and not scorer.calls


def test_cascade_transform_feeds_scorers_not_original():
    seen = {}

    class Capture(csc.Scorer):
        name, cost_estimate = "cap", 1

        def evaluate(self, context, candidates):
            seen["ctx"] = context
            return {}

    res = csc.cascade(INJECTED, CANDS, transforms=[csc.SpanSanitizer()],
                      scorers=[Capture()])
    assert "[t215/f6237]" not in seen["ctx"]
    assert "real question" in seen["ctx"]
    assert res["match_input"] == seen["ctx"]
