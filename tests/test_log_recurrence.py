"""Tests for monition.store_write.log_recurrence — the active-row recurrence verb.

t7 (on_demand, active, 0 firings) is the intended use case: a low-firing
on_demand row whose mine-time "already covered" recurrence would otherwise
evaporate. Logging it lands a helpful-rated firing tagged 'recurrence' (distinct
from the suppressed-set 'resurrection' path), which the EV scorer then counts.
"""
import monition.score as sc
from monition.score import score
from monition.store_write import WriteStore


def test_log_recurrence_writes_helpful_recurrence_firing(store_copy):
    """One firing on the active row, tagged 'recurrence' and rated 'helpful',
    with no consent gate."""
    ws = WriteStore(store_copy)
    ws.log_recurrence(7, context="mine: covered by t7")
    rows = ws._sql("SELECT trigger_kind, outcome FROM firings WHERE takeaway_id = 7")
    assert len(rows) == 1
    assert rows[0]["trigger_kind"] == "recurrence"   # distinct from 'resurrection'
    assert rows[0]["outcome"] == "helpful"


def test_log_recurrence_counts_as_scorer_evidence(store_copy, monkeypatch):
    """t7 starts at 0 firings (cold-start). After a recurrence, score() consumes
    it as evidence — the whole point of the verb."""
    assert score(7, store_copy)["evidence_count"] == 0  # cold-start, no evidence
    WriteStore(store_copy).log_recurrence(7)
    monkeypatch.setattr(sc, "N_COLD_START", 1)
    result = score(7, store_copy)
    assert result["cold_start"] is False
    assert result["evidence_count"] == 1
    assert result["ev_score"] == 1.0
    assert result["decision"] == "fire"


def test_log_recurrence_tag_distinct_from_resurrection(store_copy):
    """The recurrence verb must not reuse the 'resurrection' tag — the two
    provenance stories stay separable for export-firings / tier-3 eval."""
    ws = WriteStore(store_copy)
    ws.log_recurrence(7)
    ws.log_helpful_equivalent(7)  # default trigger_kind='resurrection'
    kinds = sorted(r["trigger_kind"]
                   for r in ws._sql("SELECT trigger_kind FROM firings WHERE takeaway_id = 7"))
    assert kinds == ["recurrence", "resurrection"]
