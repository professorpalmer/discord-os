"""Local agentic workers: cwd, read policy, environment, gate queue location."""

from __future__ import annotations

import io
import json
from pathlib import Path

from agent_discord.contracts import ContextSnapshot, DispatchRequest
from agent_discord.orchestration.gate_hook import protected_path_reason, run_hook
from agent_discord.puppetmaster.agentic import AgenticPuppetmasterBackend
from agent_discord.puppetmaster.backend import confine_worker_cwd, is_runtime_dir
from agent_discord.puppetmaster.models import AGENTIC_CANONICAL_MODEL, AGENTIC_MODEL_PIN


def _runtime(tmp_path: Path) -> tuple[Path, Path]:
    """Live host layout: ~/discord-os/{.env,.agent-discord/}, not a git repo."""

    root = tmp_path / "discord-os"
    workspace = root / ".agent-discord"
    workspace.mkdir(parents=True)
    (root / ".env").write_text("DISCORD_BOT_TOKEN=not-real\n", encoding="utf-8")
    return root, workspace


def _request(**meta) -> DispatchRequest:
    return DispatchRequest(
        task_id="t1",
        run_id="run-1",
        prompt="hello",
        model=AGENTIC_CANONICAL_MODEL,
        context=ContextSnapshot(task_id="t1", memories=[], bindings={}),
        metadata=meta,
    )


def test_is_runtime_dir(tmp_path: Path) -> None:
    root, workspace = _runtime(tmp_path)
    assert is_runtime_dir(workspace, workspace)
    assert is_runtime_dir(workspace / "puppetmaster", workspace)
    assert is_runtime_dir(root, workspace)
    repo = tmp_path / "repo"
    repo.mkdir()
    assert not is_runtime_dir(repo, workspace)
    assert not is_runtime_dir(root, None)


def test_checkout_holding_its_own_state_dir_is_not_runtime(tmp_path: Path) -> None:
    """A dev checkout with .agent-discord inside stays a valid realm cwd."""

    checkout = tmp_path / "discord-os"
    (checkout / ".git").mkdir(parents=True)
    (checkout / ".agent-discord").mkdir()
    assert not is_runtime_dir(checkout, checkout / ".agent-discord")


def test_runtime_cwd_falls_back_to_scratch(tmp_path: Path) -> None:
    root, workspace = _runtime(tmp_path)
    scratch = tmp_path / "scratch"
    env = {"DISCORD_OS_SCRATCH_DIR": str(scratch)}
    assert confine_worker_cwd(str(root), workspace=workspace, env=env) == str(scratch)
    assert confine_worker_cwd(str(workspace), workspace=workspace, env=env) == str(scratch)
    assert scratch.is_dir()
    assert (scratch.stat().st_mode & 0o777) == 0o700
    repo = tmp_path / "repo"
    repo.mkdir()
    assert confine_worker_cwd(str(repo), workspace=workspace, env=env) == str(repo)


def test_agentic_spawn_never_uses_runtime_cwd(tmp_path: Path) -> None:
    """Audit E2-2: the live host had PUPPETMASTER_CWD at the dir holding .env."""

    root, workspace = _runtime(tmp_path)
    scratch = tmp_path / "scratch"
    backend = AgenticPuppetmasterBackend(
        cli="puppetmaster",
        pin=AGENTIC_MODEL_PIN,
        cwd=root,
        workspace=workspace,
        env={"DISCORD_OS_SCRATCH_DIR": str(scratch)},
    )
    _handoff, workdir = backend._plan_agentic_spawn(_request(), stream=False)
    assert workdir == str(scratch)

    repo = tmp_path / "realm"
    repo.mkdir()
    _handoff, workdir = backend._plan_agentic_spawn(_request(cwd=str(repo)), stream=False)
    assert workdir == str(repo)


def test_protected_path_reason() -> None:
    for path in (
        ".env",
        "../.env",
        "/Users/x/discord-os/.env.local",
        ".agent-discord/agent_discord.sqlite3",
        "data/app.sqlite3",
        "keys/master.key",
        "/Users/x/.ssh/config",
        "~/.aws/credentials",
        ".git-credentials",
    ):
        assert protected_path_reason({"path": path}), path
    for path in ("src/app.py", ".env.example", "README.md", ".envrc", "docs/keys.md"):
        assert protected_path_reason({"path": path}) == "", path
    assert protected_path_reason({}) == ""
    assert protected_path_reason("cat .env") == ""


def _hook(tool_name: str, tool_input: dict, tmp_path: Path) -> dict:
    stdin = io.StringIO(json.dumps({"tool_name": tool_name, "tool_input": tool_input}))
    stdout = io.StringIO()
    run_hook(
        [],
        stdin=stdin,
        stdout=stdout,
        env={"DISCORD_OS_GATE_DIR": str(tmp_path / "gate"), "DISCORD_OS_RUN_ID": "run-1"},
    )
    return json.loads(stdout.getvalue())


def test_hook_denies_secret_reads_and_passes_normal_reads(tmp_path: Path) -> None:
    denied = _hook("read_file", {"path": ".env"}, tmp_path)
    assert denied["permissionDecision"] == "deny"
    assert "protected path" in denied["permissionDecisionReason"]
    listed = _hook("list_dir", {"path": ".agent-discord"}, tmp_path)
    assert listed["permissionDecision"] == "deny"
    allowed = _hook("read_file", {"path": "src/app.py"}, tmp_path)
    assert allowed["permissionDecision"] == "allow"


def test_repo_reach_line_names_scratch(tmp_path: Path) -> None:
    from agent_discord.host.repos import host_reach_block

    text = host_reach_block(repos=(), cwd=tmp_path / "scratch")
    assert "Discord OS runtime" not in text
    assert "scratch" in text


def test_gate_queue_lives_where_listen_drains(tmp_path: Path) -> None:
    """Audit E2-4: a realm checkout cwd must not move the gate queue."""

    from agent_discord.orchestration.gate_hook import (
        ENV_GATE_DIR,
        build_request,
        enqueue_request,
        list_pending,
        resolve_gate_root,
    )

    _root, workspace = _runtime(tmp_path)
    repo = tmp_path / "realm"
    repo.mkdir()
    backend = AgenticPuppetmasterBackend(
        cli="puppetmaster", pin=AGENTIC_MODEL_PIN, cwd=repo, workspace=workspace, env={}
    )
    child_env: dict[str, str] = {}
    backend._attach_gate_env(child_env, _request(cwd=str(repo)))
    run_dir = Path(child_env[ENV_GATE_DIR])
    assert not str(run_dir).startswith(str(repo))
    enqueue_request(run_dir, build_request(run_id="run-1", tool_name="write_file"))
    drained_root = resolve_gate_root(workspace=workspace, env={})
    assert run_dir.parent == drained_root
    assert list_pending(drained_root / run_dir.name)
