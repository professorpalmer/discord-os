"""Replay labeled runs read-only and score the replay against the label.

The input is [recorded outcomes](../../../docs/jobs/outcomes.md): runs an
operator marked good, partial or bad. ``discord-os eval`` re-asks each one in
ANALYZE mode under the current pin (or a candidate pin from the same allowlist)
and reports win / loss / same.

The rubric is arithmetic, not a judge. A replay **passes** when it settles
completed, its summary is long enough to be an answer, and the summary carries
no failure marker. The label is the baseline: good is a pass, bad is a fail,
partial is neither.

| Baseline | Replay passes | Replay fails |
|---|---|---|
| good | same | loss |
| bad | win | same |
| partial | win | loss |

There is no LLM judge, because none is wired in this product and inventing one
would make the number unfalsifiable.

Eval spends OpenRouter money, so the command needs ``--limit`` and ``--yes``.
Replays carry ``eval=True`` metadata: the orchestrator forces ANALYZE on them,
and the command builds an orchestrator with no Discord facade at all, so an
eval never posts a card into a channel.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, Optional, Sequence

from agent_discord.contracts import RunReceipt, TaskIntake, TaskStatus
from agent_discord.orchestration.outcomes import LABEL_BAD, LABEL_GOOD, LABEL_PARTIAL
from agent_discord.puppetmaster.models import AGENTIC_MODEL_PIN

EVAL_META_KEY = "eval"
MIN_SUMMARY_CHARS = 40
FAILURE_MARKERS = ("need:", "could not", "cannot", "failed", "no answer")

VERDICT_WIN = "win"
VERDICT_LOSS = "loss"
VERDICT_SAME = "same"

RUBRIC = (
    "A replay passes when it settles completed, its summary is at least "
    f"{MIN_SUMMARY_CHARS} characters, and the summary carries no failure marker "
    f"({', '.join(FAILURE_MARKERS)}). Baseline good + pass = same, good + fail = "
    "loss, bad + pass = win, bad + fail = same, partial + pass = win, "
    "partial + fail = loss. No LLM judge."
)


def is_eval_metadata(meta: Optional[Mapping[str, Any]]) -> bool:
    return bool((meta or {}).get(EVAL_META_KEY))


def assert_pin_allowed(pin: str) -> str:
    """The candidate pin, or ModelNotAllowedError. Exact allowlist, no fallback."""

    candidate = (pin or "").strip() or AGENTIC_MODEL_PIN.canonical
    AGENTIC_MODEL_PIN.assert_allowed(candidate)
    return candidate


def plan_eval(store: Any, *, limit: int = 0) -> list[dict[str, Any]]:
    """Labeled runs an eval would replay, newest label first, one per run."""

    reader = getattr(store, "list_labeled_runs", None)
    if not callable(reader):
        return []
    try:
        rows = list(reader(limit=max(1, int(limit)) * 4 if limit else 200) or ())
    except Exception:
        return []
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        run_id = str(row.get("run_id") or "").strip()
        text = str(row.get("intake_text") or "").strip()
        label = str(row.get("label") or "").strip()
        if not run_id or not text or label not in {LABEL_GOOD, LABEL_PARTIAL, LABEL_BAD}:
            continue
        if run_id in seen:
            continue
        seen.add(run_id)
        out.append(
            {
                "run_id": run_id,
                "job_code": str(row.get("job_code") or ""),
                "label": label,
                "intake_text": text,
                "channel_id": str(row.get("channel_id") or ""),
                "workspace_id": str(row.get("workspace_id") or "default"),
                "baseline_status": str(row.get("run_status") or ""),
                "baseline_summary": str(row.get("summary") or ""),
            }
        )
        if limit and len(out) >= int(limit):
            break
    return out


def replay_passes(receipt: Optional[RunReceipt]) -> bool:
    if receipt is None or receipt.status != TaskStatus.COMPLETED:
        return False
    summary = (receipt.summary or "").strip()
    if len(summary) < MIN_SUMMARY_CHARS:
        return False
    low = summary.lower()
    return not any(marker in low for marker in FAILURE_MARKERS)


def verdict(label: str, *, passed: bool) -> str:
    if label == LABEL_GOOD:
        return VERDICT_SAME if passed else VERDICT_LOSS
    if label == LABEL_BAD:
        return VERDICT_WIN if passed else VERDICT_SAME
    return VERDICT_WIN if passed else VERDICT_LOSS


def eval_intake(candidate: Mapping[str, Any], *, pin: str) -> TaskIntake:
    """A read-only replay of one labeled ask. No thread, no message to react to."""

    return TaskIntake(
        text=str(candidate.get("intake_text") or ""),
        channel_id=str(candidate.get("channel_id") or ""),
        workspace_id=str(candidate.get("workspace_id") or "default"),
        metadata={
            EVAL_META_KEY: True,
            "eval_of": str(candidate.get("run_id") or ""),
            "eval_label": str(candidate.get("label") or ""),
            "eval_pin": pin,
            "workers": 0,
        },
    )


def run_eval(
    store: Any,
    *,
    dispatch: Callable[[TaskIntake], Optional[RunReceipt]],
    candidates: Sequence[Mapping[str, Any]] = (),
    limit: int = 0,
    pin: str = "",
) -> dict[str, Any]:
    """Replay each candidate and score it. Returns the JSON report body."""

    chosen = assert_pin_allowed(pin)
    rows = list(candidates) if candidates else plan_eval(store, limit=limit)
    results: list[dict[str, Any]] = []
    for candidate in rows:
        intake = eval_intake(candidate, pin=chosen)
        try:
            receipt = dispatch(intake)
        except Exception as exc:
            receipt = None
            error = f"{type(exc).__name__}: {exc}"[:200]
        else:
            error = receipt.error if receipt is not None else "no receipt"
        passed = replay_passes(receipt)
        results.append(
            {
                "run_id": str(candidate.get("run_id") or ""),
                "job_code": str(candidate.get("job_code") or ""),
                "label": str(candidate.get("label") or ""),
                "replay_run_id": "" if receipt is None else receipt.run_id,
                "replay_status": "" if receipt is None else receipt.status.value,
                "replay_summary_chars": 0
                if receipt is None
                else len((receipt.summary or "").strip()),
                "replay_passed": passed,
                "verdict": verdict(str(candidate.get("label") or ""), passed=passed),
                "error": error or None,
            }
        )
    totals = {VERDICT_WIN: 0, VERDICT_LOSS: 0, VERDICT_SAME: 0}
    for row in results:
        totals[row["verdict"]] = totals.get(row["verdict"], 0) + 1
    return {
        "pin": chosen,
        "rubric": RUBRIC,
        "replayed": len(results),
        "totals": totals,
        "results": results,
    }


def format_plan(candidates: Sequence[Mapping[str, Any]], *, pin: str) -> str:
    """Dry-run text: what eval would replay and how much it would cost in asks."""

    lines = [
        f"eval plan: {len(candidates)} labeled run(s) would replay in ANALYZE mode",
        f"pin: {pin}",
        "spend: one OpenRouter analyze ask per run (no implement, no writes)",
    ]
    for candidate in candidates:
        code = str(candidate.get("job_code") or "") or str(candidate.get("run_id") or "")[:12]
        label = str(candidate.get("label") or "")
        text = " ".join(str(candidate.get("intake_text") or "").split())[:60]
        lines.append(f"  {code}  {label:7}  {text}")
    lines.append("Add --limit N --yes to run it.")
    return "\n".join(lines)


def pin_refusal(pin: str) -> str:
    allowed = ", ".join(AGENTIC_MODEL_PIN.allowlist)
    return (
        f"eval: refused pin {pin!r} — not in the model allowlist ({allowed}). "
        "The pin is exact-match; there is no silent fallback."
    )


__all__ = [
    "EVAL_META_KEY",
    "FAILURE_MARKERS",
    "MIN_SUMMARY_CHARS",
    "RUBRIC",
    "VERDICT_LOSS",
    "VERDICT_SAME",
    "VERDICT_WIN",
    "assert_pin_allowed",
    "eval_intake",
    "format_plan",
    "is_eval_metadata",
    "pin_refusal",
    "plan_eval",
    "replay_passes",
    "run_eval",
    "verdict",
]
