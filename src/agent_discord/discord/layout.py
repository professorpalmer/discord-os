"""Discord Components V2 layout — the in-channel ceiling, not a TUI.

Container + Section + Text + Separator + File/Gallery + buttons.
Edit the same message to update it.
"""

from __future__ import annotations

import time
from typing import Any, Iterable, Optional, Sequence


FLAG_COMPONENTS_V2 = 1 << 15
FLAG_IS_VOICE_MESSAGE = 1 << 13

TYPE_ACTION_ROW = 1
TYPE_BUTTON = 2
TYPE_STRING_SELECT = 3
TYPE_SECTION = 9
TYPE_TEXT = 10
TYPE_THUMBNAIL = 11
TYPE_MEDIA_GALLERY = 12
TYPE_FILE = 13
TYPE_SEPARATOR = 14
TYPE_CONTAINER = 17

STYLE_PRIMARY = 1
STYLE_SECONDARY = 2
STYLE_SUCCESS = 3
STYLE_DANGER = 4
STYLE_LINK = 5

#: Discord rejects a Components V2 message past either ceiling with a 400.
#: Nested components count toward the first; every text display's content
#: counts toward the second.
COMPONENTS_V2_MAX_COMPONENTS = 40
COMPONENTS_V2_MAX_TEXT_CHARS = 4000
TRIM_MARKER = "\n[trimmed]"

ACTIVITY_WATCHING = 3
ACTIVITY_NAME_MAX = 128
CUSTOM_ID_MAX = 100
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp")


def text_display(content: str) -> dict[str, Any]:
    return {"type": TYPE_TEXT, "content": content}


def separator(*, divider: bool = True, spacing: int = 1) -> dict[str, Any]:
    return {"type": TYPE_SEPARATOR, "divider": bool(divider), "spacing": int(spacing)}


def file_ref(filename: str) -> dict[str, Any]:
    name = _basename(filename)
    return {"type": TYPE_FILE, "file": {"url": f"attachment://{name}"}}


def media_gallery(filename: str) -> dict[str, Any]:
    name = _basename(filename)
    return {
        "type": TYPE_MEDIA_GALLERY,
        "items": [{"media": {"url": f"attachment://{name}"}}],
    }


def is_image_name(filename: str) -> bool:
    lower = _basename(filename).lower()
    return any(lower.endswith(suffix) for suffix in IMAGE_SUFFIXES)


def attachment_component(filename: str) -> dict[str, Any]:
    if is_image_name(filename):
        return media_gallery(filename)
    return file_ref(filename)


def section(texts: Sequence[str], accessory: dict[str, Any]) -> dict[str, Any]:
    children = [text_display(item) for item in texts if item][:3]
    return {"type": TYPE_SECTION, "components": children, "accessory": accessory}


def action_row(components: Sequence[dict[str, Any]]) -> dict[str, Any]:
    return {"type": TYPE_ACTION_ROW, "components": list(components)[:5]}


def button(
    label: str,
    custom_id: str,
    *,
    style: int = STYLE_SECONDARY,
    disabled: bool = False,
) -> dict[str, Any]:
    return {
        "type": TYPE_BUTTON,
        "style": int(style),
        "label": (label or "Button")[:80],
        "custom_id": (custom_id or "")[:CUSTOM_ID_MAX],
        "disabled": bool(disabled),
    }


def thumbnail(url: str, *, description: str = "Discord OS") -> dict[str, Any]:
    return {
        "type": TYPE_THUMBNAIL,
        "media": {"url": url},
        "description": (description or "Discord OS")[:256],
    }


def string_select(
    custom_id: str,
    options: Sequence[dict[str, str]],
    *,
    placeholder: str = "Jobs",
) -> dict[str, Any]:
    items = []
    for option in options[:25]:
        label = str(option.get("label") or "job")[:100]
        value = str(option.get("value") or "")[:100]
        if not value:
            continue
        item = {"label": label, "value": value}
        desc = str(option.get("description") or "").strip()
        if desc:
            item["description"] = desc[:100]
        items.append(item)
    return {
        "type": TYPE_STRING_SELECT,
        "custom_id": custom_id,
        "placeholder": (placeholder or "Jobs")[:150],
        "min_values": 1,
        "max_values": 1,
        "options": items,
    }


def link_button(label: str, url: str) -> dict[str, Any]:
    return {
        "type": TYPE_BUTTON,
        "style": STYLE_LINK,
        "label": (label or "Open")[:80],
        "url": url,
    }


def container(
    children: list[dict[str, Any]],
    *,
    color: int,
) -> dict[str, Any]:
    return {
        "type": TYPE_CONTAINER,
        "accent_color": int(color),
        "components": list(children),
    }


def status_table(rows: Sequence[tuple[str, str]]) -> str:
    pairs = [(str(key), str(value)) for key, value in rows if key]
    if not pairs:
        return ""
    width = max(len(key) for key, _value in pairs)
    lines = [f"{key.ljust(width)}  {value}" for key, value in pairs]
    return "```\n" + "\n".join(lines) + "\n```"


def discord_time(ts: Optional[int] = None) -> str:
    when = int(ts if ts is not None else time.time())
    return f"<t:{when}:R>"


def presence_update(*, status: str, name: str) -> dict[str, Any]:
    return {
        "op": 3,
        "d": {
            "since": None,
            "activities": [{"name": name, "type": ACTIVITY_WATCHING}],
            "status": status,
            "afk": False,
        },
    }


def _basename(filename: str) -> str:
    return (filename or "object.bin").replace("\\", "/").rsplit("/", 1)[-1]


def progress_bar(percent: float, *, width: int = 12) -> str:
    """TUI-adjacent meter. ASCII only — Discord markdown, not a terminal."""

    try:
        value = float(percent)
    except (TypeError, ValueError):
        value = 0.0
    value = max(0.0, min(100.0, value))
    filled = int(round(width * value / 100.0))
    filled = max(0, min(width, filled))
    return f"[{'=' * filled}{'.' * (width - filled)}] {value:.0f}%"


_CONTROL_TYPES = frozenset({TYPE_ACTION_ROW, TYPE_BUTTON, TYPE_STRING_SELECT})


def _child_lists(node: dict[str, Any]) -> list[list[Any]]:
    lists: list[list[Any]] = []
    nested = node.get("components")
    if isinstance(nested, list):
        lists.append(nested)
    return lists


def _nodes(components: Optional[Iterable[Any]]) -> list[dict[str, Any]]:
    """Every component dict in document order, accessories included."""

    found: list[dict[str, Any]] = []
    for item in components or ():
        if not isinstance(item, dict):
            continue
        found.append(item)
        accessory = item.get("accessory")
        if isinstance(accessory, dict):
            found.append(accessory)
        for child in _child_lists(item):
            found.extend(_nodes(child))
    return found


def count_components(components: Optional[Iterable[Any]]) -> int:
    """Total components Discord will count, nesting and accessories included."""

    return len(_nodes(components))


def total_text_chars(components: Optional[Iterable[Any]]) -> int:
    return sum(len(text) for text in iter_component_text(components))


def _holds_control(node: dict[str, Any]) -> bool:
    if int(node.get("type") or 0) in _CONTROL_TYPES:
        return True
    accessory = node.get("accessory")
    if isinstance(accessory, dict) and int(accessory.get("type") or 0) in _CONTROL_TYPES:
        return True
    for child in _child_lists(node):
        for item in child:
            if isinstance(item, dict) and _holds_control(item):
                return True
    return False


def _drop_last_droppable(nodes: list[Any]) -> bool:
    """Remove the trailing component that carries no control. Deepest last."""

    for index in range(len(nodes) - 1, -1, -1):
        node = nodes[index]
        if not isinstance(node, dict):
            nodes.pop(index)
            return True
        if not _holds_control(node):
            nodes.pop(index)
            return True
        for child in _child_lists(node):
            if _drop_last_droppable(child):
                return True
    return False


def _trim_text_in_place(nodes: list[dict[str, Any]], budget: int) -> None:
    """Spend the character budget on earlier text displays first.

    Every remaining display keeps one reserved character, because Discord
    rejects an empty text display and dropping it would renumber the tree.
    """

    texts = [node for node in nodes if int(node.get("type") or 0) == TYPE_TEXT]
    left = max(0, int(budget))
    for index, node in enumerate(texts):
        allowance = max(0, left - (len(texts) - index - 1))
        content = str(node.get("content") or "")
        if len(content) <= allowance:
            left -= len(content)
            continue
        if allowance <= len(TRIM_MARKER):
            node["content"] = "."
            left -= 1
            continue
        node["content"] = content[: allowance - len(TRIM_MARKER)] + TRIM_MARKER
        left -= allowance


def fit_components_v2(
    components: Optional[Iterable[Any]],
    *,
    max_components: int = COMPONENTS_V2_MAX_COMPONENTS,
    max_text_chars: int = COMPONENTS_V2_MAX_TEXT_CHARS,
) -> list[dict[str, Any]]:
    """Trim a Components V2 tree to Discord's ceilings, keeping the controls.

    Overflow rows go first, then long text displays are truncated. Action rows,
    buttons, and selects are never dropped: a card that stops updating is worse
    than a card that lost its tail, and the job controls have to stay live.
    """

    out = _deep_copy(list(components or ()))
    while count_components(out) > max_components:
        if not _drop_last_droppable(out):
            break
    if total_text_chars(out) > max_text_chars:
        _trim_text_in_place(_nodes(out), max_text_chars)
    return out


def _deep_copy(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _deep_copy(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_deep_copy(item) for item in value]
    return value


def iter_component_text(components: Optional[Iterable[Any]]) -> list[str]:
    found: list[str] = []
    for item in components or ():
        if not isinstance(item, dict):
            continue
        if item.get("type") == TYPE_TEXT:
            text = str(item.get("content") or "")
            if text:
                found.append(text)
        nested = item.get("components")
        if isinstance(nested, list):
            found.extend(iter_component_text(nested))
    return found
