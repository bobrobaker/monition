"""Relevance cascade (Phase 5): the learned head `L2'` and its evaluation harness.

The head is a logistic over L2-normalized prompt-row embedding products — a measured,
serialized artifact (contract `docs/contracts/relevance-cascade.md` §2). The runtime
(B03/B04) loads it to gate the passive `on_demand` fire path; the LLM is only an offline
label oracle, never on the hook path.
"""
