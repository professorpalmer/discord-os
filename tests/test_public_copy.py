"""Public copy: board + brain lakes brand on Wave 5 share paths."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

WAVE5_SHARE = [
    ROOT / "docs" / "co-work" / "wave5-board-brain-demo.md",
    ROOT / "docs" / "co-work" / "wave5-handoff-envelope.md",
    ROOT / "docs" / "co-work" / "handoff.md",
]


def test_wave5_share_brand():
    for path in WAVE5_SHARE:
        assert path.is_file(), path
        text = path.read_text().lower()
        assert "graham" not in text
    demo = (ROOT / "docs" / "co-work" / "wave5-board-brain-demo.md").read_text().lower()
    assert "board + brain lakes" in demo
    assert "handoff" in demo
    readme = (ROOT / "README.md").read_text().lower()
    assert "board + brain lakes" in readme
    comparison = (ROOT / "docs" / "COMPARISON.md").read_text().lower()
    assert "wave 5" in comparison
    assert "handoff envelope" in comparison or "typed handoff" in comparison
