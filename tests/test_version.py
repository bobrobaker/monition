"""`monition --version` and version-source parity.

The CMS bootstrap handshake probes `monition --version`, so the flag must
exist and the declared package version must not drift from the module's
VERSION constant (which stamps installed skills/docs).
"""
import os
import re

import pytest

from monition.cli import main
from monition.init_sync import VERSION


def test_version_flag_prints_and_exits_zero(capsys):
    with pytest.raises(SystemExit) as e:
        main(["--version"])
    assert e.value.code == 0
    out = capsys.readouterr().out
    assert re.match(r"^monition \d+\.\d+", out)


def test_pyproject_version_matches_module_version():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "pyproject.toml")) as f:
        m = re.search(r'(?m)^version = "([^"]+)"$', f.read())
    assert m, "no [project] version in pyproject.toml"
    assert m.group(1) == VERSION, (
        f"pyproject version {m.group(1)} != init_sync.VERSION {VERSION} — "
        "bump them together (bootstrap handshakes probe the installed version)")
