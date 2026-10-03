"""Ship copy says board + brain lakes. The old internal name stays out of product text."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_OLD_NAME = re.compile(r"graham", re.IGNORECASE)
_ALLOWED = re.compile(r"never\s+\"?graham", re.IGNORECASE)


def _product_text_files():
    yield from (ROOT / "src").rglob("*.py")
    for path in (ROOT / "docs").rglob("*.md"):
        if "co-work" not in path.parts:
            yield path
    for name in ("README.md", "README.pypi.md", "AGENTS.md"):
        yield ROOT / name


def test_old_internal_name_is_not_in_product_text():
    offenders = []
    for path in _product_text_files():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _OLD_NAME.search(line) and not _ALLOWED.search(line):
                offenders.append(f"{path.relative_to(ROOT)}:{number}")
    assert offenders == []
