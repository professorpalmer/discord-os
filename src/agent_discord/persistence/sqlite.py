"""Small SQLite store — stdlib only, optional FTS5 when available."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence
from uuid import uuid4

from agent_discord import CLI_OWNER_PREFIX, LEGACY_CLI_OWNER_PREFIX
from agent_discord.contracts import EventKind, JOB_CODE_PREFIX, TaskStatus
from agent_discord.discord.errors import GatewayOwnershipError
from agent_discord.persistence.research import RESEARCH_SCHEMA
from agent_discord.redaction import redact_text_markers, strip_forbidden_keys


SCHEMA = """
CREATE TABLE IF NOT EXISTS workspace_bindings (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    channel_id TEXT NOT NULL,
    guild_id TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(workspace_id, channel_id)
);

CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    channel_id TEXT NOT NULL,
    thread_id TEXT,
    intake_text TEXT NOT NULL,
    status TEXT NOT NULL,
    requester_id TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    job_code TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    model TEXT NOT NULL,
    adapter_name TEXT NOT NULL,
    status TEXT NOT NULL,
    summary TEXT,
    error TEXT,
    usage_json TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(task_id) REFERENCES tasks(task_id)
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    summary TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    source TEXT NOT NULL,
    provenance_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS memory_entries (
    memory_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    channel_id TEXT NOT NULL,
    content TEXT NOT NULL,
    source TEXT NOT NULL,
    provenance_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    path TEXT NOT NULL DEFAULT '',
    channel_id TEXT,
    message_id TEXT,
    attachment_id TEXT,
    filename TEXT,
    sha256 TEXT,
    size INTEGER,
    content_type TEXT,
    provenance_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS seen_messages (
    message_id TEXT PRIMARY KEY,
    channel_id TEXT,
    task_id TEXT,
    run_id TEXT,
    seen_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS gateway_owners (
    bot_token_fingerprint TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    claimed_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS listen_watermarks (
    channel_id TEXT PRIMARY KEY,
    last_created_ms INTEGER,
    last_message_id TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS host_control (
    channel_id TEXT PRIMARY KEY,
    armed INTEGER NOT NULL DEFAULT 1,
    card_message_id TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS preferences (
    workspace_id TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    kind TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(workspace_id, key)
);

CREATE TABLE IF NOT EXISTS operators (
    user_id TEXT PRIMARY KEY,
    role TEXT NOT NULL,
    created_ms INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS operator_roles (
    role_id TEXT PRIMARY KEY,
    created_ms INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS schedules (
    schedule_id TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    prompt TEXT NOT NULL,
    every_s INTEGER NOT NULL,
    next_ms INTEGER NOT NULL,
    created_by TEXT,
    enabled INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS spend_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    usd REAL NOT NULL,
    created_ms INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS lineage_nodes (
    node_key TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    step TEXT NOT NULL,
    parent_keys_json TEXT NOT NULL DEFAULT '[]',
    input_sha256 TEXT NOT NULL,
    artifact_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'complete',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_lineage_run ON lineage_nodes(run_id);

CREATE TABLE IF NOT EXISTS job_pull_requests (
    repo TEXT NOT NULL,
    number INTEGER NOT NULL,
    task_id TEXT NOT NULL,
    branch TEXT NOT NULL DEFAULT '',
    base TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (repo, number)
);
CREATE INDEX IF NOT EXISTS idx_job_pr_task ON job_pull_requests(task_id);

CREATE TABLE IF NOT EXISTS github_wake_events (
    event_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    created_ms INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS github_rules (
    rule_id TEXT PRIMARY KEY,
    prompt TEXT NOT NULL DEFAULT '',
    destination TEXT NOT NULL DEFAULT 'new',
    repo TEXT NOT NULL DEFAULT '',
    branch TEXT NOT NULL DEFAULT '',
    conclusion TEXT NOT NULL DEFAULT '',
    channel_id TEXT NOT NULL DEFAULT '',
    workspace_id TEXT NOT NULL DEFAULT 'default',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_ms INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS inbound_queue (
    queue_id TEXT PRIMARY KEY,
    message_id TEXT NOT NULL UNIQUE,
    channel_id TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    run_id TEXT NOT NULL DEFAULT '',
    workspace_id TEXT NOT NULL DEFAULT 'default',
    author_id TEXT,
    text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    created_ms INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_inbound_queue_open ON inbound_queue(thread_id, status);
"""

PREFERENCE_KINDS = frozenset({"preference", "style", "failure"})
_PROMPT_MEMORY_PER_KIND = 8
_PROMPT_MEMORY_VALUE_CHARS = 160
_PROMPT_MEMORY_BLOCK_CHARS = 1500


class SQLiteStore:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._local = threading.local()
        self._fts_enabled = False

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._connection()
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)
        conn.executescript(RESEARCH_SCHEMA)
        self._migrate_seen_messages(conn)
        self._migrate_artifacts(conn)
        self._migrate_preferences(conn)
        self._migrate_service_tables(conn)
        self._migrate_lineage_nodes(conn)
        self._migrate_job_queue(conn)
        self._migrate_inbound_queue(conn)
        self._fts_enabled = self._try_enable_fts(conn)
        conn.commit()

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    def _connection(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(str(self.path), timeout=30.0)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=30000")
            self._local.conn = conn
        return conn

    def _migrate_seen_messages(self, conn: sqlite3.Connection) -> None:
        cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(seen_messages)").fetchall()
        }
        if "task_id" not in cols:
            conn.execute("ALTER TABLE seen_messages ADD COLUMN task_id TEXT")
        if "run_id" not in cols:
            conn.execute("ALTER TABLE seen_messages ADD COLUMN run_id TEXT")

    def _migrate_artifacts(self, conn: sqlite3.Connection) -> None:
        cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(artifacts)").fetchall()
        }
        for name, decl in (
            ("channel_id", "TEXT"),
            ("message_id", "TEXT"),
            ("attachment_id", "TEXT"),
            ("filename", "TEXT"),
            ("sha256", "TEXT"),
            ("size", "INTEGER"),
            ("content_type", "TEXT"),
        ):
            if name not in cols:
                conn.execute(f"ALTER TABLE artifacts ADD COLUMN {name} {decl}")

    def _migrate_preferences(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS preferences (
                workspace_id TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                kind TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(workspace_id, key)
            )
            """
        )
        cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(preferences)").fetchall()
        }
        for name, decl in (
            ("workspace_id", "TEXT"),
            ("key", "TEXT"),
            ("value", "TEXT"),
            ("kind", "TEXT"),
            ("updated_at", "TEXT"),
        ):
            if name not in cols:
                conn.execute(f"ALTER TABLE preferences ADD COLUMN {name} {decl}")
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_preferences_workspace_key
            ON preferences(workspace_id, key)
            """
        )

    def _migrate_service_tables(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS operators (
                user_id TEXT PRIMARY KEY,
                role TEXT NOT NULL,
                created_ms INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS operator_roles (
                role_id TEXT PRIMARY KEY,
                created_ms INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS schedules (
                schedule_id TEXT PRIMARY KEY,
                channel_id TEXT NOT NULL,
                workspace_id TEXT NOT NULL,
                prompt TEXT NOT NULL,
                every_s INTEGER NOT NULL,
                next_ms INTEGER NOT NULL,
                created_by TEXT,
                enabled INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS spend_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workspace_id TEXT NOT NULL,
                run_id TEXT NOT NULL,
                usd REAL NOT NULL,
                created_ms INTEGER NOT NULL
            );
            """
        )

    def _migrate_lineage_nodes(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS lineage_nodes (
                node_key TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                step TEXT NOT NULL,
                parent_keys_json TEXT NOT NULL DEFAULT '[]',
                input_sha256 TEXT NOT NULL,
                artifact_id TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'complete',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_lineage_run ON lineage_nodes(run_id);
            """
        )

    def _migrate_job_queue(self, conn: sqlite3.Connection) -> None:
        cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(tasks)").fetchall()
        }
        if "job_code" not in cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN job_code TEXT NOT NULL DEFAULT ''")
        conn.executescript(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_job_code
            ON tasks(job_code) WHERE job_code != '';
            CREATE TABLE IF NOT EXISTS job_pull_requests (
                repo TEXT NOT NULL,
                number INTEGER NOT NULL,
                task_id TEXT NOT NULL,
                branch TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (repo, number)
            );
            CREATE INDEX IF NOT EXISTS idx_job_pr_task ON job_pull_requests(task_id);
            CREATE TABLE IF NOT EXISTS github_wake_events (
                event_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                created_ms INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS github_rules (
                rule_id TEXT PRIMARY KEY,
                prompt TEXT NOT NULL DEFAULT '',
                destination TEXT NOT NULL DEFAULT 'new',
                repo TEXT NOT NULL DEFAULT '',
                branch TEXT NOT NULL DEFAULT '',
                conclusion TEXT NOT NULL DEFAULT '',
                channel_id TEXT NOT NULL DEFAULT '',
                workspace_id TEXT NOT NULL DEFAULT 'default',
                enabled INTEGER NOT NULL DEFAULT 1,
                created_ms INTEGER NOT NULL
            );
            """
        )
        pr_cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(job_pull_requests)").fetchall()
        }
        if pr_cols and "base" not in pr_cols:
            conn.execute(
                "ALTER TABLE job_pull_requests ADD COLUMN base TEXT NOT NULL DEFAULT ''"
            )
        missing = conn.execute(
            "SELECT task_id FROM tasks WHERE job_code IS NULL OR job_code = ''"
        ).fetchall()
        for row in missing:
            conn.execute(
                "UPDATE tasks SET job_code=? WHERE task_id=?",
                (self._mint_job_code(conn), row["task_id"]),
            )

    def _migrate_inbound_queue(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS inbound_queue (
                queue_id TEXT PRIMARY KEY,
                message_id TEXT NOT NULL UNIQUE,
                channel_id TEXT NOT NULL,
                thread_id TEXT NOT NULL,
                run_id TEXT NOT NULL DEFAULT '',
                workspace_id TEXT NOT NULL DEFAULT 'default',
                author_id TEXT,
                text TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                created_ms INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_inbound_queue_open
            ON inbound_queue(thread_id, status);
            """
        )

    def _mint_job_code(self, conn: sqlite3.Connection) -> str:
        row = conn.execute(
            """
            SELECT COALESCE(MAX(CAST(substr(job_code, ?) AS INTEGER)), 10000)
            FROM tasks
            WHERE job_code GLOB 'DOS-[0-9]*'
            """,
            (len(JOB_CODE_PREFIX) + 1,),
        ).fetchone()
        nxt = int(row[0] or 10000) + 1
        return f"{JOB_CODE_PREFIX}{nxt}"

    def _try_enable_fts(self, conn: sqlite3.Connection) -> bool:
        try:
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
                    memory_id UNINDEXED,
                    content,
                    workspace_id UNINDEXED,
                    channel_id UNINDEXED
                )
                """
            )
            return True
        except sqlite3.OperationalError:
            return False

    # --- bindings ---

    def upsert_binding(
        self,
        *,
        workspace_id: str,
        channel_id: str,
        guild_id: Optional[str] = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> str:
        conn = self._connection()
        row = conn.execute(
            "SELECT id FROM workspace_bindings WHERE workspace_id=? AND channel_id=?",
            (workspace_id, channel_id),
        ).fetchone()
        binding_id = row["id"] if row else uuid4().hex
        conn.execute(
            """
            INSERT INTO workspace_bindings (id, workspace_id, channel_id, guild_id, metadata_json)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(workspace_id, channel_id) DO UPDATE SET
                guild_id=excluded.guild_id,
                metadata_json=excluded.metadata_json
            """,
            (
                binding_id,
                workspace_id,
                channel_id,
                guild_id,
                json.dumps(dict(metadata or {}), sort_keys=True),
            ),
        )
        conn.commit()
        return binding_id

    def get_binding(self, workspace_id: str, channel_id: str) -> Optional[dict[str, Any]]:
        row = self._connection().execute(
            "SELECT * FROM workspace_bindings WHERE workspace_id=? AND channel_id=?",
            (workspace_id, channel_id),
        ).fetchone()
        return dict(row) if row else None

    def list_bindings(self, workspace_id: str = "") -> list[dict[str, Any]]:
        conn = self._connection()
        if workspace_id:
            rows = conn.execute(
                "SELECT * FROM workspace_bindings WHERE workspace_id=? ORDER BY channel_id",
                (workspace_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM workspace_bindings ORDER BY channel_id"
            ).fetchall()
        return [dict(row) for row in rows]

    def merge_binding_metadata(
        self,
        workspace_id: str,
        channel_id: str,
        updates: Mapping[str, Any],
        *,
        guild_id: Optional[str] = None,
    ) -> str:
        current = self.get_binding(workspace_id, channel_id) or {}
        raw = current.get("metadata_json") or "{}"
        try:
            meta = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
        except json.JSONDecodeError:
            meta = {}
        if not isinstance(meta, dict):
            meta = {}
        meta.update(dict(updates))
        return self.upsert_binding(
            workspace_id=workspace_id,
            channel_id=channel_id,
            guild_id=guild_id if guild_id is not None else current.get("guild_id"),
            metadata=meta,
        )

    # --- tasks / runs ---

    def create_task(
        self,
        *,
        task_id: str,
        workspace_id: str,
        channel_id: str,
        intake_text: str,
        thread_id: Optional[str] = None,
        requester_id: Optional[str] = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> None:
        """Insert a task with a unique DOS-* job_code.

        Mint+insert under BEGIN IMMEDIATE so parallel JobPool workers cannot
        both read the same MAX(job_code) and collide on the unique index.
        """

        conn = self._connection()
        meta_json = json.dumps(dict(metadata or {}), sort_keys=True)
        last_err: Optional[BaseException] = None
        for attempt in range(12):
            try:
                conn.execute("BEGIN IMMEDIATE")
                job_code = self._mint_job_code(conn)
                conn.execute(
                    """
                    INSERT INTO tasks (
                        task_id, workspace_id, channel_id, thread_id, intake_text,
                        status, requester_id, metadata_json, job_code
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        task_id,
                        workspace_id,
                        channel_id,
                        thread_id,
                        intake_text,
                        TaskStatus.PENDING.value,
                        requester_id,
                        meta_json,
                        job_code,
                    ),
                )
                conn.commit()
                return
            except sqlite3.IntegrityError as exc:
                last_err = exc
                try:
                    conn.rollback()
                except sqlite3.Error:
                    pass
                # Collision on job_code (or task_id); remint on next attempt.
                continue
            except sqlite3.OperationalError as exc:
                last_err = exc
                try:
                    conn.rollback()
                except sqlite3.Error:
                    pass
                if "locked" in str(exc).lower() and attempt < 11:
                    time.sleep(0.01 * (attempt + 1))
                    continue
                raise
        raise sqlite3.IntegrityError(
            f"create_task failed after retries: {last_err}"
        )

    def create_run(
        self,
        *,
        run_id: str,
        task_id: str,
        model: str,
        adapter_name: str,
        status: TaskStatus = TaskStatus.PENDING,
    ) -> None:
        conn = self._connection()
        conn.execute(
            """
            INSERT INTO runs (run_id, task_id, model, adapter_name, status)
            VALUES (?, ?, ?, ?, ?)
            """,
            (run_id, task_id, model, adapter_name, status.value),
        )
        conn.execute(
            "UPDATE tasks SET status=?, updated_at=datetime('now') WHERE task_id=?",
            (status.value, task_id),
        )
        conn.commit()

    def fail_stale_runs(self, *, reason: str = "host restarted") -> int:
        """Mark leftover running rows failed. Lineage stays so Retry can parent a new run."""

        conn = self._connection()
        cur = conn.execute(
            """
            UPDATE runs
            SET status=?, error=?, updated_at=datetime('now')
            WHERE status IN ('running', 'progress', 'pending')
            """,
            (TaskStatus.FAILED.value, reason),
        )
        conn.execute(
            """
            UPDATE tasks
            SET status=?, updated_at=datetime('now')
            WHERE status IN ('running', 'progress', 'pending')
            """,
            (TaskStatus.FAILED.value,),
        )
        conn.commit()
        return int(cur.rowcount or 0)

    def update_run(
        self,
        run_id: str,
        *,
        status: TaskStatus,
        summary: Optional[str] = None,
        error: Optional[str] = None,
        usage: Optional[Mapping[str, Any]] = None,
    ) -> None:
        conn = self._connection()
        conn.execute(
            """
            UPDATE runs SET status=?, summary=COALESCE(?, summary),
                error=?, usage_json=?, updated_at=datetime('now')
            WHERE run_id=?
            """,
            (
                status.value,
                summary,
                error,
                json.dumps(dict(usage), sort_keys=True) if usage else None,
                run_id,
            ),
        )
        row = conn.execute("SELECT task_id FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row:
            conn.execute(
                "UPDATE tasks SET status=?, updated_at=datetime('now') WHERE task_id=?",
                (status.value, row["task_id"]),
            )
        conn.commit()

    def get_run(self, run_id: str) -> Optional[dict[str, Any]]:
        row = self._connection().execute(
            "SELECT * FROM runs WHERE run_id=?", (run_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_task(self, task_id: str) -> Optional[dict[str, Any]]:
        row = self._connection().execute(
            "SELECT * FROM tasks WHERE task_id=?", (task_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_session_thread_ids(self, *, limit: int = 32) -> tuple[str, ...]:
        """Recent job-thread ids so idle follow-ups stay REST-listenable after Done."""

        capped = max(1, min(int(limit), 64))
        rows = self._connection().execute(
            """
            SELECT thread_id FROM tasks
            WHERE thread_id IS NOT NULL AND thread_id != ''
            ORDER BY updated_at DESC, task_id DESC
            LIMIT ?
            """,
            (max(capped * 4, 64),),
        ).fetchall()
        out: list[str] = []
        seen: set[str] = set()
        for row in rows:
            tid = str(row["thread_id"] or "").strip()
            if not tid or tid in seen:
                continue
            seen.add(tid)
            out.append(tid)
            if len(out) >= capped:
                break
        return tuple(out)

    def parent_channel_for_thread(self, thread_id: str) -> str:
        """Parent channel that opened this job thread (realm bind key).

        Prefer a prior task row; else forum-post binding metadata
        (``parent_channel_id``) so new forum posts resolve before first job.
        """

        tid = (thread_id or "").strip()
        if not tid:
            return ""
        row = self._connection().execute(
            """
            SELECT channel_id FROM tasks
            WHERE thread_id=?
            ORDER BY updated_at DESC, task_id DESC
            LIMIT 1
            """,
            (tid,),
        ).fetchone()
        if row and str(row["channel_id"] or "").strip():
            return str(row["channel_id"] or "").strip()
        # Forum-as-realm: thread id may be bound as a pseudo-channel with parent.
        try:
            from agent_discord.host.forum_realm import parent_from_forum_thread_binding

            parent = parent_from_forum_thread_binding(self, tid)
            if parent:
                return parent
        except Exception:
            pass
        return ""

    def latest_run_id_for_thread(
        self, thread_id: str, *, excluding_run_id: str = ""
    ) -> str:
        """Most recent prior run in this job thread (for lineage tip parenting)."""

        tid = (thread_id or "").strip()
        if not tid:
            return ""
        exclude = (excluding_run_id or "").strip()
        row = self._connection().execute(
            """
            SELECT r.run_id
            FROM tasks t
            JOIN runs r ON r.task_id = t.task_id
            WHERE t.thread_id=?
              AND (? = '' OR r.run_id != ?)
            ORDER BY r.created_at DESC, r.run_id DESC
            LIMIT 1
            """,
            (tid, exclude, exclude),
        ).fetchone()
        return str(row["run_id"] or "") if row else ""

    def list_recent_jobs(
        self, channel_id: str, *, limit: int = 5
    ) -> list[dict[str, Any]]:
        """Latest run per task, attention first: parked, failed, waiting, live, then Done."""

        capped = max(1, min(int(limit), 25))
        channel = (channel_id or "").strip()
        rows = self._connection().execute(
            """
            SELECT t.task_id, t.intake_text, t.status AS task_status,
                   t.metadata_json, t.job_code, t.thread_id, t.updated_at,
                   r.run_id, r.summary, r.status AS run_status
            FROM tasks t
            LEFT JOIN runs r ON r.run_id = (
                SELECT run_id FROM runs
                WHERE task_id = t.task_id
                ORDER BY created_at DESC, run_id DESC
                LIMIT 1
            )
            WHERE (? = '' OR t.channel_id=?)
            ORDER BY t.updated_at DESC
            LIMIT ?
            """,
            (channel, channel, max(capped * 4, 50)),
        ).fetchall()
        seen: set[str] = set()
        ranked: list[tuple[int, dict[str, Any]]] = []
        for row in rows:
            run_id = str(row["run_id"] or "")
            if not run_id or run_id in seen:
                continue
            seen.add(run_id)
            status = str(row["run_status"] or row["task_status"] or "")
            attention = _github_attention(row["metadata_json"])
            summary = str(row["summary"] or "")
            wake_summary = _github_last_summary(row["metadata_json"])
            if attention and wake_summary:
                summary = wake_summary
            item = {
                "task_id": str(row["task_id"] or ""),
                "run_id": run_id,
                "intake_text": str(row["intake_text"] or ""),
                "summary": summary,
                "status": status,
                "job_code": str(row["job_code"] or ""),
                "thread_id": str(row["thread_id"] or ""),
                "attention": attention,
            }
            ranked.append((_job_rank(status, attention), item))
        ranked.sort(key=lambda pair: pair[0])
        return [item for _rank, item in ranked][:capped]

    def list_dismissable_needs(
        self,
        *,
        channel_id: str = "",
        older_than_days: int | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """Failed runs and attention=need jobs eligible for dismiss / bulk clear.

        Latest run per task. Optional ``older_than_days`` filters on task
        ``updated_at`` (SQLite utc datetime). Empty ``channel_id`` = all channels.
        """

        capped = max(1, min(int(limit), 2000))
        channel = (channel_id or "").strip()
        days: int | None = None
        if older_than_days is not None:
            try:
                days = max(0, int(older_than_days))
            except (TypeError, ValueError):
                days = None
        params: list[Any] = [channel, channel]
        age_sql = ""
        if days is not None:
            age_sql = " AND t.updated_at <= datetime('now', ?)"
            params.append(f"-{days} days")
        params.append(max(capped * 4, 100))
        rows = self._connection().execute(
            f"""
            SELECT t.task_id, t.intake_text, t.status AS task_status,
                   t.metadata_json, t.job_code, t.thread_id, t.channel_id,
                   t.updated_at,
                   r.run_id, r.summary, r.status AS run_status
            FROM tasks t
            LEFT JOIN runs r ON r.run_id = (
                SELECT run_id FROM runs
                WHERE task_id = t.task_id
                ORDER BY created_at DESC, run_id DESC
                LIMIT 1
            )
            WHERE (? = '' OR t.channel_id=?){age_sql}
            ORDER BY t.updated_at ASC
            LIMIT ?
            """,
            tuple(params),
        ).fetchall()
        seen: set[str] = set()
        out: list[dict[str, Any]] = []
        for row in rows:
            run_id = str(row["run_id"] or "")
            if not run_id or run_id in seen:
                continue
            seen.add(run_id)
            status = str(row["run_status"] or row["task_status"] or "").strip().lower()
            attention = _github_attention(row["metadata_json"])
            if status != TaskStatus.FAILED.value and attention != "need":
                continue
            out.append(
                {
                    "task_id": str(row["task_id"] or ""),
                    "run_id": run_id,
                    "channel_id": str(row["channel_id"] or ""),
                    "intake_text": str(row["intake_text"] or ""),
                    "summary": str(row["summary"] or ""),
                    "status": status,
                    "job_code": str(row["job_code"] or ""),
                    "thread_id": str(row["thread_id"] or ""),
                    "attention": attention,
                    "updated_at": str(row["updated_at"] or ""),
                }
            )
            if len(out) >= capped:
                break
        return out

    def list_parked_approvals(self) -> list[dict[str, Any]]:
        """Pending runs still awaiting write-gate Allow."""

        rows = self._connection().execute(
            """
            SELECT r.run_id, r.task_id, r.created_at, r.status,
                   t.channel_id, t.thread_id, t.metadata_json
            FROM runs r
            JOIN tasks t ON t.task_id = r.task_id
            WHERE r.status = 'pending'
            ORDER BY r.created_at ASC, r.run_id ASC
            """
        ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            try:
                meta = json.loads(row["metadata_json"] or "{}")
            except json.JSONDecodeError:
                meta = {}
            if not isinstance(meta, dict) or not meta.get("awaiting_approval"):
                continue
            raw_ms = meta.get("parked_at_ms")
            parked_ms: Optional[int]
            try:
                parked_ms = int(raw_ms) if raw_ms is not None and str(raw_ms).strip() != "" else None
            except (TypeError, ValueError):
                parked_ms = None
            out.append(
                {
                    "run_id": str(row["run_id"] or ""),
                    "task_id": str(row["task_id"] or ""),
                    "created_at": str(row["created_at"] or ""),
                    "parked_at_ms": parked_ms,
                    "channel_id": str(row["channel_id"] or ""),
                    "thread_id": str(row["thread_id"] or meta.get("thread_id") or ""),
                }
            )
        return out

    def task_job_code(self, task_id: str) -> str:
        row = self.get_task(task_id)
        if row is None:
            return ""
        return str(row.get("job_code") or "").strip()

    def get_task_by_job_code(self, job_code: str) -> Optional[dict[str, Any]]:
        code = (job_code or "").strip().upper()
        if not code:
            return None
        row = self._connection().execute(
            "SELECT * FROM tasks WHERE job_code=? COLLATE NOCASE",
            (code,),
        ).fetchone()
        return dict(row) if row else None

    def latest_run_id_for_task(self, task_id: str) -> str:
        row = self._connection().execute(
            """
            SELECT run_id FROM runs
            WHERE task_id=?
            ORDER BY created_at DESC, run_id DESC
            LIMIT 1
            """,
            (task_id,),
        ).fetchone()
        return str(row["run_id"] or "") if row else ""

    def list_runs_for_task(self, task_id: str) -> list[dict[str, Any]]:
        rows = self._connection().execute(
            """
            SELECT * FROM runs
            WHERE task_id=?
            ORDER BY created_at DESC, run_id DESC
            """,
            (task_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def bind_job_pull_request(
        self,
        task_id: str,
        *,
        repo: str,
        number: int,
        branch: str = "",
        base: str = "",
    ) -> None:
        rid = (task_id or "").strip()
        owner_repo = (repo or "").strip().strip("/")
        try:
            pr_number = int(number)
        except (TypeError, ValueError):
            return
        if not rid or not owner_repo or pr_number < 1:
            return
        head = (branch or "").strip()
        onto = (base or "").strip()
        conn = self._connection()
        conn.execute(
            """
            INSERT INTO job_pull_requests (repo, number, task_id, branch, base)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(repo, number) DO UPDATE SET
                task_id=excluded.task_id,
                branch=CASE
                    WHEN excluded.branch != '' THEN excluded.branch
                    ELSE job_pull_requests.branch
                END,
                base=CASE
                    WHEN excluded.base != '' THEN excluded.base
                    ELSE job_pull_requests.base
                END
            """,
            (owner_repo, pr_number, rid, head, onto),
        )
        conn.commit()
        github = self.task_metadata(rid).get("github")
        blob = dict(github) if isinstance(github, dict) else {}
        blob.update({"repo": owner_repo, "number": pr_number})
        if head:
            blob["branch"] = head
        if onto:
            blob["base"] = onto
        self.merge_task_metadata(rid, {"github": blob})

    def job_for_pull_request(self, repo: str, number: int) -> Optional[dict[str, Any]]:
        try:
            pr_number = int(number)
        except (TypeError, ValueError):
            return None
        row = self._connection().execute(
            """
            SELECT p.repo, p.number, p.task_id, p.branch, p.base,
                   t.channel_id, t.thread_id
            FROM job_pull_requests p
            JOIN tasks t ON t.task_id = p.task_id
            WHERE p.repo=? AND p.number=?
            """,
            ((repo or "").strip(), pr_number),
        ).fetchone()
        return dict(row) if row else None

    def job_for_head_branch(self, repo: str, branch: str) -> Optional[dict[str, Any]]:
        owner_repo = (repo or "").strip().strip("/")
        head = (branch or "").strip()
        if not owner_repo or not head:
            return None
        row = self._connection().execute(
            """
            SELECT p.repo, p.number, p.task_id, p.branch, p.base,
                   t.channel_id, t.thread_id
            FROM job_pull_requests p
            JOIN tasks t ON t.task_id = p.task_id
            WHERE p.repo=? AND p.branch=?
            ORDER BY t.updated_at DESC
            LIMIT 1
            """,
            (owner_repo, head),
        ).fetchone()
        return dict(row) if row else None

    def list_job_pull_requests(self) -> list[dict[str, Any]]:
        rows = self._connection().execute(
            """
            SELECT p.repo, p.number, p.task_id, p.branch, p.base,
                   t.channel_id, t.thread_id,
                   (
                       SELECT run_id FROM runs
                       WHERE task_id = t.task_id
                       ORDER BY created_at DESC, run_id DESC
                       LIMIT 1
                   ) AS run_id
            FROM job_pull_requests p
            JOIN tasks t ON t.task_id = p.task_id
            ORDER BY t.updated_at DESC
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def add_github_rule(
        self,
        *,
        prompt: str = "",
        destination: str = "new",
        repo: str = "",
        branch: str = "",
        conclusion: str = "",
        channel_id: str = "",
        workspace_id: str = "default",
    ) -> str:
        rule_id = uuid4().hex
        dest = (destination or "new").strip().lower() or "new"
        conn = self._connection()
        conn.execute(
            """
            INSERT INTO github_rules (
                rule_id, prompt, destination, repo, branch, conclusion,
                channel_id, workspace_id, enabled, created_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
            """,
            (
                rule_id,
                (prompt or "").strip(),
                dest,
                (repo or "").strip().strip("/"),
                (branch or "").strip(),
                (conclusion or "").strip().lower(),
                (channel_id or "").strip(),
                (workspace_id or "default").strip() or "default",
                int(time.time() * 1000),
            ),
        )
        conn.commit()
        return rule_id

    def list_github_rules(self) -> list[dict[str, Any]]:
        rows = self._connection().execute(
            """
            SELECT * FROM github_rules
            WHERE enabled = 1
            ORDER BY created_ms ASC
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def set_job_github_attention(
        self, task_id: str, attention: str, *, summary: str = ""
    ) -> None:
        meta = self.task_metadata(task_id)
        github = dict(meta.get("github") or {}) if isinstance(meta.get("github"), dict) else {}
        github["attention"] = str(attention or "")
        if summary:
            github["last_summary"] = summary
        elif not attention:
            github.pop("last_summary", None)
        self.merge_task_metadata(task_id, {"github": github})

    def claim_github_wake(self, event_id: str, task_id: str) -> bool:
        eid = (event_id or "").strip()
        rid = (task_id or "").strip()
        if not eid or not rid:
            return False
        conn = self._connection()
        try:
            conn.execute(
                """
                INSERT INTO github_wake_events (event_id, task_id, created_ms)
                VALUES (?, ?, ?)
                """,
                (eid, rid, int(time.time() * 1000)),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            return False
        return True


    # --- events ---

    def append_event(
        self,
        *,
        task_id: str,
        run_id: str,
        kind: EventKind,
        summary: str,
        payload: Mapping[str, Any],
        source: str,
        provenance: Mapping[str, Any],
    ) -> int:
        safe_payload = strip_forbidden_keys(dict(payload))
        if not isinstance(safe_payload, dict):
            safe_payload = {}
        safe_provenance = strip_forbidden_keys(dict(provenance))
        if not isinstance(safe_provenance, dict):
            safe_provenance = {}
        conn = self._connection()
        cur = conn.execute(
            """
            INSERT INTO events (
                task_id, run_id, kind, summary, payload_json, source, provenance_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                run_id,
                kind.value if isinstance(kind, EventKind) else str(kind),
                redact_text_markers(summary),
                json.dumps(safe_payload, sort_keys=True),
                source,
                json.dumps(safe_provenance, sort_keys=True),
            ),
        )
        conn.commit()
        return int(cur.lastrowid)

    def list_events(self, run_id: str) -> Sequence[Mapping[str, Any]]:
        rows = self._connection().execute(
            "SELECT * FROM events WHERE run_id=? ORDER BY id ASC", (run_id,)
        ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json") or "{}")
            item["provenance"] = json.loads(item.pop("provenance_json") or "{}")
            out.append(item)
        return out

    # --- memory ---

    def remember(
        self,
        *,
        workspace_id: str,
        channel_id: str,
        content: str,
        source: str,
        provenance: Mapping[str, Any],
    ) -> str:
        memory_id = uuid4().hex
        conn = self._connection()
        safe_prov = strip_forbidden_keys(dict(provenance))
        if not isinstance(safe_prov, dict):
            safe_prov = {}
        conn.execute(
            """
            INSERT INTO memory_entries (
                memory_id, workspace_id, channel_id, content, source, provenance_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                memory_id,
                workspace_id,
                channel_id,
                content,
                source,
                json.dumps(safe_prov, sort_keys=True),
            ),
        )
        if self._fts_enabled:
            conn.execute(
                """
                INSERT INTO memory_fts (memory_id, content, workspace_id, channel_id)
                VALUES (?, ?, ?, ?)
                """,
                (memory_id, content, workspace_id, channel_id),
            )
        conn.commit()
        return memory_id

    def recall(
        self,
        *,
        workspace_id: str,
        channel_id: str,
        query: str,
        limit: int = 8,
    ) -> Sequence[Mapping[str, Any]]:
        conn = self._connection()
        if self._fts_enabled and query.strip():
            try:
                rows = conn.execute(
                    """
                    SELECT m.* FROM memory_fts f
                    JOIN memory_entries m ON m.memory_id = f.memory_id
                    WHERE f.workspace_id=? AND f.channel_id=?
                      AND memory_fts MATCH ?
                    ORDER BY m.created_at DESC
                    LIMIT ?
                    """,
                    (workspace_id, channel_id, _fts_query(query), limit),
                ).fetchall()
                return [_memory_row(r) for r in rows]
            except sqlite3.OperationalError:
                pass
        like = f"%{query.strip()}%" if query.strip() else "%"
        rows = conn.execute(
            """
            SELECT * FROM memory_entries
            WHERE workspace_id=? AND channel_id=? AND content LIKE ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (workspace_id, channel_id, like, limit),
        ).fetchall()
        return [_memory_row(r) for r in rows]

    # --- preferences / style / failure memory ---

    def set_preference(
        self,
        workspace_id: str,
        key: str,
        value: str,
        kind: str = "preference",
    ) -> None:
        workspace_id = str(workspace_id or "").strip()
        key = str(key or "").strip()
        if not workspace_id:
            raise ValueError("workspace_id is required")
        if not key:
            raise ValueError("key is required")
        kind_value = str(kind or "preference").strip()
        if kind_value not in PREFERENCE_KINDS:
            allowed = ", ".join(sorted(PREFERENCE_KINDS))
            raise ValueError(f"kind must be one of {allowed}; got {kind_value!r}")
        safe_value = redact_text_markers(str(value or ""))
        conn = self._connection()
        conn.execute(
            """
            INSERT INTO preferences (workspace_id, key, value, kind, updated_at)
            VALUES (?, ?, ?, ?, datetime('now'))
            ON CONFLICT(workspace_id, key) DO UPDATE SET
                value=excluded.value,
                kind=excluded.kind,
                updated_at=datetime('now')
            """,
            (workspace_id, key, safe_value, kind_value),
        )
        conn.commit()

    def get_preference(self, workspace_id: str, key: str) -> Optional[str]:
        row = self._connection().execute(
            "SELECT value FROM preferences WHERE workspace_id=? AND key=?",
            (workspace_id, key),
        ).fetchone()
        return None if row is None else str(row["value"])

    def list_preferences(
        self,
        workspace_id: str,
        kind: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        conn = self._connection()
        if kind is None:
            rows = conn.execute(
                """
                SELECT workspace_id, key, value, kind, updated_at
                FROM preferences
                WHERE workspace_id=?
                ORDER BY kind ASC, updated_at DESC
                """,
                (workspace_id,),
            ).fetchall()
        else:
            kind_value = str(kind).strip()
            if kind_value not in PREFERENCE_KINDS:
                allowed = ", ".join(sorted(PREFERENCE_KINDS))
                raise ValueError(f"kind must be one of {allowed}; got {kind_value!r}")
            rows = conn.execute(
                """
                SELECT workspace_id, key, value, kind, updated_at
                FROM preferences
                WHERE workspace_id=? AND kind=?
                ORDER BY updated_at DESC
                """,
                (workspace_id, kind_value),
            ).fetchall()
        return [dict(row) for row in rows]

    def record_failure(self, workspace_id: str, key: str, reason: str) -> None:
        self.set_preference(workspace_id, key, reason, kind="failure")

    def list_failures(
        self, workspace_id: str, limit: int = 8
    ) -> list[dict[str, Any]]:
        capped = max(1, min(int(limit), 25))
        rows = self._connection().execute(
            """
            SELECT workspace_id, key, value, kind, updated_at
            FROM preferences
            WHERE workspace_id=? AND kind='failure'
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (workspace_id, capped),
        ).fetchall()
        return [dict(row) for row in rows]

    def prompt_memory_block(self, workspace_id: str) -> str:
        lines: list[str] = []
        for kind, heading in (
            ("preference", "[preferences]"),
            ("style", "[style]"),
            ("failure", "[failures]"),
        ):
            rows = self.list_preferences(workspace_id, kind=kind)[:_PROMPT_MEMORY_PER_KIND]
            if not rows:
                continue
            lines.append(heading)
            for row in rows:
                key = str(row.get("key") or "")
                value = redact_text_markers(str(row.get("value") or ""))
                if len(value) > _PROMPT_MEMORY_VALUE_CHARS:
                    value = value[: _PROMPT_MEMORY_VALUE_CHARS - 3] + "..."
                if kind == "failure":
                    lines.append(f"{key}: {value}")
                else:
                    lines.append(f"{key}={value}")
        if not lines:
            return ""
        block = redact_text_markers("\n".join(lines))
        if len(block) > _PROMPT_MEMORY_BLOCK_CHARS:
            return block[: _PROMPT_MEMORY_BLOCK_CHARS - 3] + "..."
        return block

    def merge_task_metadata(self, task_id: str, updates: Mapping[str, Any]) -> None:
        row = self.get_task(task_id)
        if row is None:
            return
        raw = row.get("metadata_json") or "{}"
        try:
            meta = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
        except json.JSONDecodeError:
            meta = {}
        if not isinstance(meta, dict):
            meta = {}
        meta.update(dict(updates))
        self._connection().execute(
            "UPDATE tasks SET metadata_json=?, updated_at=datetime('now') WHERE task_id=?",
            (json.dumps(meta, sort_keys=True), task_id),
        )
        self._connection().commit()

    def bind_task_thread(self, task_id: str, thread_id: str) -> None:
        tid = (thread_id or "").strip()
        rid = (task_id or "").strip()
        if not tid or not rid:
            return
        self._connection().execute(
            "UPDATE tasks SET thread_id=?, updated_at=datetime('now') WHERE task_id=?",
            (tid, rid),
        )
        self._connection().commit()
        self.merge_task_metadata(rid, {"thread_id": tid})

    def task_metadata(self, task_id: str) -> dict[str, Any]:
        row = self.get_task(task_id)
        if row is None:
            return {}
        raw = row.get("metadata_json") or "{}"
        try:
            meta = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
        except json.JSONDecodeError:
            return {}
        return dict(meta) if isinstance(meta, dict) else {}

    # --- operators ---

    def add_operator(self, user_id: str, role: str = "operator") -> None:
        uid = str(user_id or "").strip()
        if not uid:
            raise ValueError("user_id is required")
        kind = str(role or "operator").strip().lower()
        if kind not in {"owner", "operator"}:
            raise ValueError("role must be owner or operator")
        conn = self._connection()
        conn.execute(
            """
            INSERT INTO operators (user_id, role, created_ms)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET role=excluded.role
            """,
            (uid, kind, int(time.time() * 1000)),
        )
        conn.commit()

    def add_operator_role(self, role_id: str) -> None:
        rid = str(role_id or "").strip()
        if not rid:
            raise ValueError("role_id is required")
        conn = self._connection()
        conn.execute(
            """
            INSERT INTO operator_roles (role_id, created_ms)
            VALUES (?, ?)
            ON CONFLICT(role_id) DO NOTHING
            """,
            (rid, int(time.time() * 1000)),
        )
        conn.commit()

    def list_operators(self) -> list[dict[str, Any]]:
        rows = self._connection().execute(
            "SELECT user_id, role, created_ms FROM operators ORDER BY created_ms ASC"
        ).fetchall()
        return [dict(row) for row in rows]

    def list_operator_roles(self) -> list[str]:
        rows = self._connection().execute(
            "SELECT role_id FROM operator_roles"
        ).fetchall()
        return [str(row["role_id"]) for row in rows]

    def is_operator(
        self,
        user_id: str,
        *,
        role_ids: Optional[Sequence[str]] = None,
    ) -> bool:
        uid = str(user_id or "").strip()
        if uid:
            row = self._connection().execute(
                "SELECT 1 FROM operators WHERE user_id=?",
                (uid,),
            ).fetchone()
            if row is not None:
                return True
        allowed = set(self.list_operator_roles())
        if not allowed:
            return False
        for role_id in role_ids or ():
            if str(role_id).strip() in allowed:
                return True
        return False

    def seed_owner_if_empty(self, user_id: Optional[str]) -> bool:
        uid = str(user_id or "").strip()
        if not uid:
            return False
        if self.list_operators():
            return False
        self.add_operator(uid, role="owner")
        return True

    def seed_owner_from_env(self, env: Optional[Mapping[str, str]] = None) -> None:
        owner = str((env or os.environ).get("DISCORD_OWNER_ID") or "").strip()
        if owner:
            self.seed_owner_if_empty(owner)
        roles = str((env or os.environ).get("DISCORD_OPERATOR_ROLE_IDS") or "")
        for role_id in roles.replace(",", " ").split():
            if role_id.strip():
                self.add_operator_role(role_id.strip())

    # --- spend ---

    def record_spend(self, workspace_id: str, run_id: str, usd: float) -> None:
        conn = self._connection()
        conn.execute(
            """
            INSERT INTO spend_events (workspace_id, run_id, usd, created_ms)
            VALUES (?, ?, ?, ?)
            """,
            (
                str(workspace_id or "").strip() or "default",
                str(run_id or "").strip(),
                max(0.0, float(usd)),
                int(time.time() * 1000),
            ),
        )
        conn.commit()

    def session_spend_usd(self, workspace_id: str = "") -> float:
        conn = self._connection()
        if workspace_id:
            row = conn.execute(
                "SELECT COALESCE(SUM(usd), 0) AS total FROM spend_events WHERE workspace_id=?",
                (workspace_id,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COALESCE(SUM(usd), 0) AS total FROM spend_events"
            ).fetchone()
        return float(row["total"] if row is not None else 0.0)

    # --- schedules ---

    def add_schedule(
        self,
        *,
        channel_id: str,
        workspace_id: str,
        prompt: str,
        every_s: int,
        created_by: str = "",
        next_ms: Optional[int] = None,
    ) -> str:
        schedule_id = uuid4().hex
        now = int(time.time() * 1000)
        interval = max(60, int(every_s))
        due = int(next_ms) if next_ms is not None else now + interval * 1000
        conn = self._connection()
        conn.execute(
            """
            INSERT INTO schedules (
                schedule_id, channel_id, workspace_id, prompt,
                every_s, next_ms, created_by, enabled
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                schedule_id,
                str(channel_id or "").strip(),
                str(workspace_id or "default").strip() or "default",
                str(prompt or "").strip(),
                interval,
                due,
                str(created_by or "").strip(),
            ),
        )
        conn.commit()
        return schedule_id

    def due_schedules(
        self,
        now_ms: int,
        channel_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        conn = self._connection()
        if channel_id:
            rows = conn.execute(
                """
                SELECT * FROM schedules
                WHERE enabled=1 AND next_ms<=? AND channel_id=?
                ORDER BY next_ms ASC
                """,
                (int(now_ms), channel_id),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM schedules
                WHERE enabled=1 AND next_ms<=?
                ORDER BY next_ms ASC
                """,
                (int(now_ms),),
            ).fetchall()
        return [dict(row) for row in rows]

    def bump_schedule(self, schedule_id: str, next_ms: int) -> None:
        self._connection().execute(
            "UPDATE schedules SET next_ms=? WHERE schedule_id=?",
            (int(next_ms), schedule_id),
        )
        self._connection().commit()

    def list_schedules(self, channel_id: Optional[str] = None) -> list[dict[str, Any]]:
        conn = self._connection()
        if channel_id:
            rows = conn.execute(
                "SELECT * FROM schedules WHERE channel_id=? ORDER BY next_ms ASC",
                (channel_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM schedules ORDER BY next_ms ASC"
            ).fetchall()
        return [dict(row) for row in rows]

    # --- artifacts ---

    def add_artifact(
        self,
        *,
        artifact_id: str,
        task_id: str,
        run_id: str,
        kind: str,
        path: str = "",
        provenance: Mapping[str, Any] | None = None,
        channel_id: str = "",
        message_id: str = "",
        attachment_id: str = "",
        filename: str = "",
        sha256: str = "",
        size: int = 0,
        content_type: str = "",
    ) -> None:
        conn = self._connection()
        safe_prov = strip_forbidden_keys(dict(provenance or {}))
        if not isinstance(safe_prov, dict):
            safe_prov = {}
        conn.execute(
            """
            INSERT INTO artifacts (
                artifact_id, task_id, run_id, kind, path,
                channel_id, message_id, attachment_id, filename,
                sha256, size, content_type, provenance_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                artifact_id,
                task_id,
                run_id,
                kind,
                path,
                channel_id,
                message_id,
                attachment_id,
                filename,
                sha256,
                size,
                content_type,
                json.dumps(safe_prov, sort_keys=True),
            ),
        )
        conn.commit()

    def list_artifacts(self, run_id: str) -> Sequence[Mapping[str, Any]]:
        rows = self._connection().execute(
            "SELECT * FROM artifacts WHERE run_id=? ORDER BY created_at ASC", (run_id,)
        ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["provenance"] = json.loads(item.pop("provenance_json") or "{}")
            out.append(item)
        return out

    def upsert_lineage_node(
        self,
        *,
        node_key: str,
        run_id: str,
        task_id: str,
        step: str,
        parent_keys: Sequence[str] = (),
        input_sha256: str = "",
        artifact_id: str = "",
        status: str = "complete",
    ) -> None:
        conn = self._connection()
        parents = json.dumps(list(parent_keys), sort_keys=True)
        conn.execute(
            """
            INSERT INTO lineage_nodes (
                node_key, run_id, task_id, step, parent_keys_json,
                input_sha256, artifact_id, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(node_key) DO UPDATE SET
                artifact_id=CASE
                    WHEN excluded.artifact_id != '' THEN excluded.artifact_id
                    ELSE lineage_nodes.artifact_id
                END,
                status=excluded.status
            """,
            (
                node_key,
                run_id,
                task_id,
                step,
                parents,
                input_sha256,
                artifact_id,
                status,
            ),
        )
        conn.commit()

    def list_lineage_nodes(self, run_id: str) -> Sequence[Mapping[str, Any]]:
        rows = self._connection().execute(
            """
            SELECT * FROM lineage_nodes
            WHERE run_id=?
            ORDER BY created_at ASC, node_key ASC
            """,
            (run_id,),
        ).fetchall()
        return [self._decode_lineage_row(row) for row in rows]

    def list_lineage_children(self, parent_key: str) -> Sequence[Mapping[str, Any]]:
        key = (parent_key or "").strip()
        if not key:
            return []
        rows = self._connection().execute(
            """
            SELECT * FROM lineage_nodes
            WHERE parent_keys_json LIKE ?
            ORDER BY created_at ASC, node_key ASC
            """,
            (f'%"{key}"%',),
        ).fetchall()
        return [self._decode_lineage_row(row) for row in rows]

    def _decode_lineage_row(self, row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        raw = item.pop("parent_keys_json", "[]")
        try:
            item["parent_keys"] = json.loads(raw or "[]")
        except json.JSONDecodeError:
            item["parent_keys"] = []
        return item

    def mark_lineage_stale(self, node_keys: Sequence[str]) -> int:
        keys = [str(k) for k in node_keys if str(k or "").strip()]
        if not keys:
            return 0
        conn = self._connection()
        placeholders = ",".join("?" for _ in keys)
        cur = conn.execute(
            f"UPDATE lineage_nodes SET status='stale' WHERE node_key IN ({placeholders})",
            keys,
        )
        conn.commit()
        return int(cur.rowcount or 0)

    def latest_lineage_run_id(self) -> Optional[str]:
        row = self._connection().execute(
            """
            SELECT run_id FROM lineage_nodes
            ORDER BY created_at DESC
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            return None
        return str(row["run_id"] or "") or None

    def list_objects(
        self,
        channel_id: str,
        *,
        run_id: Optional[str] = None,
        limit: int = 50,
    ) -> Sequence[Mapping[str, Any]]:
        """Pointer index for CLI ls — rows with a Discord message/attachment id."""

        conn = self._connection()
        if run_id:
            rows = conn.execute(
                """
                SELECT * FROM artifacts
                WHERE channel_id=? AND run_id=?
                  AND message_id IS NOT NULL AND message_id != ''
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (channel_id, run_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM artifacts
                WHERE channel_id=?
                  AND message_id IS NOT NULL AND message_id != ''
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (channel_id, limit),
            ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["provenance"] = json.loads(item.pop("provenance_json") or "{}")
            out.append(item)
        return out

    # --- inbound message dedupe (durable / idempotent) ---

    def claim_inbound_message(
        self,
        message_id: str,
        channel_id: Optional[str] = None,
    ) -> bool:
        """Atomically claim a Discord message id. True if newly claimed."""
        if not message_id:
            return True
        conn = self._connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO seen_messages (message_id, channel_id) VALUES (?, ?)",
                (message_id, channel_id),
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            conn.rollback()
            return False

    def bind_inbound_message(
        self,
        message_id: str,
        *,
        task_id: str,
        run_id: str,
        channel_id: Optional[str] = None,
    ) -> None:
        if not message_id:
            return
        conn = self._connection()
        conn.execute(
            """
            UPDATE seen_messages
            SET task_id=?, run_id=?, channel_id=COALESCE(?, channel_id)
            WHERE message_id=?
            """,
            (task_id, run_id, channel_id, message_id),
        )
        conn.commit()

    def get_inbound_message(self, message_id: str) -> Optional[dict[str, Any]]:
        if not message_id:
            return None
        row = self._connection().execute(
            "SELECT * FROM seen_messages WHERE message_id=?", (message_id,)
        ).fetchone()
        return dict(row) if row else None

    def enqueue_inbound(
        self,
        *,
        message_id: str,
        channel_id: str,
        thread_id: str,
        text: str,
        run_id: str = "",
        workspace_id: str = "default",
        author_id: str = "",
        queue_id: str = "",
        created_ms: Optional[int] = None,
    ) -> Optional[str]:
        """Durable live-thread follow-up. None if duplicate or incomplete."""

        mid = (message_id or "").strip()
        tid = (thread_id or "").strip()
        cid = (channel_id or "").strip()
        body = (text or "").strip()
        if not mid or not tid or not cid or not body:
            return None
        qid = (queue_id or "").strip() or str(uuid4())
        now = int(created_ms if created_ms is not None else time.time() * 1000)
        conn = self._connection()
        try:
            conn.execute(
                """
                INSERT INTO inbound_queue (
                    queue_id, message_id, channel_id, thread_id, run_id,
                    workspace_id, author_id, text, status, created_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?)
                """,
                (
                    qid,
                    mid,
                    cid,
                    tid,
                    (run_id or "").strip(),
                    (workspace_id or "default").strip() or "default",
                    (author_id or "").strip(),
                    body,
                    now,
                ),
            )
            conn.commit()
            return qid
        except sqlite3.IntegrityError:
            conn.rollback()
            return None

    def list_queued_inbound(
        self, thread_id: str = "", *, limit: int = 20
    ) -> list[dict[str, Any]]:
        capped = max(1, min(int(limit), 50))
        tid = (thread_id or "").strip()
        conn = self._connection()
        if tid:
            rows = conn.execute(
                """
                SELECT * FROM inbound_queue
                WHERE status='queued' AND thread_id=?
                ORDER BY created_ms ASC, queue_id ASC
                LIMIT ?
                """,
                (tid, capped),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM inbound_queue
                WHERE status='queued'
                ORDER BY created_ms ASC, queue_id ASC
                LIMIT ?
                """,
                (capped,),
            ).fetchall()
        return [dict(row) for row in rows]

    def mark_inbound_applied(
        self, queue_id: str = "", *, message_id: str = ""
    ) -> None:
        self._mark_inbound_status(queue_id, "applied", message_id=message_id)

    def mark_inbound_dropped(
        self, queue_id: str = "", *, message_id: str = ""
    ) -> None:
        self._mark_inbound_status(queue_id, "dropped", message_id=message_id)

    def _mark_inbound_status(
        self, queue_id: str, status: str, *, message_id: str = ""
    ) -> None:
        qid = (queue_id or "").strip()
        mid = (message_id or "").strip()
        if not qid and not mid:
            return
        conn = self._connection()
        if qid:
            conn.execute(
                "UPDATE inbound_queue SET status=? WHERE queue_id=?",
                (status, qid),
            )
        else:
            conn.execute(
                "UPDATE inbound_queue SET status=? WHERE message_id=?",
                (status, mid),
            )
        conn.commit()

    def mark_message_seen(self, message_id: str, channel_id: Optional[str] = None) -> bool:
        """Return True if newly seen, False if duplicate. Compatibility helper."""
        return self.claim_inbound_message(message_id, channel_id)

    # --- listen watermark (durable per-channel high-water) ---

    def get_listen_watermark(self, channel_id: str) -> Optional[dict[str, Any]]:
        row = self._connection().execute(
            """
            SELECT channel_id, last_created_ms, last_message_id
            FROM listen_watermarks
            WHERE channel_id=?
            """,
            (channel_id,),
        ).fetchone()
        if row is None:
            return None
        raw_ms = row["last_created_ms"]
        return {
            "channel_id": str(row["channel_id"]),
            "last_created_ms": int(raw_ms) if raw_ms is not None else None,
            "last_message_id": str(row["last_message_id"] or ""),
        }

    def seed_listen_watermark(self, channel_id: str, created_ms: int) -> dict[str, Any]:
        """Insert first-listen high-water if absent. Never overwrite a later mark."""

        conn = self._connection()
        conn.execute(
            """
            INSERT OR IGNORE INTO listen_watermarks (channel_id, last_created_ms, last_message_id)
            VALUES (?, ?, '')
            """,
            (channel_id, created_ms),
        )
        conn.commit()
        existing = self.get_listen_watermark(channel_id)
        if existing is not None:
            return existing
        return {
            "channel_id": channel_id,
            "last_created_ms": created_ms,
            "last_message_id": "",
        }

    def get_host_control(self, channel_id: str) -> Optional[dict[str, Any]]:
        row = self._connection().execute(
            """
            SELECT channel_id, armed, card_message_id
            FROM host_control
            WHERE channel_id=?
            """,
            (channel_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "channel_id": str(row["channel_id"]),
            "armed": bool(int(row["armed"])),
            "card_message_id": str(row["card_message_id"] or ""),
        }

    def host_is_armed(self, channel_id: str, *, default: bool = True) -> bool:
        row = self.get_host_control(channel_id)
        if row is None:
            return default
        return bool(row["armed"])

    def set_host_control(
        self,
        channel_id: str,
        *,
        armed: Optional[bool] = None,
        card_message_id: Optional[str] = None,
        default_armed: bool = True,
    ) -> dict[str, Any]:
        current = self.get_host_control(channel_id)
        next_armed = default_armed if current is None else bool(current["armed"])
        next_card = "" if current is None else str(current["card_message_id"] or "")
        if armed is not None:
            next_armed = bool(armed)
        if card_message_id is not None:
            next_card = str(card_message_id)
        conn = self._connection()
        conn.execute(
            """
            INSERT INTO host_control (
                channel_id, armed, card_message_id, updated_at
            ) VALUES (?, ?, ?, datetime('now'))
            ON CONFLICT(channel_id) DO UPDATE SET
                armed=excluded.armed,
                card_message_id=excluded.card_message_id,
                updated_at=datetime('now')
            """,
            (channel_id, 1 if next_armed else 0, next_card),
        )
        conn.commit()
        stored = self.get_host_control(channel_id)
        if stored is not None:
            return stored
        return {
            "channel_id": channel_id,
            "armed": next_armed,
            "card_message_id": next_card,
        }

    def set_listen_watermark(
        self,
        channel_id: str,
        *,
        created_ms: Optional[int],
        message_id: str = "",
    ) -> None:
        conn = self._connection()
        conn.execute(
            """
            INSERT INTO listen_watermarks (
                channel_id, last_created_ms, last_message_id, updated_at
            ) VALUES (?, ?, ?, datetime('now'))
            ON CONFLICT(channel_id) DO UPDATE SET
                last_created_ms=excluded.last_created_ms,
                last_message_id=excluded.last_message_id,
                updated_at=datetime('now')
            """,
            (channel_id, created_ms, message_id),
        )
        conn.commit()

    # --- gateway ownership ---

    def claim_gateway(self, bot_token_fingerprint: str, owner_id: str) -> None:
        if not bot_token_fingerprint:
            raise GatewayOwnershipError("bot_token_fingerprint is required")
        if not owner_id:
            raise GatewayOwnershipError("owner_id is required")
        conn = self._connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT owner_id FROM gateway_owners WHERE bot_token_fingerprint=?",
                (bot_token_fingerprint,),
            ).fetchone()
            if row is not None and row["owner_id"] != owner_id:
                if not _cli_owner_is_dead(str(row["owner_id"])):
                    conn.rollback()
                    raise GatewayOwnershipError(
                        f"token {bot_token_fingerprint} already owned by {row['owner_id']!r}; "
                        f"refusing claim by {owner_id!r}"
                    )
            conn.execute(
                """
                INSERT INTO gateway_owners (bot_token_fingerprint, owner_id, claimed_at)
                VALUES (?, ?, datetime('now'))
                ON CONFLICT(bot_token_fingerprint) DO UPDATE SET
                    owner_id=excluded.owner_id,
                    claimed_at=datetime('now')
                """,
                (bot_token_fingerprint, owner_id),
            )
            conn.commit()
        except GatewayOwnershipError:
            raise
        except sqlite3.Error as exc:
            conn.rollback()
            raise GatewayOwnershipError(f"gateway claim failed: {exc}") from exc

    def release_gateway(self, bot_token_fingerprint: str, owner_id: str) -> None:
        conn = self._connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT owner_id FROM gateway_owners WHERE bot_token_fingerprint=?",
                (bot_token_fingerprint,),
            ).fetchone()
            if row is None:
                conn.commit()
                return
            if row["owner_id"] != owner_id:
                conn.rollback()
                raise GatewayOwnershipError(
                    f"token {bot_token_fingerprint} owned by {row['owner_id']!r}; "
                    f"cannot release as {owner_id!r}"
                )
            conn.execute(
                "DELETE FROM gateway_owners WHERE bot_token_fingerprint=?",
                (bot_token_fingerprint,),
            )
            conn.commit()
        except GatewayOwnershipError:
            raise
        except sqlite3.Error as exc:
            conn.rollback()
            raise GatewayOwnershipError(f"gateway release failed: {exc}") from exc

    def gateway_owner(self, bot_token_fingerprint: str) -> Optional[str]:
        row = self._connection().execute(
            "SELECT owner_id FROM gateway_owners WHERE bot_token_fingerprint=?",
            (bot_token_fingerprint,),
        ).fetchone()
        return str(row["owner_id"]) if row else None


def _cli_owner_is_dead(owner_id: str) -> bool:
    """True when owner looks like discord-os-cli-<pid>-<hex> and pid is gone."""

    prefix = ""
    for candidate in (CLI_OWNER_PREFIX, LEGACY_CLI_OWNER_PREFIX):
        if owner_id.startswith(candidate):
            prefix = candidate
            break
    if not prefix:
        return False
    pid_text, sep, _ = owner_id[len(prefix) :].partition("-")
    if not sep:
        return False
    try:
        pid = int(pid_text)
    except ValueError:
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return True
    return False


def _github_attention(raw: Any) -> str:
    github = _github_blob(raw)
    return str(github.get("attention") or "").strip().lower()


def _github_last_summary(raw: Any) -> str:
    github = _github_blob(raw)
    return str(github.get("last_summary") or "").strip()


def _github_blob(raw: Any) -> dict[str, Any]:
    try:
        meta = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
    except (TypeError, json.JSONDecodeError):
        return {}
    if not isinstance(meta, dict):
        return {}
    github = meta.get("github")
    return dict(github) if isinstance(github, dict) else {}


def _job_rank(status: str, attention: str) -> int:
    if status == TaskStatus.PENDING.value:
        return 0
    if status == TaskStatus.FAILED.value or attention == "need":
        return 1
    if attention == "waiting":
        return 2
    if status in {TaskStatus.RUNNING.value, TaskStatus.PROGRESS.value}:
        return 3
    if status == TaskStatus.CANCELLED.value:
        return 4
    return 5


def _memory_row(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["provenance"] = json.loads(item.pop("provenance_json") or "{}")
    return item


def _fts_query(query: str) -> str:
    tokens = [t for t in query.replace('"', " ").split() if t]
    if not tokens:
        return '""'
    return " OR ".join(f'"{t}"' for t in tokens)
