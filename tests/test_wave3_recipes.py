"""Wave 3: durable recipes exist and keep Catch-up honesty wording."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_recipes_index_lists_overnight_and_demo():
    text = (ROOT / "docs" / "recipes" / "README.md").read_text()
    assert "overnight-brief" in text
    assert "shared-desk-demo" in text
    assert "PARKED" in text


def test_overnight_brief_catch_up_honesty():
    text = (ROOT / "docs" / "co-work" / "overnight-brief.md").read_text()
    assert "skipped_while_disarmed" in text
    assert "schedule" in text.lower()


def test_shared_desk_demo_includes_handoff_and_brief():
    text = (ROOT / "docs" / "co-work" / "shared-desk-demo.md").read_text()
    assert "handoff" in text.lower()
    assert "overnight" in text.lower()
    assert "15" in text
