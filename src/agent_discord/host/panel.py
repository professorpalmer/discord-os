"""Native Discord On/Off/Ask. Users do not type power commands."""

from __future__ import annotations

from typing import Any, Callable, Mapping, Optional

from agent_discord.discord.layout import action_row, string_select
from agent_discord.host.actions import (
    DEST_HOST,
    DEST_REMOTE,
    OpenIntent,
    open_custom_id,
    open_intent_from_custom_id,
)


ON_ID = "discord-os:on"
OFF_ID = "discord-os:off"
CONFIRM_OFF_ID = "discord-os:off-confirm"
CANCEL_OFF_ID = "discord-os:off-cancel"
ASK_ID = "discord-os:ask"
ASK_MODAL_ID = "discord-os:ask-modal"
ASK_TEXT_ID = "discord-os:ask-text"
JOBS_ID = "discord-os:jobs"
# Status flips that change HOST Jobs ranking — refresh panel immediately.
JOBS_PANEL_RANK_ACTIONS = frozenset({"dismiss", "ack", "cancel"})
_HOST_PANEL_MARKERS = frozenset(
    {
        "discord-os:on",
        "discord-os:off",
        "discord-os:off-confirm",
        "discord-os:off-cancel",
        "discord-os:ask",
        "discord-os:jobs",
        "discord-os:more",
    }
)
_PANEL_STALE_NEED_PREF = "jobs_panel_stale_need"
_PANEL_STALE_NEED_SPOKEN = (
    "Need: HOST Jobs panel could not refresh. Tap On or open Jobs."
)
MORE_ID = "discord-os:more"
PAIR_ID = "discord-os:pair"
HALT_ID = "discord-os:halt"
GATE_ID = "discord-os:gate"
ROLES_ID = "discord-os:roles"
ROLES_MODAL_ID = "discord-os:roles-modal"
ROLES_TEXT_ID = "discord-os:roles-text"
FILES_ID = "discord-os:files"
TERMINAL_ID = "discord-os:terminal"
BROWSER_ID = "discord-os:browser"
BROWSER_MODAL_ID = "discord-os:browser-modal"
BROWSER_REMOTE_MODAL_ID = "discord-os:browser-modal:remote"
BROWSER_TEXT_ID = "discord-os:browser-text"
GITHUB_ID = "discord-os:github"
COMPONENT_ROW = 1
BUTTON = 2
STYLE_PRIMARY = 1
STYLE_SECONDARY = 2
STYLE_SUCCESS = 3
STYLE_DANGER = 4
INTERACTION_MESSAGE_COMPONENT = 3
INTERACTION_MODAL_SUBMIT = 5
CALLBACK_DEFERRED_UPDATE = 6
CALLBACK_UPDATE_MESSAGE = 7
CALLBACK_MODAL = 9


def host_panel_components(
    armed: bool,
    *,
    confirm_off: bool = False,
    jobs: Optional[list[dict[str, Any]]] = None,
    paired: bool = False,
    write_gate: bool = False,
) -> list[dict[str, Any]]:
    if confirm_off:
        rows = [
            {
                "type": COMPONENT_ROW,
                "components": [
                    {
                        "type": BUTTON,
                        "style": STYLE_DANGER,
                        "custom_id": CONFIRM_OFF_ID,
                        "label": "Confirm",
                    },
                    {
                        "type": BUTTON,
                        "style": STYLE_PRIMARY,
                        "custom_id": CANCEL_OFF_ID,
                        "label": "Cancel",
                    },
                ],
            }
        ]
    else:
        power = [
            {
                "type": BUTTON,
                "style": STYLE_SUCCESS,
                "custom_id": ON_ID,
                "label": "On",
                "disabled": bool(armed),
            },
            {
                "type": BUTTON,
                "style": STYLE_DANGER,
                "custom_id": OFF_ID,
                "label": "Off",
                "disabled": not bool(armed),
            },
        ]
        if armed:
            power.append(
                {
                    "type": BUTTON,
                    "style": STYLE_PRIMARY,
                    "custom_id": ASK_ID,
                    "label": "Ask",
                }
            )
        rows = [{"type": COMPONENT_ROW, "components": power}]
        more = _more_select_options(
            armed=armed,
            paired=paired,
            write_gate=write_gate,
        )
        if more:
            rows.append(
                action_row(
                    [string_select(MORE_ID, more, placeholder="More")]
                )
            )
    options = _job_select_options(jobs or ())
    if options:
            rows.append(
                action_row([string_select(JOBS_ID, options, placeholder="Jobs")])
            )
    return rows


def _more_select_options(
    *,
    armed: bool,
    paired: bool,
    write_gate: bool,
) -> list[dict[str, str]]:
    options: list[dict[str, str]] = []
    if not paired:
        options.append(
            {
                "label": "Pair",
                "value": PAIR_ID,
                "description": "First click becomes owner",
            }
        )
    options.append(
        {"label": "Halt", "value": HALT_ID, "description": "Stop new jobs"}
    )
    if write_gate:
        options.append(
            {
                "label": "Auto writes",
                "value": GATE_ID,
                "description": "Skip Approve",
            }
        )
    else:
        options.append(
            {
                "label": "Gate writes",
                "value": GATE_ID,
                "description": "Require Approve",
            }
        )
    options.append(
        {
            "label": "Roles",
            "value": ROLES_ID,
            "description": "Add an operator role",
        }
    )
    options.append(
        {
            "label": "GitHub",
            "value": GITHUB_ID,
            "description": "Host gh sign-in",
        }
    )
    if armed:
        options.extend(
            [
                {
                    "label": "Files here",
                    "value": open_custom_id("files", DEST_REMOTE),
                    "description": "List the folder in Discord",
                },
                {
                    "label": "Files on host",
                    "value": open_custom_id("files", DEST_HOST),
                    "description": "Open Finder on the host",
                },
                {
                    "label": "Terminal on host",
                    "value": open_custom_id("terminal", DEST_HOST),
                    "description": "Open a shell on the host",
                },
                {
                    "label": "Browser here",
                    "value": open_custom_id("browser", DEST_REMOTE),
                    "description": "Open a link in Discord",
                },
                {
                    "label": "Browser on host",
                    "value": open_custom_id("browser", DEST_HOST),
                    "description": "Open Chromium on the host",
                },
            ]
        )
    return options


def _job_select_options(jobs: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> list[dict[str, str]]:
    options: list[dict[str, str]] = []
    seen: set[str] = set()
    for job in jobs:
        run_id = str(job.get("run_id") or "").strip()
        if not run_id or run_id in seen:
            continue
        seen.add(run_id)
        label = str(job.get("intake_text") or job.get("summary") or run_id).replace("\n", " ")
        status = str(job.get("status") or "").strip()
        code = str(job.get("job_code") or "").strip()
        if code:
            label = f"{code} {label}".strip()
        options.append(
            {
                "label": label[:80] or run_id[:80],
                "value": run_id[:100],
                "description": (f"{code} {status}".strip() if code else status)[:100],
            }
        )
    return options


def ask_modal_payload() -> dict[str, Any]:
    return _text_modal_payload(
        ASK_MODAL_ID,
        "Ask Discord OS",
        ASK_TEXT_ID,
        "Task",
        "What should this host do?",
        max_length=4000,
    )


def roles_modal_payload() -> dict[str, Any]:
    return _text_modal_payload(
        ROLES_MODAL_ID,
        "Add operator role",
        ROLES_TEXT_ID,
        "Discord role id",
        "Snowflake role id",
        max_length=32,
    )


def browser_remote_modal_payload() -> dict[str, Any]:
    return _text_modal_payload(
        BROWSER_REMOTE_MODAL_ID,
        "Open here",
        BROWSER_TEXT_ID,
        "URL",
        "http://127.0.0.1 or Discord jump",
        max_length=400,
    )


def _text_modal_payload(
    custom_id: str,
    title: str,
    field_id: str,
    label: str,
    placeholder: str,
    *,
    max_length: int,
) -> dict[str, Any]:
    return {
        "type": CALLBACK_MODAL,
        "data": {
            "custom_id": custom_id,
            "title": title,
            "components": [
                {
                    "type": COMPONENT_ROW,
                    "components": [
                        {
                            "type": 4,
                            "custom_id": field_id,
                            "style": 2,
                            "label": label,
                            "min_length": 1,
                            "max_length": max_length,
                            "required": True,
                            "placeholder": placeholder,
                        }
                    ],
                }
            ],
        },
    }


def ask_text_from_interaction(payload: Mapping[str, Any]) -> str:
    data = payload.get("data")
    if not isinstance(data, dict):
        return ""
    if str(data.get("custom_id") or "") != ASK_MODAL_ID:
        return ""
    return _first_text_input(data.get("components"))


def selected_more_id(payload: Mapping[str, Any]) -> str:
    data = payload.get("data")
    if not isinstance(data, dict):
        return ""
    if str(data.get("custom_id") or "") != MORE_ID:
        return ""
    values = data.get("values")
    if not isinstance(values, list) or not values:
        return ""
    return str(values[0] or "").strip()


def selected_job_id(payload: Mapping[str, Any]) -> str:
    data = payload.get("data")
    if not isinstance(data, dict):
        return ""
    if str(data.get("custom_id") or "") != JOBS_ID:
        return ""
    values = data.get("values")
    if not isinstance(values, list) or not values:
        return ""
    return str(values[0] or "").strip()


def _first_text_input(components: Any) -> str:
    for item in components or ():
        if not isinstance(item, dict):
            continue
        if int(item.get("type") or 0) == 4:
            return str(item.get("value") or "").strip()
        if str(item.get("custom_id") or "") in {ASK_TEXT_ID, ROLES_TEXT_ID, BROWSER_TEXT_ID}:
            return str(item.get("value") or "").strip()
        nested = _first_text_input(item.get("components"))
        if nested:
            return nested
        inner = item.get("component")
        if isinstance(inner, dict):
            nested = _first_text_input([inner])
            if nested:
                return nested
    return ""


def host_panel_payload(
    armed: bool,
    *,
    channel_id: str = "",
    confirm_off: bool = False,
    jobs: Optional[list[dict[str, Any]]] = None,
    avatar_url: str = "",
    store: Any = None,
) -> dict[str, Any]:
    from agent_discord.orchestration.cards import host_card
    from agent_discord.orchestration.service import (
        is_spend_halted,
        session_spend_usd,
        spend_cap_usd,
        writes_need_approval,
    )

    spend_usd = 0.0
    spend_known = False
    cap_usd = None
    halted = False
    write_gate = False
    paired = False
    operator_count = 0
    role_count = 0
    last_job = ""
    realm = ""
    bank = False
    if store is not None:
        try:
            from agent_discord.orchestration.service import spend_cost_known as _spend_known

            spend_usd = session_spend_usd(store)
            spend_known = _spend_known(store)
            cap_usd = spend_cap_usd(store)
            halted = is_spend_halted(store)
            write_gate = writes_need_approval(store)
        except Exception:
            spend_usd = 0.0
            spend_known = False
            cap_usd = None
            halted = False
            write_gate = False
        paired = _panel_paired(store)
        operator_count, role_count = _panel_acl_counts(store)
        last_job = _panel_last_job(store, channel_id)
        realm = _panel_realm(store, channel_id)
        bank = _panel_bank(store, channel_id)
    card = host_card(
        armed=armed,
        channel_id=channel_id,
        confirm_off=confirm_off,
        avatar_url=avatar_url,
        spend_usd=spend_usd,
        spend_known=spend_known,
        cap_usd=cap_usd,
        halted=halted,
        paired=paired,
        operator_count=operator_count,
        role_count=role_count,
        last_job=last_job,
        write_gate=write_gate,
        realm=realm,
        bank=bank,
        github=_panel_github(),
    )
    return card.v2_payload(
        rows=host_panel_components(
            armed,
            confirm_off=confirm_off,
            jobs=jobs,
            paired=paired,
            write_gate=write_gate,
        )
    )


def panel_action_from_custom_id(custom_id: str) -> Optional[str]:
    raw = (custom_id or "").strip()
    if raw == ON_ID:
        return "on"
    if raw == OFF_ID:
        return "off"
    if raw == CONFIRM_OFF_ID:
        return "off-confirm"
    if raw == CANCEL_OFF_ID:
        return "off-cancel"
    if raw == ASK_ID:
        return "ask"
    if raw == JOBS_ID:
        return "job"
    if raw == MORE_ID:
        return None
    if raw == PAIR_ID:
        return "pair"
    if raw == HALT_ID:
        return "halt"
    if raw == GATE_ID:
        return "gate"
    if raw == ROLES_ID:
        return "roles"
    intent = open_intent_from_custom_id(raw)
    if intent is not None:
        return intent.surface
    if raw == GITHUB_ID:
        return "github"
    return None


def panel_action_from_interaction(payload: Mapping[str, Any]) -> Optional[str]:
    if int(payload.get("type") or 0) != INTERACTION_MESSAGE_COMPONENT:
        return None
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    custom_id = str(data.get("custom_id") or "")
    if custom_id == MORE_ID:
        return panel_action_from_custom_id(selected_more_id({"data": data}))
    return panel_action_from_custom_id(custom_id)


def apply_panel_action(store: Any, channel_id: str, action: str) -> dict[str, Any]:
    writer = getattr(store, "set_host_control", None)
    if action in {"on", "off-confirm"} and callable(writer):
        return writer(channel_id, armed=action == "on")
    reader = getattr(store, "get_host_control", None)
    if callable(reader):
        current = reader(channel_id)
        if current is not None:
            return current
    return {
        "channel_id": channel_id,
        "armed": action not in {"off", "off-confirm"},
        "card_message_id": "",
    }


def interaction_callback_payload(
    armed: bool,
    *,
    channel_id: str = "",
    confirm_off: bool = False,
    store: Any = None,
    jobs: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    panel = host_panel_payload(
        armed,
        channel_id=channel_id,
        confirm_off=confirm_off,
        jobs=jobs if jobs is not None else (_panel_jobs(store, channel_id) if store is not None else []),
        store=store,
    )
    return {
        "type": CALLBACK_UPDATE_MESSAGE,
        "data": {
            "flags": panel["flags"],
            "components": panel["components"],
        },
    }


def _ack_interaction(
    payload: Mapping[str, Any],
    callback_payload: Mapping[str, Any],
    *,
    opener: Any = None,
) -> bool:
    interaction_id, ix_token = interaction_ids(payload)
    if not interaction_id or not ix_token:
        return False
    try:
        from agent_discord.discord.rest import callback_interaction

        callback_interaction(
            interaction_id=interaction_id,
            interaction_token=ix_token,
            payload=dict(callback_payload),
            opener=opener,
        )
        return True
    except Exception as exc:
        print(f"panel callback failed: {exc}", flush=True)
        return False


def interaction_ids(payload: Mapping[str, Any]) -> tuple[str, str]:
    return str(payload.get("id") or ""), str(payload.get("token") or "")


def interaction_channel_id(payload: Mapping[str, Any], fallback: str = "") -> str:
    raw = payload.get("channel_id")
    if raw:
        return str(raw)
    channel = payload.get("channel")
    if isinstance(channel, dict) and channel.get("id"):
        return str(channel["id"])
    return str(fallback or "")


def interaction_user_id(payload: Mapping[str, Any]) -> str:
    member = payload.get("member")
    if isinstance(member, dict):
        user = member.get("user")
        if isinstance(user, dict) and user.get("id"):
            return str(user.get("id") or "")
        roles = member.get("roles")
        _ = roles
    user = payload.get("user")
    if isinstance(user, dict):
        return str(user.get("id") or "")
    return ""


def interaction_role_ids(payload: Mapping[str, Any]) -> list[str]:
    member = payload.get("member")
    if not isinstance(member, dict):
        return []
    roles = member.get("roles")
    if isinstance(roles, list):
        return [str(item) for item in roles if str(item).strip()]
    return []


def handle_gateway_interaction(
    store: Any,
    channel_id: str,
    payload: Mapping[str, Any],
    *,
    token: str = "",
    opener: Any = None,
    on_ask: Optional[Callable[[str], None]] = None,
    on_power: Optional[Callable[[bool], None]] = None,
    on_job: Optional[Callable[[str, str], None]] = None,
    host_roots: Optional[list[Any]] = None,
    host_runner: Any = None,
    browser_open: Any = None,
) -> Optional[str]:
    """ACK within Discord's 3s window, then paint the panel. Best-effort."""

    from agent_discord.host.actions import job_action_from_custom_id
    from agent_discord.orchestration.ask_gate import (
        ask_action_from_custom_id,
        ask_confirm_action_from_custom_id,
    )

    channel_id = interaction_channel_id(payload, channel_id)
    data = payload.get("data")
    custom_id = ""
    if isinstance(data, dict):
        custom_id = str(data.get("custom_id") or "")
    confirm = ask_confirm_action_from_custom_id(custom_id)
    if confirm is not None:
        interaction_id, ix_token = interaction_ids(payload)
        if interaction_id and ix_token:
            try:
                from agent_discord.discord.rest import callback_interaction

                callback_interaction(
                    interaction_id=interaction_id,
                    interaction_token=ix_token,
                    payload={"type": CALLBACK_DEFERRED_UPDATE},
                    opener=opener,
                )
            except Exception:
                pass
        if callable(on_job):
            try:
                on_job("ask-confirm", confirm.run_id)
            except Exception:
                pass
        return "ask-confirm"
    ask = ask_action_from_custom_id(custom_id)
    if ask is not None:
        interaction_id, ix_token = interaction_ids(payload)
        if interaction_id and ix_token:
            try:
                from agent_discord.discord.rest import callback_interaction

                callback_interaction(
                    interaction_id=interaction_id,
                    interaction_token=ix_token,
                    payload={"type": CALLBACK_DEFERRED_UPDATE},
                    opener=opener,
                )
            except Exception:
                pass
        if callable(on_job):
            try:
                # option index rides in run_id as "run_id#idx" for apply_job_action ask
                on_job("ask", f"{ask.run_id}#{ask.option_index}")
            except Exception:
                pass
        return "ask"
    job = job_action_from_custom_id(custom_id)
    if job is not None:
        interaction_id, ix_token = interaction_ids(payload)
        if interaction_id and ix_token:
            try:
                from agent_discord.discord.rest import callback_interaction

                callback_interaction(
                    interaction_id=interaction_id,
                    interaction_token=ix_token,
                    payload={"type": CALLBACK_DEFERRED_UPDATE},
                    opener=opener,
                )
            except Exception:
                pass
        if callable(on_job):
            try:
                on_job(job.action, job.run_id)
            except Exception:
                pass
        if job.action in JOBS_PANEL_RANK_ACTIONS:
            try:
                refresh_host_jobs_panel(
                    store, channel_id, token=token, opener=opener
                )
            except Exception:
                pass
        return job.action

    if int(payload.get("type") or 0) == INTERACTION_MODAL_SUBMIT:
        return _handle_modal_submit(
            store,
            channel_id,
            payload,
            token=token,
            opener=opener,
            on_ask=on_ask,
            host_roots=host_roots,
            host_runner=host_runner,
            browser_open=browser_open,
        )

    action = panel_action_from_interaction(payload)
    if action is None:
        return None
    if action == "ask":
        _ack_interaction(payload, ask_modal_payload(), opener=opener)
        return action
    if action == "roles":
        _ack_interaction(payload, roles_modal_payload(), opener=opener)
        return action
    intent = _open_intent_from_payload(payload)
    if (
        intent is not None
        and intent.dest == DEST_REMOTE
        and intent.surface == "browser"
    ):
        _ack_interaction(payload, browser_remote_modal_payload(), opener=opener)
        return action
    _ack_interaction(payload, {"type": CALLBACK_DEFERRED_UPDATE}, opener=opener)

    from agent_discord.orchestration.service import (
        author_may_operate,
        seed_owner_if_empty,
        toggle_spend_halted,
        toggle_write_gate,
    )

    user_id = interaction_user_id(payload)
    role_ids = interaction_role_ids(payload)
    if action == "pair":
        # Intentional bootstrap — allowed even when REQUIRE_OPERATORS is on.
        seeded = seed_owner_if_empty(store, user_id, intentional=True)
        print(
            f"panel {action} user={user_id or '-'} seeded={int(bool(seeded))}",
            flush=True,
        )
    elif action == "on":
        # Silent first-On seed only when require flag is off (default Mac UX).
        seeded = seed_owner_if_empty(store, user_id)
        print(
            f"panel {action} user={user_id or '-'} seeded={int(bool(seeded))}",
            flush=True,
        )
    if not author_may_operate(store, user_id, action, role_ids=role_ids):
        return "denied"
    if action == "halt":
        toggle_spend_halted(store)
    if action == "gate":
        toggle_write_gate(store)
    if intent is not None:
        if _channel_armed(store, channel_id):
            _dispatch_open_intent(
                intent,
                payload,
                channel_id=channel_id,
                token=token,
                opener=opener,
                roots=host_roots,
                runner=host_runner,
                browser_open=browser_open,
            )
    if action == "job":
        try:
            _publish_job_card(store, channel_id, payload, token=token, opener=opener)
        except Exception as exc:
            print(f"panel job card failed: {exc}", flush=True)
        return action

    confirm_off = action == "off"
    if action in {"on", "off-confirm"}:
        apply_panel_action(store, channel_id, action)
        if action == "off-confirm":
            try:
                from agent_discord.orchestration.service import clear_write_session_allows

                clear_write_session_allows(store)
            except Exception:
                pass
        if callable(on_power):
            try:
                on_power(action == "on")
            except Exception:
                pass
        if action == "on":
            _post_status_digest_on_arm(store, channel_id, token=token, opener=opener)
    armed = _channel_armed(store, channel_id)
    if confirm_off:
        armed = True
    try:
        _paint_after_ack(
            store,
            channel_id,
            payload,
            token=token,
            armed=armed,
            confirm_off=confirm_off,
            opener=opener,
        )
        print(
            f"panel painted action={action} paired={int(_panel_paired(store))}",
            flush=True,
        )
    except Exception as exc:
        print(f"panel paint failed: {exc}", flush=True)
    return action



def _post_status_digest_on_arm(
    store: Any,
    channel_id: str,
    *,
    token: str = "",
    opener: Any = None,
) -> None:
    """P2.7: push RO dashboard digest when HOST On. Never mutates power."""

    if not (token or "").strip():
        return
    try:
        from agent_discord.host.status_digest import tick_status_digest
    except Exception:
        return
    workspace = None
    try:
        meta_reader = getattr(store, "path", None) or getattr(store, "db_path", None)
        if meta_reader is not None:
            from pathlib import Path as _Path

            workspace = _Path(meta_reader).parent
    except Exception:
        workspace = None
    if workspace is None:
        return

    class _RestPoster:
        def send_message(self, dest: str, body: str, thread_id: str | None = None) -> None:
            from agent_discord.discord.rest import send_channel_message

            # Prefer explicit status thread id as channel target when provided.
            target = (thread_id or "").strip() or dest
            send_channel_message(
                token=token,
                channel_id=target,
                content=body,
                opener=opener,
            )

    try:
        tick_status_digest(
            _RestPoster(),
            workspace=workspace,
            channel_id=channel_id,
            store=store,
            force=True,
            min_interval_s=0,
        )
    except Exception:
        pass


def _channel_armed(store: Any, channel_id: str) -> bool:
    reader = getattr(store, "host_is_armed", None)
    if not callable(reader):
        return True
    try:
        return bool(reader(channel_id, default=True))
    except Exception:
        return True


def _remember_panel_message(store: Any, channel_id: str, payload: Mapping[str, Any]) -> str:
    message = payload.get("message")
    message_id = ""
    if isinstance(message, dict) and message.get("id"):
        message_id = str(message["id"])
        writer = getattr(store, "set_host_control", None)
        if callable(writer):
            writer(channel_id, card_message_id=message_id)
    return message_id


def _handle_modal_submit(
    store: Any,
    channel_id: str,
    payload: Mapping[str, Any],
    *,
    token: str,
    opener: Any,
    on_ask: Optional[Callable[[str], None]],
    host_roots: Optional[list[Any]],
    host_runner: Any,
    browser_open: Any,
) -> Optional[str]:
    data = payload.get("data")
    custom_id = ""
    if isinstance(data, dict):
        custom_id = str(data.get("custom_id") or "")
    text = _first_text_input(data.get("components") if isinstance(data, dict) else None)
    _ack_interaction(payload, {"type": CALLBACK_DEFERRED_UPDATE}, opener=opener)
    if custom_id == ASK_MODAL_ID:
        if text and callable(on_ask):
            try:
                on_ask(text)
            except Exception:
                pass
        return "ask" if text else None
    from agent_discord.orchestration.service import author_may_operate

    user_id = interaction_user_id(payload)
    role_ids = interaction_role_ids(payload)
    if not author_may_operate(store, user_id, custom_id, role_ids=role_ids):
        return "denied"
    if custom_id == ROLES_MODAL_ID:
        role_id = text.strip()
        writer = getattr(store, "add_operator_role", None)
        if role_id and callable(writer):
            try:
                writer(role_id)
                print(f"panel role {role_id}", flush=True)
            except Exception as exc:
                print(f"panel role failed: {exc}", flush=True)
        _paint_interaction(
            store, channel_id, payload, token=token, opener=opener, confirm_off=False
        )
        return "roles"
    if custom_id in {BROWSER_MODAL_ID, BROWSER_REMOTE_MODAL_ID}:
        dest = DEST_REMOTE if custom_id == BROWSER_REMOTE_MODAL_ID else DEST_HOST
        if _channel_armed(store, channel_id):
            _dispatch_open_intent(
                OpenIntent(surface="browser", target=text, dest=dest),
                payload,
                channel_id=channel_id,
                token=token,
                opener=opener,
                roots=host_roots,
                runner=host_runner,
                browser_open=browser_open,
            )
        _paint_interaction(
            store, channel_id, payload, token=token, opener=opener, confirm_off=False
        )
        return "browser"
    return None


def _open_intent_from_payload(payload: Mapping[str, Any]) -> Optional[OpenIntent]:
    data = payload.get("data")
    custom_id = ""
    if isinstance(data, dict):
        custom_id = str(data.get("custom_id") or "")
    if custom_id == MORE_ID:
        custom_id = selected_more_id(payload)
    return open_intent_from_custom_id(custom_id)


def _dispatch_open_intent(
    intent: OpenIntent,
    payload: Mapping[str, Any],
    *,
    channel_id: str,
    token: str,
    opener: Any,
    roots: Optional[list[Any]],
    runner: Any,
    browser_open: Any,
) -> None:
    from agent_discord.host.actions import HostActionError, run_open_intent
    from agent_discord.orchestration.cards import open_card

    try:
        result = run_open_intent(
            intent,
            roots=list(roots or ()),
            runner=runner,
            browser_open=browser_open,
        )
        print(f"panel opened {result.surface} dest={result.dest}", flush=True)
    except HostActionError as exc:
        print(f"panel open failed: {exc}", flush=True)
        _followup_open_card(
            payload,
            open_card(
                surface=intent.surface,
                target=intent.target,
                dest=intent.dest,
                error=str(exc),
            ),
            channel_id=channel_id,
            token=token,
            opener=opener,
        )
        return
    except Exception as exc:
        print(f"panel open failed: {exc}", flush=True)
        return
    if result.dest == DEST_REMOTE or result.link_url:
        _followup_open_card(
            payload,
            open_card(
                surface=result.surface,
                target=result.target,
                dest=result.dest,
                link_url=result.link_url,
            ),
            channel_id=channel_id,
            token=token,
            opener=opener,
        )


def _followup_open_card(
    payload: Mapping[str, Any],
    card: Any,
    *,
    channel_id: str,
    token: str,
    opener: Any,
) -> None:
    body = card.v2_payload()
    application_id = str(payload.get("application_id") or "")
    _interaction_id, ix_token = interaction_ids(payload)
    try:
        if application_id and ix_token:
            from agent_discord.discord.rest import create_followup_message

            create_followup_message(
                application_id=application_id,
                interaction_token=ix_token,
                payload={
                    "flags": body["flags"],
                    "components": body["components"],
                },
                opener=opener,
            )
            return
        if token.strip():
            from agent_discord.discord.rest import send_channel_message

            send_channel_message(
                token=token,
                channel_id=channel_id,
                content="",
                components=body["components"],
                flags=body["flags"],
                opener=opener,
            )
    except Exception as exc:
        print(f"panel open card failed: {exc}", flush=True)


def _paint_interaction(
    store: Any,
    channel_id: str,
    payload: Mapping[str, Any],
    *,
    token: str,
    opener: Any,
    confirm_off: bool,
) -> None:
    try:
        _paint_after_ack(
            store,
            channel_id,
            payload,
            token=token,
            armed=_channel_armed(store, channel_id),
            confirm_off=confirm_off,
            opener=opener,
        )
    except Exception as exc:
        print(f"panel paint failed: {exc}", flush=True)


def _panel_acl_counts(store: Any) -> tuple[int, int]:
    operators = 0
    roles = 0
    lister = getattr(store, "list_operators", None)
    if callable(lister):
        try:
            operators = len(list(lister()))
        except Exception:
            operators = 0
    role_lister = getattr(store, "list_operator_roles", None)
    if callable(role_lister):
        try:
            roles = len(list(role_lister()))
        except Exception:
            roles = 0
    return operators, roles


def _panel_last_job(store: Any, channel_id: str) -> str:
    from agent_discord.orchestration.job_briefing import briefing_line

    jobs = _panel_jobs(store, channel_id)
    if not jobs:
        return ""
    return briefing_line(jobs[0])


def _panel_realm(store: Any, channel_id: str) -> str:
    reader = getattr(store, "get_binding", None)
    if not callable(reader):
        return ""
    try:
        from agent_discord.host.realms import binding_metadata

        return str(binding_metadata(reader("default", channel_id)).get("repo") or "")
    except Exception:
        return ""


def _panel_bank(store: Any, channel_id: str) -> bool:
    try:
        from agent_discord.host.memory import channel_is_memory

        return bool(channel_is_memory(store, channel_id))
    except Exception:
        return False


def _panel_github() -> str:
    try:
        from agent_discord.host.github import github_host_row

        return github_host_row()
    except Exception:
        return "sign-in"


def _panel_paired(store: Any) -> bool:
    if store is None:
        return False
    from agent_discord.orchestration.service import operators_configured

    try:
        return bool(operators_configured(store))
    except Exception:
        return False


def _panel_jobs(store: Any, channel_id: str) -> list[dict[str, Any]]:
    reader = getattr(store, "list_recent_jobs", None)
    jobs: list[dict[str, Any]] = []
    if callable(reader):
        try:
            jobs = list(reader(channel_id, limit=5))
        except Exception:
            jobs = []
    try:
        from pathlib import Path as _Path

        from agent_discord.host.liveness import (
            last_digest_from_state,
            merge_host_need_jobs,
            resolve_digest_for_panel,
        )

        ws = None
        db = getattr(store, "path", None)
        if db is not None:
            ws = _Path(db).parent
        digest = None
        if ws is not None:
            digest = resolve_digest_for_panel(
                workspace=ws, store=store, channel_id=channel_id
            )
            if digest is None:
                digest = last_digest_from_state(ws)
        return merge_host_need_jobs(jobs, digest)
    except Exception:
        return jobs


def _paint_after_ack(
    store: Any,
    channel_id: str,
    payload: Mapping[str, Any],
    *,
    token: str,
    armed: bool,
    confirm_off: bool,
    opener: Any,
) -> None:
    panel = host_panel_payload(
        armed,
        channel_id=channel_id,
        confirm_off=confirm_off,
        jobs=_panel_jobs(store, channel_id),
        store=store,
    )
    message = {"flags": panel["flags"], "components": panel["components"]}
    application_id = str(payload.get("application_id") or "")
    _interaction_id, ix_token = interaction_ids(payload)
    _ = _interaction_id
    if application_id and ix_token:
        from agent_discord.discord.rest import edit_original_interaction

        edit_original_interaction(
            application_id=application_id,
            interaction_token=ix_token,
            payload=message,
            opener=opener,
        )
        _remember_panel_message(store, channel_id, payload)
        return
    _paint_host_panel(
        store,
        channel_id,
        token=token,
        message_id=_remember_panel_message(store, channel_id, payload),
        armed=armed,
        confirm_off=confirm_off,
        opener=opener,
        panel=panel,
    )


def refresh_host_jobs_panel(
    store: Any,
    channel_id: str,
    *,
    token: str,
    opener: Any,
) -> bool:
    """Edit HOST Jobs select (+ Need line) after ranking-affecting status flips.

    When ``card_message_id`` is known, edit in place. When missing: recover the
    panel message from recent channel history, else post a fresh panel. If
    recovery/repaint is impossible, speak Need once — never silent lag forever.
    Returns True when the panel was edited or repainted.
    """

    return _refresh_host_jobs_panel(
        store, channel_id, token=token, opener=opener
    )


def _refresh_host_jobs_panel(
    store: Any,
    channel_id: str,
    *,
    token: str,
    opener: Any,
) -> bool:
    """Cheap HOST Jobs repaint after dismiss/cancel so ranking leaves Need/Live."""

    if not (token or "").strip():
        return False
    reader = getattr(store, "get_host_control", None)
    if not callable(reader):
        _speak_host_jobs_panel_need_once(
            store, channel_id, token=token, opener=opener
        )
        return False
    try:
        control = reader(channel_id) or {}
    except Exception:
        control = {}
    if not isinstance(control, dict):
        control = {}
    message_id = str(control.get("card_message_id") or "").strip()
    armed = True
    try:
        armed = bool(control.get("armed", True))
    except Exception:
        armed = True
    if not message_id:
        message_id = _recover_host_panel_message_id(
            store, channel_id, token=token, opener=opener
        )
    if message_id:
        try:
            _paint_host_panel(
                store,
                channel_id,
                token=token,
                message_id=message_id,
                armed=armed,
                confirm_off=False,
                opener=opener,
            )
            _clear_host_jobs_panel_need(store, channel_id)
            return True
        except Exception as exc:
            print(f"panel jobs refresh edit failed: {exc}", flush=True)
            message_id = ""
    if _repaint_host_panel_message(
        store, channel_id, token=token, armed=armed, opener=opener
    ):
        _clear_host_jobs_panel_need(store, channel_id)
        return True
    _speak_host_jobs_panel_need_once(
        store, channel_id, token=token, opener=opener
    )
    return False


def _components_look_like_host_panel(components: Any) -> bool:
    for item in components or ():
        if not isinstance(item, dict):
            continue
        cid = str(item.get("custom_id") or "").strip()
        if cid in _HOST_PANEL_MARKERS:
            return True
        nested = item.get("components")
        if isinstance(nested, list) and _components_look_like_host_panel(nested):
            return True
    return False


def _recover_host_panel_message_id(
    store: Any,
    channel_id: str,
    *,
    token: str,
    opener: Any,
) -> str:
    """Find the HOST panel message in recent history and rebind card_message_id."""

    try:
        from agent_discord.discord.rest import list_channel_messages

        messages = list_channel_messages(
            token=token,
            channel_id=channel_id,
            limit=30,
            opener=opener,
        )
    except Exception as exc:
        print(f"panel jobs recover list failed: {exc}", flush=True)
        return ""
    for msg in messages or ():
        mid = str(getattr(msg, "message_id", "") or "").strip()
        if not mid:
            continue
        meta = getattr(msg, "metadata", None) or {}
        comps = meta.get("components") if isinstance(meta, dict) else None
        if _components_look_like_host_panel(comps):
            writer = getattr(store, "set_host_control", None)
            if callable(writer):
                try:
                    writer(channel_id, card_message_id=mid)
                except Exception:
                    pass
            return mid
    return ""


def _repaint_host_panel_message(
    store: Any,
    channel_id: str,
    *,
    token: str,
    armed: bool,
    opener: Any,
) -> bool:
    """Post a fresh HOST panel and bind card_message_id. Best-effort."""

    if not (token or "").strip() or not (channel_id or "").strip():
        return False
    try:
        from agent_discord.discord.rest import send_channel_message

        panel = host_panel_payload(
            armed,
            channel_id=channel_id,
            confirm_off=False,
            jobs=_panel_jobs(store, channel_id),
            store=store,
        )
        posted = send_channel_message(
            token=token,
            channel_id=channel_id,
            content="",
            components=panel["components"],
            flags=panel["flags"],
            opener=opener,
        )
    except Exception as exc:
        print(f"panel jobs repaint failed: {exc}", flush=True)
        return False
    mid = str(getattr(posted, "message_id", "") or "").strip()
    if not mid:
        return False
    writer = getattr(store, "set_host_control", None)
    if callable(writer):
        try:
            writer(channel_id, card_message_id=mid)
        except Exception:
            pass
    return True


def _speak_host_jobs_panel_need_once(
    store: Any,
    channel_id: str,
    *,
    token: str,
    opener: Any,
) -> None:
    """Spoken Need once when Jobs panel cannot be refreshed — no silent lag."""

    if not (token or "").strip() or not (channel_id or "").strip():
        return
    key = f"{_PANEL_STALE_NEED_PREF}:{channel_id}"
    reader = getattr(store, "get_preference", None)
    if callable(reader):
        try:
            if str(reader("_host", key) or "").strip():
                return
        except Exception:
            pass
    try:
        from agent_discord.discord.rest import send_channel_message

        send_channel_message(
            token=token,
            channel_id=channel_id,
            content=_PANEL_STALE_NEED_SPOKEN,
            opener=opener,
        )
    except Exception as exc:
        print(f"panel jobs need speak failed: {exc}", flush=True)
        return
    writer = getattr(store, "set_preference", None)
    if callable(writer):
        try:
            writer("_host", key, "1")
        except Exception:
            pass


def _clear_host_jobs_panel_need(store: Any, channel_id: str) -> None:
    writer = getattr(store, "set_preference", None)
    if not callable(writer) or not (channel_id or "").strip():
        return
    try:
        writer("_host", f"{_PANEL_STALE_NEED_PREF}:{channel_id}", "")
    except Exception:
        pass


def _paint_host_panel(
    store: Any,
    channel_id: str,
    *,
    token: str,
    message_id: str,
    armed: bool,
    confirm_off: bool,
    opener: Any,
    panel: Optional[dict[str, Any]] = None,
) -> None:
    if not token.strip() or not message_id:
        return
    from agent_discord.discord.rest import edit_channel_message

    if panel is None:
        panel = host_panel_payload(
            armed,
            channel_id=channel_id,
            confirm_off=confirm_off,
            jobs=_panel_jobs(store, channel_id),
            store=store,
        )
    edit_channel_message(
        token=token,
        channel_id=channel_id,
        message_id=message_id,
        content="",
        components=panel["components"],
        flags=panel["flags"],
        opener=opener,
    )


def _publish_job_card(
    store: Any,
    channel_id: str,
    payload: Mapping[str, Any],
    *,
    token: str,
    opener: Any,
) -> None:
    run_id = selected_job_id(payload)
    if not run_id or not token.strip():
        return
    getter = getattr(store, "get_run", None)
    if not callable(getter):
        return
    run = getter(run_id)
    if not isinstance(run, dict):
        return
    from agent_discord.contracts import RunReceipt, TaskStatus
    from agent_discord.discord.rest import send_channel_message
    from agent_discord.orchestration.cards import receipt_card
    from agent_discord.orchestration.job_briefing import briefing_line
    from agent_discord.orchestration.reactive import reactive_for_job

    status_raw = str(run.get("status") or "completed")
    try:
        status = TaskStatus(status_raw)
    except ValueError:
        status = TaskStatus.COMPLETED
    task = {}
    task_getter = getattr(store, "get_task", None)
    task_id = str(run.get("task_id") or "")
    if callable(task_getter) and task_id:
        try:
            task = task_getter(task_id) or {}
        except Exception:
            task = {}
    job_row = {
        "run_id": run_id,
        "status": status.value,
        "summary": str(run.get("summary") or ""),
        "intake_text": str(task.get("intake_text") or ""),
        "job_code": str(task.get("job_code") or ""),
        "thread_id": str(task.get("thread_id") or ""),
    }
    summary = str(run.get("summary") or "No summary.")
    line = briefing_line(job_row)
    if line and line not in summary:
        summary = f"{line}\n{summary}"
    paint = reactive_for_job(job_row)
    card = receipt_card(
        RunReceipt(
            task_id=task_id,
            run_id=run_id,
            status=status,
            summary=summary,
            error=str(run.get("error") or "") or None,
        ),
        actions=paint.actions,
    )
    if paint.actions in {"idle", "failed", "failed_done"}:
        try:
            from agent_discord.orchestration.service import set_preference_safe
        except Exception:
            set_preference_safe = None
        writer = getattr(store, "set_preference", None)
        if callable(writer):
            try:
                writer("_host", f"pending_continue:{channel_id}", run_id)
            except Exception:
                pass
    send_channel_message(
        token=token,
        channel_id=channel_id,
        content="",
        components=card.v2_payload()["components"],
        flags=card.v2_payload()["flags"],
        opener=opener,
    )
