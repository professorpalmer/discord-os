"""ARG_MAX-safe prompt handoff for puppetmaster agentic spawns.

Large prompts on argv can fail with opaque OS ``E2BIG`` / "Argument list too
long" (local agentic or Path A SSH). When the planned argv would exceed a
conservative budget, Discord OS writes the prompt to a temp file (or feeds it
on stdin) and re-enters ``puppetmaster.cli.main`` in-process via the
Puppetmaster interpreter so the huge body never crosses ``execve``.

Keys stay out of argv. If handoff is still impossible (no Puppetmaster
interpreter, etc.), callers speak a clear Deny instead of an opaque OS error.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

# Conservative default well under macOS/Linux ARG_MAX (~1MiB), leaving room for
# env (OPENROUTER_API_KEY, PYTHONPATH, gate stamps) and SSH wrappers.
_DEFAULT_SAFE_ARGV_BYTES = 128 * 1024

SPOKEN_ARG_MAX = (
    "Denied. Prompt is too large for the OS command line (ARG_MAX). "
    "Discord OS could not hand it off via file/stdin."
)

# In-process bridge: prompt path is argv[1]; remaining argv are agentic flags.
# Runs under Puppetmaster's own interpreter so import resolves. sys.argv is
# rebuilt in-memory (no second execve with the prompt).
AGENTIC_FILE_BRIDGE = (
    "import sys\n"
    "from pathlib import Path\n"
    "from puppetmaster.cli import main\n"
    "prompt = Path(sys.argv[1]).read_text(encoding='utf-8')\n"
    "sys.argv = ['puppetmaster', 'agentic', prompt, *sys.argv[2:]]\n"
    "raise SystemExit(main() or 0)\n"
)


def safe_argv_budget_bytes() -> int:
    """Return the conservative argv byte budget (overridable via env)."""

    raw = (os.environ.get("DISCORD_OS_ARGV_MAX") or "").strip()
    if raw.isdigit():
        return max(4096, int(raw))
    arg_max = 0
    try:
        arg_max = int(os.sysconf("SC_ARG_MAX"))
    except (AttributeError, OSError, ValueError):
        arg_max = 0
    if arg_max <= 0:
        arg_max = 1024 * 1024
    # Quarter of ARG_MAX, capped — env + ssh wrappers need headroom.
    return max(16 * 1024, min(_DEFAULT_SAFE_ARGV_BYTES, arg_max // 4))


def estimate_argv_bytes(parts: Sequence[str]) -> int:
    """Approximate bytes ``execve`` will charge for argv (args + NULs)."""

    total = 0
    for part in parts:
        total += len(str(part).encode("utf-8", errors="surrogateescape")) + 1
    return total


def needs_prompt_handoff(
    parts: Sequence[str], *, budget: Optional[int] = None
) -> bool:
    """True when argv would likely exceed the safe ARG_MAX budget."""

    limit = safe_argv_budget_bytes() if budget is None else max(4096, int(budget))
    return estimate_argv_bytes(parts) > limit


def spoken_arg_max_denied(*, detail: str = "") -> str:
    """User-facing Deny when oversized prompt cannot be handed off."""

    bit = (detail or "").strip()
    if bit:
        return f"{SPOKEN_ARG_MAX} ({bit[:120]})"
    return SPOKEN_ARG_MAX


def write_prompt_tempfile(prompt: str, *, directory: Optional[str] = None) -> Path:
    """Write prompt to a 0600 temp file; caller must unlink when done."""

    fd, name = tempfile.mkstemp(
        prefix="discord-os-prompt-",
        suffix=".txt",
        dir=directory or None,
        text=True,
    )
    path = Path(name)
    try:
        os.write(fd, prompt.encode("utf-8"))
    finally:
        os.close(fd)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def resolve_puppetmaster_python(cli: str = "puppetmaster") -> Optional[str]:
    """Return the interpreter backing the ``puppetmaster`` console script."""

    path = shutil.which(cli)
    if not path:
        return None
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    # pipx console_script: exec '/path/to/python' "$0" "$@" (triple-quote form)
    match = re.search(r"'{3}exec'\s+'([^']+)'", text)
    if match:
        candidate = match.group(1)
        if Path(candidate).exists():
            return candidate
    match = re.match(r"#!\s*(\S+)", text)
    if match:
        candidate = match.group(1)
        if "python" in Path(candidate).name.lower() and Path(candidate).exists():
            return candidate
    return None


@dataclass
class PromptHandoff:
    """Planned spawn for ``puppetmaster agentic`` with optional file/stdin body."""

    mode: str  # "argv" | "file" | "stdin"
    argv: list[str]
    prompt_file: Optional[Path] = None
    stdin_data: Optional[str] = None
    cleanup_paths: list[Path] = field(default_factory=list)

    def cleanup(self) -> None:
        for path in self.cleanup_paths:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass


def plan_local_agentic_handoff(
    *,
    cli: str,
    prompt: str,
    flags: Sequence[str],
    budget: Optional[int] = None,
) -> PromptHandoff:
    """Plan local agentic argv; spill prompt to a file when over budget.

    ``flags`` are everything after the prompt (``--provider``, ``--model``, …).
    Small prompts keep the historical ``[cli, agentic, prompt, *flags]`` shape.
    """

    base = [cli, "agentic", prompt, *[str(f) for f in flags]]
    if not needs_prompt_handoff(base, budget=budget):
        return PromptHandoff(mode="argv", argv=base)

    pm_py = resolve_puppetmaster_python(cli)
    if not pm_py:
        return PromptHandoff(mode="file", argv=[], prompt_file=None)

    prompt_path = write_prompt_tempfile(prompt)
    argv = [pm_py, "-c", AGENTIC_FILE_BRIDGE, str(prompt_path), *[str(f) for f in flags]]
    if needs_prompt_handoff(argv, budget=budget):
        prompt_path.unlink(missing_ok=True)
        return PromptHandoff(mode="file", argv=[], prompt_file=None)

    return PromptHandoff(
        mode="file",
        argv=argv,
        prompt_file=prompt_path,
        cleanup_paths=[prompt_path],
    )


def plan_ssh_agentic_handoff(
    *,
    cli: str,
    prompt: str,
    flags: Sequence[str],
    remote_cwd: str = "",
    budget: Optional[int] = None,
) -> PromptHandoff:
    """Plan Path A remote cook argv; spill prompt on SSH stdin when over budget.

    Small prompts: ``[cli, agentic, prompt, *flags]`` (optional ``--cwd``).
    Large prompts: short ``bash -lc`` that reads stdin into a temp file and
    re-enters ``puppetmaster.cli.main`` under the remote Puppetmaster
    interpreter. Prompt body travels on the SSH process stdin — never argv.
    """

    import shlex

    cwd = (remote_cwd or "").strip()
    flag_list = [str(f) for f in flags]
    if cwd:
        flag_list = list(flag_list) + ["--cwd", cwd]

    direct = [cli, "agentic", prompt, *flag_list]
    if not needs_prompt_handoff(direct, budget=budget):
        return PromptHandoff(mode="argv", argv=direct)

    quoted_cli = shlex.quote(cli)
    quoted_flags = " ".join(shlex.quote(f) for f in flag_list)
    # Resolve PM python on the remote with a tiny python one-liner (no prompt).
    resolve_py = (
        "import pathlib,re,sys; "
        "t=pathlib.Path(sys.argv[1]).read_text(errors='replace'); "
        "m=re.search(r\\\"'{3}exec'\\\\s+'([^']+)'\\\", t); "
        "print(m.group(1) if m else '')"
    )
    remote_script = f"""set -euo pipefail
PROMPT_FILE=$(mktemp)
trap 'rm -f "$PROMPT_FILE"' EXIT
cat > "$PROMPT_FILE"
PM_BIN=$(command -v {quoted_cli} || true)
if [ -z "$PM_BIN" ]; then
  echo "puppetmaster CLI not found: {cli}" >&2
  exit 127
fi
PM_PY=$(python3 -c "{resolve_py}" "$PM_BIN" 2>/dev/null || true)
if [ -z "$PM_PY" ] || [ ! -x "$PM_PY" ]; then
  PM_PY=$(head -1 "$PM_BIN" | sed -n 's/^#![[:space:]]*//p')
fi
if [ -z "$PM_PY" ] || [ ! -x "$PM_PY" ]; then
  PM_PY=python3
fi
exec "$PM_PY" -c {shlex.quote(AGENTIC_FILE_BRIDGE)} "$PROMPT_FILE" {quoted_flags}
"""
    argv = ["bash", "-lc", remote_script]
    return PromptHandoff(
        mode="stdin",
        argv=argv,
        stdin_data=prompt,
    )


def is_arg_max_oserror(exc: BaseException) -> bool:
    """True when ``exc`` looks like OS ARG_MAX / E2BIG."""

    import errno

    if isinstance(exc, OSError):
        if getattr(exc, "errno", None) == errno.E2BIG:
            return True
        msg = str(exc).lower()
        return "argument list too long" in msg or "e2big" in msg
    return False
