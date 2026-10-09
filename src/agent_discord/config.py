"""Configuration loading for local bootstrap (env + workspace files)."""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Mapping, Optional

DEFAULT_HOST_BOT_TOKEN_PATH = Path.home() / ".pmharness" / ".discord_token"

# Workspace resolution is deliberately CWD-independent: `discord-os ...` run from
# a git checkout used to create or open a second SQLite database next to the
# source. Documented in docs/host/README.md.
LIVE_WORKSPACE_RELPATH = ("discord-os", ".agent-discord")
FALLBACK_WORKSPACE_RELPATH = (".discord-os", "workspace")


def default_workspace(*, home: Optional[Path] = None) -> Path:
    """The workspace used when AGENT_DISCORD_WORKSPACE is unset.

    Prefer the documented live layout ``~/discord-os/.agent-discord`` when it
    already exists, else ``~/.discord-os/workspace``. Never the current
    directory.
    """

    root = Path(home) if home is not None else Path.home()
    live = root.joinpath(*LIVE_WORKSPACE_RELPATH)
    if live.is_dir():
        return live
    return root.joinpath(*FALLBACK_WORKSPACE_RELPATH)


def default_dotenv_path(workspace: Path) -> Path:
    """``.env`` sits beside the workspace, not in the current directory.

    The live layout is ``~/discord-os/.env`` next to ``~/discord-os/.agent-discord``.
    """

    return Path(workspace).expanduser().parent / ".env"


class ConfigError(ValueError):
    """Invalid or incomplete local configuration."""


@dataclass(frozen=True)
class AppConfig:
    workspace: Path
    discord_bot_token: str
    discord_mcp_provider: str  # rest
    puppetmaster_model: str
    puppetmaster_cli: str
    puppetmaster_cwd: Path
    database_path: Path
    # Backend selector: puppetmaster (default) | marionette (explicit opt-in)
    agent_backend: str = "puppetmaster"
    marionette_base_url: str = ""
    marionette_sessions_path: str = "/v1/sessions"
    marionette_jobs_path: str = "/v1/jobs"
    marionette_api_token: str = ""
    discord_max_object_bytes: int = 10_485_760
    compute: str = "auto"
    openrouter_env_fingerprint: str = ""
    host_actions: bool = True
    interactions: str = "off"
    discord_application_id: str = ""
    discord_public_key: str = ""
    interactions_host: str = "127.0.0.1"
    interactions_port: int = 8743

    @property
    def bot_token_fingerprint(self) -> str:
        token = self.discord_bot_token.strip()
        if not token:
            return "empty"
        # Stable, non-reversible-enough fingerprint for Gateway exclusivity keys.
        import hashlib

        return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]


def _parse_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        values[key] = value
    return values


def _resolve_workspace(
    explicit: Optional[Path],
    from_env: Optional[str],
) -> Path:
    if explicit is not None:
        return Path(explicit).expanduser().resolve()
    if (from_env or "").strip():
        return Path(str(from_env).strip()).expanduser().resolve()
    return default_workspace().resolve()


def load_config(
    *,
    env: Optional[Mapping[str, str]] = None,
    dotenv_path: Optional[Path] = None,
    workspace: Optional[Path] = None,
) -> AppConfig:
    """Load config from process env, optionally overlaying a .env file first."""
    source = dict(os.environ if env is None else env)
    if dotenv_path is None:
        # Locate .env from the workspace we can already name, so the file read
        # does not depend on where the command was run.
        dotenv_path = default_dotenv_path(
            _resolve_workspace(workspace, source.get("AGENT_DISCORD_WORKSPACE"))
        )
    merged: dict[str, str] = {}
    merged.update(_parse_dotenv(dotenv_path))
    merged.update({k: v for k, v in source.items() if v is not None})

    ws = _resolve_workspace(workspace, merged.get("AGENT_DISCORD_WORKSPACE"))

    provider = (merged.get("DISCORD_MCP_PROVIDER") or "rest").strip().lower()
    if provider != "rest":
        raise ConfigError(
            f"DISCORD_MCP_PROVIDER must be 'rest', got {provider!r} "
            "(the saseq and braindao MCP adapters were removed)"
        )

    model = (merged.get("PUPPETMASTER_MODEL") or "openrouter/auto").strip()
    db_path = ws / "agent_discord.sqlite3"
    cwd_raw = (merged.get("PUPPETMASTER_CWD") or "").strip()
    puppetmaster_cwd = Path(cwd_raw).expanduser().resolve() if cwd_raw else Path.cwd()

    backend = (merged.get("AGENT_DISCORD_BACKEND") or "puppetmaster").strip().lower()
    if backend not in {"puppetmaster", "marionette"}:
        raise ConfigError(
            f"AGENT_DISCORD_BACKEND must be 'puppetmaster' or 'marionette', got {backend!r}"
        )

    compute = (merged.get("AGENT_DISCORD_COMPUTE") or "auto").strip().lower()
    if compute not in {"auto", "agentic"}:
        raise ConfigError(
            f"AGENT_DISCORD_COMPUTE must be 'auto' or 'agentic', got {compute!r} "
            "(Cursor compute was removed; product compute is OpenRouter/agentic only)"
        )

    openrouter_env = (merged.get("OPENROUTER_API_KEY") or "").strip()
    openrouter_env_fingerprint = openrouter_env[-4:] if openrouter_env else ""

    raw_max = (merged.get("DISCORD_MAX_OBJECT_BYTES") or "").strip()
    if raw_max:
        try:
            max_object_bytes = int(raw_max)
        except ValueError as exc:
            raise ConfigError(
                f"DISCORD_MAX_OBJECT_BYTES must be an integer, got {raw_max!r}"
            ) from exc
        if max_object_bytes < 1:
            raise ConfigError("DISCORD_MAX_OBJECT_BYTES must be >= 1")
    else:
        max_object_bytes = 10_485_760

    interactions = (merged.get("AGENT_DISCORD_INTERACTIONS") or "off").strip().lower()
    if interactions not in {"off", "http", "gateway"}:
        raise ConfigError(
            "AGENT_DISCORD_INTERACTIONS must be 'off', 'http', or 'gateway', "
            f"got {interactions!r}"
        )
    host_actions_raw = (merged.get("AGENT_DISCORD_HOST_ACTIONS") or "on").strip().lower()
    if host_actions_raw not in {"on", "off", "1", "0", "true", "false"}:
        raise ConfigError(
            f"AGENT_DISCORD_HOST_ACTIONS must be on or off, got {host_actions_raw!r}"
        )
    host_actions = host_actions_raw in {"on", "1", "true"}
    raw_port = (merged.get("DISCORD_INTERACTIONS_PORT") or "").strip()
    if raw_port:
        try:
            interactions_port = int(raw_port)
        except ValueError as exc:
            raise ConfigError(
                f"DISCORD_INTERACTIONS_PORT must be an integer, got {raw_port!r}"
            ) from exc
        if interactions_port < 1 or interactions_port > 65535:
            raise ConfigError("DISCORD_INTERACTIONS_PORT must be 1..65535")
    else:
        interactions_port = 8743

    return AppConfig(
        workspace=ws,
        discord_bot_token=(merged.get("DISCORD_BOT_TOKEN") or "").strip(),
        discord_mcp_provider=provider,
        puppetmaster_model=model,
        puppetmaster_cli=(merged.get("PUPPETMASTER_CLI") or "puppetmaster").strip(),
        puppetmaster_cwd=puppetmaster_cwd,
        database_path=db_path,
        agent_backend=backend,
        marionette_base_url=(merged.get("MARIONETTE_BASE_URL") or "").strip(),
        marionette_sessions_path=(
            merged.get("MARIONETTE_SESSIONS_PATH") or "/v1/sessions"
        ).strip(),
        marionette_jobs_path=(merged.get("MARIONETTE_JOBS_PATH") or "/v1/jobs").strip(),
        marionette_api_token=(merged.get("MARIONETTE_API_TOKEN") or "").strip(),
        discord_max_object_bytes=max_object_bytes,
        compute=compute,
        openrouter_env_fingerprint=openrouter_env_fingerprint,
        host_actions=host_actions,
        interactions=interactions,
        discord_application_id=(merged.get("DISCORD_APPLICATION_ID") or "").strip(),
        discord_public_key=(merged.get("DISCORD_PUBLIC_KEY") or "").strip(),
        interactions_host=(merged.get("DISCORD_INTERACTIONS_HOST") or "127.0.0.1").strip()
        or "127.0.0.1",
        interactions_port=interactions_port,
    )


# Declared Puppetmaster range. Mirrors `dependencies` in pyproject.toml. The
# floor is the oldest release with everything the agentic backend calls:
# `steer` landed in v1.27.24; `cost --json` with token_usage / actual_cost and
# `--emit-job-id-early` are older (checked in the Puppetmaster repo history).
PUPPETMASTER_VERSION_FLOOR = (1, 27, 24)
PUPPETMASTER_VERSION_CEILING = (2,)
PUPPETMASTER_REQUIREMENT = "puppetmaster-ai>=1.27.24,<2"

_PM_VERSION_CACHE: dict[str, str] = {}


def resolve_puppetmaster_cli(configured: str = "puppetmaster") -> str:
    """The one resolver for the PM executable. Every call site routes here.

    Prefers the CLI next to this Python, because LaunchAgents often have a tiny
    PATH. That preference is why production once ran a stale 1.22.15, so the
    version is now reported (see :func:`puppetmaster_cli_version`) rather than
    the order being guessed at.
    """

    name = (configured or "puppetmaster").strip() or "puppetmaster"
    sibling = Path(sys.executable).resolve().parent / Path(name).name
    if sibling.is_file():
        return str(sibling)
    found = shutil.which(name)
    if found:
        return found
    return name


def puppetmaster_cli_found(configured: str = "puppetmaster") -> bool:
    """True when the resolved PM executable actually exists on this host."""

    resolved = resolve_puppetmaster_cli(configured)
    if os.sep in resolved:
        return Path(resolved).is_file()
    return shutil.which(resolved) is not None


def parse_puppetmaster_version(text: str) -> tuple[int, ...]:
    """First dotted numeric run in ``puppetmaster --version`` output."""

    import re

    match = re.search(r"(\d+(?:\.\d+)+)", text or "")
    if not match:
        return ()
    return tuple(int(part) for part in match.group(1).split("."))


def puppetmaster_cli_version(cli: str = "", *, refresh: bool = False) -> str:
    """Resolved PM version string, or "" when it cannot be read. Never raises."""

    import subprocess

    target = (cli or "").strip() or resolve_puppetmaster_cli()
    if not refresh and target in _PM_VERSION_CACHE:
        return _PM_VERSION_CACHE[target]
    version = ""
    try:
        proc = subprocess.run(
            [target, "--version"], capture_output=True, text=True, timeout=15
        )
        parts = parse_puppetmaster_version(f"{proc.stdout}\n{proc.stderr}")
        if parts:
            version = ".".join(str(part) for part in parts)
    except Exception:
        version = ""
    if not version:
        try:
            from importlib.metadata import version as dist_version

            version = dist_version("puppetmaster-ai")
        except Exception:
            version = ""
    _PM_VERSION_CACHE[target] = version
    return version


def puppetmaster_version_in_range(version: str) -> bool:
    """True when ``version`` satisfies PUPPETMASTER_REQUIREMENT.

    An unreadable version is not a violation — callers report it separately.
    """

    parts = parse_puppetmaster_version(version)
    if not parts:
        return True
    return PUPPETMASTER_VERSION_FLOOR <= parts < PUPPETMASTER_VERSION_CEILING


def read_host_bot_token(*, path: Optional[Path] = None) -> str:
    """Read a bot token from a 0600 host file. Never used as a default in tests."""

    target = Path(path) if path is not None else DEFAULT_HOST_BOT_TOKEN_PATH
    try:
        text = target.read_text(encoding="utf-8")
    except OSError:
        return ""
    if not text.strip():
        return ""
    return text.strip().splitlines()[0].strip()


def resolve_runtime_bot_token(config: AppConfig) -> str:
    if config.discord_bot_token.strip():
        return config.discord_bot_token.strip()
    return read_host_bot_token()


def discord_token_source(config: AppConfig, *, host_path: Optional[Path] = None) -> str:
    """Where the bot token was resolved from: env | host-file | empty. Never the token."""

    if config.discord_bot_token.strip():
        return "env"
    if read_host_bot_token(path=host_path):
        return "host-file"
    return "empty"


def apply_runtime_secrets(config: AppConfig) -> AppConfig:
    """Overlay host-file token when repo `.env` left DISCORD_BOT_TOKEN empty."""

    token = resolve_runtime_bot_token(config)
    if token == config.discord_bot_token:
        return config
    return replace(config, discord_bot_token=token)


def check_config(config: AppConfig, *, require_token: bool = True) -> list[str]:
    """Return human-readable problems; empty list means OK for local checks."""
    problems: list[str] = []
    if require_token and not config.discord_bot_token:
        problems.append("DISCORD_BOT_TOKEN is empty")
    if config.discord_mcp_provider != "rest":
        problems.append("invalid DISCORD_MCP_PROVIDER")
    if config.compute not in {"auto", "agentic"}:
        problems.append("invalid AGENT_DISCORD_COMPUTE")
    if config.interactions not in {"off", "http", "gateway"}:
        problems.append("invalid AGENT_DISCORD_INTERACTIONS")
    if config.interactions == "http":
        if not config.discord_application_id:
            problems.append("DISCORD_APPLICATION_ID is required when interactions=http")
        if not config.discord_public_key:
            problems.append("DISCORD_PUBLIC_KEY is required when interactions=http")
    if config.interactions == "gateway" and not config.discord_application_id:
        # Gateway mode needs no public key and no HTTPS URL — only the id that
        # slash registration POSTs against.
        problems.append("DISCORD_APPLICATION_ID is required when interactions=gateway")
    resolution = resolve_compute(config)
    if resolution.mode == "agentic" and not has_openrouter_key(config):
        problems.append(
            "no OpenRouter key; run discord-os connect"
        )
    # Product model comes from resolve_compute (openrouter/auto). Stray
    # PUPPETMASTER_MODEL values are ignored — never remapped to Cursor.
    if config.agent_backend not in {"puppetmaster", "marionette"}:
        problems.append("invalid AGENT_DISCORD_BACKEND")
    if config.agent_backend == "marionette" and not config.marionette_base_url:
        problems.append(
            "MARIONETTE_BASE_URL is required when AGENT_DISCORD_BACKEND=marionette "
            "(optional seam; default backend remains puppetmaster)"
        )
    return problems


@dataclass(frozen=True)
class ComputeResolution:
    mode: str
    requested: str
    model: str


def keys_dir(config: AppConfig) -> Path:
    return config.workspace / "keys"


def has_openrouter_key(config: AppConfig) -> bool:
    if config.openrouter_env_fingerprint:
        return True
    from agent_discord.keys.vault import KeyVault

    vault = KeyVault(keys_dir(config))
    return bool(vault.fingerprint("openrouter"))


def resolve_compute(config: AppConfig) -> ComputeResolution:
    """Resolve auto|agentic. auto means agentic when OpenRouter is present.

    Missing OpenRouter fails closed via check_config / runtime Deny — never Cursor.
    """

    from agent_discord.puppetmaster.models import AGENTIC_CANONICAL_MODEL

    requested = config.compute
    if requested not in {"auto", "agentic"}:
        raise ConfigError(
            f"AGENT_DISCORD_COMPUTE must be 'auto' or 'agentic', got {requested!r}"
        )
    return ComputeResolution(
        mode="agentic",
        requested=requested,
        model=AGENTIC_CANONICAL_MODEL,
    )
