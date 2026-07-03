"""monition craft-reminder rules — fork-local overlay, merged over the managed
defaults by `key` (local wins; see craft_reminder.py). Restored from the pre-seam
customized body that `cms update` re-vendored today (old config recovered from
`git diff tools/craft_reminder.py` against the committed pre-update version)."""

RULES = [
    {"key": "decisions", "path": "docs/decisions/",
     "pointer": "Authoring a decision? Audit docs/decisions/ + road.md §2 for what "
                "this supersedes or contradicts; cite the contract section it affirms; "
                "mark any superseded doc Status: superseded-by …."},
    {"key": "docs", "path": "docs/",
     "pointer": "Editing governed material — contracts bind consumers: check "
                "docs/contracts/ and docs/road.md before changing docs/."},
]
