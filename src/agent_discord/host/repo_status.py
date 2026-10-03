"""Deterministic repo status. No model, no cook, no OpenRouter spend.

Eighteen of the forty-one real asks were "any open PRs/issues on X?". That
answer is a ``gh`` call and a ``git`` call, so it should never buy a worker.
``is_repo_status_ask`` is deliberately narrow: a general ask about a repo
still cooks. GitHub auth stays in ``host.github``; check rollup parsing stays
in ``orchestration.github_wake``.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

from agent_discord.host.github import (
    GITHUB_AUTHED,
    GITHUB_MISSING_BIN,
    gh_auth_state,
    github_host_env,
    github_status_card,
)
from agent_discord.host.repos import which_on_host

PR_LIMIT = 10
ISSUE_LIMIT = 20
NEWEST_ISSUES = 3

CHECKS_GREEN = "green"
CHECKS_RED = "red"
CHECKS_PENDING = "pending"
CHECKS_NONE = "none"
CI_UNKNOWN = "unknown"

_FAIL_CONCLUSIONS = frozenset({"failure", "cancelled", "timed_out", "action_required"})
_PENDING_STATUSES = frozenset({"queued", "in_progress", "pending", "waiting", "requested"})

# An ask that names work is a cook, however much it also says "status".
_ACTION_VERBS = re.compile(
    r"\b(fix|implement|build|add|write|refactor|rewrite|create|make|change|"
    r"update|rename|remove|delete|drop|bump|ship|tag|release|merge|revert|"
    r"draft|design|plan|debug|investigate|migrate|port|clean|polish|style)\b"
)
# "open a PR" is a request to create one, not to count them.
_CREATE_SHAPE = re.compile(r"\b(open|file|raise|cut)\s+(a|an|another|new)\b")
_SUBJECT = re.compile(r"\b(prs?|pull requests?|issues?)\b")
_STATUS_INTENT = re.compile(
    r"\b(open|any|list|show|status|outstanding|pending|how many|what)\b"
)
_STATUS_OF = re.compile(r"\b(repo|repository)\s+status\b|\bstatus\s+(of|on|for)\b")
_TITLE_CLIP = 68


@dataclass(frozen=True)
class PullRow:
    number: int
    title: str
    author: str = ""
    checks: str = CHECKS_NONE


@dataclass(frozen=True)
class IssueRow:
    number: int
    title: str


@dataclass(frozen=True)
class RepoStatus:
    """One checkout, answered from git and gh. Unknown stays unknown."""

    name: str
    path: str = ""
    slug: str = ""
    gh_state: str = GITHUB_AUTHED
    branch: str = ""
    tracking: str = ""
    ahead: int = 0
    behind: int = 0
    last_commit: str = ""
    default_branch: str = ""
    default_ci: str = CI_UNKNOWN
    default_ci_label: str = ""
    open_prs: tuple[PullRow, ...] = ()
    open_issue_count: int = 0
    newest_issues: tuple[IssueRow, ...] = ()


def is_repo_status_ask(text: str) -> bool:
    """True only for "what is the state of this repo" shaped asks.

    Any verb that asks for work wins, so "fix the status bar" and "fix CI on
    marionette" are cooks, not cards.
    """

    hay = " ".join((text or "").strip().lower().split())
    if not hay:
        return False
    if _ACTION_VERBS.search(hay) or _CREATE_SHAPE.search(hay):
        return False
    if _SUBJECT.search(hay) and _STATUS_INTENT.search(hay):
        return True
    return bool(_STATUS_OF.search(hay))


def collect_repo_status(
    path: Path | str,
    *,
    name: str = "",
    slug: str = "",
    runner: Optional[Callable[..., Any]] = None,
    env: Optional[Mapping[str, str]] = None,
    gh_bin: str = "",
    git_bin: str = "",
    timeout_s: float = 30.0,
) -> RepoStatus:
    """git facts always; gh facts when the CLI is installed and signed in."""

    root = Path(path).expanduser()
    child = github_host_env(env=env)
    run = runner or subprocess.run
    git = git_bin or which_on_host("git", env=child) or "git"
    label = (name or root.name or "repo").strip()

    branch = _git(run, git, root, child, timeout_s, "rev-parse", "--abbrev-ref", "HEAD")
    tracking = _git(
        run,
        git,
        root,
        child,
        timeout_s,
        "rev-parse",
        "--abbrev-ref",
        "--symbolic-full-name",
        "@{upstream}",
    )
    behind, ahead = _ahead_behind(run, git, root, child, timeout_s, tracking)
    last_commit = _git(run, git, root, child, timeout_s, "log", "-1", "--pretty=%h %s")

    gh = gh_bin or which_on_host("gh", env=child)
    if not gh:
        return RepoStatus(
            name=label,
            path=str(root),
            slug=slug,
            gh_state=GITHUB_MISSING_BIN,
            branch=branch,
            tracking=tracking,
            ahead=ahead,
            behind=behind,
            last_commit=last_commit,
        )
    if str(child.get("GH_TOKEN") or child.get("GITHUB_TOKEN") or "").strip():
        state = GITHUB_AUTHED
    else:
        state = gh_auth_state(env=env, runner=runner)
    if state != GITHUB_AUTHED:
        return RepoStatus(
            name=label,
            path=str(root),
            slug=slug,
            gh_state=state,
            branch=branch,
            tracking=tracking,
            ahead=ahead,
            behind=behind,
            last_commit=last_commit,
        )

    repo_view = _gh_json(
        run,
        gh,
        root,
        child,
        timeout_s,
        ["repo", "view", "--json", "nameWithOwner,defaultBranchRef"],
    )
    slug = slug or str((repo_view or {}).get("nameWithOwner") or "")
    default_branch = ""
    ref = (repo_view or {}).get("defaultBranchRef")
    if isinstance(ref, Mapping):
        default_branch = str(ref.get("name") or "")

    prs = _open_pulls(run, gh, root, child, timeout_s)
    issues, issue_count = _open_issues(run, gh, root, child, timeout_s)
    ci, ci_label = _default_branch_ci(run, gh, root, child, timeout_s, default_branch)
    return RepoStatus(
        name=label,
        path=str(root),
        slug=slug,
        gh_state=GITHUB_AUTHED,
        branch=branch,
        tracking=tracking,
        ahead=ahead,
        behind=behind,
        last_commit=last_commit,
        default_branch=default_branch,
        default_ci=ci,
        default_ci_label=ci_label,
        open_prs=prs,
        open_issue_count=issue_count,
        newest_issues=issues,
    )


def check_rollup_state(raw: Any) -> str:
    """green / red / pending / none from a ``statusCheckRollup`` payload."""

    from agent_discord.orchestration.github_wake import _checks_from_rollup

    items = _checks_from_rollup(raw)
    if not items:
        return CHECKS_NONE
    if any(
        str(item.status).lower() == "completed"
        and str(item.conclusion or "").lower() in _FAIL_CONCLUSIONS
        for item in items
    ):
        return CHECKS_RED
    if any(str(item.status).lower() in _PENDING_STATUSES for item in items):
        return CHECKS_PENDING
    return CHECKS_GREEN


def format_repo_status(status: RepoStatus) -> str:
    """The card body. Deterministic, short, and honest about unknowns."""

    head = status.name
    if status.slug:
        head = f"{status.name} · {status.slug}"
    lines = [head]
    if status.gh_state != GITHUB_AUTHED:
        lines.append(github_status_card(status.gh_state))
    if status.branch:
        drift = _drift_label(status)
        lines.append(f"Branch: {status.branch}{drift}")
    if status.last_commit:
        lines.append(f"Last commit: {status.last_commit}")
    if status.default_branch:
        label = f" ({status.default_ci_label})" if status.default_ci_label else ""
        lines.append(f"CI on {status.default_branch}: {status.default_ci}{label}")
    if status.gh_state != GITHUB_AUTHED:
        return "\n".join(lines)
    if status.open_prs:
        lines.append(f"Open PRs ({len(status.open_prs)}):")
        for row in status.open_prs:
            who = f" by {row.author}" if row.author else ""
            lines.append(f"- #{row.number} {_clip(row.title)}{who} — checks {row.checks}")
    else:
        lines.append("Open PRs: none")
    lines.append(f"Open issues: {status.open_issue_count}")
    for row in status.newest_issues:
        lines.append(f"- #{row.number} {_clip(row.title)}")
    return "\n".join(lines)


def repo_status_payload(status: RepoStatus) -> dict[str, Any]:
    return {
        "name": status.name,
        "path": status.path,
        "slug": status.slug,
        "gh_state": status.gh_state,
        "branch": status.branch,
        "tracking": status.tracking,
        "ahead": status.ahead,
        "behind": status.behind,
        "last_commit": status.last_commit,
        "default_branch": status.default_branch,
        "default_ci": status.default_ci,
        "default_ci_label": status.default_ci_label,
        "open_prs": [
            {
                "number": row.number,
                "title": row.title,
                "author": row.author,
                "checks": row.checks,
            }
            for row in status.open_prs
        ],
        "open_issue_count": status.open_issue_count,
        "newest_issues": [
            {"number": row.number, "title": row.title} for row in status.newest_issues
        ],
    }


def repo_status_card(status: RepoStatus) -> Any:
    from agent_discord.orchestration.cards import COLOR_IDLE, CardMessage

    return CardMessage(
        kind="NOTE",
        title=f"{status.name} status",
        description=format_repo_status(status),
        color=COLOR_IDLE,
    )


def _drift_label(status: RepoStatus) -> str:
    if not status.tracking:
        return " (no upstream)"
    return f" (ahead {status.ahead}, behind {status.behind} vs {status.tracking})"


def _clip(text: str, limit: int = _TITLE_CLIP) -> str:
    body = " ".join((text or "").split())
    if len(body) <= limit:
        return body
    return body[: max(0, limit - 1)].rstrip() + "…"


def _open_pulls(
    run: Callable[..., Any],
    gh: str,
    root: Path,
    env: Mapping[str, str],
    timeout_s: float,
) -> tuple[PullRow, ...]:
    rows = _gh_json(
        run,
        gh,
        root,
        env,
        timeout_s,
        [
            "pr",
            "list",
            "--state",
            "open",
            "--limit",
            str(PR_LIMIT),
            "--json",
            "number,title,author,statusCheckRollup",
        ],
    )
    out: list[PullRow] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, Mapping):
            continue
        author = row.get("author")
        login = ""
        if isinstance(author, Mapping):
            login = str(author.get("login") or "")
        elif isinstance(author, str):
            login = author
        try:
            number = int(row.get("number") or 0)
        except (TypeError, ValueError):
            continue
        out.append(
            PullRow(
                number=number,
                title=str(row.get("title") or ""),
                author=login,
                checks=check_rollup_state(row.get("statusCheckRollup")),
            )
        )
    return tuple(out)


def _open_issues(
    run: Callable[..., Any],
    gh: str,
    root: Path,
    env: Mapping[str, str],
    timeout_s: float,
) -> tuple[tuple[IssueRow, ...], int]:
    rows = _gh_json(
        run,
        gh,
        root,
        env,
        timeout_s,
        [
            "issue",
            "list",
            "--state",
            "open",
            "--limit",
            str(ISSUE_LIMIT),
            "--json",
            "number,title",
        ],
    )
    items: list[IssueRow] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, Mapping):
            continue
        try:
            number = int(row.get("number") or 0)
        except (TypeError, ValueError):
            continue
        items.append(IssueRow(number=number, title=str(row.get("title") or "")))
    items.sort(key=lambda item: item.number, reverse=True)
    return tuple(items[:NEWEST_ISSUES]), len(items)


def _default_branch_ci(
    run: Callable[..., Any],
    gh: str,
    root: Path,
    env: Mapping[str, str],
    timeout_s: float,
    default_branch: str,
) -> tuple[str, str]:
    branch = (default_branch or "").strip()
    if not branch:
        return CI_UNKNOWN, ""
    rows = _gh_json(
        run,
        gh,
        root,
        env,
        timeout_s,
        [
            "run",
            "list",
            "--branch",
            branch,
            "--limit",
            "1",
            "--json",
            "status,conclusion,workflowName",
        ],
    )
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], Mapping):
        return CI_UNKNOWN, ""
    row = rows[0]
    label = str(row.get("workflowName") or "")
    status = str(row.get("status") or "").lower()
    conclusion = str(row.get("conclusion") or "").lower()
    if status and status != "completed":
        return CHECKS_PENDING, label
    if conclusion in _FAIL_CONCLUSIONS:
        return CHECKS_RED, label
    if conclusion == "success":
        return CHECKS_GREEN, label
    return CI_UNKNOWN, label


def _ahead_behind(
    run: Callable[..., Any],
    git: str,
    root: Path,
    env: Mapping[str, str],
    timeout_s: float,
    tracking: str,
) -> tuple[int, int]:
    if not tracking:
        return 0, 0
    raw = _git(
        run,
        git,
        root,
        env,
        timeout_s,
        "rev-list",
        "--left-right",
        "--count",
        f"{tracking}...HEAD",
    )
    parts = raw.split()
    if len(parts) != 2:
        return 0, 0
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return 0, 0


def _git(
    run: Callable[..., Any],
    git: str,
    root: Path,
    env: Mapping[str, str],
    timeout_s: float,
    *args: str,
) -> str:
    proc = _invoke(run, [git, "-C", str(root), *args], root, env, timeout_s)
    if proc is None:
        return ""
    if getattr(proc, "returncode", 1) not in {0, None}:
        return ""
    return str(getattr(proc, "stdout", "") or "").strip()


def _gh_json(
    run: Callable[..., Any],
    gh: str,
    root: Path,
    env: Mapping[str, str],
    timeout_s: float,
    args: Sequence[str],
) -> Any:
    proc = _invoke(run, [gh, *args], root, env, timeout_s)
    if proc is None:
        return None
    if getattr(proc, "returncode", 1) not in {0, None}:
        return None
    try:
        return json.loads(str(getattr(proc, "stdout", "") or "") or "null")
    except json.JSONDecodeError:
        return None


def _invoke(
    run: Callable[..., Any],
    argv: Sequence[str],
    root: Path,
    env: Mapping[str, str],
    timeout_s: float,
) -> Any:
    try:
        return run(
            list(argv),
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=max(1.0, float(timeout_s)),
            env=dict(env),
        )
    except Exception:
        return None


__all__ = [
    "CHECKS_GREEN",
    "CHECKS_NONE",
    "CHECKS_PENDING",
    "CHECKS_RED",
    "CI_UNKNOWN",
    "IssueRow",
    "PullRow",
    "RepoStatus",
    "check_rollup_state",
    "collect_repo_status",
    "format_repo_status",
    "is_repo_status_ask",
    "repo_status_card",
    "repo_status_payload",
]
