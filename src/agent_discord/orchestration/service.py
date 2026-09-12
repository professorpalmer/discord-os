"""Operator pairing, spend halt, and host cron — poverty steals, not a product suite."""

from __future__ import annotations

import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Mapping, Optional, Sequence

from agent_discord.contracts import UsageReceipt

HOST_PREFS_WORKSPACE = "_host"
SPEND_HALT_KEY = "spend_halt"
SPEND_CAP_KEY = "spend_cap_usd"
WRITE_GATE_KEY = "write_gate"
WRITE_SESSION_ALLOW_PREFIX = "write_session_allow:"
# Always-allow lasts this many seconds, or until HOST Off clears it.
WRITE_SESSION_ALLOW_TTL_SECONDS = 4 * 3600
TOOL_CLASS_ALLOW_PREFIX = "tool_class_allow:"
TOOL_CLASS_ALLOW_TTL_SECONDS = WRITE_SESSION_ALLOW_TTL_SECONDS
DEFAULT_APPROVAL_TIMEOUT_MINUTES = 20
MAX_APPROVAL_TIMEOUT_SECONDS = 24 * 3600
DENIED_WRITE_SPOKEN = "Denied. Write was not started."
EXPIRED_WRITE_SPOKEN = "Expired. Write was not started."
DEFAULT_SPEND_CAP_USD = 10.0
_INPUT_USD_PER_MTOK = 0.50
_OUTPUT_USD_PER_MTOK = 1.50
_EVERY_RE = re.compile(
    r"^(?P<n>\d+(?:\.\d+)?)(?P<unit>s|m|h|d|sec|secs|min|mins|hr|hrs|hour|hours|day|days)?$",
    re.IGNORECASE,
)
_SCHEDULE_RE = re.compile(
    r"^(?:/)?schedule\s+every\s+(\d+(?:\.\d+)?[a-z]*)\s*[:\-]?\s+(.+)$",
    re.IGNORECASE,
)



def _coerce_usd(raw: Any) -> Optional[float]:
    """Accept 0.04, "0.04", "$0.04". Reject junk."""

    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw).strip().replace(",", "")
    if text.startswith("$"):
        text = text[1:].strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def provider_cost_usd(usage: Optional[UsageReceipt]) -> Optional[float]:
    """OpenRouter / PM-adapter cost when present. None when usage omits cost.

    Honest spend: missing ``cost_usd`` is **unknown**, not ``$0``. Token
    estimates are separate (``spend_usd_from_usage``) and must not paint Halt
    / status digest as zero when the provider never reported cost.
    """

    if usage is None:
        return None
    meta = usage.metadata if isinstance(usage.metadata, Mapping) else {}
    found_key = False
    for key in ("cost", "total_cost", "cost_usd", "usd", "total_cost_usd"):
        if key not in meta:
            continue
        found_key = True
        raw = meta.get(key)
        if raw is None or raw == "":
            continue
        value = _coerce_usd(raw)
        if value is not None and value >= 0:
            return value
    if found_key:
        # Explicit null/empty cost keys → unknown
        return None
    return None


def spend_usd_from_usage(usage: Optional[UsageReceipt]) -> float:
    """Provider cost when known; else conservative token estimate for caps.

    Display paths should prefer ``format_spend`` / ``provider_cost_usd`` so
    omitted OpenRouter cost shows **unknown**, not ``$0``.
    """

    known = provider_cost_usd(usage)
    if known is not None:
        return known
    if usage is None:
        return 0.0
    inbound = _token_count(usage.input_tokens)
    outbound = _token_count(usage.output_tokens)
    if inbound is None and outbound is None:
        return 0.0
    return (
        (inbound or 0) * _INPUT_USD_PER_MTOK / 1_000_000.0
        + (outbound or 0) * _OUTPUT_USD_PER_MTOK / 1_000_000.0
    )


def format_usd(amount: float) -> str:
    value = max(0.0, float(amount))
    if value >= 0.01:
        return f"${value:.2f}"
    return f"${value:.4f}"


def format_spend(amount: Optional[float], *, known: bool = True) -> str:
    """Status digest / Halt display. Unknown when provider omitted cost."""

    if not known or amount is None:
        return "unknown"
    return format_usd(float(amount))


SPEND_COST_KNOWN_KEY = "spend_cost_known"


def mark_spend_cost_known(store: Any, known: bool = True) -> None:
    writer = getattr(store, "set_preference", None)
    if not callable(writer):
        return
    try:
        writer(HOST_PREFS_WORKSPACE, SPEND_COST_KNOWN_KEY, "1" if known else "0")
    except Exception:
        pass


def spend_cost_known(store: Any) -> bool:
    return _truthy(_host_pref(store, SPEND_COST_KNOWN_KEY))


def session_spend_usd(store: Any, workspace_id: str = "") -> float:
    reader = getattr(store, "session_spend_usd", None)
    if not callable(reader):
        return 0.0
    try:
        return float(reader(workspace_id) or 0.0)
    except Exception:
        return 0.0


def spend_cap_usd(store: Any) -> Optional[float]:
    raw = _host_pref(store, SPEND_CAP_KEY)
    if raw is None or str(raw).strip() == "":
        return DEFAULT_SPEND_CAP_USD
    try:
        return float(raw)
    except (TypeError, ValueError):
        return DEFAULT_SPEND_CAP_USD


def is_spend_halted(store: Any, workspace_id: str = "") -> bool:
    if _truthy(_host_pref(store, SPEND_HALT_KEY)):
        return True
    cap = spend_cap_usd(store)
    if cap is None:
        return False
    return session_spend_usd(store, workspace_id) >= cap


def set_spend_halted(store: Any, halted: bool) -> None:
    writer = getattr(store, "set_preference", None)
    if not callable(writer):
        return
    writer(HOST_PREFS_WORKSPACE, SPEND_HALT_KEY, "1" if halted else "0")


def toggle_spend_halted(store: Any) -> bool:
    next_halted = not _truthy(_host_pref(store, SPEND_HALT_KEY))
    set_spend_halted(store, next_halted)
    return next_halted


def writes_need_approval(store: Any) -> bool:
    return _truthy(_host_pref(store, WRITE_GATE_KEY))


def set_write_gate(store: Any, gated: bool) -> None:
    writer = getattr(store, "set_preference", None)
    if not callable(writer):
        return
    writer(HOST_PREFS_WORKSPACE, WRITE_GATE_KEY, "1" if gated else "0")


def toggle_write_gate(store: Any) -> bool:
    next_gated = not writes_need_approval(store)
    set_write_gate(store, next_gated)
    return next_gated


def seed_write_gate_from_env(store: Any, env: Optional[Mapping[str, str]] = None) -> None:
    raw = str((env or os.environ).get("DISCORD_OS_WRITE_GATE") or "").strip()
    if not raw:
        return
    set_write_gate(store, _truthy(raw))


def write_session_allow_key(scope_id: str) -> str:
    return f"{WRITE_SESSION_ALLOW_PREFIX}{(scope_id or '').strip()}"


def set_write_session_allow(
    store: Any,
    scope_id: str,
    *,
    ttl_seconds: int = WRITE_SESSION_ALLOW_TTL_SECONDS,
) -> None:
    """Allow gated writes for this channel/thread until TTL or HOST Off."""

    scope = (scope_id or "").strip()
    if not scope:
        return
    writer = getattr(store, "set_preference", None)
    if not callable(writer):
        return
    ttl = max(60, int(ttl_seconds or WRITE_SESSION_ALLOW_TTL_SECONDS))
    expires = int(time.time()) + ttl
    writer(HOST_PREFS_WORKSPACE, write_session_allow_key(scope), str(expires))


def write_session_allows_writes(store: Any, scope_id: str) -> bool:
    """True when Always-allow is still live for this channel or thread."""

    scope = (scope_id or "").strip()
    if not scope:
        return False
    raw = _host_pref(store, write_session_allow_key(scope))
    if raw is None:
        return False
    try:
        expires = int(str(raw).strip())
    except (TypeError, ValueError):
        return False
    if expires <= int(time.time()):
        clear_write_session_allow(store, scope)
        return False
    return True


def clear_write_session_allow(store: Any, scope_id: str) -> None:
    writer = getattr(store, "set_preference", None)
    if not callable(writer):
        return
    scope = (scope_id or "").strip()
    if not scope:
        return
    writer(HOST_PREFS_WORKSPACE, write_session_allow_key(scope), "0")


def clear_write_session_allows(store: Any) -> None:
    """Drop every Always-allow preference (HOST Off), including tool-class."""

    lister = getattr(store, "list_preferences", None)
    writer = getattr(store, "set_preference", None)
    if not callable(lister) or not callable(writer):
        return
    try:
        rows = list(lister(HOST_PREFS_WORKSPACE, kind="preference"))
    except TypeError:
        try:
            rows = list(lister(HOST_PREFS_WORKSPACE))
        except Exception:
            return
    except Exception:
        return
    for row in rows:
        if isinstance(row, dict):
            key = str(row.get("key") or "")
        elif isinstance(row, (tuple, list)) and row:
            key = str(row[0])
        else:
            key = str(getattr(row, "key", "") or "")
        if key.startswith(WRITE_SESSION_ALLOW_PREFIX) or key.startswith(
            TOOL_CLASS_ALLOW_PREFIX
        ):
            try:
                writer(HOST_PREFS_WORKSPACE, key, "0")
            except Exception:
                pass


def writes_need_approval_for(
    store: Any,
    *,
    channel_id: str = "",
    thread_id: str = "",
) -> bool:
    """Gate writes unless Always-allow covers this thread or channel."""

    if not writes_need_approval(store):
        return False
    if write_session_allows_writes(store, thread_id):
        return False
    if write_session_allows_writes(store, channel_id):
        return False
    return True


def tool_class_allow_key(tool_class: str, scope_id: str) -> str:
    klass = (tool_class or "").strip().lower()
    scope = (scope_id or "").strip()
    return f"{TOOL_CLASS_ALLOW_PREFIX}{klass}:{scope}"


def set_tool_class_session_allow(
    store: Any,
    tool_class: str,
    scope_id: str,
    *,
    ttl_seconds: int = TOOL_CLASS_ALLOW_TTL_SECONDS,
) -> None:
    """Always-allow one tool class for this channel/thread until TTL or HOST Off."""

    from agent_discord.orchestration.ask_gate import normalize_tool_class

    klass = normalize_tool_class(tool_class) or (tool_class or "").strip().lower()
    scope = (scope_id or "").strip()
    if not klass or not scope:
        return
    writer = getattr(store, "set_preference", None)
    if not callable(writer):
        return
    ttl = max(60, int(ttl_seconds or TOOL_CLASS_ALLOW_TTL_SECONDS))
    expires = int(time.time()) + ttl
    writer(HOST_PREFS_WORKSPACE, tool_class_allow_key(klass, scope), str(expires))


def tool_class_session_allows(store: Any, tool_class: str, scope_id: str) -> bool:
    """True when Always-allow for this tool class is still live on the scope."""

    from agent_discord.orchestration.ask_gate import normalize_tool_class

    klass = normalize_tool_class(tool_class) or (tool_class or "").strip().lower()
    scope = (scope_id or "").strip()
    if not klass or not scope:
        return False
    raw = _host_pref(store, tool_class_allow_key(klass, scope))
    if raw is None:
        return False
    try:
        expires = int(str(raw).strip())
    except (TypeError, ValueError):
        return False
    if expires <= int(time.time()):
        clear_tool_class_session_allow(store, klass, scope)
        return False
    return True


def clear_tool_class_session_allow(store: Any, tool_class: str, scope_id: str) -> None:
    writer = getattr(store, "set_preference", None)
    if not callable(writer):
        return
    klass = (tool_class or "").strip().lower()
    scope = (scope_id or "").strip()
    if not klass or not scope:
        return
    writer(HOST_PREFS_WORKSPACE, tool_class_allow_key(klass, scope), "0")


def approval_timeout_seconds(env: Optional[Mapping[str, str]] = None) -> int:
    """Parked write-gate auto-deny after this many seconds. 0 disables."""

    raw = str((env or os.environ).get("DISCORD_OS_APPROVAL_TIMEOUT_MINUTES") or "").strip()
    if not raw:
        return DEFAULT_APPROVAL_TIMEOUT_MINUTES * 60
    lowered = raw.lower()
    if lowered in {"0", "off", "never", "false", "no", "disabled"}:
        return 0
    try:
        minutes = float(raw)
    except ValueError:
        return DEFAULT_APPROVAL_TIMEOUT_MINUTES * 60
    if minutes <= 0:
        return 0
    seconds = int(minutes * 60)
    return min(max(seconds, 1), MAX_APPROVAL_TIMEOUT_SECONDS)


def inbound_queue_enabled(env: Optional[Mapping[str, str]] = None) -> bool:
    """Live-thread texts queue in SQLite. Default on. 0/off disables."""

    raw = str((env or os.environ).get("DISCORD_OS_INBOUND_QUEUE") or "").strip()
    if not raw:
        return True
    return raw.lower() not in {"0", "off", "false", "no", "disabled"}


def parked_at_ms_from_row(row: Mapping[str, Any]) -> Optional[int]:
    """Epoch ms when the write parked. None if unparsable (fail closed)."""

    raw_ms = row.get("parked_at_ms") if isinstance(row, Mapping) else None
    if raw_ms is not None and str(raw_ms).strip() != "":
        try:
            return int(raw_ms)
        except (TypeError, ValueError):
            return None
    created = str(row.get("created_at") or "") if isinstance(row, Mapping) else ""
    return _parse_sqlite_utc_ms(created)


def expire_parked_approvals(
    orchestrator: Any,
    *,
    now_ms: Optional[int] = None,
    env: Optional[Mapping[str, str]] = None,
) -> list[dict[str, Any]]:
    """Auto-deny parked write-gates / tool / ask gates older than the timeout."""

    timeout_s = approval_timeout_seconds(env)
    if timeout_s <= 0:
        return []
    store = getattr(orchestrator, "store", None)
    if store is None:
        return []
    lister = getattr(store, "list_parked_approvals", None)
    if not callable(lister):
        return []
    now = int(now_ms if now_ms is not None else time.time() * 1000)
    try:
        rows = list(lister())
    except Exception:
        return []
    expirer = getattr(orchestrator, "expire_parked_run", None)
    denier = getattr(orchestrator, "_deny_parked_run", None)
    expired: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        parked_ms = parked_at_ms_from_row(row)
        if parked_ms is None:
            pass  # fail closed: unparsable age expires
        elif now - parked_ms < timeout_s * 1000:
            continue
        run_id = str(row.get("run_id") or "").strip()
        if not run_id:
            continue
        result = None
        try:
            if callable(expirer):
                result = expirer(run_id)
            elif callable(denier):
                result = denier(run_id, spoken=EXPIRED_WRITE_SPOKEN)
        except Exception:
            continue
        if isinstance(result, dict):
            expired.append(result)
    return expired


def _parse_sqlite_utc_ms(raw: str) -> Optional[int]:
    text = (raw or "").strip().replace("Z", "")
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
        try:
            dt = datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
            return int(dt.timestamp() * 1000)
        except ValueError:
            continue
    return None


def set_spend_cap_usd(store: Any, cap: float) -> None:
    writer = getattr(store, "set_preference", None)
    if not callable(writer):
        return
    writer(HOST_PREFS_WORKSPACE, SPEND_CAP_KEY, f"{float(cap):.4f}")


def seed_spend_cap_from_env(store: Any, env: Optional[Mapping[str, str]] = None) -> None:
    raw = str((env or os.environ).get("DISCORD_OS_SPEND_CAP_USD") or "").strip()
    if not raw:
        return
    try:
        set_spend_cap_usd(store, float(raw))
    except (TypeError, ValueError):
        return


REQUIRE_OPERATORS_ENV = "DISCORD_OS_REQUIRE_OPERATORS"
# Alias aligned with peer fail-closed allowlists (gjc-remote REQUIRE_ALLOWLIST).
REQUIRE_ALLOWLIST_ENV = "DISCORD_OS_REQUIRE_ALLOWLIST"


def require_operators(env: Optional[Mapping[str, str]] = None) -> bool:
    """True when operator allowlist must be non-empty before dispatch.

    Default off keeps single-user Mac UX (first armed human may seed owner).
    Set ``DISCORD_OS_REQUIRE_OPERATORS=1`` (or ``DISCORD_OS_REQUIRE_ALLOWLIST=1``)
    to refuse silent first-armed-human seed until Pair / ``discord-os pair`` /
    ``DISCORD_OWNER_ID`` has paired an owner.
    """

    source = env if env is not None else os.environ
    if _truthy(str(source.get(REQUIRE_OPERATORS_ENV) or "")):
        return True
    if _truthy(str(source.get(REQUIRE_ALLOWLIST_ENV) or "")):
        return True
    return False


def author_is_operator(
    store: Any,
    user_id: Optional[str],
    *,
    role_ids: Optional[Sequence[str]] = None,
) -> bool:
    uid = str(user_id or "").strip()
    if not uid:
        return False
    checker = getattr(store, "is_operator", None)
    if callable(checker):
        try:
            return bool(checker(uid, role_ids=role_ids))
        except Exception:
            return False
    return False


def operators_configured(store: Any) -> bool:
    lister = getattr(store, "list_operators", None)
    if not callable(lister):
        return False
    try:
        return bool(list(lister()))
    except Exception:
        return False


def seed_owner_if_empty(
    store: Any,
    user_id: Optional[str],
    *,
    intentional: bool = False,
    env: Optional[Mapping[str, str]] = None,
) -> bool:
    """Seed first owner when the operators table is empty.

    When ``require_operators`` is on, only *intentional* bootstrap paths may
    seed (Pair button, explicit CLI). Silent first-armed-human / On / dispatch
    seed is refused.
    """

    if require_operators(env) and not intentional:
        return False
    seeder = getattr(store, "seed_owner_if_empty", None)
    if not callable(seeder):
        return False
    try:
        return bool(seeder(user_id))
    except Exception:
        return False


def author_may_dispatch(
    store: Any,
    user_id: Optional[str],
    *,
    role_ids: Optional[Sequence[str]] = None,
    env: Optional[Mapping[str, str]] = None,
) -> bool:
    """Fail closed after an owner exists.

    Default: first armed human may become owner. With
    ``DISCORD_OS_REQUIRE_OPERATORS=1``, refuse dispatch until an operator is
    paired — no silent first-armed-human seed.
    """

    uid = str(user_id or "").strip()
    if not uid:
        return False
    if not operators_configured(store):
        if require_operators(env):
            return False
        return seed_owner_if_empty(store, uid, env=env)
    return author_is_operator(store, uid, role_ids=role_ids)


def author_may_operate(
    store: Any,
    user_id: Optional[str],
    action: str = "",
    *,
    role_ids: Optional[Sequence[str]] = None,
    env: Optional[Mapping[str, str]] = None,
) -> bool:
    _ = action
    if not operators_configured(store):
        # Empty allowlist: open panel until first pair, unless require is on.
        return not require_operators(env)
    uid = str(user_id or "").strip()
    if not uid:
        return False
    return author_is_operator(store, uid, role_ids=role_ids)


def parse_every_seconds(raw: str) -> int:
    text = (raw or "").strip().lower()
    match = _EVERY_RE.match(text)
    if not match:
        raise ValueError(f"unrecognized interval {raw!r}")
    amount = float(match.group("n"))
    unit = (match.group("unit") or "s").lower()
    if unit in {"s", "sec", "secs"}:
        seconds = amount
    elif unit in {"m", "min", "mins"}:
        seconds = amount * 60
    elif unit in {"h", "hr", "hrs", "hour", "hours"}:
        seconds = amount * 3600
    else:
        seconds = amount * 86400
    whole = int(seconds)
    if whole < 60:
        raise ValueError("interval must be at least 60 seconds")
    return whole


def parse_schedule_command(text: str) -> Optional[tuple[int, str]]:
    raw = (text or "").strip()
    match = _SCHEDULE_RE.match(raw)
    if not match:
        return None
    try:
        every_s = parse_every_seconds(match.group(1))
    except ValueError:
        return None
    prompt = match.group(2).strip()
    if not prompt:
        return None
    return every_s, prompt


def _host_pref(store: Any, key: str) -> Optional[str]:
    reader = getattr(store, "get_preference", None)
    if not callable(reader):
        return None
    try:
        value = reader(HOST_PREFS_WORKSPACE, key)
    except Exception:
        return None
    return None if value is None else str(value)


def _token_count(raw: Any) -> Optional[int]:
    if raw is None:
        return None
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return None


def _truthy(raw: Optional[str]) -> bool:
    return str(raw or "").strip().lower() in {"1", "true", "yes", "on", "halted"}
