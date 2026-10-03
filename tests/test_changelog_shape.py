"""CHANGELOG shape: one Unreleased at the top, then strictly descending versions."""

from __future__ import annotations

import re
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parents[1] / "CHANGELOG.md"


def test_changelog_headers_are_descending_with_one_unreleased_on_top():
    heads = re.findall(r"^## (\S+)", CHANGELOG.read_text(encoding="utf-8"), re.M)
    if "Unreleased" in heads:
        assert heads.index("Unreleased") == 0
        assert heads.count("Unreleased") == 1
        heads = heads[1:]
    versions = [tuple(int(part) for part in head.split(".")) for head in heads]
    assert all(a > b for a, b in zip(versions, versions[1:]))
