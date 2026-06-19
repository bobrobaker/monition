"""EV vocabulary + audit functions against the fixture ground truth."""
import pytest

from monition.metrics import (audit, benefit_rate, cost_rate, keep,
                              spec_matches, trigger_precision)
from monition.store import Store


def test_benefit_rate_multiplies():
    assert benefit_rate(0.5, 0.2, 1000) == pytest.approx(100.0)
    assert benefit_rate(0.5, 0.2, 1000, detectability_mult=3,
                        reversibility_mult=2) == pytest.approx(600.0)


def test_fanout_multipliers_must_be_at_least_one():
    with pytest.raises(ValueError):
        benefit_rate(0.5, 0.2, 1000, detectability_mult=0.5)


def test_cost_rate_includes_false_fire_tax():
    assert cost_rate(2.0, 50) == 100.0
    assert cost_rate(2.0, 50, false_fire_tax=10) == 110.0


def test_keep_threshold():
    assert keep(101, 100) and not keep(100, 100)


def test_precision_excludes_unrated():
    assert trigger_precision(1, 1) == 0.5
    assert trigger_precision(0, 0) is None  # all-unrated: no signal, not zero


def test_spec_matches_reproduces_executor_semantics():
    # fnmatch '*' crosses '/': the contract's load-bearing divergence from shell
    assert spec_matches("payload/*", "payload/a/b")
    assert spec_matches("src/*, tools/*", "tools/y.py")  # comma-split + strip
    assert not spec_matches("src/*", "Src/x.py")  # case-sensitive on Linux


def test_audit_ground_truth(canonical_store):
    s = Store(canonical_store)
    audits = {a.takeaway_id: a for a in audit(s.takeaways(), s.firings())}

    assert audits[1].precision == 0.0
    assert "narrow trigger_spec or retire" in audits[1].recommendation
    assert audits[1].noise_contexts == ["docs/a.md", "docs/b.md"]

    assert audits[2].precision == 0.5
    assert audits[2].unrated == 1  # NULL outcome counted as coverage gap only
    assert "mixed ratings" in audits[2].recommendation

    assert audits[3].fires == 0
    assert "never fired" in audits[3].recommendation  # general reach doesn't silence it
    assert audits[3].reach == "general"

    assert audits[4].fires == 2 and audits[4].precision is None
    assert "never rated" in audits[4].recommendation

    assert audits[5].fires == 0 and audits[5].recommendation == ""  # retired: quiet

    assert audits[6].precision == 1.0 and audits[6].recommendation == ""
