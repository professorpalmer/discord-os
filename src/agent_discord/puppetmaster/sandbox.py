"""OS sandbox for local agentic workers (macOS Seatbelt).

The gate hook decides which tool calls run. This module limits what a running
worker process can touch, whatever the gate decided: every child (the shell
tool, git, python) inherits the profile.

* Reads: everything, except the contents of host secret stores and of the
  Discord OS runtime (``.env``, the store, the key vault). The run's own gate
  folder and the Puppetmaster state folder are allowed back.
* Writes: only the job's checkout, temp, caches, the Puppetmaster state, and
  the run's gate folder. ``.git/hooks`` in the checkout stays read-only.
* Network: unchanged. The worker needs its model provider.

On by default where ``/usr/bin/sandbox-exec`` exists. ``DISCORD_OS_SANDBOX=0``
turns it off. ``DISCORD_OS_SANDBOX_DENY_READ`` adds paths (comma separated).
Other platforms run unsandboxed, and ``doctor`` says so.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Iterable, Mapping, Optional, Sequence

SANDBOX_ENV = "DISCORD_OS_SANDBOX"
SANDBOX_DENY_READ_ENV = "DISCORD_OS_SANDBOX_DENY_READ"
SANDBOX_EXEC = "/usr/bin/sandbox-exec"
_OFF = frozenset({"0", "off", "false", "no"})

# Relative to home. Credentials and shell files that often hold tokens.
HOME_SECRETS = (
    ".ssh",
    ".aws",
    ".gnupg",
    ".netrc",
    ".docker/config.json",
    ".kube",
    ".config/gh",
    ".config/gcloud",
    ".pypirc",
    ".npmrc",
    ".zshrc",
    ".zprofile",
    ".zshenv",
    ".bashrc",
    ".bash_profile",
    ".profile",
    "Library/Keychains",
    ".pmharness/state",
)
# Relative to home. Tool caches a worker may write.
HOME_CACHES = (
    ".cache",
    "Library/Caches",
    "Library/Application Support/puppetmaster",
    ".puppetmaster",
)


def sandbox_available() -> bool:
    return os.access(SANDBOX_EXEC, os.X_OK)


def sandbox_enabled(env: Optional[Mapping[str, str]] = None) -> bool:
    source = os.environ if env is None else env
    if str(source.get(SANDBOX_ENV) or "").strip().lower() in _OFF:
        return False
    return sandbox_available()


def _real(path: Path | str) -> str:
    return os.path.realpath(os.path.expanduser(str(path)))


def _quote(path: str) -> str:
    return '"' + path.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _subpaths(paths: Iterable[str]) -> str:
    return " ".join(f"(subpath {_quote(p)})" for p in sorted(set(paths)) if p)


def build_profile(
    *,
    write_roots: Sequence[Path | str],
    deny_read: Sequence[Path | str],
    allow_back: Sequence[Path | str] = (),
    read_only_within: Sequence[Path | str] = (),
) -> str:
    """Return an SBPL profile. In SBPL the last matching rule wins."""

    writes = [_real(p) for p in write_roots]
    denied = [_real(p) for p in deny_read]
    back = [_real(p) for p in allow_back]
    frozen = [_real(p) for p in read_only_within]
    lines = [
        "(version 1)",
        "(allow default)",
        "(deny file-write*)",
        f"(allow file-write* (subpath \"/dev\") {_subpaths(writes)})",
    ]
    if denied:
        # file-read-data, not file-read*: stat stays allowed, because SQLite
        # lstats every ancestor of a database path (PM state sits inside the
        # hidden workspace). Contents and listings stay denied.
        lines.append(f"(deny file-read-data file-write* {_subpaths(denied)})")
    if back:
        # Name file-read-data too: a rule that names the operation outranks a
        # file-read* wildcard, even a later one.
        lines.append(f"(allow file-read* file-read-data file-write* {_subpaths(back)})")
    if frozen:
        lines.append(f"(deny file-write* {_subpaths(frozen)})")
    return "\n".join(lines) + "\n"


def worker_profile(
    *,
    workdir: Path | str,
    child_env: Mapping[str, str],
    runtime_dirs: Sequence[Path | str] = (),
    home: Optional[Path] = None,
) -> str:
    """The profile for one local agentic worker."""

    base = home or Path.home()
    checkout = Path(workdir)
    writes: list[str] = [str(checkout), tempfile.gettempdir(), "/private/tmp", "/private/var/folders"]
    tmpdir = str(child_env.get("TMPDIR") or "").strip()
    if tmpdir:
        writes.append(tmpdir)
    writes.extend(str(base / rel) for rel in HOME_CACHES)
    back: list[str] = []
    for key in ("PUPPETMASTER_STATE_DIR", "DISCORD_OS_GATE_DIR"):
        value = str(child_env.get(key) or "").strip()
        if value:
            writes.append(value)
            back.append(value)
    denied = [str(base / rel) for rel in HOME_SECRETS]
    denied.extend(str(Path(p)) for p in runtime_dirs if str(p).strip())
    extra = str(child_env.get(SANDBOX_DENY_READ_ENV) or os.environ.get(SANDBOX_DENY_READ_ENV) or "")
    denied.extend(item.strip() for item in extra.split(",") if item.strip())
    frozen = [str(checkout / ".git" / "hooks")]
    return build_profile(
        write_roots=writes, deny_read=denied, allow_back=back, read_only_within=frozen
    )


def wrap_argv(argv: Sequence[str], profile: str) -> list[str]:
    return [SANDBOX_EXEC, "-p", profile, *argv]
