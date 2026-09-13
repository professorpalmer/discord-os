"""Orchestration flow with DI-friendly seams for tests."""

from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence
from uuid import uuid4

from agent_discord.contracts import (
    ArtifactRef,
    ContextSnapshot,
    DispatchRequest,
    DispatchResult,
    EventKind,
    ProgressSummary,
    RunReceipt,
    TaskIntake,
    TaskStatus,
    UsageReceipt,
)
from agent_discord.discord.facade import DiscordFacade
from agent_discord.discord.object_store import DEFAULT_MAX_OBJECT_BYTES, DiscordObjectStore
from agent_discord.host.memory import memory_reach_block, recall_think_tank, settle_think_tank
from agent_discord.host.realms import realm_for_channel
from agent_discord.host.repos import (
    HostRepo,
    association_block,
    host_reach_block,
    load_host_repos,
    resolve_host_repo,
)
from agent_discord.host.tools import load_host_tools, tools_reach_block
from agent_discord.orchestration.cards import (
    edit_card,
    receipt_card,
    send_card,
)
from agent_discord.orchestration.reactive import (
    reactive_paint,
    reactive_progress_card,
    reactive_receipt_card,
    reactive_working_card,
)
from agent_discord.orchestration.routing import (
    MODE_IMPLEMENT,
    compute_dispatch_mode,
    swarm_worker_count,
)
from agent_discord.persistence.research import ResearchMemoryStore
from agent_discord.persistence.sqlite import SQLiteStore
from agent_discord.puppetmaster.models import DEFAULT_MODEL_PIN
from agent_discord.redaction import redact_text_markers, strip_forbidden_keys

TOKEN_CARD_FLUSH_SECONDS = 0.35
CARD_TEXT_LIMIT = 3500
SETTLE_SHORT_LIMIT = 280
SETTLE_BUBBLE_SOFT = 420
SETTLE_MAX_BUBBLES = 3
_STREAM_PHASES = frozenset({"thinking", "plan", "code", "dispatch", "done"})
_PROCESS_PHASES = frozenset({"thinking", "start", "plan", "code", "dispatch"})
_SWARM_ROLES = (
    "explore",
    "pipeline-mapper",
    "decision-explainer",
    "conflict-auditor",
    "test-coverage-reviewer",
)
_RATE_LIMIT_MARKERS = ("429", "rate limit", "rate_limited", "ratelimited")
THREAD_BIND_RATE_SPOKEN = (
    "Could not open a job thread — Discord rate limit. Try again in a minute."
)
THREAD_BIND_FAIL_SPOKEN = (
    "Could not open a job thread. Cards need a thread so Need/Jobs stay findable."
)


def _monotonic() -> float:
    return time.monotonic()


def _is_token_stream(details: Mapping[str, Any]) -> bool:
    return bool(details.get("token")) or "stream_phase" in details


def _visible_card_text(text: str) -> str:
    """Keep model dialogue on the live card. Drop only CLI/JSON junk."""

    from agent_discord.puppetmaster.backend import is_prompt_echo, public_card_text

    cleaned = public_card_text(text)
    if not cleaned:
        return ""
    if is_prompt_echo(cleaned):
        return ""
    text = cleaned
    kept: list[str] = []
    for line in (text or "").splitlines():
        raw = line.strip()
        if not raw:
            if kept and kept[-1] != "":
                kept.append("")
            continue
        if raw[:1] in "{[":
            continue
        lower = raw.lower()
        if lower.startswith("usage: puppetmaster"):
            continue
        if "unrecognized arguments:" in lower:
            continue
        if lower.startswith(("task_id=", "run_id=", "job_id:")):
            continue
        kept.append(line.rstrip())
    return "\n".join(kept).strip()


def _strip_prompt_section(block: str, heading: str) -> str:
    skip = False
    kept: list[str] = []
    marker = (heading or "").strip().lower()
    for line in (block or "").splitlines():
        stripped = line.strip().lower()
        if stripped == marker:
            skip = True
            continue
        if skip and stripped.startswith("[") and stripped.endswith("]") and stripped != marker:
            skip = False
        if skip:
            continue
        kept.append(line)
    return "\n".join(kept).strip()



_SETTLE_SKIP = frozenset(
    {
        "starting.",
        "starting",
        "on it.",
        "on it",
        "working.",
        "working",
        "queued.",
        "queued",
    }
)


def _is_settle_worthy(text: str) -> bool:
    from agent_discord.puppetmaster.backend import public_card_text

    raw = public_card_text(text).strip()
    if not raw:
        return False
    if raw.lower() in _SETTLE_SKIP:
        return False
    compact = raw.replace("%", "").replace(".", "").replace(" ", "")
    if compact.isdigit():
        return False
    return True


def _settle_bubbles(text: str) -> list[str]:
    """Public-safe persist-then-settle bodies. Prefer 2; 3 only if needed."""

    from agent_discord.puppetmaster.backend import (
        _same_beat,
        _split_sentences,
        public_card_text,
    )

    body = public_card_text(text, limit=0).strip()
    if not body or not _is_settle_worthy(body):
        return []
    sentences: list[str] = []
    for part in _split_sentences(body):
        sentence = part.strip()
        if not sentence:
            continue
        if sentences and _same_beat(sentences[-1], sentence):
            continue
        sentences.append(sentence)
    if not sentences:
        return [body]
    if len(sentences) == 1 or len(body) <= SETTLE_SHORT_LIMIT:
        return [body]
    count = 2
    packed_two = _pack_settle_sentences(sentences, 2)
    if (
        len(sentences) >= 3
        and packed_two
        and max(len(chunk) for chunk in packed_two) > SETTLE_BUBBLE_SOFT
    ):
        count = 3
    count = min(SETTLE_MAX_BUBBLES, len(sentences), count)
    return _pack_settle_sentences(sentences, count) or [body]


def _pack_settle_sentences(sentences: list[str], count: int) -> list[str]:
    parts = [item.strip() for item in sentences if item.strip()]
    if not parts:
        return []
    n = min(max(count, 1), SETTLE_MAX_BUBBLES, len(parts))
    if n <= 1:
        return [" ".join(parts)]
    weights = [len(item) for item in parts]
    total = sum(weights)
    target = total / n
    cuts: list[int] = []
    acc = 0
    next_cut = 1
    for index, weight in enumerate(weights[:-1]):
        acc += weight
        if acc + 1e-9 >= target * next_cut:
            cuts.append(index + 1)
            next_cut += 1
            if next_cut >= n:
                break
    starts = [0, *cuts]
    ends = [*cuts, len(parts)]
    return [" ".join(parts[start:end]) for start, end in zip(starts, ends) if start < end]


def _card_window(text: str) -> str:
    """Live-card body. Keep the start of the current beat under Discord's limit."""

    from agent_discord.puppetmaster.backend import _clip_to_limit, public_card_text

    body = public_card_text(text, limit=0)
    if not body:
        return ""
    if len(body) <= CARD_TEXT_LIMIT:
        return body
    return _clip_to_limit(body, CARD_TEXT_LIMIT)


class _LiveCard:
    """One editable card. Persist-then-settle on beat change / Done."""

    def __init__(
        self,
        orch: "AgentOrchestrator",
        channel_id: str,
        thread_id: Optional[str],
        run_id: str,
    ) -> None:
        self.orch = orch
        self.channel_id = channel_id
        self.thread_id = thread_id
        self.run_id = run_id
        self.message_id: Optional[str] = None
        self.stage = ""
        self.text = ""
        self.thinking = ""

    def paint(
        self,
        card: Any,
        *,
        stage: str,
        settle: bool = False,
        keep: str = "",
    ) -> None:
        from agent_discord.puppetmaster.backend import public_card_text

        painted = public_card_text(getattr(card, "description", "") or "", limit=0)
        new_text = public_card_text(keep, limit=0) if keep else painted
        prior = public_card_text(self.text, limit=0)
        should = False
        if self.thread_id and prior and prior != new_text:
            if settle:
                should = True
            elif stage and self.stage and stage != self.stage:
                should = True
        if should and _is_settle_worthy(prior):
            self.orch._settle_beat(self.channel_id, self.thread_id, prior)
        self.message_id = self.orch._post_or_edit_progress(
            self.channel_id,
            card,
            thread_id=self.thread_id,
            message_id=self.message_id,
        )
        if stage:
            self.stage = stage
        if new_text:
            self.text = new_text
        incoming_thinking = str(getattr(card, "thinking", "") or "")
        if incoming_thinking:
            self.thinking = incoming_thinking

    def finish(self, card: Any, *, summary: str) -> None:
        from agent_discord.puppetmaster.backend import public_card_text

        if self.orch.discord is None:
            return
        spoken = public_card_text(summary, limit=0) or public_card_text(
            getattr(card, "description", "") or "",
            limit=0,
        )
        prior = public_card_text(self.text, limit=0)
        # Settle only a previous different user-facing beat. Never reprint Done.
        if (
            self.thread_id
            and prior
            and spoken
            and prior != spoken
            and _is_settle_worthy(prior)
        ):
            self.orch._settle_beat(self.channel_id, self.thread_id, prior)
        bubbles = _settle_bubbles(spoken) if spoken else []
        extras = bubbles[1:]
        first = bubbles[0] if bubbles else spoken
        card_body = public_card_text(getattr(card, "description", "") or "")
        if first and card_body == spoken:
            card = replace(card, description=first)
        try:
            dest = self.thread_id or self.channel_id
            if self.message_id:
                try:
                    edit_card(self.orch.discord, dest, self.message_id, card)
                except Exception:
                    send_card(self.orch.discord, self.channel_id, card, thread_id=self.thread_id)
            else:
                send_card(self.orch.discord, self.channel_id, card, thread_id=self.thread_id)
        except Exception:
            pass
        if extras and self.thread_id:
            self.orch._post_settle_messages(self.channel_id, self.thread_id, extras)



def _posted_message_id(posted: Any) -> str:
    if posted is None:
        return ""
    if isinstance(posted, list) and posted:
        return str(getattr(posted[-1], "message_id", "") or "")
    if isinstance(posted, dict):
        return str(posted.get("message_id") or posted.get("id") or "")
    return str(getattr(posted, "message_id", "") or "")


class AgentOrchestrator:
    """intake → context snapshot → pinned dispatch → events → Discord → receipt."""

    def __init__(
        self,
        *,
        store: SQLiteStore,
        backend: Any,
        discord: Optional[DiscordFacade] = None,
        model: str = DEFAULT_MODEL_PIN.canonical,
        post_progress_to_discord: bool = True,
        research: Optional[ResearchMemoryStore] = None,
        max_object_bytes: int = DEFAULT_MAX_OBJECT_BYTES,
        workspace: Optional[Path] = None,
        compute_cwd: Optional[Path] = None,
        host_repos: Optional[tuple[HostRepo, ...]] = None,
        retry_backoff_s: float = 0.0,
        presence: Optional[Callable[[str, str], None]] = None,
        ssh_exec: Optional[Callable[..., Any]] = None,
    ) -> None:
        self.store = store
        self.backend = backend
        self.discord = discord
        self.model = model
        self.post_progress_to_discord = post_progress_to_discord
        # Optional research seam — None keeps normal tasks free of research metadata.
        self.research = research
        self.max_object_bytes = max_object_bytes
        self.workspace = Path(workspace) if workspace is not None else None
        self.compute_cwd = Path(compute_cwd) if compute_cwd is not None else None
        self.host_repos = host_repos
        self.host_github: Optional[Callable[[Path], str]] = None
        self.retry_backoff_s = float(retry_backoff_s)
        self.presence = presence
        # Injectable SSH runner for Path A remote cook tests (argv, *, timeout_seconds).
        self.ssh_exec = ssh_exec
        self._run_status: dict[str, TaskStatus] = {}
        self._checkpoints: dict[str, dict[str, Any]] = {}
        self._steer_lock = threading.Lock()
        self._live_threads: dict[str, str] = {}
        self._steer_inbox: dict[str, list[str]] = {}
        # Path A Cancel must interrupt the SSH cook backend, not only local agentic.
        self._cook_backends: dict[str, Any] = {}
        self.steer_count = 0
        self._lineage_tips: dict[str, str] = {}

    def run_task(self, intake: TaskIntake) -> RunReceipt:
        pin = self.backend.resolve_model(self.model)
        if intake.message_id:
            already = bool((intake.metadata or {}).get("inbound_claimed"))
            if not already:
                claimed = self.store.claim_inbound_message(
                    intake.message_id, intake.channel_id
                )
                if not claimed:
                    return self._duplicate_receipt(intake.message_id)

        from agent_discord.orchestration.service import is_spend_halted

        if is_spend_halted(self.store, intake.workspace_id):
            return self._halted_receipt(intake)

        task_id = uuid4().hex
        run_id = uuid4().hex

        self.store.merge_binding_metadata(
            intake.workspace_id,
            intake.channel_id,
            {"thread_id": intake.thread_id},
            guild_id=intake.guild_id,
        )
        self.store.create_task(
            task_id=task_id,
            workspace_id=intake.workspace_id,
            channel_id=intake.channel_id,
            intake_text=intake.text,
            thread_id=intake.thread_id,
            requester_id=intake.requester_id,
            metadata=dict(intake.metadata),
        )
        self.store.create_run(
            run_id=run_id,
            task_id=task_id,
            model=pin.canonical,
            adapter_name=pin.adapter_name,
            status=TaskStatus.RUNNING,
        )
        self._run_status[run_id] = TaskStatus.RUNNING
        self._set_presence("dnd", intake.text)
        replay_of = str((intake.metadata or {}).get("replay_of") or "").strip()
        if replay_of:
            from agent_discord.orchestration.lineage import list_nodes, tip_key

            prev_tip = tip_key(list_nodes(self.store, replay_of))
            self._record_lineage(
                task_id,
                run_id,
                "replay",
                replay_of,
                parent_keys=(prev_tip,) if prev_tip else (),
            )
        session_parents: tuple[str, ...] = ()
        follow_tid = str(intake.thread_id or "").strip()
        if follow_tid and not replay_of:
            prev_reader = getattr(self.store, "latest_run_id_for_thread", None)
            if callable(prev_reader):
                try:
                    prev_run = str(
                        prev_reader(follow_tid, excluding_run_id=run_id) or ""
                    ).strip()
                except TypeError:
                    try:
                        prev_run = str(prev_reader(follow_tid) or "").strip()
                    except Exception:
                        prev_run = ""
                except Exception:
                    prev_run = ""
                if prev_run and prev_run != run_id:
                    from agent_discord.orchestration.lineage import list_nodes, tip_key

                    tip = tip_key(list_nodes(self.store, prev_run))
                    if tip:
                        session_parents = (tip,)
        self._record_lineage(
            task_id,
            run_id,
            "intake",
            intake.text,
            parent_keys=session_parents,
        )

        job_thread_id = intake.thread_id
        if (
            self.post_progress_to_discord
            and self.discord is not None
            and str(intake.channel_id or "").strip()
            and not str(intake.thread_id or "").strip()
        ):
            # Channel-parent asks always bind a Discord job thread (P0.2).
            # message_id present → thread on the user ask; else HOST Ask posts
            # a channel starter first. Existing thread_id steers stay untouched.
            started, bind_err = self._ensure_job_thread(
                intake.channel_id,
                intake.text,
                message_id=intake.message_id,
            )
            if started:
                job_thread_id = started
                binder = getattr(self.store, "bind_task_thread", None)
                if callable(binder):
                    try:
                        binder(task_id, started)
                    except Exception:
                        pass
                merger = getattr(self.store, "merge_task_metadata", None)
                if callable(merger):
                    meta_patch: dict[str, Any] = {"thread_id": started}
                    if intake.message_id:
                        meta_patch["message_id"] = intake.message_id
                    try:
                        merger(task_id, meta_patch)
                    except Exception:
                        pass
            else:
                spoken = self._thread_bind_spoken(bind_err)
                try:
                    self.store.update_run(
                        run_id,
                        status=TaskStatus.FAILED,
                        summary=spoken,
                        error=spoken,
                    )
                except Exception:
                    pass
                self._run_status[run_id] = TaskStatus.FAILED
                receipt = RunReceipt(
                    task_id=task_id,
                    run_id=run_id,
                    status=TaskStatus.FAILED,
                    summary=spoken,
                    error=spoken,
                )
                if self.discord is not None:
                    try:
                        send_card(
                            self.discord,
                            intake.channel_id,
                            reactive_receipt_card(receipt, has_thread=False),
                        )
                    except Exception:
                        try:
                            send = getattr(self.discord, "send_message", None)
                            if callable(send):
                                send(intake.channel_id, spoken)
                        except Exception:
                            pass
                self._react_terminal(intake, TaskStatus.FAILED)
                self._set_presence("idle", "Discord OS")
                return receipt
        if job_thread_id:
            from agent_discord.orchestration.jobs import note_origin_thread

            note_origin_thread(job_thread_id)
            self._mark_thread_live(job_thread_id, run_id)
        live = _LiveCard(self, intake.channel_id, job_thread_id, run_id)
        resume_card = str((intake.metadata or {}).get("card_message_id") or "").strip()
        if resume_card:
            live.message_id = resume_card
        if self.post_progress_to_discord and self.discord is not None:
            job_code = ""
            reader = getattr(self.store, "task_job_code", None)
            if callable(reader):
                try:
                    job_code = str(reader(task_id) or "")
                except Exception:
                    job_code = ""
            live.paint(
                reactive_progress_card(
                    stage="start",
                    message="On it.",
                    percent=1,
                    run_id=run_id,
                    job_code=job_code,
                ),
                stage="start",
            )
        self._react_intake(intake, "\U0001F440")

        if intake.message_id:
            self.store.bind_inbound_message(
                intake.message_id,
                task_id=task_id,
                run_id=run_id,
                channel_id=intake.channel_id,
            )
            if self.discord is not None:
                try:
                    self.discord.observe_message_id(intake.message_id)
                except Exception:
                    # Process-local facade dedupe is best-effort; SQLite is authoritative.
                    pass

        self._event(
            task_id,
            run_id,
            EventKind.INTAKE,
            "task intake accepted",
            {"text": intake.text, "channel_id": intake.channel_id},
            source="orchestrator",
        )

        memories = list(
            self.store.recall(
                workspace_id=intake.workspace_id,
                channel_id=intake.channel_id,
                query=intake.text,
                limit=8,
            )
        )
        tank = ""
        if self.discord is not None:
            try:
                tank = recall_think_tank(
                    self.discord,
                    self.store,
                    intake.text,
                    workspace_id=intake.workspace_id,
                )
            except Exception:
                tank = ""
        if tank:
            memories.insert(
                0,
                {
                    "memory_id": "think-tank",
                    "content": tank[:2000],
                    "source": "think-tank",
                },
            )
        pref_block = ""
        reader = getattr(self.store, "prompt_memory_block", None)
        if callable(reader):
            try:
                pref_block = reader(intake.workspace_id) or ""
            except Exception:
                pref_block = ""
        if pref_block:
            kept = _strip_prompt_section(pref_block, "[failures]")
            if kept:
                memories.insert(
                    0,
                    {
                        "memory_id": "preferences",
                        "content": kept,
                        "source": "preferences",
                    },
                )
        binding = self.store.get_binding(intake.workspace_id, intake.channel_id) or {}
        research_context = self._optional_research_context(intake)
        provenance: dict[str, Any] = {
            "source": "sqlite",
            "memory_count": len(memories),
        }
        if research_context:
            provenance["research"] = research_context
        snapshot = ContextSnapshot(
            task_id=task_id,
            memories=memories,
            bindings={
                "workspace_id": intake.workspace_id,
                "channel_id": intake.channel_id,
                "guild_id": intake.guild_id,
                "binding": binding,
            },
            provenance=provenance,
        )
        self._event(
            task_id,
            run_id,
            EventKind.CONTEXT_SNAPSHOT,
            f"context snapshot ({len(memories)} memories)",
            {
                "memory_ids": [m.get("memory_id") for m in memories],
                "provenance": dict(snapshot.provenance),
            },
            source="orchestrator",
        )

        progress_items: list[ProgressSummary] = []
        progress_message_id = live.message_id
        requested_workers = None
        thread_history = ""
        if intake.metadata:
            requested_workers = intake.metadata.get("workers")
            bits = intake.metadata.get("thread_history") or []
            if bits:
                thread_history = "\n".join(str(item)[:200] for item in list(bits)[:6])
        workers = swarm_worker_count(intake.text, requested_workers)
        prompt = intake.text.strip()
        if thread_history:
            prompt = f"{prompt}\n\nThread history:\n{thread_history}"
        compute_mode = compute_dispatch_mode(intake.text)
        extra_meta = dict(intake.metadata) if intake.metadata else {}
        extra_meta.update(
            {
                "channel_id": intake.channel_id,
                "compute_mode": compute_mode,
                "workers": workers,
            }
        )
        repos = self.host_repos if self.host_repos is not None else load_host_repos()
        from agent_discord.host.remote_cook import (
            assert_ssh_remote_cook_ready,
            make_ssh_cook_backend,
        )
        from agent_discord.host.runners import (
            HostAllowlistError,
            assert_host_cook_allowed,
            load_host_allowlist,
            resolve_channel_host,
        )

        cook_backend = self.backend
        try:
            remote_host = resolve_channel_host(
                self.store,
                intake.channel_id,
                workspace_id=intake.workspace_id,
                allowlist=load_host_allowlist(),
            )
            # Unknown kinds / missing ssh target Deny. kind=ssh continues to
            # Path A remote cook (never silent local cook on this Mac).
            assert_host_cook_allowed(remote_host)
            if (
                remote_host is not None
                and (remote_host.kind or "").strip().lower() == "ssh"
            ):
                assert_ssh_remote_cook_ready(
                    remote_host, exec_fn=self.ssh_exec
                )
                cook_backend = make_ssh_cook_backend(
                    remote_host,
                    exec_fn=self.ssh_exec,
                    workspace=self.workspace,
                    store=self.store,
                )
                # Preflight already probed; avoid a second BatchMode round-trip.
                cook_backend.probe_first = False
        except HostAllowlistError as exc:
            receipt = self._close_without_worker(
                intake,
                task_id=task_id,
                run_id=run_id,
                summary=str(exc.spoken),
                live=live,
            )
            self._release_live_thread(job_thread_id, run_id)
            return receipt
        host_cwd = None
        if remote_host is not None:
            extra_meta["host_id"] = remote_host.id
            extra_meta["host_label"] = remote_host.label
            extra_meta["host_kind"] = remote_host.kind
            if remote_host.workdir:
                extra_meta["host_workdir"] = remote_host.workdir
            # Path A: stamp write-gate so SSH cook can speak Need + fail-close
            # remote writes when Discord gate holds cannot cross SSH yet.
            # When DISCORD_OS_SSH_GATES=bridge, arm live phone Allow/Deny instead.
            if (remote_host.kind or "").strip().lower() == "ssh":
                try:
                    from agent_discord.orchestration.service import writes_need_approval
                    from agent_discord.orchestration.ssh_gate import (
                        remote_gate_dir_for_run,
                        ssh_gates_cross,
                    )
                    from agent_discord.orchestration.gate_hook import (
                        ensure_run_gate_dir,
                        resolve_gate_root,
                        run_gate_dir,
                    )

                    if ssh_gates_cross():
                        extra_meta["ssh_gate_bridge"] = True
                        extra_meta["ssh_gate_remote_dir"] = remote_gate_dir_for_run(
                            run_id
                        )
                        root = resolve_gate_root(
                            workspace=self.workspace, store=self.store
                        )
                        ensure_run_gate_dir(run_gate_dir(root, run_id))
                    elif writes_need_approval(self.store):
                        extra_meta["ssh_write_gate"] = True
                except Exception:
                    pass
            # Local path-root hosts may supply the run cwd. ssh uses remote
            # workdir via Path A (SshRemoteCookBackend) — never local cook.
            if remote_host.kind == "local" and remote_host.target:
                root = Path(remote_host.target).expanduser()
                if root.is_dir():
                    host_cwd = root.resolve()
        channel_realm = realm_for_channel(
            self.store,
            intake.channel_id,
            workspace_id=intake.workspace_id,
            repos=repos,
        )
        chosen = resolve_host_repo(
            intake.text,
            repos,
            default_cwd=self.compute_cwd,
        )
        if chosen is None:
            chosen = channel_realm
        run_cwd = chosen.path if chosen is not None else (host_cwd or self.compute_cwd)
        if run_cwd is not None:
            extra_meta["cwd"] = str(run_cwd)
        if chosen is not None:
            extra_meta["repo"] = chosen.name
        from agent_discord.host.github import is_github_status_ask
        from agent_discord.host.github import is_github_unauthed_report

        status_ask = is_github_status_ask(intake.text)
        scan = ""
        if callable(self.host_github) and run_cwd is not None:
            if chosen is not None or status_ask:
                try:
                    scan = str(self.host_github(Path(run_cwd)) or "").strip()
                except Exception:
                    scan = ""
        host_github = scan if status_ask else ""
        if host_github:
            extra_meta["host_github"] = host_github
        if scan and not is_github_unauthed_report(scan):
            extra_meta["github_scan"] = scan
        if chosen is not None:
            extra_meta["association"] = association_block(
                chosen,
                github="" if status_ask or is_github_unauthed_report(scan) else scan,
            )

        if status_ask and is_github_unauthed_report(host_github):
            receipt = self._close_without_worker(
                intake,
                task_id=task_id,
                run_id=run_id,
                summary=host_github,
                live=live,
            )
            self._release_live_thread(job_thread_id, run_id)
            return receipt
        extra_meta["host_reach"] = "\n\n".join(
            item
            for item in (
                host_reach_block(repos, cwd=run_cwd),
                tools_reach_block(load_host_tools()),
                memory_reach_block(self.store, workspace_id=intake.workspace_id),
            )
            if item
        )
        approved = bool(extra_meta.get("approved"))
        if compute_mode == MODE_IMPLEMENT and not approved:
            from agent_discord.orchestration.service import writes_need_approval_for

            if writes_need_approval_for(
                self.store,
                channel_id=str(intake.channel_id or ""),
                thread_id=str(job_thread_id or intake.thread_id or ""),
            ):
                receipt = self._park_for_approval(
                    intake,
                    task_id=task_id,
                    run_id=run_id,
                    thread_id=job_thread_id,
                    live=live,
                )
                self._release_live_thread(job_thread_id, run_id)
                return receipt
        request = DispatchRequest(
            task_id=task_id,
            run_id=run_id,
            prompt=prompt,
            model=pin.canonical,
            context=snapshot,
            metadata=extra_meta,
        )
        self._record_lineage(task_id, run_id, "dispatch", prompt)
        prefer_host_report = bool(host_github) and not is_github_unauthed_report(
            host_github
        )
        if prefer_host_report:
            from agent_discord.puppetmaster.backend import public_card_text

            shown = public_card_text(host_github)
            if shown:
                live.paint(
                    reactive_progress_card(
                        stage="working",
                        message=shown,
                        percent=12,
                        run_id=run_id,
                    ),
                    stage="working",
                )
                progress_message_id = live.message_id
        self._cook_backends[run_id] = cook_backend
        if workers:
            try:
                return self.dispatch_swarm(
                    intake,
                    request,
                    task_id=task_id,
                    run_id=run_id,
                    workers=workers,
                    job_thread_id=job_thread_id,
                    progress_message_id=progress_message_id,
                    live=live,
                    backend=cook_backend,
                )
            finally:
                self._cook_backends.pop(run_id, None)
        stream = getattr(cook_backend, "stream", None)
        if callable(stream):
            events_iter = stream(request)
            result = None
        else:
            result = cook_backend.dispatch(request)
            events_iter = iter(result.events)

        from agent_discord.puppetmaster.backend import public_card_text as _card_text

        token_text = (
            _card_text(host_github, limit=0)
            if prefer_host_report
            else (host_github or "")
        )
        thinking_hold = ""
        token_dirty = bool(token_text)
        last_flush_at = _monotonic()
        last_percent: Optional[float] = None
        stream_stage = "start"
        stream_error: Optional[str] = None
        painted_live = False

        def _remember_process(text: str) -> None:
            nonlocal thinking_hold
            raw = (text or "").strip()
            if not raw:
                return
            if thinking_hold:
                if raw not in thinking_hold:
                    thinking_hold = f"{thinking_hold}\n\n{raw}"
            else:
                thinking_hold = raw

        def flush_token_card(*, force: bool = False) -> None:
            nonlocal progress_message_id, token_dirty, last_flush_at, painted_live
            from agent_discord.puppetmaster.backend import is_prompt_echo
            from agent_discord.puppetmaster.backend import public_card_text

            visible = redact_text_markers(token_text).strip()
            if is_prompt_echo(visible):
                visible = ""
            if not token_dirty and not force:
                return
            if not visible and not thinking_hold and not force and last_percent is None:
                return
            first_tokens = bool(visible or thinking_hold) and not painted_live
            if (
                not force
                and not first_tokens
                and (_monotonic() - last_flush_at) < TOKEN_CARD_FLUSH_SECONDS
            ):
                return
            if self.post_progress_to_discord and self.discord is not None:
                shown = public_card_text(visible, limit=0)
                if stream_stage in _PROCESS_PHASES:
                    think_zone = (
                        f"{thinking_hold}\n\n{visible}".strip()
                        if thinking_hold and visible and visible not in thinking_hold
                        else (visible or thinking_hold)
                    )
                    spoken = ""
                else:
                    think_zone = thinking_hold
                    spoken = shown
                live.paint(
                    reactive_progress_card(
                        stage=stream_stage,
                        message=_card_window(spoken) if spoken else "",
                        thinking=think_zone,
                        percent=last_percent,
                        run_id=run_id,
                    ),
                    stage=stream_stage,
                    keep=spoken,
                )
                progress_message_id = live.message_id
            token_dirty = False
            last_flush_at = _monotonic()
            if visible or thinking_hold:
                painted_live = True

        receipt_payload: dict[str, Any] = {}
        for event in events_iter:
            incoming = self._take_steers(run_id)
            if incoming:
                add = "\n".join(incoming)
                token_text = (token_text + "\n\n" + add).strip()
                token_dirty = True
            safe_details = strip_forbidden_keys(dict(event.summary.details))
            if not isinstance(safe_details, dict):
                safe_details = {}
            safe_payload = strip_forbidden_keys(dict(event.payload))
            if not isinstance(safe_payload, dict):
                safe_payload = {}
            summary = ProgressSummary(
                stage=event.summary.stage,
                message=redact_text_markers(event.summary.message),
                percent=event.summary.percent,
                details=safe_details,
            )
            progress_items.append(summary)
            self._event(
                task_id,
                run_id,
                event.kind,
                summary.message,
                {
                    "stage": summary.stage,
                    "percent": summary.percent,
                    "details": dict(summary.details),
                    **safe_payload,
                },
                source="backend",
            )
            if event.kind == EventKind.CANCEL_REQUESTED:
                self._run_status[run_id] = TaskStatus.CANCELLED
                stream_error = None
            if event.kind == EventKind.ERROR:
                stream_error = summary.message
            if event.kind == EventKind.RECEIPT:
                receipt_payload = dict(safe_payload)
            if (
                self.post_progress_to_discord
                and self.discord is not None
                and event.kind in {EventKind.PROGRESS, EventKind.DISPATCH}
            ):
                if prefer_host_report:
                    continue
                if summary.percent is not None:
                    last_percent = summary.percent
                if (summary.message or "").strip().lower().startswith("dispatched via"):
                    if last_percent is not None:
                        live.paint(
                            reactive_progress_card(
                                stage="working",
                                message=_visible_card_text(token_text) or "Working.",
                                percent=last_percent,
                                run_id=run_id,
                            ),
                            stage="working",
                        )
                        progress_message_id = live.message_id
                    continue
                if _is_token_stream(summary.details):
                    from agent_discord.puppetmaster.backend import public_card_text

                    raw_incoming = redact_text_markers(
                        str(summary.details.get("token_text") or "")
                    ).strip()
                    phase = str(
                        summary.details.get("stream_phase") or summary.stage or stream_stage
                    )
                    if phase in _STREAM_PHASES and phase != stream_stage:
                        if stream_stage in _PROCESS_PHASES:
                            _remember_process(token_text)
                        stream_stage = phase
                    if raw_incoming:
                        token_text = raw_incoming
                        token_dirty = True
                    else:
                        spoken_bit = public_card_text(summary.message or "", limit=0)
                        if spoken_bit:
                            token_text = (token_text + spoken_bit).strip()
                            token_dirty = True
                    if phase in _STREAM_PHASES:
                        stream_stage = phase
                    flush_token_card()
                    continue
                visible = _visible_card_text(summary.message)
                if not visible:
                    continue
                if summary.stage:
                    stream_stage = summary.stage
                live.paint(
                    reactive_progress_card(
                        stage=summary.stage,
                        message=visible,
                        percent=summary.percent,
                        run_id=run_id,
                    ),
                    stage=summary.stage or stream_stage,
                )
                progress_message_id = live.message_id
                last_flush_at = _monotonic()

        flush_token_card(force=True)

        if result is None:
            streamed_status = cook_backend.status(run_id)
            if streamed_status in {
                TaskStatus.PENDING,
                TaskStatus.RUNNING,
                TaskStatus.PROGRESS,
            }:
                if (
                    self._run_status.get(run_id) == TaskStatus.CANCELLED
                    or self.backend.status(run_id) == TaskStatus.CANCELLED
                ):
                    streamed_status = TaskStatus.CANCELLED
                    stream_error = None
                else:
                    streamed_status = (
                        TaskStatus.FAILED if stream_error else TaskStatus.COMPLETED
                    )
            usage = None
            if receipt_payload:
                from agent_discord.puppetmaster.backend import usage_from_cli_meta

                usage = usage_from_cli_meta(pin, "", receipt_payload)
            if (
                streamed_status == TaskStatus.FAILED
                and stream_error
            ):
                from agent_discord.puppetmaster.backend import salvage_swarm_incomplete_answer

                progress_spoken = "\n".join(
                    item.message for item in progress_items if (item.message or "").strip()
                )
                salvaged = salvage_swarm_incomplete_answer(
                    error=str(stream_error),
                    token_text=token_text or progress_spoken,
                )
                if salvaged:
                    streamed_status = TaskStatus.COMPLETED
                    stream_error = None
                    final_bit = salvaged
                else:
                    final_bit = (
                        progress_items[-1].message if progress_items else "completed"
                    )
            else:
                final_bit = (
                    progress_items[-1].message if progress_items else "completed"
                )
            result = DispatchResult(
                run_id=run_id,
                status=streamed_status,
                events=tuple(progress_items),
                final_summary=final_bit,
                error=stream_error,
                usage=usage,
            )
            self._run_status[run_id] = streamed_status

        if (
            result.status == TaskStatus.FAILED
            and self._is_rate_limit(result.error)
        ):
            self._sleep_retry()
            retry_request = DispatchRequest(
                task_id=request.task_id,
                run_id=request.run_id,
                prompt=request.prompt,
                model=request.model,
                context=request.context,
                metadata={**dict(request.metadata), "resume": "rate_limit"},
            )
            result = cook_backend.dispatch(retry_request)
            self._run_status[run_id] = result.status

        if result.status == TaskStatus.FAILED:
            from agent_discord.puppetmaster.backend import salvage_swarm_incomplete_answer

            progress_spoken = "\n".join(
                item.message
                for item in progress_items
                if (item.message or "").strip()
            )
            salvaged = salvage_swarm_incomplete_answer(
                error=str(result.error or result.final_summary or ""),
                token_text=token_text or progress_spoken or str(result.final_summary or ""),
                stdout="",
                safe_meta=receipt_payload if isinstance(receipt_payload, dict) else {},
            )
            if salvaged:
                result = replace(
                    result,
                    status=TaskStatus.COMPLETED,
                    error=None,
                    final_summary=salvaged,
                )
                stream_error = None
                self._run_status[run_id] = TaskStatus.COMPLETED
            else:
                writer = getattr(self.store, "record_failure", None)
                if callable(writer):
                    try:
                        writer(
                            intake.workspace_id,
                            run_id,
                            result.error or result.final_summary or "failed",
                        )
                    except Exception:
                        pass
                self._rollback_on_red(run_id)

        receipt_artifacts: list[ArtifactRef] = []
        for art in result.artifacts:
            persisted = self._persist_artifact(art, intake=intake, task_id=task_id, run_id=run_id)
            receipt_artifacts.append(persisted)
            step = "diff" if persisted.kind in {"diff", "patch"} else "finding"
            self._record_lineage(
                task_id,
                run_id,
                step,
                persisted.sha256 or persisted.kind,
                artifact_id=persisted.artifact_id,
            )

        usage_map = None
        if result.usage is not None:
            usage_map = {
                "model": result.usage.model,
                "adapter_name": result.usage.adapter_name,
                "input_tokens": result.usage.input_tokens,
                "output_tokens": result.usage.output_tokens,
                "metadata": strip_forbidden_keys(dict(result.usage.metadata)),
            }
            self._record_usage_spend(intake.workspace_id, run_id, result.usage)

        from agent_discord.puppetmaster.backend import choose_spoken_answer
        from agent_discord.puppetmaster.backend import provider_failure_spoken
        from agent_discord.puppetmaster.backend import public_card_text

        progress_bits = tuple(
            item.message
            for item in progress_items
            if item.stage in {"thinking", "plan", "code", "done"}
        )
        done_bits = tuple(
            item.message for item in progress_items if item.stage == "done"
        )
        if prefer_host_report:
            spoken = public_card_text(host_github) or host_github.strip()
        else:
            spoken = choose_spoken_answer(
                result.final_summary,
                *reversed(done_bits),
                token_text,
                *reversed(progress_bits),
            )
            if not spoken:
                spoken = public_card_text(token_text)
                if (
                    not spoken
                    and is_github_status_ask(intake.text)
                    and is_github_unauthed_report(host_github)
                ):
                    spoken = host_github
        failure = provider_failure_spoken(
            "\n".join(
                bit
                for bit in (
                    spoken,
                    token_text,
                    result.final_summary,
                    result.error,
                    *progress_bits,
                )
                if bit
            )
        )
        if failure:
            spoken = failure
            result = replace(
                result,
                status=TaskStatus.FAILED,
                error=result.error or failure,
                final_summary=failure,
            )
        if stream_stage in _PROCESS_PHASES:
            _remember_process(token_text)
        safe_final_summary = spoken or "Worker finished without a written answer."
        safe_error = redact_text_markers(result.error) if result.error else None
        self.store.update_run(
            run_id,
            status=result.status,
            summary=safe_final_summary,
            error=safe_error,
            usage=usage_map,
        )
        self._run_status[run_id] = result.status

        from agent_discord.puppetmaster.backend import is_prompt_echo

        if spoken and not is_prompt_echo(safe_final_summary):
            self.store.remember(
                workspace_id=intake.workspace_id,
                channel_id=intake.channel_id,
                content=f"{intake.text[:160]} → {safe_final_summary[:240]}",
                source="orchestrator",
                provenance={"task_id": task_id, "run_id": run_id, "status": result.status.value},
            )
        if self.discord is not None and result.status == TaskStatus.COMPLETED:
            try:
                settle_think_tank(
                    self.discord,
                    self.store,
                    workspace_id=intake.workspace_id,
                    origin_channel=intake.channel_id,
                    summary=safe_final_summary[:400],
                )
            except Exception:
                pass

        settle_art = self._persist_text_artifact(
            safe_final_summary,
            kind="settle",
            intake=intake,
            task_id=task_id,
            run_id=run_id,
        )
        receipt_artifacts.append(settle_art)
        self._record_lineage(
            task_id,
            run_id,
            "settle",
            safe_final_summary,
            artifact_id=settle_art.artifact_id,
        )

        receipt = RunReceipt(
            task_id=task_id,
            run_id=run_id,
            status=result.status,
            summary=safe_final_summary,
            progress=tuple(progress_items),
            artifacts=tuple(receipt_artifacts),
            usage=result.usage,
            error=safe_error,
        )
        think = live.thinking or thinking_hold
        if think and public_card_text(think, limit=0) == safe_final_summary:
            think = ""
        card = reactive_receipt_card(
            receipt,
            has_thread=bool(live.thread_id or job_thread_id),
            thinking=think,
        )
        rendered = card.text
        self._event(
            task_id,
            run_id,
            EventKind.RECEIPT,
            "final receipt",
            {"rendered": rendered, "status": result.status.value},
            source="orchestrator",
        )

        if self.post_progress_to_discord and self.discord is not None:
            live.finish(card, summary=safe_final_summary)
        # P2.13: opt-in local TTS for Done / spoken summary. Fail closed; never raises.
        try:
            from agent_discord.discord.tts import maybe_speak_done

            maybe_speak_done(safe_final_summary)
        except Exception:
            pass
        self._release_live_thread(live.thread_id or job_thread_id, run_id)
        self._react_terminal(intake, result.status)
        self._set_presence("idle", "Discord OS")
        self._cook_backends.pop(run_id, None)

        return receipt

    def dispatch_swarm(
        self,
        intake: TaskIntake,
        request: DispatchRequest,
        *,
        task_id: str,
        run_id: str,
        workers: int,
        job_thread_id: Optional[str],
        progress_message_id: Optional[str],
        live: Optional[_LiveCard] = None,
        backend: Optional[Any] = None,
    ) -> RunReceipt:
        """Fan out one analyze worker per role, then optional implement handoff."""

        if live is None:
            live = _LiveCard(self, intake.channel_id, job_thread_id, run_id)
            live.message_id = progress_message_id
        cook = backend if backend is not None else self.backend
        roles = list(_SWARM_ROLES[: max(2, min(int(workers), 5))])
        summaries: list[str] = []
        progress_items: list[ProgressSummary] = []
        for index, role in enumerate(roles):
            child_id = f"{run_id}-{role}"
            child = DispatchRequest(
                task_id=task_id,
                run_id=child_id,
                prompt=f"[{role}] {request.prompt}",
                model=request.model,
                context=request.context,
                metadata={**dict(request.metadata), "role": role, "parent_run_id": run_id},
            )
            result = cook.dispatch(child)
            bit = _visible_card_text(result.final_summary or role) or role
            summaries.append(f"{role}: {bit}")
            progress_items.append(
                ProgressSummary(
                    stage=role,
                    message=bit,
                    percent=round((index + 1) * 100.0 / (len(roles) + 1), 1),
                )
            )
            if self.post_progress_to_discord and self.discord is not None:
                live.paint(
                    reactive_progress_card(
                        stage=role,
                        message=bit,
                        percent=progress_items[-1].percent,
                        run_id=run_id,
                    ),
                    stage=role,
                )
                progress_message_id = live.message_id

        stitched = "\n".join(summaries)
        final_status = TaskStatus.COMPLETED
        handoff_error: Optional[str] = None
        if compute_dispatch_mode(intake.text) == MODE_IMPLEMENT or "implement" in intake.text.lower():
            handoff = DispatchRequest(
                task_id=task_id,
                run_id=f"{run_id}-implement",
                prompt=f"Implement from swarm findings:\n{stitched}\n\nTask:\n{intake.text}",
                model=request.model,
                context=request.context,
                metadata={**dict(request.metadata), "compute_mode": MODE_IMPLEMENT, "handoff": True},
            )
            handoff_result = cook.dispatch(handoff)
            stitched = f"{stitched}\nimplement: {handoff_result.final_summary}"
            final_status = handoff_result.status
            handoff_error = handoff_result.error

        self.store.update_run(
            run_id,
            status=final_status,
            summary=redact_text_markers(stitched),
            error=handoff_error,
        )
        self._run_status[run_id] = final_status
        receipt = RunReceipt(
            task_id=task_id,
            run_id=run_id,
            status=final_status,
            summary=redact_text_markers(stitched),
            progress=tuple(progress_items),
            error=handoff_error,
        )
        if self.post_progress_to_discord and self.discord is not None:
            live.finish(reactive_receipt_card(receipt, has_thread=bool(live.thread_id or job_thread_id)), summary=redact_text_markers(stitched))
        self._event(
            task_id,
            run_id,
            EventKind.RECEIPT,
            "swarm receipt",
            {"workers": len(roles), "roles": roles},
            source="orchestrator",
        )
        self._release_live_thread(live.thread_id or job_thread_id, run_id)
        self._react_terminal(intake, final_status)
        self._set_presence("idle", "Discord OS")
        return receipt

    def apply_job_action(
        self,
        action: str,
        run_id: str,
        *,
        prompt: str = "",
    ) -> dict[str, Any]:
        """Allow / Always allow / Deny / cancel / retry / Continue / Dismiss. Best-effort."""

        verb = (action or "").strip().lower()
        run = self.store.get_run(run_id) or {}
        if verb == "cancel":
            # Plan park Cancel = deny plan (ExitPlanMode), not live-cook interrupt.
            if self._task_awaiting_gate(run_id) and self._gate_kind(run_id) == "plan_approve":
                return self._resolve_plan_gate(run_id, "deny")
            return self._cancel_live_cook(run_id)
        if verb == "retry":
            task_id = str(run.get("task_id") or "")
            task = self.store.get_task(task_id) if task_id else None
            text = ""
            if task:
                text = str(task.get("intake_text") or "")
            if text:
                return {
                    "action": verb,
                    "run_id": run_id,
                    "status": "queued",
                    "intake_text": text,
                    "replay_of": run_id,
                }
            return {"action": verb, "run_id": run_id, "status": "missing"}
        if verb in {"ask-confirm", "ask_confirm"}:
            return self._confirm_ask_multi(run_id)
        if verb == "ask":
            # custom_id path packs run_id#option_index
            rid, sep, idx_raw = (run_id or "").partition("#")
            if not sep:
                return {"action": "ask", "run_id": run_id, "status": "missing"}
            try:
                option_index = int(idx_raw)
            except ValueError:
                return {"action": "ask", "run_id": rid, "status": "missing"}
            return self._resolve_ask_option(rid, option_index)
        if verb in {"approve", "always", "deny", "expire"}:
            if self._task_awaiting_gate(run_id):
                if self._gate_kind(run_id) == "plan_approve":
                    if verb == "always":
                        # Plan park has no Always — fail closed / ignore.
                        return {
                            "action": "always",
                            "run_id": run_id,
                            "status": "ignored",
                            "summary": "Plan Approve has no Always; use Approve or Cancel.",
                        }
                    if verb == "expire":
                        return self.expire_parked_run(run_id)
                    return self._resolve_plan_gate(run_id, verb)
                if verb == "expire":
                    return self.expire_parked_run(run_id)
                return self._resolve_tool_gate(run_id, verb)
        if verb == "approve":
            return self._approve_parked_run(run_id)
        if verb == "always":
            return self._always_allow_parked_run(run_id)
        if verb == "deny":
            return self._deny_parked_run(run_id)
        if verb == "expire":
            return self.expire_parked_run(run_id)
        if verb == "continue":
            return self._continue_idle_run(run_id, prompt=prompt)
        if verb in {"dismiss", "ack"}:
            return self._dismiss_failed_need(run_id)
        return {"action": verb, "run_id": run_id, "status": "ignored"}

    def _approve_parked_run(self, run_id: str) -> dict[str, Any]:
        run = self.store.get_run(run_id) or {}
        task_id = str(run.get("task_id") or "")
        reader = getattr(self.store, "task_metadata", None)
        meta = reader(task_id) if callable(reader) and task_id else {}
        if not isinstance(meta, dict) or not meta.get("awaiting_approval"):
            return {"action": "approve", "run_id": run_id, "status": "approved"}
        task = self.store.get_task(task_id) or {}
        intake_meta = dict(meta.get("intake_meta") or {})
        intake_meta["approved"] = True
        intake_meta["inbound_claimed"] = True
        card_mid = str(meta.get("card_message_id") or "").strip()
        if card_mid:
            intake_meta["card_message_id"] = card_mid
        parked_thread = str(task.get("thread_id") or meta.get("thread_id") or "").strip()
        parked_message = str(meta.get("message_id") or "").strip()
        intake = TaskIntake(
            text=str(task.get("intake_text") or meta.get("text") or ""),
            channel_id=str(task.get("channel_id") or meta.get("channel_id") or ""),
            workspace_id=str(task.get("workspace_id") or meta.get("workspace_id") or "default"),
            guild_id=meta.get("guild_id"),
            thread_id=parked_thread or None,
            message_id=parked_message or None,
            requester_id=task.get("requester_id") or meta.get("requester_id"),
            metadata=intake_meta,
        )
        merger = getattr(self.store, "merge_task_metadata", None)
        if callable(merger):
            merger(task_id, {"awaiting_approval": False})
        try:
            self.store.update_run(
                run_id,
                status=TaskStatus.COMPLETED,
                summary="approved; write started",
            )
        except Exception:
            pass
        if not intake.text.strip() or not intake.channel_id:
            return {"action": "approve", "run_id": run_id, "status": "missing"}
        receipt = self.run_task(intake)
        return {
            "action": "approve",
            "run_id": receipt.run_id,
            "parked_run_id": run_id,
            "status": receipt.status.value,
            "receipt": receipt,
        }

    def _always_allow_parked_run(self, run_id: str) -> dict[str, Any]:
        from agent_discord.orchestration.service import set_write_session_allow

        run = self.store.get_run(run_id) or {}
        task_id = str(run.get("task_id") or "")
        reader = getattr(self.store, "task_metadata", None)
        meta = reader(task_id) if callable(reader) and task_id else {}
        if not isinstance(meta, dict):
            meta = {}
        task = self.store.get_task(task_id) or {}
        scope = (
            str(task.get("thread_id") or meta.get("thread_id") or "").strip()
            or str(task.get("channel_id") or meta.get("channel_id") or "").strip()
        )
        if scope:
            set_write_session_allow(self.store, scope)
        result = self._approve_parked_run(run_id)
        result["action"] = "always"
        result["session_allow"] = scope
        return result

    def expire_parked_run(self, run_id: str) -> dict[str, Any]:
        from agent_discord.orchestration.ask_gate import (
            EXPIRED_ASK_SPOKEN,
            EXPIRED_TOOL_SPOKEN,
            GATE_KIND_ASK,
        )
        from agent_discord.orchestration.plan_approve import (
            EXPIRED_PLAN_SPOKEN,
            GATE_KIND_PLAN,
        )
        from agent_discord.orchestration.service import EXPIRED_WRITE_SPOKEN

        spoken = EXPIRED_WRITE_SPOKEN
        if self._task_awaiting_gate(run_id):
            kind = self._gate_kind(run_id)
            if kind == GATE_KIND_PLAN:
                result = self._resolve_plan_gate(
                    run_id, "deny", spoken=EXPIRED_PLAN_SPOKEN
                )
                result["action"] = "expire"
                return result
            spoken = EXPIRED_ASK_SPOKEN if kind == GATE_KIND_ASK else EXPIRED_TOOL_SPOKEN
            result = self._resolve_tool_gate(run_id, "deny", spoken=spoken)
            result["action"] = "expire"
            return result
        result = self._deny_parked_run(run_id, spoken=spoken)
        result["action"] = "expire"
        return result

    def _deny_parked_run(
        self, run_id: str, *, spoken: str = "Denied. Write was not started."
    ) -> dict[str, Any]:
        run = self.store.get_run(run_id) or {}
        task_id = str(run.get("task_id") or "")
        reader = getattr(self.store, "task_metadata", None)
        meta = reader(task_id) if callable(reader) and task_id else {}
        if not isinstance(meta, dict):
            meta = {}
        spoken = (spoken or "Denied. Write was not started.").strip() or "Denied. Write was not started."
        merger = getattr(self.store, "merge_task_metadata", None)
        if callable(merger) and task_id:
            try:
                merger(task_id, {"awaiting_approval": False})
            except Exception:
                pass
        try:
            self.store.update_run(
                run_id,
                status=TaskStatus.FAILED,
                summary=spoken,
                error=spoken,
            )
        except Exception:
            pass
        self._run_status[run_id] = TaskStatus.FAILED
        if self.post_progress_to_discord and self.discord is not None:
            task = self.store.get_task(task_id) or {}
            channel_id = str(task.get("channel_id") or meta.get("channel_id") or "").strip()
            thread_id = str(task.get("thread_id") or meta.get("thread_id") or "").strip() or None
            card_mid = str(meta.get("card_message_id") or "").strip()
            card = reactive_receipt_card(
                RunReceipt(
                    task_id=task_id,
                    run_id=run_id,
                    status=TaskStatus.FAILED,
                    summary=spoken,
                    error=spoken,
                ),
                has_thread=bool(thread_id),
            )
            try:
                dest = thread_id or channel_id
                if card_mid and dest:
                    edit_card(self.discord, dest, card_mid, card)
                elif channel_id:
                    send_card(
                        self.discord,
                        channel_id,
                        card,
                        thread_id=thread_id,
                    )
            except Exception:
                pass
        self._set_presence("idle", "Discord OS")
        return {
            "action": "deny",
            "run_id": run_id,
            "status": TaskStatus.FAILED.value,
            "summary": spoken,
        }

    def _dismiss_failed_need(
        self, run_id: str, *, refresh_host: bool = True
    ) -> dict[str, Any]:
        """Ack a failed Need: mark cancelled so briefing ranks Last, not Need."""

        rid = (run_id or "").strip()
        run = self.store.get_run(rid) or {}
        if not run:
            return {"action": "dismiss", "run_id": rid, "status": "missing"}
        status = str(run.get("status") or "").strip().lower()
        task_id = str(run.get("task_id") or "")
        attention = ""
        reader = getattr(self.store, "task_metadata", None)
        if callable(reader) and task_id:
            try:
                meta = reader(task_id) or {}
                github = meta.get("github") if isinstance(meta, dict) else None
                if isinstance(github, dict):
                    attention = str(github.get("attention") or "").strip().lower()
            except Exception:
                attention = ""
        if status != "failed" and attention != "need":
            return {
                "action": "dismiss",
                "run_id": rid,
                "status": "ignored",
                "summary": "Only failed Needs can be dismissed.",
            }
        if status == "failed":
            try:
                self.store.update_run(
                    rid,
                    status=TaskStatus.CANCELLED,
                    summary="dismissed",
                    error="dismissed",
                )
            except Exception:
                pass
            self._run_status[rid] = TaskStatus.CANCELLED
        clearer = getattr(self.store, "set_job_github_attention", None)
        if callable(clearer) and task_id:
            try:
                clearer(task_id, "")
            except Exception:
                pass
        # Best-effort: repaint the job card as Cancelled / Last.
        try:
            task = self.store.get_task(task_id) if task_id else None
            thread_id = ""
            if isinstance(task, dict):
                thread_id = str(task.get("thread_id") or "").strip()
            if self.post_progress_to_discord and self.discord is not None:
                card = reactive_receipt_card(
                    RunReceipt(
                        task_id=task_id,
                        run_id=rid,
                        status=TaskStatus.CANCELLED if status == "failed" else TaskStatus.COMPLETED,
                        summary="dismissed",
                        error="dismissed" if status == "failed" else None,
                    ),
                    has_thread=bool(thread_id),
                )
                meta = {}
                if callable(reader) and task_id:
                    try:
                        meta = reader(task_id) or {}
                    except Exception:
                        meta = {}
                if not isinstance(meta, dict):
                    meta = {}
                card_mid = str(meta.get("card_message_id") or "").strip()
                channel_id = ""
                if isinstance(task, dict):
                    channel_id = str(task.get("channel_id") or "").strip()
                dest = thread_id or channel_id
                if card_mid and dest:
                    edit_card(self.discord, dest, card_mid, card)
        except Exception:
            pass
        channel_id = ""
        try:
            task = self.store.get_task(task_id) if task_id else None
            if isinstance(task, dict):
                channel_id = str(task.get("channel_id") or "").strip()
        except Exception:
            channel_id = ""
        if channel_id and refresh_host:
            self._refresh_host_jobs_after_rank_change(channel_id)
        return {
            "action": "dismiss",
            "run_id": rid,
            "status": "cancelled" if status == "failed" else "cleared",
            "summary": "dismissed",
        }

    def _refresh_host_jobs_after_rank_change(self, channel_id: str) -> None:
        """Best-effort HOST Jobs / Need line refresh after dismiss or cancel settle."""

        cid = (channel_id or "").strip()
        if not cid or self.discord is None:
            return
        try:
            from agent_discord.orchestration.listen import publish_host_card

            publish_host_card(self.discord, self.store, cid)
        except Exception:
            return

    def clear_failed_needs(
        self,
        *,
        failed: bool = False,
        older_than_days: int | None = None,
        channel_id: str = "",
        dry_run: bool = False,
        limit: int = 500,
    ) -> dict[str, Any]:
        """Bulk dismiss stale failed (and attention-need) jobs; refresh HOST panels.

        Fail-closed: ``failed`` must be True. Same dismiss semantics as P0.1.
        """

        if not failed:
            return {
                "action": "clear-needs",
                "status": "refused",
                "summary": "Pass --failed to clear failed Needs (fail-closed).",
                "matched": 0,
                "cleared": 0,
                "dry_run": bool(dry_run),
                "runs": [],
            }
        lister = getattr(self.store, "list_dismissable_needs", None)
        if not callable(lister):
            return {
                "action": "clear-needs",
                "status": "unsupported",
                "summary": "Store cannot list dismissable needs.",
                "matched": 0,
                "cleared": 0,
                "dry_run": bool(dry_run),
                "runs": [],
            }
        try:
            matches = list(
                lister(
                    channel_id=channel_id or "",
                    older_than_days=older_than_days,
                    limit=limit,
                )
            )
        except Exception as exc:
            return {
                "action": "clear-needs",
                "status": "error",
                "summary": str(exc),
                "matched": 0,
                "cleared": 0,
                "dry_run": bool(dry_run),
                "runs": [],
            }
        preview = [
            {
                "run_id": str(item.get("run_id") or ""),
                "task_id": str(item.get("task_id") or ""),
                "channel_id": str(item.get("channel_id") or ""),
                "status": str(item.get("status") or ""),
                "attention": str(item.get("attention") or ""),
                "job_code": str(item.get("job_code") or ""),
                "summary": str(item.get("summary") or item.get("intake_text") or "")[:120],
            }
            for item in matches
        ]
        if dry_run:
            return {
                "action": "clear-needs",
                "status": "dry-run",
                "matched": len(preview),
                "cleared": 0,
                "dry_run": True,
                "older_than_days": older_than_days,
                "channel_id": (channel_id or "").strip(),
                "runs": preview,
            }
        cleared = 0
        results: list[dict[str, Any]] = []
        channels: set[str] = set()
        for item in matches:
            rid = str(item.get("run_id") or "").strip()
            if not rid:
                continue
            result = self._dismiss_failed_need(rid, refresh_host=False)
            results.append(
                {
                    "run_id": rid,
                    "status": str(result.get("status") or ""),
                    "channel_id": str(item.get("channel_id") or ""),
                    "job_code": str(item.get("job_code") or ""),
                }
            )
            if str(result.get("status") or "") in {"cancelled", "cleared"}:
                cleared += 1
            cid = str(item.get("channel_id") or "").strip()
            if cid:
                channels.add(cid)
        # Dismiss already refreshes per-job; one more pass covers any missed channel.
        for cid in sorted(channels):
            self._refresh_host_jobs_after_rank_change(cid)
        return {
            "action": "clear-needs",
            "status": "ok",
            "matched": len(preview),
            "cleared": cleared,
            "dry_run": False,
            "older_than_days": older_than_days,
            "channel_id": (channel_id or "").strip(),
            "runs": results,
        }

    def _continue_idle_run(self, run_id: str, *, prompt: str = "") -> dict[str, Any]:
        """Start a new tip-parented job in the prior idle Discord thread."""

        from agent_discord.orchestration.job_briefing import DEFAULT_CONTINUE_PROMPT

        run = self.store.get_run(run_id) or {}
        task_id = str(run.get("task_id") or "")
        task = self.store.get_task(task_id) if task_id else None
        if not isinstance(task, dict):
            return {"action": "continue", "run_id": run_id, "status": "missing"}
        thread_id = str(task.get("thread_id") or "").strip()
        channel_id = str(task.get("channel_id") or "").strip()
        if not thread_id or not channel_id:
            return {"action": "continue", "run_id": run_id, "status": "missing"}
        status_raw = str(run.get("status") or "").strip().lower()
        if status_raw in {"running", "progress", "pending"}:
            return {
                "action": "continue",
                "run_id": run_id,
                "status": "busy",
                "summary": "Job is not idle.",
            }
        text = (prompt or "").strip() or DEFAULT_CONTINUE_PROMPT
        intake = TaskIntake(
            text=text,
            channel_id=channel_id,
            workspace_id=str(task.get("workspace_id") or "default"),
            thread_id=thread_id,
            requester_id=task.get("requester_id"),
            metadata={"continued_from": run_id, "inbound_claimed": True},
        )
        receipt = self.run_task(intake)
        return {
            "action": "continue",
            "run_id": receipt.run_id,
            "prior_run_id": run_id,
            "status": receipt.status.value,
            "intake_text": text,
            "thread_id": thread_id,
            "receipt": receipt,
        }

    def raise_tool_gate(
        self,
        run_id: str,
        *,
        tool_class: str,
        detail: str = "",
        message: str = "",
        live: bool = False,
        request_id: str = "",
        tool_name: str = "",
    ) -> dict[str, Any]:
        """Park mid-run for a tool Allow / Always / Deny card.

        Adapters call this when ``tool_class_decision`` returns ``ask``.
        Unknown classes should be denied by the adapter before calling.
        ``live=True`` keeps the worker blocked until ``gate_result_for``.
        Always remembers the **exact** tool name when provided.
        """

        import time

        from agent_discord.orchestration.ask_gate import (
            GATE_KIND_TOOL,
            gate_meta_payload,
            normalize_tool_class,
            tool_gate_card,
        )

        klass = normalize_tool_class(tool_class)
        if klass is None:
            return {
                "action": "raise_tool_gate",
                "run_id": run_id,
                "status": "denied",
                "summary": "Denied. Unknown tool class.",
                "gate_class": (tool_class or "").strip(),
            }
        run = self.store.get_run(run_id) or {}
        task_id = str(run.get("task_id") or "")
        if not task_id:
            return {"action": "raise_tool_gate", "run_id": run_id, "status": "missing"}
        task = self.store.get_task(task_id) or {}
        reader = getattr(self.store, "task_metadata", None)
        meta = reader(task_id) if callable(reader) else {}
        if not isinstance(meta, dict):
            meta = {}
        parked_ms = int(time.time() * 1000)
        exact = (tool_name or "").strip() or (tool_class or "").strip()
        patch = gate_meta_payload(
            kind=GATE_KIND_TOOL,
            tool_class=klass,
            tool_name=exact,
            detail=detail,
            parked_at_ms=parked_ms,
            live=live,
            request_id=request_id,
        )
        channel_id = str(task.get("channel_id") or meta.get("channel_id") or "").strip()
        thread_id = str(task.get("thread_id") or meta.get("thread_id") or "").strip() or None
        patch["channel_id"] = channel_id
        patch["thread_id"] = thread_id
        merger = getattr(self.store, "merge_task_metadata", None)
        if callable(merger):
            merger(task_id, patch)
        summary = f"Waiting for Allow on `{klass}`."
        try:
            self.store.update_run(run_id, status=TaskStatus.PENDING, summary=summary)
        except Exception:
            pass
        self._run_status[run_id] = TaskStatus.PENDING
        card = tool_gate_card(
            run_id, tool_class=klass, detail=detail, message=message or summary
        )
        self._paint_gate_card(
            card,
            channel_id=channel_id,
            thread_id=thread_id,
            task_id=task_id,
            meta=meta,
            stage=reactive_paint(awaiting_approval=True).stage,
        )
        self._set_presence("idle", "Discord OS")
        return {
            "action": "raise_tool_gate",
            "run_id": run_id,
            "status": "parked",
            "gate_kind": GATE_KIND_TOOL,
            "gate_class": klass,
            "gate_live": bool(live),
            "gate_request_id": (request_id or "").strip(),
            "summary": summary,
        }

    def raise_ask_user(
        self,
        run_id: str,
        *,
        question: str,
        options: Sequence[Any] = (),
        header: str = "Need input",
        live: bool = False,
        request_id: str = "",
        allow_multiple: bool = False,
    ) -> dict[str, Any]:
        """Park mid-run for an AskUserQuestion Discord card.

        ``live=True`` keeps the worker blocked until an option or Deny.
        ``allow_multiple=True`` parks a multi-select Confirm row (toggle
        options, then Confirm) instead of resolving on the first tap.
        """

        import time

        from agent_discord.orchestration.ask_gate import (
            GATE_KIND_ASK,
            ask_user_question_card,
            gate_meta_payload,
        )

        run = self.store.get_run(run_id) or {}
        task_id = str(run.get("task_id") or "")
        if not task_id:
            return {"action": "raise_ask_user", "run_id": run_id, "status": "missing"}
        opts = tuple(options or ())
        if not opts:
            return {
                "action": "raise_ask_user",
                "run_id": run_id,
                "status": "denied",
                "summary": "Denied. No options provided.",
            }
        task = self.store.get_task(task_id) or {}
        reader = getattr(self.store, "task_metadata", None)
        meta = reader(task_id) if callable(reader) else {}
        if not isinstance(meta, dict):
            meta = {}
        parked_ms = int(time.time() * 1000)
        patch = gate_meta_payload(
            kind=GATE_KIND_ASK,
            tool_class="ask",
            question=question,
            options=opts,
            parked_at_ms=parked_ms,
            live=live,
            request_id=request_id,
            allow_multiple=bool(allow_multiple),
        )
        channel_id = str(task.get("channel_id") or meta.get("channel_id") or "").strip()
        thread_id = str(task.get("thread_id") or meta.get("thread_id") or "").strip() or None
        patch["channel_id"] = channel_id
        patch["thread_id"] = thread_id
        merger = getattr(self.store, "merge_task_metadata", None)
        if callable(merger):
            merger(task_id, patch)
        summary = "Waiting for an answer."
        try:
            self.store.update_run(run_id, status=TaskStatus.PENDING, summary=summary)
        except Exception:
            pass
        self._run_status[run_id] = TaskStatus.PENDING
        card = ask_user_question_card(
            run_id,
            question=question,
            options=opts,
            header=header,
            allow_multiple=bool(allow_multiple),
            selected=(),
        )
        self._paint_gate_card(
            card,
            channel_id=channel_id,
            thread_id=thread_id,
            task_id=task_id,
            meta=meta,
            stage=reactive_paint(awaiting_approval=True).stage,
        )
        self._set_presence("idle", "Discord OS")
        return {
            "action": "raise_ask_user",
            "run_id": run_id,
            "status": "parked",
            "gate_kind": GATE_KIND_ASK,
            "gate_live": bool(live),
            "gate_multi": bool(allow_multiple),
            "gate_request_id": (request_id or "").strip(),
            "summary": summary,
        }

    def raise_plan_approve(
        self,
        run_id: str,
        *,
        plan_text: str = "",
        summary: str = "",
        plan_status: str = "ready",
        message: str = "",
    ) -> dict[str, Any]:
        """Park after plan-ready for Approve / Cancel (no Always).

        Adapters call this when ``plan_ready_decision`` returns ``ask``.
        Empty / unknown plan fails closed (denied) — do not invent a plan.
        """

        import time

        from agent_discord.orchestration.plan_approve import (
            GATE_KIND_PLAN,
            plan_approve_card,
            plan_meta_payload,
            plan_ready_decision,
        )
        from agent_discord.orchestration.reactive import reactive_paint

        decision = plan_ready_decision(plan_text, plan_status=plan_status)
        if decision.decision == "deny":
            return {
                "action": "raise_plan_approve",
                "run_id": run_id,
                "status": "denied",
                "summary": f"Denied. {decision.reason or 'unknown plan'}.",
                "gate_kind": GATE_KIND_PLAN,
            }
        run = self.store.get_run(run_id) or {}
        task_id = str(run.get("task_id") or "")
        if not task_id:
            return {"action": "raise_plan_approve", "run_id": run_id, "status": "missing"}
        task = self.store.get_task(task_id) or {}
        reader = getattr(self.store, "task_metadata", None)
        meta = reader(task_id) if callable(reader) else {}
        if not isinstance(meta, dict):
            meta = {}
        parked_ms = int(time.time() * 1000)
        patch = plan_meta_payload(
            plan_text=decision.plan_text,
            summary=summary,
            parked_at_ms=parked_ms,
        )
        channel_id = str(task.get("channel_id") or meta.get("channel_id") or "").strip()
        thread_id = str(task.get("thread_id") or meta.get("thread_id") or "").strip() or None
        patch["channel_id"] = channel_id
        patch["thread_id"] = thread_id
        merger = getattr(self.store, "merge_task_metadata", None)
        if callable(merger):
            merger(task_id, patch)
        spoken_summary = "Waiting for Approve to implement."
        try:
            self.store.update_run(run_id, status=TaskStatus.PENDING, summary=spoken_summary)
        except Exception:
            pass
        self._run_status[run_id] = TaskStatus.PENDING
        card = plan_approve_card(
            run_id,
            plan_text=decision.plan_text,
            message=message or spoken_summary,
            summary=summary,
        )
        self._paint_gate_card(
            card,
            channel_id=channel_id,
            thread_id=thread_id,
            task_id=task_id,
            meta=meta,
            stage=reactive_paint(awaiting_plan=True).stage,
        )
        self._set_presence("idle", "Discord OS")
        return {
            "action": "raise_plan_approve",
            "run_id": run_id,
            "status": "parked",
            "gate_kind": GATE_KIND_PLAN,
            "summary": spoken_summary,
        }

    def _resolve_plan_gate(
        self,
        run_id: str,
        verb: str,
        *,
        spoken: str = "",
    ) -> dict[str, Any]:
        from agent_discord.orchestration.plan_approve import (
            APPROVED_PLAN_SPOKEN,
            DENIED_PLAN_SPOKEN,
            GATE_KIND_PLAN,
            is_plan_gate_meta,
        )

        run = self.store.get_run(run_id) or {}
        task_id = str(run.get("task_id") or "")
        reader = getattr(self.store, "task_metadata", None)
        meta = reader(task_id) if callable(reader) and task_id else {}
        if not isinstance(meta, dict) or not meta.get("awaiting_gate"):
            return {"action": verb, "run_id": run_id, "status": "missing"}
        if not is_plan_gate_meta(meta) and str(meta.get("gate_kind") or "") != GATE_KIND_PLAN:
            return {"action": verb, "run_id": run_id, "status": "ignored"}
        if verb == "approve":
            out = self._finish_gate(
                run_id,
                result="allow",
                answer="",
                spoken=spoken or APPROVED_PLAN_SPOKEN,
                action="approve",
            )
            # Mark plan approved so a follow-up implement can skip re-plan park.
            merger = getattr(self.store, "merge_task_metadata", None)
            if callable(merger) and task_id:
                try:
                    merger(
                        task_id,
                        {
                            "plan_approved": True,
                            "awaiting_plan": False,
                            "intake_meta": {
                                **dict(meta.get("intake_meta") or {}),
                                "approved": True,
                                "plan_approved": True,
                            },
                        },
                    )
                except Exception:
                    pass
            return out
        # deny / cancel
        return self._finish_gate(
            run_id,
            result="deny",
            answer="",
            spoken=spoken or DENIED_PLAN_SPOKEN,
            action="deny" if verb == "deny" else verb,
            failed=True,
        )

    def request_tool_hold(
        self,
        run_id: str,
        tool_name: str,
        *,
        detail: str = "",
        timeout_seconds: float | None = None,
        poll_seconds: float = 0.05,
        sleeper: Any = None,
        clock: Any = None,
    ) -> dict[str, Any]:
        """Block this worker until Allow / Deny / Always or timeout.

        In-process canUseTool. Parks a Discord card when
        ``tool_class_decision`` returns ``ask``. Fail closed on timeout.
        """

        from agent_discord.orchestration.gate_hook import hold_tool_decision

        held = hold_tool_decision(
            self.store,
            self,
            run_id=run_id,
            tool_name=tool_name,
            detail=detail,
            timeout_seconds=timeout_seconds,
            poll_seconds=poll_seconds,
            sleeper=sleeper,
            clock=clock,
        )
        return {
            "run_id": run_id,
            "request_id": held.request_id,
            "decision": held.decision,
            "gate_result": held.decision,
            "gate_answer": held.gate_answer,
            "reason": held.reason,
            "tool_class": held.tool_class,
        }

    def request_plan_hold(
        self,
        run_id: str,
        *,
        plan_text: str = "",
        plan_status: str = "ready",
        summary: str = "",
        timeout_seconds: float | None = None,
        poll_seconds: float = 0.05,
        sleeper: Any = None,
        clock: Any = None,
    ) -> dict[str, Any]:
        """Block this worker until plan Approve / Cancel or timeout.

        ExitPlanMode live path. Parks Approve / Cancel (no Always). Fail
        closed on empty plan / deny / timeout.
        """

        from agent_discord.orchestration.gate_hook import hold_plan_decision

        held = hold_plan_decision(
            self.store,
            self,
            run_id=run_id,
            plan_text=plan_text,
            plan_status=plan_status,
            summary=summary,
            timeout_seconds=timeout_seconds,
            poll_seconds=poll_seconds,
            sleeper=sleeper,
            clock=clock,
        )
        return {
            "run_id": run_id,
            "request_id": held.request_id,
            "decision": held.decision,
            "gate_result": held.decision,
            "gate_answer": held.gate_answer,
            "reason": held.reason,
            "tool_class": held.tool_class or "plan",
            "gate_kind": "plan_approve",
        }

    def gate_result_for(self, run_id: str) -> dict[str, Any]:
        """Adapter poll: gate_result / gate_answer from task metadata."""

        run = self.store.get_run(run_id) or {}
        task_id = str(run.get("task_id") or "")
        reader = getattr(self.store, "task_metadata", None)
        meta = reader(task_id) if callable(reader) and task_id else {}
        if not isinstance(meta, dict):
            meta = {}
        return {
            "run_id": run_id,
            "awaiting_gate": bool(meta.get("awaiting_gate")),
            "gate_kind": str(meta.get("gate_kind") or ""),
            "gate_class": str(meta.get("gate_class") or ""),
            "gate_result": str(meta.get("gate_result") or ""),
            "gate_answer": str(meta.get("gate_answer") or ""),
        }

    def _task_awaiting_gate(self, run_id: str) -> bool:
        run = self.store.get_run(run_id) or {}
        task_id = str(run.get("task_id") or "")
        reader = getattr(self.store, "task_metadata", None)
        meta = reader(task_id) if callable(reader) and task_id else {}
        return isinstance(meta, dict) and bool(meta.get("awaiting_gate"))

    def _gate_kind(self, run_id: str) -> str:
        run = self.store.get_run(run_id) or {}
        task_id = str(run.get("task_id") or "")
        reader = getattr(self.store, "task_metadata", None)
        meta = reader(task_id) if callable(reader) and task_id else {}
        if not isinstance(meta, dict):
            return ""
        return str(meta.get("gate_kind") or "")

    def _resolve_ask_option(self, run_id: str, option_index: int) -> dict[str, Any]:
        from agent_discord.orchestration.ask_gate import GATE_KIND_ASK

        run = self.store.get_run(run_id) or {}
        task_id = str(run.get("task_id") or "")
        reader = getattr(self.store, "task_metadata", None)
        meta = reader(task_id) if callable(reader) and task_id else {}
        if not isinstance(meta, dict) or not meta.get("awaiting_gate"):
            return {"action": "ask", "run_id": run_id, "status": "missing"}
        if str(meta.get("gate_kind") or "") != GATE_KIND_ASK:
            return {"action": "ask", "run_id": run_id, "status": "ignored"}
        if meta.get("gate_multi"):
            return self._toggle_ask_option(run_id, option_index)
        options = meta.get("gate_options") if isinstance(meta.get("gate_options"), list) else []
        if option_index < 0 or option_index >= len(options):
            return {"action": "ask", "run_id": run_id, "status": "missing"}
        opt = options[option_index] if isinstance(options[option_index], dict) else {}
        answer = str(opt.get("label") or "").strip() or f"option-{option_index}"
        return self._finish_gate(
            run_id,
            result="allow",
            answer=answer,
            spoken=f"Answered: {answer}",
            action="ask",
        )

    def _toggle_ask_option(self, run_id: str, option_index: int) -> dict[str, Any]:
        """Multi-select: toggle one option and re-paint; do not resolve yet."""

        from agent_discord.orchestration.ask_gate import (
            GATE_KIND_ASK,
            ask_user_question_card,
            coerce_selected_indices,
            format_ask_answer,
        )
        from agent_discord.orchestration.reactive import reactive_paint

        run = self.store.get_run(run_id) or {}
        task_id = str(run.get("task_id") or "")
        reader = getattr(self.store, "task_metadata", None)
        meta = reader(task_id) if callable(reader) and task_id else {}
        if not isinstance(meta, dict) or not meta.get("awaiting_gate"):
            return {"action": "ask", "run_id": run_id, "status": "missing"}
        if str(meta.get("gate_kind") or "") != GATE_KIND_ASK or not meta.get("gate_multi"):
            return {"action": "ask", "run_id": run_id, "status": "ignored"}
        options = meta.get("gate_options") if isinstance(meta.get("gate_options"), list) else []
        if option_index < 0 or option_index >= len(options):
            return {"action": "ask", "run_id": run_id, "status": "missing"}
        chosen = coerce_selected_indices(meta.get("gate_selected"), option_count=len(options))
        if option_index in chosen:
            chosen = [i for i in chosen if i != option_index]
        else:
            chosen = sorted([*chosen, option_index])
        merger = getattr(self.store, "merge_task_metadata", None)
        if callable(merger) and task_id:
            try:
                merger(task_id, {"gate_selected": chosen})
            except Exception:
                pass
        meta = dict(meta)
        meta["gate_selected"] = chosen
        channel_id = str(meta.get("channel_id") or "").strip()
        thread_id = str(meta.get("thread_id") or "").strip() or None
        question = str(meta.get("gate_question") or "Choose one.")
        card = ask_user_question_card(
            run_id,
            question=question,
            options=options,
            allow_multiple=True,
            selected=chosen,
        )
        self._paint_gate_card(
            card,
            channel_id=channel_id,
            thread_id=thread_id,
            task_id=task_id,
            meta=meta,
            stage=reactive_paint(awaiting_approval=True).stage,
        )
        answer_preview = format_ask_answer(options, chosen)
        return {
            "action": "ask",
            "run_id": run_id,
            "status": "toggled",
            "gate_selected": chosen,
            "gate_answer": answer_preview,
            "summary": (
                f"Selected: {answer_preview}" if answer_preview else "Select options, then Confirm."
            ),
        }

    def _confirm_ask_multi(self, run_id: str) -> dict[str, Any]:
        """Multi-select Confirm — finish with joined labels, or stay parked if empty."""

        from agent_discord.orchestration.ask_gate import (
            GATE_KIND_ASK,
            coerce_selected_indices,
            format_ask_answer,
        )

        rid = (run_id or "").strip()
        run = self.store.get_run(rid) or {}
        task_id = str(run.get("task_id") or "")
        reader = getattr(self.store, "task_metadata", None)
        meta = reader(task_id) if callable(reader) and task_id else {}
        if not isinstance(meta, dict) or not meta.get("awaiting_gate"):
            return {"action": "ask-confirm", "run_id": rid, "status": "missing"}
        if str(meta.get("gate_kind") or "") != GATE_KIND_ASK or not meta.get("gate_multi"):
            return {"action": "ask-confirm", "run_id": rid, "status": "ignored"}
        options = meta.get("gate_options") if isinstance(meta.get("gate_options"), list) else []
        chosen = coerce_selected_indices(meta.get("gate_selected"), option_count=len(options))
        if not chosen:
            return {
                "action": "ask-confirm",
                "run_id": rid,
                "status": "ignored",
                "summary": "Need: select at least one option, then Confirm.",
            }
        answer = format_ask_answer(options, chosen)
        if not answer:
            return {
                "action": "ask-confirm",
                "run_id": rid,
                "status": "ignored",
                "summary": "Need: select at least one option, then Confirm.",
            }
        return self._finish_gate(
            rid,
            result="allow",
            answer=answer,
            spoken=f"Answered: {answer}",
            action="ask-confirm",
        )

    def _resolve_tool_gate(
        self,
        run_id: str,
        verb: str,
        *,
        spoken: str = "",
    ) -> dict[str, Any]:
        from agent_discord.orchestration.ask_gate import (
            ALLOWED_TOOL_SPOKEN,
            ALWAYS_TOOL_SPOKEN,
            DENIED_ASK_SPOKEN,
            DENIED_TOOL_SPOKEN,
            GATE_KIND_ASK,
        )
        from agent_discord.orchestration.service import (
            set_tool_class_session_allow,
            set_tool_exact_session_allow,
        )

        run = self.store.get_run(run_id) or {}
        task_id = str(run.get("task_id") or "")
        reader = getattr(self.store, "task_metadata", None)
        meta = reader(task_id) if callable(reader) and task_id else {}
        if not isinstance(meta, dict) or not meta.get("awaiting_gate"):
            return {"action": verb, "run_id": run_id, "status": "missing"}
        kind = str(meta.get("gate_kind") or "")
        klass = str(meta.get("gate_class") or "").strip()
        exact = str(meta.get("gate_tool") or "").strip() or klass
        task = self.store.get_task(task_id) or {}
        scope = (
            str(task.get("thread_id") or meta.get("thread_id") or "").strip()
            or str(task.get("channel_id") or meta.get("channel_id") or "").strip()
        )
        if verb == "always":
            # Exact-tool Always: remember the concrete tool, never a wildcard.
            remembered = False
            if exact and scope:
                remembered = set_tool_exact_session_allow(self.store, exact, scope)
            # Fail closed on wildcards — do not fall back to class-wide Always.
            if not remembered and klass and scope and exact == klass:
                # Only when the parked tool *is* the class token itself.
                set_tool_class_session_allow(self.store, klass, scope)
                remembered = True
            return self._finish_gate(
                run_id,
                result="always",
                answer="",
                spoken=spoken or ALWAYS_TOOL_SPOKEN,
                action="always",
                session_allow=scope if remembered else "",
            )
        if verb == "approve":
            return self._finish_gate(
                run_id,
                result="allow",
                answer="",
                spoken=spoken or ALLOWED_TOOL_SPOKEN,
                action="approve",
            )
        # deny
        deny_spoken = spoken or (
            DENIED_ASK_SPOKEN if kind == GATE_KIND_ASK else DENIED_TOOL_SPOKEN
        )
        return self._finish_gate(
            run_id,
            result="deny",
            answer="",
            spoken=deny_spoken,
            action="deny",
            failed=True,
        )

    def _finish_gate(
        self,
        run_id: str,
        *,
        result: str,
        answer: str,
        spoken: str,
        action: str,
        session_allow: str = "",
        failed: bool = False,
    ) -> dict[str, Any]:
        run = self.store.get_run(run_id) or {}
        task_id = str(run.get("task_id") or "")
        reader = getattr(self.store, "task_metadata", None)
        meta = reader(task_id) if callable(reader) and task_id else {}
        if not isinstance(meta, dict):
            meta = {}
        merger = getattr(self.store, "merge_task_metadata", None)
        live = bool(meta.get("gate_live"))
        request_id = str(meta.get("gate_request_id") or "").strip()
        if callable(merger) and task_id:
            try:
                merger(
                    task_id,
                    {
                        "awaiting_approval": False,
                        "awaiting_gate": False,
                        "awaiting_plan": False,
                        "gate_result": result,
                        "gate_answer": answer,
                    },
                )
            except Exception:
                pass
        if live:
            self._write_live_gate_result(
                run_id,
                request_id=request_id,
                result=result,
                answer=answer,
                tool_class=str(meta.get("gate_class") or ""),
            )
            # Worker is still mid-cook — do not settle the run.
            try:
                self.store.update_run(run_id, status=TaskStatus.RUNNING, summary=spoken)
            except Exception:
                pass
            self._run_status[run_id] = TaskStatus.RUNNING
            if self.post_progress_to_discord and self.discord is not None:
                task = self.store.get_task(task_id) or {}
                channel_id = str(task.get("channel_id") or meta.get("channel_id") or "").strip()
                thread_id = str(task.get("thread_id") or meta.get("thread_id") or "").strip() or None
                card_mid = str(meta.get("card_message_id") or "").strip()
                try:
                    card = reactive_working_card(
                        message=spoken,
                        run_id=run_id,
                        status=TaskStatus.RUNNING,
                    )
                    dest = thread_id or channel_id
                    if card_mid and dest:
                        edit_card(self.discord, dest, card_mid, card)
                    elif channel_id:
                        send_card(self.discord, channel_id, card, thread_id=thread_id)
                except Exception:
                    pass
            out = {
                "action": action,
                "run_id": run_id,
                "status": TaskStatus.RUNNING.value,
                "summary": spoken,
                "gate_result": result,
                "gate_answer": answer,
                "gate_live": True,
            }
            if session_allow:
                out["session_allow"] = session_allow
            return out
        status = TaskStatus.FAILED if failed else TaskStatus.COMPLETED
        try:
            self.store.update_run(
                run_id,
                status=status,
                summary=spoken,
                error=spoken if failed else "",
            )
        except Exception:
            pass
        self._run_status[run_id] = status
        if self.post_progress_to_discord and self.discord is not None:
            task = self.store.get_task(task_id) or {}
            channel_id = str(task.get("channel_id") or meta.get("channel_id") or "").strip()
            thread_id = str(task.get("thread_id") or meta.get("thread_id") or "").strip() or None
            card_mid = str(meta.get("card_message_id") or "").strip()
            card = reactive_receipt_card(
                RunReceipt(
                    task_id=task_id,
                    run_id=run_id,
                    status=status,
                    summary=spoken,
                    error=spoken if failed else "",
                ),
                has_thread=bool(thread_id),
            )
            try:
                dest = thread_id or channel_id
                if card_mid and dest:
                    edit_card(self.discord, dest, card_mid, card)
                elif channel_id:
                    send_card(self.discord, channel_id, card, thread_id=thread_id)
            except Exception:
                pass
        self._set_presence("idle", "Discord OS")
        out = {
            "action": action,
            "run_id": run_id,
            "status": status.value,
            "summary": spoken,
            "gate_result": result,
            "gate_answer": answer,
        }
        if session_allow:
            out["session_allow"] = session_allow
        return out

    def _write_live_gate_result(
        self,
        run_id: str,
        *,
        request_id: str,
        result: str,
        answer: str = "",
        tool_class: str = "",
    ) -> None:
        if not request_id:
            return
        try:
            from agent_discord.orchestration.gate_hook import (
                GateHoldResult,
                complete_request,
                resolve_run_gate_dir,
            )

            run_dir = resolve_run_gate_dir(
                run_id=run_id,
                workspace=self.workspace,
                store=self.store,
            )
            complete_request(
                run_dir,
                GateHoldResult(
                    request_id=request_id,
                    decision=result,
                    gate_answer=answer,
                    reason=result,
                    tool_class=tool_class,
                ),
            )
        except Exception:
            pass

    def _paint_gate_card(
        self,
        card: Any,
        *,
        channel_id: str,
        thread_id: Optional[str],
        task_id: str,
        meta: Mapping[str, Any],
        stage: str = "parked",
    ) -> None:
        if not (self.post_progress_to_discord and self.discord is not None and channel_id):
            return
        merger = getattr(self.store, "merge_task_metadata", None)
        card_mid = str(meta.get("card_message_id") or "").strip()
        try:
            dest = thread_id or channel_id
            if card_mid and dest:
                edit_card(self.discord, dest, card_mid, card)
            else:
                sent = send_card(
                    self.discord,
                    channel_id,
                    card,
                    thread_id=thread_id,
                )
                mid = ""
                if isinstance(sent, dict):
                    mid = str(sent.get("id") or sent.get("message_id") or "").strip()
                elif sent is not None:
                    mid = str(getattr(sent, "message_id", "") or getattr(sent, "id", "") or "").strip()
                if mid and callable(merger):
                    merger(task_id, {"card_message_id": mid})
        except Exception:
            pass

    def _park_for_approval(
        self,
        intake: TaskIntake,
        *,
        task_id: str,
        run_id: str,
        thread_id: Optional[str] = None,
        live: Optional[_LiveCard] = None,
    ) -> RunReceipt:
        job_thread = (thread_id or intake.thread_id or "").strip() or None
        merger = getattr(self.store, "merge_task_metadata", None)
        if callable(merger):
            merger(
                task_id,
                {
                    "awaiting_approval": True,
                    "parked_at_ms": int(time.time() * 1000),
                    "text": intake.text,
                    "channel_id": intake.channel_id,
                    "workspace_id": intake.workspace_id,
                    "guild_id": intake.guild_id,
                    "thread_id": job_thread,
                    "message_id": intake.message_id,
                    "requester_id": intake.requester_id,
                    "intake_meta": dict(intake.metadata or {}),
                },
            )
        summary = "Waiting for Allow to write."
        try:
            self.store.update_run(run_id, status=TaskStatus.PENDING, summary=summary)
        except Exception:
            pass
        self._run_status[run_id] = TaskStatus.PENDING
        receipt = RunReceipt(
            task_id=task_id,
            run_id=run_id,
            status=TaskStatus.PENDING,
            summary=summary,
        )
        if self.post_progress_to_discord and self.discord is not None:
            card = reactive_working_card(
                message=summary,
                run_id=run_id,
                status=TaskStatus.PENDING,
            )
            try:
                if live is not None:
                    live.paint(card, stage=reactive_paint(TaskStatus.PENDING).stage)
                    if live.message_id and callable(merger):
                        merger(task_id, {"card_message_id": live.message_id})
                else:
                    send_card(
                        self.discord,
                        intake.channel_id,
                        card,
                        thread_id=job_thread,
                    )
            except Exception:
                pass
        self._set_presence("idle", "Discord OS")
        return receipt

    def _halted_receipt(self, intake: TaskIntake) -> RunReceipt:
        return RunReceipt(
            task_id="",
            run_id="",
            status=TaskStatus.FAILED,
            summary="spend halted",
            error="spend halted",
        )

    def _record_usage_spend(
        self,
        workspace_id: str,
        run_id: str,
        usage: UsageReceipt,
    ) -> None:
        from agent_discord.orchestration.service import (
            is_spend_halted,
            mark_spend_cost_known,
            provider_cost_usd,
            set_spend_halted,
        )

        # Honest OpenRouter/PM-adapter: only record when cost_usd present.
        # Omitted cost must not paint Halt / digest as $0.
        usd = provider_cost_usd(usage)
        if usd is None:
            return
        mark_spend_cost_known(self.store, True)
        writer = getattr(self.store, "record_spend", None)
        if callable(writer) and usd > 0:
            try:
                writer(workspace_id, run_id, usd)
            except Exception:
                return
        if is_spend_halted(self.store, workspace_id):
            set_spend_halted(self.store, True)

    def _set_presence(self, status: str, name: str) -> None:
        sender = self.presence
        if not callable(sender):
            return
        label = " ".join((name or "").split())[:80] or "Discord OS"
        if status == "dnd" and not label.startswith("Working"):
            label = f"Working on {label}"
        try:
            sender(status, label)
        except Exception:
            pass

    def _is_rate_limit(self, error: Optional[str]) -> bool:
        raw = (error or "").lower()
        return any(marker in raw for marker in _RATE_LIMIT_MARKERS)

    def _sleep_retry(self) -> None:
        delay = max(0.0, float(self.retry_backoff_s))
        if delay:
            time.sleep(delay)

    def _rollback_on_red(self, run_id: str) -> None:
        """Best-effort reverse of the uncommitted workspace diff after a failed run."""

        if self.workspace is None:
            return
        root = Path(self.workspace)
        if not (root / ".git").exists():
            return
        try:
            import subprocess

            snapped = subprocess.run(
                ["git", "diff", "--binary"],
                cwd=str(root),
                check=False,
                capture_output=True,
                text=True,
                timeout=20,
            )
        except Exception:
            return
        diff = snapped.stdout or ""
        if not diff.strip():
            stored = self._checkpoints.get(run_id) or {}
            diff = str(stored.get("diff") or "")
        if not diff.strip():
            return
        path = root / ".agent-discord" / "checkpoints" / f"{run_id}.patch"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(diff, encoding="utf-8")
            self._checkpoints[run_id] = {"diff": diff}
            subprocess.run(
                ["git", "apply", "-R", "--whitespace=nowarn", str(path)],
                cwd=str(root),
                check=False,
                capture_output=True,
                text=True,
                timeout=20,
            )
        except Exception:
            return

    def _duplicate_receipt(self, message_id: str) -> RunReceipt:
        """Return prior receipt or an explicit ignored-duplicate result (no re-dispatch)."""
        prior = self.store.get_inbound_message(message_id) or {}
        run_id = prior.get("run_id") or ""
        task_id = prior.get("task_id") or ""
        if run_id:
            run = self.store.get_run(str(run_id))
            if run:
                usage = None
                if run.get("usage_json"):
                    import json

                    try:
                        raw = json.loads(run["usage_json"])
                    except json.JSONDecodeError:
                        raw = None
                    if isinstance(raw, dict):
                        usage = UsageReceipt(
                            model=str(raw.get("model") or run.get("model") or ""),
                            adapter_name=str(
                                raw.get("adapter_name") or run.get("adapter_name") or ""
                            ),
                            input_tokens=raw.get("input_tokens"),
                            output_tokens=raw.get("output_tokens"),
                            metadata=strip_forbidden_keys(dict(raw.get("metadata") or {})),
                        )
                status = TaskStatus(run["status"])
                self._run_status[str(run_id)] = status
                return RunReceipt(
                    task_id=str(run["task_id"]),
                    run_id=str(run_id),
                    status=status,
                    summary=str(
                        run.get("summary")
                        or f"reused prior receipt for duplicate message_id={message_id}"
                    ),
                    usage=usage,
                    error=run.get("error"),
                )
        return RunReceipt(
            task_id=str(task_id or "duplicate"),
            run_id=str(run_id or "duplicate"),
            status=TaskStatus.COMPLETED,
            summary=f"ignored duplicate inbound message_id={message_id}",
            error=None,
        )

    def _record_lineage(
        self,
        task_id: str,
        run_id: str,
        step: str,
        body: str,
        *,
        artifact_id: str = "",
        parent_keys: tuple[str, ...] = (),
    ) -> str:
        from agent_discord.orchestration.lineage import record_node

        parents = list(parent_keys)
        tip = self._lineage_tips.get(run_id)
        if tip and tip not in parents:
            parents.insert(0, tip)
        key = record_node(
            self.store,
            run_id=run_id,
            task_id=task_id,
            step=step,
            body=body,
            parent_keys=parents,
            artifact_id=artifact_id,
        )
        self._lineage_tips[run_id] = key
        return key

    def _persist_text_artifact(
        self,
        text: str,
        *,
        kind: str,
        intake: TaskIntake,
        task_id: str,
        run_id: str,
    ) -> ArtifactRef:
        body = (text or "").encode("utf-8")
        digest = hashlib.sha256(body).hexdigest()
        artifact_id = uuid4().hex
        filename = f"{kind}.md"
        provenance = {
            "run_id": run_id,
            "task_id": task_id,
            "channel_id": intake.channel_id,
        }
        ref = ArtifactRef(
            artifact_id=artifact_id,
            kind=kind,
            path="",
            provenance=provenance,
            sha256=digest,
            size=len(body),
            filename=filename,
        )
        self.store.add_artifact(
            artifact_id=artifact_id,
            task_id=task_id,
            run_id=run_id,
            kind=kind,
            filename=filename,
            sha256=digest,
            size=len(body),
            provenance=provenance,
        )
        return ref

    def _persist_artifact(
        self,
        art: ArtifactRef,
        *,
        intake: TaskIntake,
        task_id: str,
        run_id: str,
    ) -> ArtifactRef:
        provenance = (
            strip_forbidden_keys(dict(art.provenance))
            if isinstance(art.provenance, Mapping)
            else {}
        )
        if not isinstance(provenance, dict):
            provenance = {}
        persisted = art
        if art.message_id and art.attachment_id:
            persisted = art
        elif self.discord is not None and art.path and Path(art.path).is_file():
            try:
                data = Path(art.path).read_bytes()
                store = DiscordObjectStore(
                    self.discord,
                    max_bytes=self.max_object_bytes,
                    workspace=self.workspace,
                )
                ref = store.put_or_overflow(
                    data,
                    channel_id=intake.channel_id,
                    filename=art.filename or Path(art.path).name,
                    kind=art.kind,
                    thread_id=intake.thread_id,
                    guild_id=intake.guild_id,
                    author_id=intake.requester_id,
                )
                if intake.guild_id:
                    provenance = {**provenance, "guild_id": intake.guild_id}
                if intake.thread_id:
                    provenance = {**provenance, "thread_id": intake.thread_id}
                persisted = ArtifactRef(
                    artifact_id=art.artifact_id,
                    kind=ref.kind,
                    path=art.path,
                    provenance=provenance,
                    channel_id=ref.channel_id,
                    message_id=ref.message_id,
                    attachment_id=ref.attachment_id,
                    sha256=ref.sha256,
                    size=ref.size,
                    filename=ref.filename,
                )
            except Exception as exc:
                provenance = {**provenance, "object_store_error": str(exc)}
                persisted = ArtifactRef(
                    artifact_id=art.artifact_id,
                    kind=art.kind,
                    path=art.path,
                    provenance=provenance,
                    filename=art.filename,
                    size=art.size,
                    sha256=art.sha256,
                )
        self.store.add_artifact(
            artifact_id=persisted.artifact_id,
            task_id=task_id,
            run_id=run_id,
            kind=persisted.kind,
            path=persisted.path or "",
            provenance=persisted.provenance
            if isinstance(persisted.provenance, Mapping)
            else provenance,
            channel_id=persisted.channel_id,
            message_id=persisted.message_id,
            attachment_id=persisted.attachment_id,
            filename=persisted.filename,
            sha256=persisted.sha256,
            size=persisted.size,
        )
        return persisted

    def _optional_research_context(self, intake: TaskIntake) -> Optional[dict[str, Any]]:
        """Attach research claims/negatives only when a research store is configured."""
        if self.research is None:
            return None
        claims = self.research.list_claims(workspace_id=intake.workspace_id, limit=8)
        negatives = self.research.list_negative_findings(
            workspace_id=intake.workspace_id, limit=8
        )
        if not claims and not negatives:
            return None
        return {
            "claim_count": len(claims),
            "negative_count": len(negatives),
            "claims": [
                {
                    "fingerprint": c.fingerprint,
                    "status": c.status.value,
                    "scope": c.scope,
                    "claim_text": c.claim_text[:400],
                }
                for c in claims
            ],
            "negative_findings": [
                {
                    "fingerprint": n.fingerprint,
                    "scope": n.scope,
                    "claim_text": n.claim_text[:400],
                }
                for n in negatives
            ],
        }

    def _settle_beat(
        self,
        channel_id: str,
        thread_id: Optional[str],
        text: str,
    ) -> None:
        if self.discord is None or not thread_id:
            return
        bubbles = _settle_bubbles(text)
        if not bubbles:
            return
        self._post_settle_messages(channel_id, thread_id, bubbles)

    def _post_settle_messages(
        self,
        channel_id: str,
        thread_id: Optional[str],
        bodies: list[str],
    ) -> None:
        """Best-effort thread bubbles. A follow-up failure keeps the first."""

        if self.discord is None or not thread_id:
            return
        poster = getattr(self.discord, "send_message", None)
        if not callable(poster):
            return
        posted = 0
        for body in bodies:
            text = (body or "").strip()
            if not text or not _is_settle_worthy(text):
                continue
            try:
                try:
                    poster(channel_id, text, thread_id=thread_id)
                except TypeError:
                    poster(channel_id, text)
            except Exception:
                return
            posted += 1
            if posted >= SETTLE_MAX_BUBBLES:
                return

    def _close_without_worker(
        self,
        intake: TaskIntake,
        *,
        task_id: str,
        run_id: str,
        summary: str,
        live: _LiveCard,
    ) -> RunReceipt:
        from agent_discord.puppetmaster.backend import public_card_text

        spoken = public_card_text(summary) or summary.strip() or "Done."
        try:
            self.store.update_run(run_id, status=TaskStatus.COMPLETED, summary=spoken)
        except Exception:
            pass
        self._run_status[run_id] = TaskStatus.COMPLETED
        receipt = RunReceipt(
            task_id=task_id,
            run_id=run_id,
            status=TaskStatus.COMPLETED,
            summary=spoken,
        )
        if self.post_progress_to_discord and self.discord is not None:
            live.finish(reactive_receipt_card(receipt, has_thread=bool(live.thread_id)), summary=spoken)
        self._react_terminal(intake, TaskStatus.COMPLETED)
        self._set_presence("idle", "Discord OS")
        return receipt

    def _react_intake(self, intake: TaskIntake, emoji: str) -> None:
        if self.discord is None or not intake.message_id or not intake.channel_id:
            return
        adder = getattr(self.discord, "add_reaction", None)
        if not callable(adder):
            return
        try:
            adder(intake.channel_id, intake.message_id, emoji)
        except Exception:
            pass

    def _react_terminal(self, intake: TaskIntake, status: TaskStatus) -> None:
        if status == TaskStatus.COMPLETED:
            self._react_intake(intake, "\u2705")
        elif status in {TaskStatus.FAILED, TaskStatus.CANCELLED}:
            self._react_intake(intake, "\u274c")

    def _thread_bind_spoken(self, error: Optional[str]) -> str:
        if self._is_rate_limit(error):
            return THREAD_BIND_RATE_SPOKEN
        return THREAD_BIND_FAIL_SPOKEN

    def _ensure_job_thread(
        self,
        channel_id: str,
        text: str,
        *,
        message_id: Optional[str] = None,
    ) -> tuple[Optional[str], Optional[str]]:
        """Create a Discord job thread for a channel-parent ask.

        Returns ``(thread_id, error)``. Does not retry on rate limit — caller
        speaks Need honestly. When ``message_id`` is empty (HOST Ask modal),
        posts a channel starter then starts the thread from that message.
        """

        if self.discord is None:
            return None, "no discord"
        cid = (channel_id or "").strip()
        if not cid:
            return None, "no channel"
        starter_mid = str(message_id or "").strip()
        if not starter_mid:
            body = (text or "job").strip() or "job"
            if len(body) > 1800:
                body = body[:1797] + "..."
            try:
                posted = self.discord.send_message(cid, body)
            except Exception as exc:
                return None, str(exc) or "starter post failed"
            starter_mid = _posted_message_id(posted)
            if not starter_mid:
                return None, "starter post missing id"
        opener = getattr(self.discord, "start_thread_from_message", None)
        if not callable(opener):
            return None, "provider cannot start a thread"
        try:
            title = (text or "job").replace("\n", " ").strip() or "job"
            thread_id = opener(cid, starter_mid, title[:100])
        except Exception as exc:
            return None, str(exc) or "thread create failed"
        tid = str(thread_id or "").strip()
        if not tid:
            return None, "thread create missing id"
        return tid, None

    def _start_job_thread(
        self,
        channel_id: str,
        message_id: str,
        text: str,
    ) -> Optional[str]:
        started, _err = self._ensure_job_thread(
            channel_id, text, message_id=message_id
        )
        return started

    def _post_or_edit_progress(
        self,
        channel_id: str,
        card: Any,
        *,
        thread_id: Optional[str],
        message_id: Optional[str],
    ) -> Optional[str]:
        if self.discord is None:
            return message_id
        dest = thread_id or channel_id
        if message_id:
            try:
                edited = edit_card(self.discord, dest, message_id, card)
                return edited.message_id or message_id
            except Exception:
                return message_id
        try:
            posted = send_card(self.discord, channel_id, card, thread_id=thread_id)
        except Exception:
            return message_id
        if isinstance(posted, list) and posted:
            return posted[-1].message_id or message_id
        if posted is not None:
            return getattr(posted, "message_id", None) or message_id
        return message_id

    def running_run_for_thread(self, thread_id: str) -> Optional[str]:
        """Return the live run_id for a Discord thread, if one is cooking."""

        tid = (thread_id or "").strip()
        if not tid:
            return None
        with self._steer_lock:
            return self._live_threads.get(tid)

    def live_thread_ids(self) -> tuple[str, ...]:
        with self._steer_lock:
            return tuple(self._live_threads.keys())

    def steer(self, run_id: str, text: str) -> bool:
        """Append user text to a running worker. No sibling job, no second card."""

        rid = (run_id or "").strip()
        body = (text or "").strip()
        if not rid or not body:
            return False
        with self._steer_lock:
            live = rid in self._live_threads.values()
            status = self._run_status.get(rid)
        if not live and status != TaskStatus.RUNNING:
            return False
        if status not in (None, TaskStatus.RUNNING, TaskStatus.PROGRESS, TaskStatus.PENDING):
            return False
        with self._steer_lock:
            self._steer_inbox.setdefault(rid, []).append(body)
            self.steer_count += 1
        hook = getattr(self.backend, "steer", None)
        if callable(hook):
            try:
                hook(rid, body)
            except Exception:
                pass
        run = self.store.get_run(rid) or {}
        self._record_lineage(str(run.get("task_id") or ""), rid, "steer", body)
        return True

    def _mark_thread_live(self, thread_id: Optional[str], run_id: str) -> None:
        tid = (thread_id or "").strip()
        rid = (run_id or "").strip()
        if not tid or not rid:
            return
        with self._steer_lock:
            self._live_threads[tid] = rid

    def _release_live_thread(self, thread_id: Optional[str], run_id: str) -> None:
        tid = (thread_id or "").strip()
        rid = (run_id or "").strip()
        with self._steer_lock:
            if tid and self._live_threads.get(tid) == rid:
                self._live_threads.pop(tid, None)
            elif rid:
                for key, value in list(self._live_threads.items()):
                    if value == rid:
                        self._live_threads.pop(key, None)
            self._steer_inbox.pop(rid, None)
        if tid:
            from agent_discord.orchestration.jobs import drop_origin_thread

            drop_origin_thread(tid)

    def _take_steers(self, run_id: str) -> list[str]:
        rid = (run_id or "").strip()
        if not rid:
            return []
        with self._steer_lock:
            return list(self._steer_inbox.pop(rid, []))

    def _active_cook_backend(self, run_id: str) -> Any:
        """Prefer the Path A / per-run cook backend when Cancel must kill remote."""

        rid = (run_id or "").strip()
        return self._cook_backends.get(rid) or self.backend

    def _cancel_live_cook(self, run_id: str) -> dict[str, Any]:
        """Phone Cancel honesty: kill child or speak Cancel unconfirmed (no false paint)."""

        from agent_discord.puppetmaster.cancel_honesty import (
            CANCEL_UNCONFIRMED_SPOKEN,
            cancel_receipt,
        )

        rid = (run_id or "").strip()
        ok = False
        cook = self._active_cook_backend(rid)
        try:
            ok = bool(cook.cancel(rid))
        except Exception:
            ok = False
        # If Path A cook missed, still try the default backend once.
        if not ok and cook is not self.backend:
            try:
                ok = bool(self.backend.cancel(rid))
            except Exception:
                ok = False
        receipt = cancel_receipt(confirmed=ok, run_id=rid)
        if ok:
            self._run_status[rid] = TaskStatus.CANCELLED
            try:
                self.store.update_run(
                    rid, status=TaskStatus.CANCELLED, summary="cancelled", error="cancelled"
                )
            except Exception:
                pass
            run = self.store.get_run(rid) or {}
            task_id = str(run.get("task_id") or "")
            if task_id:
                self._event(
                    task_id,
                    rid,
                    EventKind.CANCEL_REQUESTED,
                    "cancel confirmed",
                    receipt.as_dict(),
                    source="orchestrator",
                )
            self._paint_cancel_outcome(rid, confirmed=True, spoken="cancelled")
            try:
                run_row = self.store.get_run(rid) or {}
                tid = str(run_row.get("task_id") or "")
                task_row = self.store.get_task(tid) if tid else None
                ch = ""
                if isinstance(task_row, dict):
                    ch = str(task_row.get("channel_id") or "").strip()
                if ch:
                    self._refresh_host_jobs_after_rank_change(ch)
            except Exception:
                pass
            out = {"action": "cancel", "run_id": rid, **receipt.as_dict()}
            return out

        # Fail closed honesty: do NOT paint Cancelled / Done as success.
        merger = getattr(self.store, "merge_task_metadata", None)
        run = self.store.get_run(rid) or {}
        task_id = str(run.get("task_id") or "")
        if callable(merger) and task_id:
            try:
                merger(task_id, {"cancellation_pending": True})
            except Exception:
                pass
        if task_id:
            self._event(
                task_id,
                rid,
                EventKind.CANCEL_REQUESTED,
                CANCEL_UNCONFIRMED_SPOKEN,
                receipt.as_dict(),
                source="orchestrator",
            )
        self._paint_cancel_outcome(
            rid, confirmed=False, spoken=CANCEL_UNCONFIRMED_SPOKEN
        )
        return {"action": "cancel", "run_id": rid, **receipt.as_dict()}

    def _paint_cancel_outcome(
        self, run_id: str, *, confirmed: bool, spoken: str
    ) -> None:
        """Update the live card / post spoken honesty. Never lies about Cancelled."""

        if not self.post_progress_to_discord or self.discord is None:
            return
        run = self.store.get_run(run_id) or {}
        task_id = str(run.get("task_id") or "")
        reader = getattr(self.store, "task_metadata", None)
        meta = reader(task_id) if callable(reader) and task_id else {}
        if not isinstance(meta, dict):
            meta = {}
        task = self.store.get_task(task_id) or {}
        channel_id = str(task.get("channel_id") or meta.get("channel_id") or "").strip()
        thread_id = str(task.get("thread_id") or meta.get("thread_id") or "").strip() or None
        card_mid = str(meta.get("card_message_id") or "").strip()
        if not channel_id and not thread_id:
            return
        try:
            if confirmed:
                card = reactive_receipt_card(
                    RunReceipt(
                        task_id=task_id,
                        run_id=run_id,
                        status=TaskStatus.CANCELLED,
                        summary=spoken or "cancelled",
                        error="cancelled",
                    ),
                    has_thread=bool(thread_id),
                )
                dest = thread_id or channel_id
                if card_mid and dest:
                    edit_card(self.discord, dest, card_mid, card)
                elif channel_id:
                    send_card(
                        self.discord,
                        channel_id,
                        card,
                        thread_id=thread_id,
                    )
            else:
                # Spoken only — leave the running card / status alone.
                poster = getattr(self.discord, "send_message", None)
                dest = thread_id or channel_id
                if callable(poster) and dest:
                    poster(dest, spoken)
        except Exception:
            pass

    def cancel(self, run_id: str) -> bool:
        cook = self._active_cook_backend(run_id)
        ok = bool(cook.cancel(run_id))
        if not ok and cook is not self.backend:
            ok = bool(self.backend.cancel(run_id))
        if ok:
            self._run_status[run_id] = TaskStatus.CANCELLED
            run = self.store.get_run(run_id)
            if run:
                self.store.update_run(run_id, status=TaskStatus.CANCELLED, error="cancelled")
                self._event(
                    run["task_id"],
                    run_id,
                    EventKind.CANCEL_REQUESTED,
                    "cancel confirmed",
                    {"confirmed": True, "cancellation_pending": False},
                    source="orchestrator",
                )
        return ok

    def status(self, run_id: str) -> TaskStatus:
        if run_id in self._run_status:
            return self._run_status[run_id]
        backend_status = self._active_cook_backend(run_id).status(run_id)
        run = self.store.get_run(run_id)
        if run:
            return TaskStatus(run["status"])
        return backend_status

    def _event(
        self,
        task_id: str,
        run_id: str,
        kind: EventKind,
        summary: str,
        payload: dict[str, Any],
        *,
        source: str,
    ) -> None:
        self.store.append_event(
            task_id=task_id,
            run_id=run_id,
            kind=kind,
            summary=redact_text_markers(summary),
            payload=strip_forbidden_keys(payload),
            source=source,
            provenance={"component": "AgentOrchestrator"},
        )
