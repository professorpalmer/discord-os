"""Model pin / no silent fallback."""

from __future__ import annotations

import pytest

from agent_discord.contracts import ModelNotAllowedError, ModelPin
from agent_discord.puppetmaster.fake import FakePuppetmasterBackend
from agent_discord.puppetmaster.models import ADAPTER_NAME, CANONICAL_MODEL, DEFAULT_MODEL_PIN


def test_default_pin_constants():
    assert CANONICAL_MODEL == "openrouter/auto"
    assert ADAPTER_NAME == "openrouter/auto"
    assert DEFAULT_MODEL_PIN.allowlist == ("openrouter/auto",)
    assert DEFAULT_MODEL_PIN.adapter_name == "openrouter/auto"


def test_allowlist_rejects_other_models():
    pin = ModelPin()
    with pytest.raises(ModelNotAllowedError, match="no silent fallback"):
        pin.assert_allowed("openrouter/gpt-5")


def test_fake_backend_no_fallback():
    backend = FakePuppetmasterBackend()
    with pytest.raises(ModelNotAllowedError):
        backend.resolve_model("claude-sonnet")
    pin = backend.resolve_model("openrouter/auto")
    assert pin.canonical == "openrouter/auto"
    assert pin.adapter_name == "openrouter/auto"
