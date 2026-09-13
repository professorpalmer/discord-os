"""Discord-native harness cards (Components v2 console).

The live card is always a Components v2 container (``FLAG_COMPONENTS_V2``).
Embeds exist only as a narrow TypeError fallback in ``send_card`` / ``edit_card``
for ancient fakes that reject ``flags`` / v2 kwargs — not a production paint path.
Skip marker remains embed footer ``Discord OS`` for legacy harness detection.

State → button set / accent / stage lives in ``reactive.py`` (P2.14 spike).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Sequence

from agent_discord import PRODUCT_NAME
from agent_discord.contracts import RunReceipt, TaskStatus
from agent_discord.discord.layout import (
    FLAG_COMPONENTS_V2,
    STYLE_DANGER,
    STYLE_PRIMARY,
    STYLE_SECONDARY,
    STYLE_SUCCESS,
    action_row,
    attachment_component,
    button,
    container,
    discord_time,
    iter_component_text,
    link_button,
    progress_bar,
    section,
    status_table,
    text_display,
    thumbnail,
)
from agent_discord.host.actions import job_custom_id
from agent_discord.redaction import redact_text_markers, strip_forbidden_keys


CARD_PREFIX = "**Card**"
CARD_FOOTER = PRODUCT_NAME

COLOR_IDLE = 0x4E5058
COLOR_LIVE = 0x248046
COLOR_WORK = 0xC27C0E
COLOR_FAIL = 0xDA373C
COLOR_FILE = 0x5865F2
SETTLE_FILE_MAX = 512 * 1024
CODE_BODY_MAX = 1800
THINKING_BODY_MAX = 1000
V2_TEXT_BUDGET = 3900
_TRUNCATION_NOTE = f"Truncated to {CODE_BODY_MAX} characters."

_PROVIDER_LABELS = {"openrouter": "OpenRouter"}
_SURFACE_LABELS = {
    "files": "Files",
    "terminal": "Terminal",
    "browser": "Browser",
}
_RECEIPT_TITLES = {
    TaskStatus.COMPLETED: ("Done", COLOR_LIVE),
    TaskStatus.FAILED: ("Failed", COLOR_FAIL),
    TaskStatus.CANCELLED: ("Cancelled", COLOR_IDLE),
    TaskStatus.RUNNING: ("Working", COLOR_WORK),
    TaskStatus.PROGRESS: ("Working", COLOR_WORK),
    TaskStatus.PENDING: ("Queued", COLOR_IDLE),
}


@dataclass(frozen=True)
class CardMessage:
    """One Discord V2 container.

    Production paint uses ``v2_payload`` / ``v2_components``. ``embeds()`` is
    TypeError-only legacy. ``text`` is the last-resort MCP/plain fallback.
    """

    kind: str
    title: str
    description: str = ""
    color: int = COLOR_IDLE
    fields: tuple[tuple[str, str, bool], ...] = ()
    percent: Optional[float] = None
    file_name: str = ""
    file_data: bytes = b""
    link_url: str = ""
    updated_ts: Optional[int] = None
    avatar_url: str = ""
    rows: tuple[dict[str, Any], ...] = ()
    thinking: str = ""
    chrome: str = ""  # Need / Live / Done Section label
    job_code: str = ""

    @property
    def text(self) -> str:
        lines = [self.title]
        if self.thinking:
            lines.append(self.thinking)
        if self.description:
            lines.append(self.description)
        for name, value, _inline in self.fields:
            lines.append(f"{name}: {value}")
        return redact_text_markers("\n".join(lines))

    def embeds(self) -> list[dict[str, Any]]:
        """Legacy embed shape for TypeError fallbacks only — not production."""
        embed: dict[str, Any] = {
            "title": self.title,
            "color": int(self.color),
            "footer": {"text": CARD_FOOTER},
        }
        if self.description:
            embed["description"] = self.description
        if self.fields:
            embed["fields"] = [
                {"name": name, "value": value, "inline": bool(inline)}
                for name, value, inline in self.fields
            ]
        return [embed]

    def v2_components(
        self,
        *,
        rows: Optional[list[dict[str, Any]]] = None,
    ) -> list[dict[str, Any]]:
        """One Container: Section-by-state heading, thinking, body, file, buttons."""

        heading = f"### {self.title}"
        chrome = (self.chrome or "").strip()
        code = (self.job_code or "").strip()
        children: list[dict[str, Any]] = []
        if self.kind in {"RECEIPT", "PROGRESS", "WORKING", "ASK", "TOOL"} or chrome:
            # Discord-half P1: Section layout by Need / Live / Done.
            label = chrome or self.title
            lines = [f"### {label}"]
            if code:
                lines.append(f"`{code}` · {self.title}" if chrome else f"`{code}`")
            elif chrome and self.title and self.title != chrome:
                lines.append(self.title)
            if self.avatar_url:
                children.append(section(lines[:3], thumbnail(self.avatar_url)))
            else:
                chip = button(label[:80] or "Job", f"discord-os:chrome:{label[:40]}", style=STYLE_SECONDARY, disabled=True)
                children.append(section(lines[:3], chip))
            used = sum(len(x) for x in lines)
        elif self.avatar_url:
            children = [section([heading], thumbnail(self.avatar_url))]
            used = len(heading)
        else:
            children = [text_display(heading)]
            used = len(heading)
        if self.kind == "HOST":
            live = self.title == "Running"
            table = [
                ("power", "on" if live else "off"),
                ("listen", "live" if live else "idle"),
            ]
            table.extend((name, value) for name, value, _inline in self.fields)
            table_text = status_table(table)
            children.append(text_display(table_text))
            used += len(table_text)
        if self.thinking:
            think_cap = min(THINKING_BODY_MAX, max(120, V2_TEXT_BUDGET - used - 80))
            fence = _bounded_fence("", self.thinking, max_chars=think_cap)
            children.append(text_display(fence))
            used += len(fence)
        body_parts: list[str] = []
        if self.description:
            body_parts.append(self.description)
        if self.percent is not None:
            body_parts.append(f"`{progress_bar(self.percent)}`")
        if self.fields and self.kind != "HOST":
            body_parts.append(
                "\n".join(f"`{name}`  {value}" for name, value, _inline in self.fields)
            )
        stamp = discord_time(self.updated_ts)
        body_parts.append(f"-# {CARD_FOOTER}  ·  {stamp}")
        body = redact_text_markers("\n\n".join(body_parts))
        leftover = V2_TEXT_BUDGET - used
        if leftover >= 0 and len(body) > leftover:
            body = body[:leftover]
        children.append(text_display(body))
        if self.file_name:
            children.append(attachment_component(self.file_name))
        extra = list(self.rows)
        extra.extend(rows or [])
        if self.link_url:
            extra.append(action_row([link_button("Open", self.link_url)]))
        if extra:
            children.extend(extra)
        return [container(children, color=self.color)]

    def v2_payload(
        self,
        *,
        rows: Optional[list[dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        return {
            "flags": FLAG_COMPONENTS_V2,
            "components": self.v2_components(rows=rows),
        }


def is_harness_card(content: str) -> bool:
    text = (content or "").strip()
    return text.startswith(CARD_PREFIX) or text.startswith("**Receipt**")


def is_harness_message(
    content: str,
    embeds: Optional[Sequence[MappingLike]] = None,
    components: Optional[Sequence[MappingLike]] = None,
) -> bool:
    if is_harness_card(content):
        return True
    for embed in embeds or ():
        if not isinstance(embed, dict):
            continue
        footer = embed.get("footer")
        text = ""
        if isinstance(footer, dict):
            text = str(footer.get("text") or "")
        if text == CARD_FOOTER or text.startswith(f"{CARD_FOOTER} "):
            return True
    for text in iter_component_text(components):
        if CARD_FOOTER in text or text.startswith(CARD_PREFIX):
            return True
    return False


def render_connect_card(
    *,
    provider: str,
    fingerprint: str,
    source: str,
    ticket: str = "",
    error: str = "",
) -> str:
    return connect_card(
        provider=provider,
        fingerprint=fingerprint,
        source=source,
        ticket=ticket,
        error=error,
    ).text


def connect_card(
    *,
    provider: str,
    fingerprint: str = "",
    source: str = "",
    ticket: str = "",
    error: str = "",
) -> CardMessage:
    _ = fingerprint
    label = _PROVIDER_LABELS.get(provider, provider or "OpenRouter")
    if error:
        return CardMessage(
            kind="CONNECT",
            title="Connect failed",
            description=redact_text_markers(error),
            color=COLOR_FAIL,
        )
    if ticket:
        return CardMessage(
            kind="CONNECT",
            title="Finish on the host",
            description=(
                f"Run this on the machine, then paste the {label} key on stdin.\n"
                f"discord-os connect --ticket {ticket} --provider {provider}\n"
                "Expires in 15 minutes."
            ),
            color=COLOR_IDLE,
        )
    detail = "from this host" if source == "env" else "on this host"
    return CardMessage(
        kind="CONNECT",
        title="Connected",
        description=f"{label} is ready {detail}.",
        color=COLOR_LIVE,
    )


def github_wake_card(summary: str, *, kind: str = "") -> CardMessage:
    title = "Checks failed" if kind == "check_failed" else "Review"
    color = COLOR_FAIL if kind == "check_failed" else COLOR_WORK
    return CardMessage(
        kind="NOTE",
        title=title,
        description=redact_text_markers(summary or ""),
        color=color,
    )


def render_progress_card(
    *,
    stage: str,
    message: str,
    percent: Optional[float] = None,
    run_id: str = "",
) -> str:
    return progress_card(
        stage=stage, message=message, percent=percent, run_id=run_id
    ).text


def progress_card(
    *,
    stage: str,
    message: str,
    percent: Optional[float] = None,
    run_id: str = "",
    actions: str = "running",
    thinking: str = "",
    job_code: str = "",
    chrome: str = "",
) -> CardMessage:
    from agent_discord.orchestration.job_briefing import CHROME_LIVE

    title = _title_case(stage) or "Working"
    code = (job_code or "").strip()
    if code:
        title = f"{code} · {title}"
    body = redact_text_markers(message or "")
    think = redact_text_markers(thinking or "")
    return CardMessage(
        kind="PROGRESS",
        title=title,
        description=body,
        thinking=think,
        color=COLOR_WORK,
        percent=percent,
        rows=_job_rows(run_id, actions, job_code=code),
        chrome=(chrome or CHROME_LIVE),
        job_code=code,
    )



def working_card(
    *,
    task_label: str = "",
    message: str = "",
    percent: Optional[float] = None,
    run_id: str = "",
    actions: str = "running",
    job_code: str = "",
    chrome: str = "",
) -> CardMessage:
    from agent_discord.orchestration.job_briefing import CHROME_LIVE, CHROME_NEED

    title = _title_case(task_label) or "Working"
    mode = (actions or "").strip().lower()
    bucket = chrome or (CHROME_NEED if mode in {"parked", "plan"} else CHROME_LIVE)
    return CardMessage(
        kind="WORKING",
        title=title,
        description=redact_text_markers(message or ""),
        color=COLOR_WORK,
        percent=percent,
        rows=_job_rows(run_id, actions, job_code=job_code),
        chrome=bucket,
        job_code=(job_code or "").strip(),
    )


def code_card(language: str, code: str, title: str = "Code") -> CardMessage:
    return CardMessage(
        kind="CODE",
        title=title or "Code",
        description=_bounded_fence(language, code),
        color=COLOR_FILE,
    )


def diff_card(
    diff_text: str,
    filename: str = "patch.diff",
    title: str = "Diff",
) -> CardMessage:
    heading = f"`{filename}`" if filename else ""
    body = _bounded_fence("diff", diff_text)
    description = f"{heading}\n{body}" if heading else body
    return CardMessage(
        kind="DIFF",
        title=title or "Diff",
        description=description,
        color=COLOR_FILE,
    )


def job_action_row(run_id: str, *, actions: str = "parked", job_code: str = "") -> dict[str, Any]:
    rid = (run_id or "").strip()
    code = (job_code or "").strip()
    mode = (actions or "parked").strip().lower()
    if mode == "running":
        items = [button("Cancel", job_custom_id("cancel", rid, job_code=code), style=STYLE_DANGER)]
    elif mode == "done":
        items = [
            button("Continue", job_custom_id("continue", rid, job_code=code), style=STYLE_PRIMARY),
            button("Retry", job_custom_id("retry", rid, job_code=code), style=STYLE_SECONDARY),
        ]
    elif mode == "idle":
        items = [button("Continue", job_custom_id("continue", rid, job_code=code), style=STYLE_PRIMARY)]
    elif mode == "failed":
        items = [
            button("Continue", job_custom_id("continue", rid, job_code=code), style=STYLE_PRIMARY),
            button("Dismiss", job_custom_id("dismiss", rid, job_code=code), style=STYLE_SECONDARY),
        ]
    elif mode == "failed_done":
        items = [
            button("Continue", job_custom_id("continue", rid, job_code=code), style=STYLE_PRIMARY),
            button("Retry", job_custom_id("retry", rid, job_code=code), style=STYLE_SECONDARY),
            button("Dismiss", job_custom_id("dismiss", rid, job_code=code), style=STYLE_SECONDARY),
        ]
    elif mode == "plan":
        # P2.8 plan Approve / Cancel — no Always (write-gate only)
        items = [
            button("Approve", job_custom_id("approve", rid, job_code=code), style=STYLE_SUCCESS),
            button("Cancel", job_custom_id("cancel", rid, job_code=code), style=STYLE_DANGER),
        ]
    elif mode == "all":
        items = [
            button("Allow", job_custom_id("approve", rid, job_code=code), style=STYLE_SUCCESS),
            button("Always allow", job_custom_id("always", rid, job_code=code), style=STYLE_PRIMARY),
            button("Deny", job_custom_id("deny", rid, job_code=code), style=STYLE_DANGER),
            button("Cancel", job_custom_id("cancel", rid, job_code=code), style=STYLE_SECONDARY),
            button("Retry", job_custom_id("retry", rid, job_code=code), style=STYLE_SECONDARY),
        ]
    else:
        # parked write-gate: DisCode-style Allow / Always allow / Deny
        items = [
            button("Allow", job_custom_id("approve", rid, job_code=code), style=STYLE_SUCCESS),
            button("Always allow", job_custom_id("always", rid, job_code=code), style=STYLE_PRIMARY),
            button("Deny", job_custom_id("deny", rid, job_code=code), style=STYLE_DANGER),
        ]
    return action_row(items)


def render_receipt_card(receipt: RunReceipt, *, max_progress: int = 5) -> str:
    return receipt_card(receipt, max_progress=max_progress).text


def receipt_card(
    receipt: RunReceipt,
    *,
    max_progress: int = 5,
    thinking: str = "",
    actions: str = "done",
    job_code: str = "",
) -> CardMessage:
    title, color = _RECEIPT_TITLES.get(receipt.status, ("Receipt", COLOR_IDLE))
    summary = str(strip_forbidden_keys({"summary": receipt.summary}).get("summary", ""))
    description = redact_text_markers(summary.strip() or title)
    think = redact_text_markers(thinking or "")
    if think and think.strip() == description.strip():
        think = ""
    fields: list[tuple[str, str, bool]] = []
    jump = ""
    if receipt.artifacts:
        lines = []
        for art in receipt.artifacts:
            _ = strip_forbidden_keys(dict(art.provenance))
            obj = art.as_object_ref()
            if obj is not None:
                from agent_discord.contracts import discord_jump_url

                if not jump:
                    jump = discord_jump_url(
                        obj.guild_id, obj.channel_id, obj.message_id
                    )
                label = obj.filename or art.kind
            elif art.path:
                label = art.path
            else:
                label = art.kind
            digest = (art.sha256 or "")[:12]
            lines.append(f"{label} {digest}".strip() if digest else label)
        if lines:
            fields.append(("Files", "\n".join(lines[:8]), False))
    if receipt.usage and receipt.usage.model:
        fields.append(("Model", receipt.usage.model, True))
    if receipt.error:
        fields.append(("Error", redact_text_markers(receipt.error)[:1024], False))
    _ = max_progress
    fname, fbytes = settle_file_attachment(receipt)
    chrome = _receipt_chrome(receipt.status)
    return CardMessage(
        kind="RECEIPT",
        title=title,
        description=description,
        thinking=think,
        color=color,
        fields=tuple(fields),
        link_url=jump,
        rows=_job_rows(
            receipt.run_id,
            actions,
            job_code=(job_code or str(getattr(receipt, "job_code", "") or "")).strip(),
        ),
        file_name=fname,
        file_data=fbytes,
        chrome=chrome,
        job_code=(job_code or str(getattr(receipt, "job_code", "") or "")).strip(),
    )


def render_open_card(
    *,
    surface: str,
    target: str,
    error: str = "",
    dest: str = "host",
    link_url: str = "",
) -> str:
    return open_card(
        surface=surface,
        target=target,
        error=error,
        dest=dest,
        link_url=link_url,
    ).text


def open_card(
    *,
    surface: str,
    target: str,
    error: str = "",
    dest: str = "host",
    link_url: str = "",
) -> CardMessage:
    label = _SURFACE_LABELS.get(surface, surface or "Host")
    if error:
        return CardMessage(
            kind="OPEN",
            title="Could not open",
            description=redact_text_markers(error),
            color=COLOR_FAIL,
        )
    href = (link_url or target).strip()
    if dest == "remote" and surface == "browser":
        return CardMessage(
            kind="OPEN",
            title="Open here",
            description=redact_text_markers(href or label),
            color=COLOR_LIVE,
            link_url=href,
        )
    if dest == "remote":
        return CardMessage(
            kind="OPEN",
            title=f"{label} here",
            description=redact_text_markers(target or label),
            color=COLOR_LIVE,
        )
    detail = target if surface == "browser" and target else label
    return CardMessage(
        kind="OPEN",
        title="Opened on the host",
        description=detail,
        color=COLOR_LIVE,
    )


def render_host_card(
    *,
    armed: bool,
    channel_id: str = "",
) -> str:
    return host_card(armed=armed, channel_id=channel_id).text


def _host_description(*, last_job: str = "", update_pill: str = "") -> str:
    """HOST card body: optional Update-available pill above the Jobs briefing line."""

    pill = (update_pill or "").strip()
    job = (last_job or "").strip()
    if pill and job:
        return f"{pill}\n{job}"
    return pill or job


def host_card(
    *,
    armed: bool,
    channel_id: str = "",
    confirm_off: bool = False,
    confirm_clear_needs: int = 0,
    avatar_url: str = "",
    spend_usd: float = 0.0,
    cap_usd: Optional[float] = None,
    halted: bool = False,
    paired: bool = False,
    operator_count: int = 0,
    role_count: int = 0,
    last_job: str = "",
    write_gate: bool = False,
    realm: str = "",
    bank: bool = False,
    github: str = "",
    spend_known: bool = True,
    update_pill: str = "",
) -> CardMessage:
    _ = channel_id
    fields = _host_status_fields(
        paired=paired,
        operator_count=operator_count,
        role_count=role_count,
        write_gate=write_gate,
        spend_usd=spend_usd,
        cap_usd=cap_usd,
        halted=halted,
        realm=realm,
        bank=bank,
        github=github,
        spend_known=spend_known,
    )
    if confirm_off:
        return CardMessage(
            kind="HOST",
            title="Stop?",
            description="Confirm to stop. Cancel keeps it running.",
            color=COLOR_WORK,
            avatar_url=avatar_url,
            fields=fields,
        )
    if int(confirm_clear_needs or 0) > 0:
        n = int(confirm_clear_needs)
        return CardMessage(
            kind="HOST",
            title="Clear failed Needs?",
            description=(
                f"Dismiss {n} failed Need{'s' if n != 1 else ''} "
                "(same as Dismiss on a job card). Cancel leaves them."
            ),
            color=COLOR_WORK,
            avatar_url=avatar_url,
            fields=fields,
        )
    return CardMessage(
        kind="HOST",
        title="Halted" if halted and armed else ("Running" if armed else "Stopped"),
        description=_host_description(last_job=last_job, update_pill=update_pill),
        color=COLOR_FAIL if halted and armed else (COLOR_LIVE if armed else COLOR_IDLE),
        avatar_url=avatar_url,
        fields=fields,
    )


def _host_status_fields(
    *,
    paired: bool,
    operator_count: int,
    role_count: int,
    write_gate: bool,
    spend_usd: float,
    cap_usd: Optional[float],
    halted: bool,
    realm: str,
    bank: bool,
    github: str = "",
    spend_known: bool = True,
) -> tuple[tuple[str, str, bool], ...]:
    from agent_discord.orchestration.service import format_spend, format_usd

    acl = "open"
    if paired:
        ops = max(0, int(operator_count))
        roles = max(0, int(role_count))
        op_word = "op" if ops == 1 else "ops"
        role_word = "role" if roles == 1 else "roles"
        acl = f"paired · {ops} {op_word} · {roles} {role_word}"
    rows: list[tuple[str, str, bool]] = [
        ("acl", acl, True),
        ("writes", "gate" if write_gate else "auto", True),
    ]
    spend = format_spend(
        float(spend_usd) if spend_known else None,
        known=bool(spend_known),
    )
    if cap_usd is not None:
        spend = f"{spend} / {format_usd(cap_usd)}"
    if halted:
        spend = f"{spend} halt"
    rows.append(("spend", spend, True))
    name = (realm or "").strip()
    if name:
        rows.append(("realm", name, True))
    if bank:
        rows.append(("bank", "yes", True))
    if github:
        rows.append(("github", github, True))
    return tuple(rows)


def note_card(text: str, *, source_channel: str = "") -> CardMessage:
    body = (text or "").strip()
    if source_channel:
        body = f"From #{source_channel}\n{body}"
    return CardMessage(
        kind="NOTE",
        title="Note",
        description=body or "Empty note.",
        color=COLOR_IDLE,
    )


def render_overflow_card(
    *,
    filename: str,
    sha256: str,
    size: int,
    jump_url: str,
    local_stash: str = "",
) -> str:
    return overflow_card(
        filename=filename,
        sha256=sha256,
        size=size,
        jump_url=jump_url,
        local_stash=local_stash,
    ).text


def overflow_card(
    *,
    filename: str,
    sha256: str,
    size: int,
    jump_url: str,
    local_stash: str = "",
) -> CardMessage:
    _ = sha256
    fields: list[tuple[str, str, bool]] = [("Size", format_size(size), True)]
    if local_stash:
        fields.append(("Host copy", local_stash, False))
    return CardMessage(
        kind="OVERFLOW",
        title="Too large for Discord",
        description=filename,
        color=COLOR_FAIL,
        fields=tuple(fields),
        link_url=jump_url,
    )


def object_card(*, filename: str, size: int, kind: str = "blob") -> CardMessage:
    label = "Overflow pointer" if kind == "overflow" else filename
    return CardMessage(
        kind="OBJECT",
        title=label,
        description=format_size(size),
        color=COLOR_FILE,
        file_name="" if kind == "overflow" else filename,
    )


def format_size(size: int) -> str:
    n = max(0, int(size))
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        value = n / 1024
        return f"{value:.1f} KB".replace(".0 KB", " KB")
    value = n / (1024 * 1024)
    return f"{value:.1f} MB".replace(".0 MB", " MB")


def send_card(
    discord: Any,
    channel_id: str,
    card: CardMessage,
    *,
    thread_id: Optional[str] = None,
    components: Optional[list[dict[str, Any]]] = None,
) -> Any:
    """Post a card. Prefer Components v2; embed/text only on TypeError."""
    payload = card.v2_payload(rows=components)
    if card.file_name and card.file_data:
        uploader = getattr(discord, "send_attachment", None)
        if callable(uploader):
            try:
                return uploader(
                    channel_id,
                    card.file_name,
                    card.file_data,
                    content="",
                    thread_id=thread_id,
                    components=payload["components"],
                    flags=payload["flags"],
                )
            except TypeError:
                try:
                    return uploader(
                        channel_id,
                        card.file_name,
                        card.file_data,
                        content="",
                        thread_id=thread_id,
                    )
                except Exception:
                    pass
            except Exception:
                pass
    poster = getattr(discord, "send_message", None)
    if not callable(poster):
        return None
    try:
        return poster(
            channel_id,
            "",
            thread_id=thread_id,
            components=payload["components"],
            flags=payload["flags"],
        )
    except TypeError:
        # Ancient fakes / signatures: narrow embed fallback, then plain text.
        try:
            return poster(
                channel_id,
                "",
                thread_id=thread_id,
                embeds=card.embeds(),
                components=components,
            )
        except TypeError:
            try:
                return poster(
                    channel_id, card.text, thread_id=thread_id, components=components
                )
            except TypeError:
                return poster(channel_id, card.text, thread_id=thread_id)


def edit_card(
    discord: Any,
    channel_id: str,
    message_id: str,
    card: CardMessage,
    *,
    components: Optional[list[dict[str, Any]]] = None,
) -> Any:
    """Edit a live card. Prefer Components v2; embed/text only on TypeError."""
    editor = getattr(discord, "edit_message", None)
    if not callable(editor):
        raise TypeError("edit_message is not available")
    payload = card.v2_payload(rows=components)
    try:
        return editor(
            channel_id,
            message_id,
            "",
            components=payload["components"],
            flags=payload["flags"],
        )
    except TypeError:
        try:
            return editor(
                channel_id,
                message_id,
                "",
                embeds=card.embeds(),
                components=components,
            )
        except TypeError:
            if components is not None:
                try:
                    return editor(
                        channel_id, message_id, card.text, components=components
                    )
                except TypeError:
                    pass
            return editor(channel_id, message_id, card.text)


def _title_case(stage: str) -> str:
    raw = (stage or "").replace("_", " ").strip()
    return raw[:1].upper() + raw[1:] if raw else ""


def _job_rows(run_id: str, actions: str = "running", job_code: str = "") -> tuple[dict[str, Any], ...]:
    if not (run_id or "").strip():
        return ()
    return (job_action_row(run_id, actions=actions, job_code=job_code),)


def _fence_language(language: str) -> str:
    return "".join((language or "").split()).replace("`", "")[:32]


def _bounded_fence(language: str, source: str, *, max_chars: int = CODE_BODY_MAX) -> str:
    cleaned = redact_text_markers(source or "")
    cap = max(1, int(max_chars))
    truncated = len(cleaned) > cap
    if truncated:
        cleaned = cleaned[:cap]
    fence = "```"
    while fence in cleaned:
        fence += "`"
    lang = _fence_language(language)
    opener = f"{fence}{lang}" if lang else fence
    block = f"{opener}\n{cleaned}\n{fence}"
    if truncated:
        if cap == CODE_BODY_MAX:
            return f"{block}\n{_TRUNCATION_NOTE}"
        return f"{block}\nTruncated to {cap} characters."
    return block


def _receipt_chrome(status: TaskStatus | str | None) -> str:
    from agent_discord.orchestration.job_briefing import (
        CHROME_DONE,
        CHROME_LIVE,
        CHROME_NEED,
    )

    state = status.value if isinstance(status, TaskStatus) else str(status or "").strip().lower()
    if state in {"failed", "pending"}:
        return CHROME_NEED
    if state in {"running", "progress"}:
        return CHROME_LIVE
    return CHROME_DONE


def settle_file_attachment(receipt: RunReceipt) -> tuple[str, bytes]:
    """Last log/diff on settle/fail when present — size-capped File component bytes."""

    from pathlib import Path as _Path

    status = receipt.status
    if status not in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}:
        return "", b""
    # Prefer on-disk diff/patch/log artifacts.
    for art in reversed(tuple(receipt.artifacts or ())):
        kind = str(getattr(art, "kind", "") or "").lower()
        if kind not in {"diff", "patch", "log", "error"}:
            continue
        path = str(getattr(art, "path", "") or "").strip()
        if path and _Path(path).is_file():
            try:
                data = _Path(path).read_bytes()[:SETTLE_FILE_MAX]
            except OSError:
                continue
            if not data:
                continue
            name = str(getattr(art, "filename", "") or "") or f"{kind}.txt"
            return _safe_attach_name(name), data
    # Fallback: failed → error.log from error/summary; done → optional settle excerpt.
    if status is TaskStatus.FAILED:
        body = "\n".join(
            part for part in (str(receipt.error or "").strip(), str(receipt.summary or "").strip()) if part
        )
        if body:
            data = body.encode("utf-8")[:SETTLE_FILE_MAX]
            return "error.log", data
    if status is TaskStatus.COMPLETED:
        # Prefer an explicit settle/diff-ish artifact filename already listed.
        for art in reversed(tuple(receipt.artifacts or ())):
            kind = str(getattr(art, "kind", "") or "").lower()
            if kind in {"settle", "diff", "patch"}:
                summary = str(receipt.summary or "").strip()
                if summary:
                    return _safe_attach_name(str(getattr(art, "filename", "") or f"{kind}.md")), summary.encode("utf-8")[:SETTLE_FILE_MAX]
    return "", b""


def _safe_attach_name(name: str) -> str:
    base = (name or "attach.txt").replace('\\', "/").rsplit("/", 1)[-1].strip() or "attach.txt"
    return base[:80]


MappingLike = dict[str, Any]
