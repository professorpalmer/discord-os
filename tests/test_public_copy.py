"""Public copy: board + brain lakes brand on Wave 5 share paths."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

WAVE5_SHARE = [
    ROOT / "docs" / "co-work" / "wave5-board-brain-demo.md",
    ROOT / "docs" / "co-work" / "wave5-handoff-envelope.md",
    ROOT / "docs" / "co-work" / "handoff.md",
]

WAVE6_SHARE = [
    ROOT / "docs" / "co-work" / "wave6-board-brain-demo.md",
    ROOT / "docs" / "co-work" / "wave6-spend-meter.md",
]

FORBIDDEN_OVERCLAIM = (
    "graham",
    "companion-strip",
    "tailscale/ttyd/filebrowser as product",
    "multi-host durable objects",
    "fleet hard-cap",
)


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


def test_wave6_share_brand_and_no_overclaim():
    for path in WAVE6_SHARE:
        assert path.is_file(), path
        text = path.read_text().lower()
        # Allow explicit "never graham" / park callouts; forbid affirmative branding.
        if "graham" in text:
            assert "never graham" in text or "not graham" in text
        assert "companion-strip" not in text.replace(" ", "")
        if "tailscale" in text or "ttyd" in text or "filebrowser" in text:
            assert "no " in text or "park" in text or "not " in text
    demo = (ROOT / "docs" / "co-work" / "wave6-board-brain-demo.md").read_text().lower()
    assert "board + brain lakes" in demo or "board + brain" in demo
    assert "spend meter" in demo
    comparison = (ROOT / "docs" / "COMPARISON.md").read_text().lower()
    assert "wave 6" in comparison
    assert "goose" in comparison
    assert "ledger" in comparison or "spendguard" in comparison
    assert "cloud agent" in comparison
