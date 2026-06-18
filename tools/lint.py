#!/usr/bin/env python3
"""monition pre-commit linter — tier 1 of the enforcement split.

ERROR blocks the commit; WARN advises. The ERROR/WARN assignment IS the split: a
check is ERROR only if a violation is unambiguously wrong; a loose mechanical shadow
of a semantic rule is always WARN (a high-precision backstop, never a substitute for
judgment). Each check's docstring names the governance rule it shadows — the linter
is indexed to the semantic layer, not a replacement for it.

Add project checks in the marked slot at the bottom. Anything computable from the
corpus (indexes, derived views) belongs here too: regenerate at commit time, never
hand-maintain.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC_DIRS = ["docs"]  # directories holding governed markdown
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")

errors = []
warnings = []


def error(path, msg):
    errors.append(f"ERROR  {os.path.relpath(path, ROOT)}: {msg}")


def warn(path, msg):
    warnings.append(f"WARN   {os.path.relpath(path, ROOT)}: {msg}")


def md_files():
    yield os.path.join(ROOT, "README.md")
    for d in DOC_DIRS:
        for dirpath, _, names in os.walk(os.path.join(ROOT, d)):
            for n in names:
                if n.endswith(".md"):
                    yield os.path.join(dirpath, n)


def check_relative_links(path, text):
    """Shadows: 'every pointer targets an existing file'. Mechanical → ERROR."""
    for m in LINK_RE.finditer(text):
        target = m.group(1).split("#")[0]
        if not target or "://" in target or target.startswith("mailto:"):
            continue
        resolved = os.path.normpath(os.path.join(os.path.dirname(path), target))
        if not os.path.exists(resolved):
            error(path, f"broken relative link: {m.group(1)}")


def check_opening_thesis(path, text):
    """Shadows: 'open with a one-sentence thesis'. Loose backstop → always WARN."""
    body = re.sub(r"^---\n.*?\n---\n", "", text, flags=re.S)  # skip frontmatter
    lines = [l for l in body.splitlines() if l.strip() and not l.startswith("#")]
    if lines and len(lines[0]) > 400:
        warn(path, "opening line is very long — is it still a one-sentence thesis?")


# ---- project checks go here ----------------------------------------------
# def check_<name>(path, text):
#     """Shadows: '<the governance rule this check backstops>'. <ERROR|WARN>."""
#     ...
# ---------------------------------------------------------------------------

CHECKS = [check_relative_links, check_opening_thesis]


def main():
    for path in md_files():
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            text = f.read()
        for check in CHECKS:
            check(path, text)

    for w in warnings:
        print(w)
    for e in errors:
        print(e)
    if errors:
        print(f"\n{len(errors)} error(s) — commit blocked. (Warnings are advisory.)")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
