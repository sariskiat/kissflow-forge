"""Walk a real item through the item data plane, for `ForgeSimulateCase`.

Ported from `app.infrastructure.kissflow.dataplane` (pre-refactor), onto the
async `ItemService` port. THE TRAP this module exists to defend against: an
HTTP 200 is not verification. Kissflow's admin PUT accepts a Select value
that isn't a real option, returns 200, and silently never stores it --
`fill_and_verify` exists for exactly this reason.

THE OTHER TRAP: a "my items"-style listing's activity-instance id is the
initiator's already-CONSUMED instance. Submitting or rejecting against it
fails ("...anymore"). `live_aiid` is the lookup that refuses that decoy.

THE TWO-PHASE aiid RULE (proven live 2026-08-07, walking a real item Start ->
... -> Completed): `detail._current_context[0]._context_activity_instance_id`
is the correct source ONLY from the SECOND submit onward. A Draft item still
sitting at Start, never yet submitted, has no such context at all -- the
only usable aiid for that FIRST submit is the one `create_item`'s own
response returns. `usable_aiid` is `live_aiid` plus that one documented
first-hop fallback; `walk` threads the create response's aiid through as
that fallback for the first step only, never a later one.

`walk` itself never raises: every failure -- a port call, the aiid trap, an
unresolvable field name, an exhausted poll -- lands in its returned
`WalkReport`'s own `failed`/`error` fields, exactly as the pre-refactor
version returned an `Err` in place of a report. The use case
(`forge_simulate_case.ForgeSimulateCase`) is what turns `not report.ok()`
into a raised `ApplicationError` (rule 7, `brief_stage_d_common.md`) --
`walk` itself stays the output-invariant collector it always was.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from app.application.exceptions import ExternalServiceError
from app.application.interfaces.item import ItemService

Item = dict[str, Any]  # a /process create, detail, submit, or reject response body

_TERMINAL_STATUSES = frozenset({"Completed", "Rejected"})


def _root_model_ids(draft: dict[str, Any]) -> set[str]:
    """Model node ids that are the form's own root model, not a child table.

    Args:
        draft: The flow's wire-format draft.

    Returns:
        Every root-model node id.
    """
    return {
        k
        for k, v in draft.items()
        if isinstance(v, dict) and v.get("Kind") == "Model" and not v.get("Column")
    }


def field_name_index(draft: dict[str, Any]) -> dict[str, str]:
    """name -> field id, for every root-model Field in a flow's draft graph.

    Scoped to root-model fields on purpose (documented limit): a child-table
    field can share a display name with a root field, and a top-level
    `/process` admin fill only ever addresses root-model fields.

    Args:
        draft: The flow's wire-format draft.

    Returns:
        Every root-model field's `Name` mapped to its id.
    """
    roots = _root_model_ids(draft)
    out: dict[str, str] = {}
    for key, node in draft.items():
        if not isinstance(node, dict) or node.get("Kind") != "Field":
            continue
        if node.get("Model") not in roots:
            continue
        name = node.get("Name")
        if isinstance(name, str) and name:
            fid = node.get("Id")
            out[name] = fid if isinstance(fid, str) and fid else key
    return out


def resolve_value_keys(
    values: dict[str, object],
    field_index: dict[str, str],
    passthrough: frozenset[str] = frozenset(),
) -> dict[str, object]:
    """Translate a fill dict's KEYS (field name or field id) to field ids,
    leaving every VALUE untouched.

    Args:
        values: The fill dict as the caller supplied it.
        field_index: `name -> id`, from `field_name_index`.
        passthrough: Extra keys allowed through verbatim without being
            treated as field names.

    Returns:
        `values` with every key resolved to a field id.

    Raises:
        ValueError: A key matches no field -- names the unresolved key and
            lists every available field name.
    """
    known_ids = set(field_index.values())
    resolved: dict[str, object] = {}
    for key, val in values.items():
        if key in passthrough or key.startswith("Field_") or key in known_ids:
            resolved[key] = val
        elif key in field_index:
            resolved[field_index[key]] = val
        else:
            available = ", ".join(sorted(field_index)) or "(none)"
            raise ValueError(
                f"fill key {key!r} matches no field on this flow — not a "
                f"field id, and no field is named {key!r}. Available field "
                f"names: {available}"
            )
    return resolved


def live_aiid(detail: Item) -> str:
    """THE aiid trap, isolated as a pure function. "My items"'
    `_activity_instance_id` is the initiator's CONSUMED instance --
    submitting or rejecting against it fails with an "...anymore" style
    error. The only source THIS function will ever read is
    `detail._current_context[0]._context_activity_instance_id`.

    Hop 1 (a Draft item still sitting at Start, never yet submitted)
    genuinely has no `_current_context` at all -- that is not this function
    malfunctioning, it is the documented two-phase aiid rule (module
    docstring): the first hop's aiid comes from `create_item`'s own response
    instead. A caller that needs to submit the very first hop wants
    `usable_aiid`, not this function directly.

    Args:
        detail: An item's admin detail, as `ItemService.get_detail` returns.

    Returns:
        The live activity-instance id.

    Raises:
        ValueError: `detail` has no (or an empty) `_current_context`, or its
            first entry carries no activity-instance id.
    """
    ctx = detail.get("_current_context")
    if not ctx or not isinstance(ctx, list):
        raise ValueError(
            "detail has no _current_context — this is either the myitems "
            "consumed-instance trap (CLAUDE.md > Item data plane), or a "
            "hop-1 Draft item that hasn't been submitted yet (see "
            "usable_aiid for that case): fetch ADMIN detail and read "
            "_current_context[0]._context_activity_instance_id, never a "
            "myitems-style aiid"
        )
    first = ctx[0]
    if (
        not isinstance(first, dict)
        or not isinstance(first.get("_context_activity_instance_id"), str)
        or not first["_context_activity_instance_id"]
    ):
        raise ValueError(
            "detail._current_context[0] has no _context_activity_instance_id "
            "— cannot submit or reject without the live aiid"
        )
    return first["_context_activity_instance_id"]


def usable_aiid(detail: Item, create_aiid: str | None = None) -> str:
    """`live_aiid` plus the documented two-phase first-hop fallback (module
    docstring). Tries the live context first, exactly like `live_aiid` --
    always preferred when present, on ANY hop. Falls back to `create_aiid`
    ONLY when the context is genuinely absent AND a caller supplied one;
    with `create_aiid=None` (the default) this is byte-for-byte `live_aiid`.

    Args:
        detail: An item's admin detail.
        create_aiid: `create_item`'s own response aiid, offered as the
            first-hop fallback. `None` on every hop after the first.

    Returns:
        The usable activity-instance id.

    Raises:
        ValueError: `live_aiid(detail)` raised, and `create_aiid` is `None`.
    """
    try:
        return live_aiid(detail)
    except ValueError:
        if create_aiid is not None:
            return create_aiid
        raise


@dataclass(frozen=True)
class FillReport:
    """Every key of a fill request lands in exactly one bucket after a
    read-back. This exists because a 200 from `put_fields` proves nothing
    (CLAUDE.md > Item data plane): a Select value that isn't a real option
    PUTs 200 and is silently never stored.
    """

    landed: tuple[str, ...]
    discarded: tuple[str, ...]
    mismatched: tuple[str, ...]

    def ok(self) -> bool:
        """Whether every key landed with the value it was sent."""
        return not self.discarded and not self.mismatched


async def fill_and_verify(
    item: ItemService,
    *,
    flow_id: str,
    iid: str,
    values: dict[str, object],
) -> FillReport:
    """PUT `values`, then GET admin detail and compare EVERY key against
    what was sent. Never trusts the PUT response alone -- see `FillReport`.

    Args:
        item: The item-family port.
        flow_id: The process flow's id.
        iid: The item's id.
        values: The field values to write, already keyed by field id.

    Returns:
        The per-key landed/discarded/mismatched partition.

    Raises:
        ExternalServiceError: The PUT or the read-back GET failed.
    """
    await item.put_fields(flow_id, iid, values)
    detail = await item.get_detail(flow_id, iid)

    landed: list[str] = []
    discarded: list[str] = []
    mismatched: list[str] = []
    for key, sent in values.items():
        got = detail.get(key)
        if got is None and sent is not None:
            discarded.append(key)
        elif got == sent:
            landed.append(key)
        else:
            mismatched.append(key)
    return FillReport(
        landed=tuple(landed), discarded=tuple(discarded), mismatched=tuple(mismatched)
    )


@dataclass(frozen=True)
class StepResult:
    """What one successful `advance` did: the step the item left (from
    detail, read just before submitting), the LIVE aiid it moved with, and
    the raw submit response.
    """

    step: str
    aiid: str
    response: Item


async def _detail_and_live_aiid(
    item: ItemService,
    *,
    flow_id: str,
    iid: str,
    create_aiid: str | None = None,
) -> tuple[Item, str]:
    """detail -> usable_aiid, bundled: `advance` and a reject both need this
    exact pair, fetched fresh every time.

    Args:
        item: The item-family port.
        flow_id: The process flow's id.
        iid: The item's id.
        create_aiid: The two-phase rule's optional first-hop fallback.

    Returns:
        The item's detail and the usable activity-instance id.

    Raises:
        ExternalServiceError: The detail read failed.
        ValueError: No usable aiid, from `usable_aiid`.
    """
    detail = await item.get_detail(flow_id, iid)
    aiid = usable_aiid(detail, create_aiid)
    return detail, aiid


async def advance(
    item: ItemService,
    *,
    flow_id: str,
    iid: str,
    create_aiid: str | None = None,
) -> StepResult:
    """Fetch detail -> derive the USABLE aiid -> submit.

    Args:
        item: The item-family port.
        flow_id: The process flow's id.
        iid: The item's id.
        create_aiid: The two-phase rule's optional first-hop fallback.

    Returns:
        The step just left, the aiid used, and the raw submit response.

    Raises:
        ExternalServiceError: The detail read or the submit failed.
        ValueError: No usable aiid.
    """
    detail, aiid = await _detail_and_live_aiid(
        item, flow_id=flow_id, iid=iid, create_aiid=create_aiid
    )
    resp = await item.submit(flow_id, iid, aiid)
    step = detail.get("_current_step")
    return StepResult(
        step=step if isinstance(step, str) else "?", aiid=aiid, response=resp
    )


async def wait_new_aiid(
    item: ItemService,
    *,
    flow_id: str,
    iid: str,
    prev_aiid: str,
    tries: int = 8,
    delay: float = 0.9,
    sleep_fn: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> str:
    """Bounded poll for the step transition after a submit/reject: keep
    re-deriving the LIVE aiid until it differs from `prev_aiid`, or the item
    reaches a TERMINAL status, or give up.

    Args:
        item: The item-family port.
        flow_id: The process flow's id.
        iid: The item's id.
        prev_aiid: The aiid the item was on before this transition.
        tries: The hard cap on read attempts.
        delay: Seconds to wait between attempts.
        sleep_fn: The async sleep to call between attempts (injectable for
            tests).

    Returns:
        The new activity-instance id, or the terminal `_status` string when
        the item finished with nothing left to transition into.

    Raises:
        ValueError: `tries` attempts never saw a new aiid or a terminal
            status.
    """
    last_message = f"wait_new_aiid: tries={tries} must be >= 1"
    for attempt in range(tries):
        if attempt > 0:
            await sleep_fn(delay)
        try:
            detail = await item.get_detail(flow_id, iid)
        except ExternalServiceError as exc:
            last_message = str(exc)
            continue
        status = detail.get("_status")
        if status in _TERMINAL_STATUSES:
            return status
        try:
            aiid = live_aiid(detail)
        except ValueError as exc:
            last_message = str(exc)
            continue
        if aiid != prev_aiid:
            return aiid
        last_message = (
            f"wait_new_aiid: aiid still {aiid!r} after {attempt + 1}/{tries} "
            f"tries ({(attempt + 1) * delay:.1f}s) — step transition did "
            "not happen in time"
        )
    raise ValueError(last_message)


@dataclass(frozen=True)
class StepPlan:
    """One hop of a walk: fields to set (fill_and_verify'd before anything
    else), then either advance (submit) or, when `reject` is set, reject
    with `comment`.
    """

    name: str
    values: dict[str, object] = field(default_factory=dict)
    reject: bool = False
    comment: str = ""


@dataclass(frozen=True)
class WalkReport:
    """Output-invariant audit of one walk: every step in the plan lands in
    exactly one bucket -- `advanced`, `rejected`, or (the one it stopped at)
    `failed`.
    """

    flow_id: str
    iid: str | None
    created: bool
    planned: tuple[str, ...]
    filled: tuple[str, ...]
    advanced: tuple[str, ...]
    rejected: tuple[str, ...]
    failed: tuple[str, ...]
    error: str | None

    def ok(self) -> bool:
        """Whether the walk created its item and never failed a step."""
        return self.created and not self.failed


def _failed_report(
    *,
    flow_id: str,
    iid: str | None,
    created: bool,
    planned: tuple[str, ...],
    filled: tuple[str, ...],
    advanced: tuple[str, ...],
    rejected: tuple[str, ...],
    step_name: str,
    error: str,
) -> WalkReport:
    return WalkReport(
        flow_id=flow_id,
        iid=iid,
        created=created,
        planned=planned,
        filled=filled,
        advanced=advanced,
        rejected=rejected,
        failed=(step_name,),
        error=error,
    )


async def walk(
    item: ItemService,
    *,
    flow_id: str,
    steps: list[StepPlan],
    field_index: dict[str, str] | None = None,
    poll_after_transition: bool = False,
    poll_tries: int = 8,
    poll_delay: float = 0.9,
    poll_sleep_fn: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> WalkReport:
    """create, then per step: fill_and_verify -> advance (or reject when the
    plan says so). Stops at the FIRST failure -- including a fill that PUT
    200 but didn't verify.

    Args:
        item: The item-family port.
        flow_id: The process flow's id.
        steps: The plan, in order.
        field_index: `name -> id`, from `field_name_index` on the flow's
            draft. When given, each step's `values` KEYS are resolved from
            field NAMES to field ids before the fill PUT. Omitted (`None`,
            the default) skips resolution entirely.
        poll_after_transition: When `True`, waits for the step transition to
            actually show up (`wait_new_aiid`) after each advance/reject,
            before moving to the next step.
        poll_tries: `wait_new_aiid`'s own `tries`.
        poll_delay: `wait_new_aiid`'s own `delay`.
        poll_sleep_fn: `wait_new_aiid`'s own `sleep_fn`.

    Returns:
        The output-invariant audit. Never raises -- every failure lands in
        `failed`/`error` instead.
    """
    planned = tuple(p.name for p in steps)
    try:
        created = await item.create_item(flow_id)
    except ExternalServiceError as exc:
        return WalkReport(
            flow_id=flow_id,
            iid=None,
            created=False,
            planned=planned,
            filled=(),
            advanced=(),
            rejected=(),
            failed=(),
            error=f"create: {exc.message}",
        )
    iid = created.get("_id")
    if not isinstance(iid, str):
        return WalkReport(
            flow_id=flow_id,
            iid=None,
            created=False,
            planned=planned,
            filled=(),
            advanced=(),
            rejected=(),
            failed=(),
            error=f"create: no _id in response {created!r}",
        )
    create_aiid = created.get("_activity_instance_id")
    if not isinstance(create_aiid, str) or not create_aiid:
        create_aiid = None

    filled: tuple[str, ...] = ()
    advanced: tuple[str, ...] = ()
    rejected: tuple[str, ...] = ()

    for i, plan in enumerate(steps):
        hop_create_aiid = create_aiid if i == 0 else None
        values = plan.values
        if field_index is not None:
            try:
                values = resolve_value_keys(plan.values, field_index)
            except ValueError as exc:
                return _failed_report(
                    flow_id=flow_id,
                    iid=iid,
                    created=True,
                    planned=planned,
                    filled=filled,
                    advanced=advanced,
                    rejected=rejected,
                    step_name=plan.name,
                    error=f"{plan.name}: {exc}",
                )

        try:
            fill_report = await fill_and_verify(
                item, flow_id=flow_id, iid=iid, values=values
            )
        except ExternalServiceError as exc:
            return _failed_report(
                flow_id=flow_id,
                iid=iid,
                created=True,
                planned=planned,
                filled=filled,
                advanced=advanced,
                rejected=rejected,
                step_name=plan.name,
                error=f"{plan.name}: fill failed: {exc.message}",
            )
        if not fill_report.ok():
            return _failed_report(
                flow_id=flow_id,
                iid=iid,
                created=True,
                planned=planned,
                filled=filled,
                advanced=advanced,
                rejected=rejected,
                step_name=plan.name,
                error=(
                    f"{plan.name}: fill not verified — "
                    f"discarded={fill_report.discarded} "
                    f"mismatched={fill_report.mismatched}"
                ),
            )
        filled += (plan.name,)

        if plan.reject:
            try:
                _detail, aiid = await _detail_and_live_aiid(
                    item, flow_id=flow_id, iid=iid, create_aiid=hop_create_aiid
                )
            except (ExternalServiceError, ValueError) as exc:
                return _failed_report(
                    flow_id=flow_id,
                    iid=iid,
                    created=True,
                    planned=planned,
                    filled=filled,
                    advanced=advanced,
                    rejected=rejected,
                    step_name=plan.name,
                    error=f"{plan.name}: {exc}",
                )
            try:
                await item.reject(flow_id, iid, aiid, plan.comment)
            except ExternalServiceError as exc:
                return _failed_report(
                    flow_id=flow_id,
                    iid=iid,
                    created=True,
                    planned=planned,
                    filled=filled,
                    advanced=advanced,
                    rejected=rejected,
                    step_name=plan.name,
                    error=f"{plan.name}: reject failed: {exc.message}",
                )
            rejected += (plan.name,)
            if poll_after_transition:
                try:
                    await wait_new_aiid(
                        item,
                        flow_id=flow_id,
                        iid=iid,
                        prev_aiid=aiid,
                        tries=poll_tries,
                        delay=poll_delay,
                        sleep_fn=poll_sleep_fn,
                    )
                except ValueError as exc:
                    return _failed_report(
                        flow_id=flow_id,
                        iid=iid,
                        created=True,
                        planned=planned,
                        filled=filled,
                        advanced=advanced,
                        rejected=rejected,
                        step_name=plan.name,
                        error=(
                            f"{plan.name}: post-reject transition poll failed: {exc}"
                        ),
                    )
            continue

        try:
            result = await advance(
                item, flow_id=flow_id, iid=iid, create_aiid=hop_create_aiid
            )
        except (ExternalServiceError, ValueError) as exc:
            return _failed_report(
                flow_id=flow_id,
                iid=iid,
                created=True,
                planned=planned,
                filled=filled,
                advanced=advanced,
                rejected=rejected,
                step_name=plan.name,
                error=f"{plan.name}: advance failed: {exc}",
            )
        advanced += (plan.name,)
        if poll_after_transition:
            try:
                await wait_new_aiid(
                    item,
                    flow_id=flow_id,
                    iid=iid,
                    prev_aiid=result.aiid,
                    tries=poll_tries,
                    delay=poll_delay,
                    sleep_fn=poll_sleep_fn,
                )
            except ValueError as exc:
                return _failed_report(
                    flow_id=flow_id,
                    iid=iid,
                    created=True,
                    planned=planned,
                    filled=filled,
                    advanced=advanced,
                    rejected=rejected,
                    step_name=plan.name,
                    error=(f"{plan.name}: post-advance transition poll failed: {exc}"),
                )

    return WalkReport(
        flow_id=flow_id,
        iid=iid,
        created=True,
        planned=planned,
        filled=filled,
        advanced=advanced,
        rejected=rejected,
        failed=(),
        error=None,
    )
