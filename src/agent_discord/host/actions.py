"""Open Terminal, files, or a browser.

Dest is the noun: ``host`` opens a GUI on the listen machine;
``remote`` stays in Discord so the tapping client (phone or desktop)
is the dest. Discord does not send client platform on INTERACTION_CREATE.
Presence client_status is not a dest. ``used_client`` is parsed if Discord
ever ships it, and never routes Terminal by itself.

Paths stay inside configured roots. Browser URLs are allowlisted.
The runner is injectable so tests never spawn a GUI.

Job button custom_ids are parsed here as intent only — they never
toggle host power or dispatch Puppetmaster.
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence
from urllib.parse import urlparse

from agent_discord.discord.layout import CUSTOM_ID_MAX


class HostActionError(ValueError):
    """Rejected host open (path escape, bad URL, unknown surface)."""


DEST_HOST = "host"
DEST_REMOTE = "remote"
DESTS = frozenset({DEST_HOST, DEST_REMOTE})
SURFACES = frozenset({"terminal", "files", "browser"})
OPEN_ID_PREFIX = "discord-os:open:"
JOB_ID_PREFIX = "discord-os:job:"
JOB_VERBS = frozenset({"approve", "cancel", "retry"})
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_DISCORD_HOSTS = frozenset({"discord.com", "canary.discord.com", "ptb.discord.com"})
_CLIENT_TO_DEST = {
    "mobile": DEST_REMOTE,
    "android": DEST_REMOTE,
    "ios": DEST_REMOTE,
    "desktop": DEST_HOST,
    "web": DEST_HOST,
}
_LEGACY_OPEN_IDS = {
    "discord-os:files": ("files", DEST_HOST),
    "discord-os:terminal": ("terminal", DEST_HOST),
    "discord-os:browser": ("browser", DEST_HOST),
}
_REMOTE_FILE_LIMIT = 24


@dataclass(frozen=True)
class HostActionResult:
    surface: str
    target: str
    argv: tuple[str, ...] = ()
    error: str = ""
    opened: bool = False
    dest: str = DEST_HOST
    listing: str = ""
    link_url: str = ""


@dataclass(frozen=True)
class OpenIntent:
    """One open: surface, target, dest. Dest is never inferred from presence."""

    surface: str
    target: str
    dest: str = DEST_HOST


CommandRunner = Callable[..., object]


@dataclass(frozen=True)
class JobAction:
    """Parsed job-button intent. Does not start or stop a Puppetmaster run."""

    action: str
    run_id: str


def job_custom_id(action: str, run_id: str) -> str:
    verb = (action or "").strip().lower()
    prefix = f"{JOB_ID_PREFIX}{verb}:"
    budget = max(0, CUSTOM_ID_MAX - len(prefix))
    return prefix + (run_id or "").strip()[:budget]


def job_action_from_custom_id(custom_id: str) -> Optional[JobAction]:
    raw = (custom_id or "").strip()
    if not raw.startswith(JOB_ID_PREFIX):
        return None
    rest = raw[len(JOB_ID_PREFIX) :]
    verb, sep, run_id = rest.partition(":")
    if not sep or verb not in JOB_VERBS:
        return None
    run_id = run_id.strip()
    if not run_id:
        return None
    return JobAction(action=verb, run_id=run_id)


def open_custom_id(surface: str, dest: str) -> str:
    kind = (surface or "").strip().lower()
    where = (dest or "").strip().lower()
    return f"{OPEN_ID_PREFIX}{kind}:{where}"[:CUSTOM_ID_MAX]


def open_intent_from_custom_id(custom_id: str) -> Optional[OpenIntent]:
    raw = (custom_id or "").strip()
    legacy = _LEGACY_OPEN_IDS.get(raw)
    if legacy is not None:
        surface, dest = legacy
        target = "" if surface == "browser" else "."
        return OpenIntent(surface=surface, target=target, dest=dest)
    if not raw.startswith(OPEN_ID_PREFIX):
        return None
    rest = raw[len(OPEN_ID_PREFIX) :]
    surface, sep, dest = rest.partition(":")
    if not sep or surface not in SURFACES or dest not in DESTS:
        return None
    target = "" if surface == "browser" else "."
    return OpenIntent(surface=surface, target=target, dest=dest)


def legal_dests(surface: str) -> frozenset[str]:
    kind = (surface or "").strip().lower()
    if kind == "terminal":
        return frozenset({DEST_HOST})
    if kind in SURFACES:
        return frozenset({DEST_HOST, DEST_REMOTE})
    return frozenset()


def default_dest(surface: str, target: str = "") -> str:
    if (surface or "").strip().lower() == "browser" and (target or "").strip():
        return DEST_REMOTE
    return DEST_HOST


def interaction_client_platform(payload: Mapping[str, Any]) -> str:
    """Client string if Discord ever puts one on INTERACTION_CREATE. Else empty."""

    for key in ("used_client", "client", "platform"):
        raw = payload.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip().lower()
    data = payload.get("data")
    if isinstance(data, Mapping):
        for key in ("used_client", "client", "platform"):
            raw = data.get(key)
            if isinstance(raw, str) and raw.strip():
                return raw.strip().lower()
    return ""


def dest_hint_from_interaction(payload: Mapping[str, Any]) -> str:
    """Label hint only. Never a dest router. Empty on today's Discord payloads."""

    return _CLIENT_TO_DEST.get(interaction_client_platform(payload), "")


def run_open_intent(
    intent: OpenIntent,
    *,
    roots: Sequence[Path],
    runner: Optional[CommandRunner] = None,
    browser_open: Optional[Callable[[str], object]] = None,
) -> HostActionResult:
    kind = (intent.surface or "").strip().lower()
    dest = (intent.dest or default_dest(kind, intent.target)).strip().lower()
    if kind not in SURFACES:
        raise HostActionError(f"unknown surface {intent.surface!r}")
    if dest not in DESTS:
        raise HostActionError(f"unknown dest {intent.dest!r}")
    if dest not in legal_dests(kind):
        raise HostActionError(f"{kind} dest is host")
    if dest == DEST_HOST:
        result = run_host_action(
            kind,
            intent.target,
            roots=roots,
            runner=runner,
            browser_open=browser_open,
        )
        return HostActionResult(
            surface=result.surface,
            target=result.target,
            argv=result.argv,
            error=result.error,
            opened=result.opened,
            dest=DEST_HOST,
        )
    if kind == "browser":
        url = allow_browser_url(intent.target)
        return HostActionResult(
            surface="browser",
            target=url,
            dest=DEST_REMOTE,
            link_url=url,
            opened=True,
        )
    listing = list_remote_files(intent.target, roots)
    return HostActionResult(
        surface="files",
        target=listing,
        dest=DEST_REMOTE,
        listing=listing,
        opened=True,
    )


def list_remote_files(
    raw: str,
    roots: Sequence[Path],
    *,
    limit: int = _REMOTE_FILE_LIMIT,
) -> str:
    path = confine_host_path(raw, roots)
    if path.is_file():
        return path.name
    if not path.is_dir():
        raise HostActionError("path is not a file or folder")
    shown: list[str] = []
    hidden = 0
    children = sorted(path.iterdir(), key=lambda item: item.name.lower())
    for child in children:
        if child.name.startswith("."):
            continue
        if len(shown) < max(1, int(limit)):
            suffix = "/" if child.is_dir() else ""
            shown.append(f"{child.name}{suffix}")
        else:
            hidden += 1
    body = "\n".join(shown) if shown else "(empty)"
    if hidden:
        body += f"\n+{hidden} more"
    return body


def run_host_action(
    surface: str,
    target: str,
    *,
    roots: Sequence[Path],
    runner: Optional[CommandRunner] = None,
    browser_open: Optional[Callable[[str], object]] = None,
) -> HostActionResult:
    kind = (surface or "").strip().lower()
    if kind not in SURFACES:
        raise HostActionError(f"unknown surface {surface!r}")
    if kind == "browser":
        url = (target or "").strip()
        if url:
            url = allow_browser_url(url)
        argv = host_browser_argv(url)
        label = url or host_browser_label(argv)
        if browser_open is not None:
            browser_open(label)
            return HostActionResult(
                surface="browser",
                target=label,
                argv=tuple(argv),
                opened=True,
            )
        do_run = runner or _default_runner
        do_run(argv, cwd=None)
        return HostActionResult(
            surface="browser",
            target=label,
            argv=tuple(argv),
            opened=True,
        )
    path = confine_host_path(target, roots)
    argv, cwd = _open_argv(kind, path)
    do_run = runner or _default_runner
    do_run(argv, cwd=str(cwd) if cwd is not None else None)
    return HostActionResult(
        surface=kind,
        target=str(path),
        argv=tuple(argv),
        opened=True,
    )


def confine_host_path(raw: str, roots: Sequence[Path]) -> Path:
    if not roots:
        raise HostActionError("no host roots configured")
    text = (raw or "").strip() or "."
    if text.startswith("~"):
        raise HostActionError("home-relative paths are not allowed")
    resolved_roots = [Path(root).expanduser().resolve() for root in roots]
    candidate = Path(text)
    if not candidate.is_absolute():
        candidate = (resolved_roots[0] / text).resolve()
    else:
        candidate = candidate.resolve()
    for root in resolved_roots:
        try:
            candidate.relative_to(root)
            return candidate
        except ValueError:
            continue
    raise HostActionError("path is outside host roots")


def host_browser_argv(url: str = "") -> list[str]:
    """Launch Chromium-family if present; otherwise the system default browser."""

    href = (url or "").strip()
    env_argv = _env_browser_argv(href)
    if env_argv:
        return env_argv
    found = _discover_chromium()
    if found is not None:
        return _launch_browser_argv(found, href)
    return _system_browser_argv(href)


def host_browser_label(argv: Optional[Sequence[str]] = None) -> str:
    command = list(argv) if argv is not None else host_browser_argv("")
    if len(command) >= 3 and command[0] == "open" and command[1] == "-a":
        return Path(command[2]).stem or "Browser"
    if command:
        name = Path(command[0]).stem.replace("-", " ").strip()
        if name and name.lower() not in {"open", "xdg-open", "cmd", "start"}:
            return name
    return "System browser"


def _env_browser_argv(url: str) -> Optional[list[str]]:
    raw = (
        os.environ.get("DISCORD_OS_BROWSER")
        or os.environ.get("AGENT_DISCORD_BROWSER")
        or ""
    ).strip()
    if not raw:
        return None
    looks_like_path = raw.startswith("/") or (len(raw) > 2 and raw[1] == ":" and raw[2] in {"\\", "/"})
    if looks_like_path:
        argv = [raw]
        if url:
            argv.append(url)
        return argv
    if sys.platform == "darwin":
        argv = ["open", "-a", raw]
        if url:
            argv.append(url)
        return argv
    which = shutil.which(raw)
    if which:
        argv = [which]
        if url:
            argv.append(url)
        return argv
    return None


def _discover_chromium() -> Optional[Path]:
    playwright = _playwright_chromium()
    if playwright is not None:
        return playwright
    if sys.platform == "darwin":
        for name in (
            "Google Chrome",
            "Chromium",
            "Google Chrome for Testing",
            "Brave Browser",
            "Microsoft Edge",
        ):
            for parent in (Path("/Applications"), Path.home() / "Applications"):
                app = parent / f"{name}.app"
                if app.is_dir():
                    return app
    for binary in ("google-chrome", "chromium", "chromium-browser", "chrome", "brave-browser"):
        found = shutil.which(binary)
        if found:
            return Path(found)
    return None


def _playwright_chromium() -> Optional[Path]:
    roots = (
        Path.home() / "Library" / "Caches" / "ms-playwright",
        Path.home() / ".cache" / "ms-playwright",
        Path.home() / "AppData" / "Local" / "ms-playwright",
    )
    patterns = (
        "chromium-*/chrome-mac*/Chromium.app",
        "chromium-*/chrome-mac*/Google Chrome for Testing.app",
        "chrome-*/chrome-mac*/Google Chrome for Testing.app",
        "chromium-*/chrome-linux/chrome",
        "chromium-*/chrome-win64/chrome.exe",
        "chromium-*/chrome-win/chrome.exe",
    )
    for root in roots:
        if not root.is_dir():
            continue
        for pattern in patterns:
            matches = sorted(root.glob(pattern))
            if matches:
                return matches[-1]
    return None


def _launch_browser_argv(app_or_bin: Path, url: str) -> list[str]:
    if sys.platform == "darwin" and app_or_bin.suffix == ".app":
        argv = ["open", "-a", str(app_or_bin)]
        if url:
            argv.append(url)
        return argv
    argv = [str(app_or_bin)]
    if url:
        argv.append(url)
    return argv


def _system_browser_argv(url: str) -> list[str]:
    if sys.platform == "darwin":
        if url:
            return ["open", url]
        return ["open", "-a", "Safari"]
    if sys.platform == "win32":
        return ["cmd", "/c", "start", "", url or "about:blank"]
    return ["xdg-open", url or "about:blank"]


def allow_browser_url(raw: str) -> str:
    url = (raw or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HostActionError("browser target must be an http(s) URL")
    host = parsed.hostname.lower()
    if host in _LOOPBACK_HOSTS:
        return url
    if parsed.scheme == "https" and host in _DISCORD_HOSTS:
        if parsed.path.startswith("/channels/"):
            return url
        raise HostActionError("Discord URLs must be channel jump links")
    raise HostActionError("browser URL is not on the host allowlist")


def _open_argv(surface: str, path: Path) -> tuple[list[str], Optional[Path]]:
    location = str(path)
    platform = sys.platform
    if surface == "files":
        if platform == "darwin":
            return ["open", location], None
        if platform == "win32":
            return ["explorer", location], None
        return ["xdg-open", location], None
    if platform == "darwin":
        return ["open", "-a", "Terminal"], path
    if platform == "win32":
        # Visible console is the point. Do not hide this window.
        return ["cmd", "/k"], path
    terminal = os.environ.get("AGENT_DISCORD_TERMINAL") or "x-terminal-emulator"
    return [terminal, "--working-directory", location], path


def _default_runner(argv: Sequence[str], *, cwd: Optional[str] = None) -> None:
    import subprocess

    kwargs: dict[str, object] = {"check": False}
    if cwd:
        kwargs["cwd"] = cwd
    subprocess.run(list(argv), **kwargs)
