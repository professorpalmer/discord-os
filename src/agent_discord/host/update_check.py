"""HOST Update-available pill — PyPI latest vs installed (fail soft, no auto-upgrade)."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional

from agent_discord import __version__

PYPI_JSON_URL = "https://pypi.org/pypi/discord-os/json"
DEFAULT_TIMEOUT_S = 2.5
_CACHE: dict[str, Any] = {"checked_at": 0.0, "result": None}
_CACHE_TTL_S = 3600.0


@dataclass(frozen=True)
class UpdateCheckResult:
    """Public, phone-safe update glance. Never includes credentials."""

    installed: str
    latest: str = ""
    update_available: bool = False
    checked: bool = False
    error: str = ""

    @property
    def pill(self) -> str:
        if not self.update_available:
            return ""
        latest = (self.latest or "").strip()
        if not latest:
            return "Update available"
        return f"Update available · {latest}"


def _parse_version(raw: str) -> tuple[int, ...]:
    text = (raw or "").strip().lstrip("vV")
    if not text:
        return ()
    parts: list[int] = []
    for bit in text.split("."):
        digits = ""
        for ch in bit:
            if ch.isdigit():
                digits += ch
            else:
                break
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def version_less(left: str, right: str) -> bool:
    """True when ``left`` is strictly older than ``right`` (numeric dotted)."""

    a = _parse_version(left)
    b = _parse_version(right)
    if not a or not b:
        return False
    # Pad for compare
    n = max(len(a), len(b))
    a = a + (0,) * (n - len(a))
    b = b + (0,) * (n - len(b))
    return a < b


def fetch_pypi_latest(
    *,
    url: str = PYPI_JSON_URL,
    timeout_seconds: float = DEFAULT_TIMEOUT_S,
    opener: Optional[Callable[..., Any]] = None,
) -> str:
    """Return PyPI ``info.version`` or \"\" on any failure (fail soft)."""

    open_fn = opener or urllib.request.urlopen
    try:
        req = urllib.request.Request(
            url,
            headers={"Accept": "application/json", "User-Agent": "discord-os-update-check"},
            method="GET",
        )
        with open_fn(req, timeout=float(timeout_seconds)) as resp:
            raw = resp.read()
        payload = json.loads(raw.decode("utf-8"))
        info = payload.get("info") if isinstance(payload, dict) else None
        if not isinstance(info, dict):
            return ""
        return str(info.get("version") or "").strip()
    except Exception:
        return ""


def check_update_available(
    *,
    installed: str = "",
    latest: str = "",
    fetch: bool = True,
    url: str = PYPI_JSON_URL,
    timeout_seconds: float = DEFAULT_TIMEOUT_S,
    opener: Optional[Callable[..., Any]] = None,
    env: Optional[Mapping[str, str]] = None,
    now: Optional[Callable[[], float]] = None,
    force: bool = False,
) -> UpdateCheckResult:
    """Compare installed package version to PyPI latest.

    Fail soft when PyPI is unreachable. Never auto-upgrades. Disable with
    ``DISCORD_OS_UPDATE_CHECK=0``.
    """

    import time

    source = dict(os.environ if env is None else env)
    raw = (source.get("DISCORD_OS_UPDATE_CHECK") or "1").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return UpdateCheckResult(installed=(installed or __version__), checked=False)

    current = (installed or __version__).strip()
    clock = now or time.monotonic
    if latest:
        newer = version_less(current, latest)
        return UpdateCheckResult(
            installed=current,
            latest=latest,
            update_available=newer,
            checked=True,
        )

    if not fetch:
        return UpdateCheckResult(installed=current, checked=False)

    cached = _CACHE.get("result")
    checked_at = float(_CACHE.get("checked_at") or 0.0)
    if (
        not force
        and isinstance(cached, UpdateCheckResult)
        and (clock() - checked_at) < _CACHE_TTL_S
        and cached.installed == current
    ):
        return cached

    remote = fetch_pypi_latest(
        url=url, timeout_seconds=timeout_seconds, opener=opener
    )
    if not remote:
        result = UpdateCheckResult(
            installed=current,
            checked=False,
            error="pypi unreachable",
        )
        _CACHE["checked_at"] = clock()
        _CACHE["result"] = result
        return result

    result = UpdateCheckResult(
        installed=current,
        latest=remote,
        update_available=version_less(current, remote),
        checked=True,
    )
    _CACHE["checked_at"] = clock()
    _CACHE["result"] = result
    return result


def update_available_pill(
    *,
    installed: str = "",
    latest: str = "",
    fetch: bool = True,
    **kwargs: Any,
) -> str:
    """Phone-visible HOST pill text, or \"\" when current / unchecked / disabled."""

    return check_update_available(
        installed=installed, latest=latest, fetch=fetch, **kwargs
    ).pill
