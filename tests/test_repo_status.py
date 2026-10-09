"""Deterministic repo status card (audit I1 bet 2). Canned gh/git only."""

from __future__ import annotations

import argparse
import io
import json
from pathlib import Path

from agent_discord.host.repo_status import (
    CHECKS_GREEN,
    CHECKS_PENDING,
    CHECKS_RED,
    collect_repo_status,
    format_repo_status,
    is_repo_status_ask,
    repo_status_payload,
)


class _Proc:
    def __init__(self, stdout: str = "", returncode: int = 0) -> None:
        self.stdout = stdout
        self.stderr = ""
        self.returncode = returncode


_GIT = {
    ("rev-parse", "--abbrev-ref", "HEAD"): "dev",
    (
        "rev-parse",
        "--abbrev-ref",
        "--symbolic-full-name",
        "@{upstream}",
    ): "origin/dev",
    ("log", "-1", "--pretty=%h %s"): "74a01c2 Delete the companion dashboard",
}

_PRS = [
    {
        "number": 68,
        "title": "Fold brain lakes into host memory",
        "author": {"login": "professorpalmer"},
        "statusCheckRollup": [
            {"name": "tests", "status": "completed", "conclusion": "failure"}
        ],
    },
    {
        "number": 70,
        "title": "Morning summary",
        "author": {"login": "contributor"},
        "statusCheckRollup": [
            {"name": "tests", "status": "completed", "conclusion": "success"}
        ],
    },
    {
        "number": 71,
        "title": "Waiting on checks",
        "author": {"login": "contributor"},
        "statusCheckRollup": [{"name": "tests", "status": "in_progress"}],
    },
]

_ISSUES = [
    {"number": 35, "title": "Two-tier swarm"},
    {"number": 41, "title": "Repo status card"},
    {"number": 12, "title": "Older ask"},
    {"number": 40, "title": "CI watcher"},
]


def _runner(*, ci_conclusion: str = "success"):
    def run(argv, **kwargs):
        args = list(argv)
        if args[0] == "git":
            key = tuple(args[3:])
            if key[:1] == ("rev-list",):
                return _Proc("2\t5\n")
            return _Proc(_GIT.get(key, "") + "\n")
        rest = tuple(args[1:])
        if rest[:2] == ("repo", "view"):
            return _Proc(
                json.dumps(
                    {
                        "nameWithOwner": "professorpalmer/discord-os",
                        "defaultBranchRef": {"name": "master"},
                    }
                )
            )
        if rest[:2] == ("pr", "list"):
            return _Proc(json.dumps(_PRS))
        if rest[:2] == ("issue", "list"):
            return _Proc(json.dumps(_ISSUES))
        if rest[:2] == ("run", "list"):
            return _Proc(
                json.dumps(
                    [
                        {
                            "status": "completed",
                            "conclusion": ci_conclusion,
                            "workflowName": "tests",
                        }
                    ]
                )
            )
        raise AssertionError(f"unexpected argv {args}")

    return run


def _status(tmp_path: Path, **kwargs):
    return collect_repo_status(
        tmp_path,
        name="discord-os",
        runner=_runner(**kwargs),
        env={"GH_TOKEN": "canned"},
        gh_bin="gh",
        git_bin="git",
    )


def test_matcher_takes_status_asks_and_leaves_work_asks_alone():
    assert is_repo_status_ask("any open PRs on discord-os?")
    assert is_repo_status_ask("open issues on Puppetmaster")
    assert is_repo_status_ask("status of marionette")
    assert is_repo_status_ask("what is the repo status")
    assert is_repo_status_ask("how many open issues do we have")
    assert not is_repo_status_ask("fix the status bar")
    assert not is_repo_status_ask("fix CI on marionette")
    assert not is_repo_status_ask("open a PR against dev")
    assert not is_repo_status_ask("write a status page for the repo")
    assert not is_repo_status_ask("what time is it")
    assert not is_repo_status_ask("")


def test_card_contents_come_from_canned_gh_json(tmp_path: Path):
    status = _status(tmp_path)
    assert status.slug == "professorpalmer/discord-os"
    assert status.branch == "dev"
    assert (status.behind, status.ahead) == (2, 5)
    assert status.last_commit.startswith("74a01c2 ")
    assert status.default_branch == "master"
    assert status.default_ci == CHECKS_GREEN
    assert [row.checks for row in status.open_prs] == [
        CHECKS_RED,
        CHECKS_GREEN,
        CHECKS_PENDING,
    ]
    assert status.open_issue_count == 4
    assert [row.number for row in status.newest_issues] == [41, 40, 35]

    body = format_repo_status(status)
    assert "discord-os · professorpalmer/discord-os" in body
    assert "Branch: dev (ahead 5, behind 2 vs origin/dev)" in body
    assert "CI on master: green (tests)" in body
    assert "#68 Fold brain lakes into host memory by professorpalmer — checks red" in body
    assert "Open issues: 4" in body
    assert "#41 Repo status card" in body


def test_red_default_branch_ci_is_reported(tmp_path: Path):
    status = _status(tmp_path, ci_conclusion="failure")
    assert status.default_ci == CHECKS_RED
    assert "CI on master: red (tests)" in format_repo_status(status)


def test_missing_gh_still_answers_from_git(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "agent_discord.host.repo_status.which_on_host", lambda name, env=None: ""
    )
    status = collect_repo_status(
        tmp_path,
        name="discord-os",
        runner=_runner(),
        env={},
        git_bin="git",
    )
    assert status.gh_state == "missing_bin"
    assert status.branch == "dev"
    body = format_repo_status(status)
    assert "GitHub CLI is not installed" in body
    assert "Open PRs" not in body


def test_payload_is_json_serialisable(tmp_path: Path):
    payload = repo_status_payload(_status(tmp_path))
    assert json.loads(json.dumps(payload))["open_prs"][0]["number"] == 68


def test_cli_repo_status_prints_one_block(tmp_path: Path):
    from agent_discord.host.repos import HostRepo

    repo = tmp_path / "discord-os"
    (repo / ".git").mkdir(parents=True)
    out = io.StringIO()
    code = _cmd_repo(
        argparse.Namespace(repo_command="status", name="", json=False),
        out=out,
        repos=(HostRepo(name="discord-os", path=repo),),
        tmp_path=repo,
    )
    assert code == 0
    assert "Open issues: 4" in out.getvalue()


def test_cli_repo_status_json(tmp_path: Path):
    from agent_discord.host.repos import HostRepo

    repo = tmp_path / "discord-os"
    (repo / ".git").mkdir(parents=True)
    out = io.StringIO()
    code = _cmd_repo(
        argparse.Namespace(repo_command="status", name="discord-os", json=True),
        out=out,
        repos=(HostRepo(name="discord-os", path=repo),),
        tmp_path=repo,
    )
    assert code == 0
    assert json.loads(out.getvalue())[0]["slug"] == "professorpalmer/discord-os"


def _cmd_repo(args, *, out, repos, tmp_path: Path):
    from agent_discord.cli import cmd_repo

    def collector(path, *, name=""):
        return _status(tmp_path)

    return cmd_repo(args, out=out, repos=repos, collector=collector)


def test_status_ask_closes_without_a_worker(tmp_path: Path):
    from agent_discord.contracts import TaskIntake, TaskStatus
    from agent_discord.host.repos import HostRepo
    from tests.test_orchestration import _orch

    orch, store, _discord, backend = _orch(tmp_path)
    repo = tmp_path / "discord-os"
    (repo / ".git").mkdir(parents=True)
    orch.host_repos = (HostRepo(name="discord-os", path=repo, aliases=("discord os",)),)
    orch.repo_status_collector = lambda path, name="": _status(repo)
    receipt = orch.run_task(
        TaskIntake(
            text="any open PRs on discord-os?",
            channel_id="ch",
            workspace_id="ws",
        )
    )
    assert backend.last_request is None
    assert receipt.status == TaskStatus.COMPLETED
    assert "Open issues: 4" in receipt.summary
    store.close()
