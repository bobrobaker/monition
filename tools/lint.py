#!/usr/bin/env python3
"""monition pre-commit linter — a thin wrapper. Managed checks live in
tools/lint_skeleton.py and are re-vendored by `./bootstrap.sh --update`; do NOT edit
that file. Add THIS fork's checks below (they survive updates), then pass them to
run()."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lint_skeleton

# ---- this fork's checks (survive `--update`) ------------------------------
# def check_mine(path, text):
#     """Shadows: '<the governance rule this backstops>'. <ERROR|WARN>."""
#     lint_skeleton.error(path, "...")   # or lint_skeleton.warn(path, "...")
FORK_CHECKS = []
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    sys.exit(lint_skeleton.run(extra_checks=FORK_CHECKS))
