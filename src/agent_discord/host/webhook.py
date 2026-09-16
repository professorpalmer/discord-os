"""Optional ops alert side-channel via discord-webhook (HTTP only).

NOT primary JobPool UI — interactive cards stay on the bot.
Fail soft: never block gateway, cards, JobPool, or the host loop.

Install: ``pip install discord-os[webhook]``.
Disable: ``DISCORD_OS_WEBHOOK=0`` or empty ``DISCORD_OS_WEBHOOK_URL``.
URLs: ``DISCORD_OS_WEBHOOK_URL`` (comma-separated) or ``DISCORD_OS_WEBHOOK_URLS``.
"""

from __future__ import annotations

import os
import time
from typing import Any, Callable, Mapping, Optional, Sequence

from agent_discord import PRODUCT_NAME, __version__

ENV_WEBHOOK = "DISCORD_OS_WEBHOOK"
ENV_WEBHOOK_URL = "DISCORD_OS_WEBHOOK_URL"
ENV_WEBHOOK_URLS = "DISCORD_OS_WEBHOOK_URLS"

KIND_HOST_START = "host_start"
KIND_JOB_FAIL = "job_fail"
KIND_HALT = "halt"
KIND_RATE_LIMIT = "rate_limit"

_FALSEY = frozenset({"0", "false", "off", "no"})
_CONTENT_MAX = 1800
_RATE_LIMIT_WINDOW_S = 60.0
_TIMEOUT_S = 8.0

_HOST_START_SENT = False
_HALT_SENT = False
_RATE_LIMIT_AT = 0.0
_QUIET = False


ExecuteFn = Callable[[str, str], Any]


def webhook_flag_on(env: Optional[Mapping[str, str]] = None) -> bool:
    """``DISCORD_OS_WEBHOOK=0`` (or off/false/no) disables. Default on."""

    source = env if env is not None else os.environ
    raw = str(source.get(ENV_WEBHOOK) or "1").strip().lower()
    return raw not in _FALSEY


def webhook_urls(env: Optional[Mapping[str, str]] = None) -> tuple[str, ...]:
    """Parse webhook URL(s). Empty / unset → no destinations."""

    source = env if env is not None else os.environ
    chunks: list[str] = []
    for key in (ENV_WEBHOOK_URL, ENV_WEBHOOK_URLS):
        raw = str(source.get(key) or "").strip()
        if not raw:
            continue
        for part in raw.replace(";", ",").split(","):
            url = part.strip()
            if url:
                chunks.append(url)
    seen: set[str] = set()
    out: list[str] = []
    for url in chunks:
        if url in seen:
            continue
        seen.add(url)
        out.append(url)
    return tuple(out)


def webhook_enabled(env: Optional[Mapping[str, str]] = None) -> bool:
    """On only when the flag is not off **and** at least one URL is set."""

    return webhook_flag_on(env) and bool(webhook_urls(env))


def discord_webhook_available() -> bool:
    try:
        import discord_webhook  # noqa: F401

        return True
    except Exception:
        return False


def format_ops_alert(
    kind: str,
    *,
    detail: str = "",
    version: str = "",
) -> str:
    """Plain ops line. Brand is Discord OS / board + brain — never Graham."""

    label = {
        KIND_HOST_START: "host start",
        KIND_JOB_FAIL: "job fail",
        KIND_HALT: "halt",
        KIND_RATE_LIMIT: "rate-limit",
    }.get(kind, kind.replace("_", "-") or "ops")
    ver = (version or __version__).strip() or __version__
    head = f"{PRODUCT_NAME} {ver} · {label}"
    body = " ".join((detail or "").split())
    if not body:
        if kind == KIND_HOST_START:
            body = "tip / version kick"
        elif kind == KIND_HALT:
            body = "spend Halt · next JobPool admit not run"
        elif kind == KIND_RATE_LIMIT:
            body = "429"
    text = f"{head}\n{body}" if body else head
    if len(text) > _CONTENT_MAX:
        text = text[: _CONTENT_MAX - 1] + "…"
    return text


def _default_execute(url: str, content: str) -> Any:
    from discord_webhook import DiscordWebhook

    hook = DiscordWebhook(
        url=url,
        content=content,
        timeout=_TIMEOUT_S,
        username=PRODUCT_NAME,
        rate_limit_retry=False,
        allowed_mentions={"parse": []},
    )
    return hook.execute()


def _note_skip(exc: BaseException) -> None:
    global _QUIET
    if _QUIET:
        return
    _QUIET = True
    print(f"webhook skipped: {exc}", flush=True)


def emit_ops_alert(
    kind: str,
    *,
    detail: str = "",
    version: str = "",
    env: Optional[Mapping[str, str]] = None,
    execute: Optional[ExecuteFn] = None,
    urls: Optional[Sequence[str]] = None,
) -> bool:
    """Best-effort sync HTTP. Never raises to the host loop."""

    try:
        if not webhook_flag_on(env):
            return False
        dests = tuple(urls) if urls is not None else webhook_urls(env)
        if not dests:
            return False
        content = format_ops_alert(kind, detail=detail, version=version)
        sender = execute if execute is not None else _default_execute
        if execute is None and not discord_webhook_available():
            return False
        sent = False
        for url in dests:
            try:
                sender(url, content)
                sent = True
            except Exception as exc:
                _note_skip(exc)
        return sent
    except Exception as exc:
        _note_skip(exc)
        return False


def notify_host_start(
    *,
    channel_id: str = "",
    env: Optional[Mapping[str, str]] = None,
    execute: Optional[ExecuteFn] = None,
) -> bool:
    """Tip deploy / version kick / host start. Cheap, once per process."""

    global _HOST_START_SENT
    if _HOST_START_SENT:
        return False
    if not webhook_enabled(env) and execute is None:
        return False
    clip = f"channel={channel_id}" if channel_id else "tip / version kick"
    ok = emit_ops_alert(
        KIND_HOST_START,
        detail=clip,
        env=env,
        execute=execute,
    )
    _HOST_START_SENT = True
    return ok


def notify_job_fail(
    *,
    job_code: str = "",
    summary: str = "",
    error: str = "",
    run_id: str = "",
    env: Optional[Mapping[str, str]] = None,
    execute: Optional[ExecuteFn] = None,
) -> bool:
    bits = [bit for bit in (job_code, summary or error, run_id) if bit]
    detail = " · ".join(bits) if bits else "job failed"
    return emit_ops_alert(
        KIND_JOB_FAIL,
        detail=detail,
        env=env,
        execute=execute,
    )


def notify_halt(
    *,
    detail: str = "",
    env: Optional[Mapping[str, str]] = None,
    execute: Optional[ExecuteFn] = None,
) -> bool:
    """Halt-style failure (manual Halt or spend cap). Once until cleared."""

    global _HALT_SENT
    if _HALT_SENT:
        return False
    ok = emit_ops_alert(
        KIND_HALT,
        detail=detail,
        env=env,
        execute=execute,
    )
    _HALT_SENT = True
    return ok


def clear_halt_alert() -> None:
    global _HALT_SENT
    _HALT_SENT = False


def notify_rate_limit(
    *,
    detail: str = "",
    env: Optional[Mapping[str, str]] = None,
    execute: Optional[ExecuteFn] = None,
    now: Optional[float] = None,
    window_s: float = _RATE_LIMIT_WINDOW_S,
) -> bool:
    """Rate-limit storm hook. Debounced — a burst is one alert."""

    global _RATE_LIMIT_AT
    clock = time.monotonic if now is None else (lambda: float(now))
    stamp = float(clock())
    if _RATE_LIMIT_AT and (stamp - _RATE_LIMIT_AT) < float(window_s):
        return False
    ok = emit_ops_alert(
        KIND_RATE_LIMIT,
        detail=detail or "429",
        env=env,
        execute=execute,
    )
    _RATE_LIMIT_AT = stamp
    return ok


def reset_webhook_for_tests() -> None:
    global _HOST_START_SENT, _HALT_SENT, _RATE_LIMIT_AT, _QUIET
    _HOST_START_SENT = False
    _HALT_SENT = False
    _RATE_LIMIT_AT = 0.0
    _QUIET = False
