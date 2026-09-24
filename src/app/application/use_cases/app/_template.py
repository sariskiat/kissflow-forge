"""app.application.use_cases.app._template — private helpers for
`forge_create_template_app`: the doctor read-back and the abandon-on-failure
cleanup.

Ported from `app.infrastructure.kissflow.client.run_doctor` /
`create_template_app`'s own `_abandon` closure (Stage D group 6, app family).

The "members FIRST" grant itself is `app.application.use_cases.app._members.
apply_own_app_roles` -- `forge_create_template_app` shares it with
`forge_member_batch` rather than keeping its own scoped copy (review fix 8):
`apply_own_app_roles` is exactly the one path old `apply_member_batch` could
ever take from this call site anyway, since the application
`forge_create_template_app` grants members on is one it just created, seconds
earlier, in the very same call, so it can never have a sibling flow with
members to harvest from yet.
"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Any

from app.application.exceptions import VERIFY_FAILED, ApplicationError
from app.application.interfaces.app import AppRepository
from app.application.interfaces.flow import FlowRepository
from app.domain.value_objects.kinds import FlowKind

_TEMPLATE_KIND: FlowKind = "process"


async def doctor_report(
    flow: FlowRepository, app_id: str, flow_id: str
) -> dict[str, Any]:
    """Fetch the LIVE draft, harvest every Select field's REAL list options, and
    run the offline `FlowDraft.problems()` audit for real.

    Ported from `client.run_doctor`, scoped to what `forge_create_template_app`
    needs: a fresh process, no role-scoped visibility claims to check.

    Args:
        flow: The flow/process/form/case/list port.
        app_id: The application's id.
        flow_id: The process flow's id.

    Returns:
        The same shaped dict `client.run_doctor` returned, minus `isError`
        (rule 2, `brief_stage_d_common.md`): `problems`, `checked`,
        `unvalidated`, `unvalidatable_scripts`, `list_ids_checked`,
        `list_fetch_errors`, `members_found`, `member_fetch_error`, `ok` --
        an embedded free-form audit blob, not itself reshaped into a typed
        DTO.

    Raises:
        ApplicationError: The draft read failed, propagated unchanged, or the
            draft has no valid `Root` key (`code=VERIFY_FAILED`).
    """
    draft = await flow.get_draft(app_id, _TEMPLATE_KIND, flow_id)
    wire = draft.to_wire()

    list_ids = {
        v.get("ReferredList")
        for v in wire.values()
        if isinstance(v, dict)
        and v.get("Kind") == "Field"
        and v.get("Type") == "Select"
        and v.get("ReferredList")
    }
    list_options: dict[str, list[str]] = {}
    list_errors: dict[str, str] = {}
    for list_id in sorted(list_ids):
        try:
            items = await flow.get_list_items(app_id, list_id)
        except ApplicationError as exc:
            list_errors[list_id] = exc.message
            continue
        list_options[list_id] = list(items) if isinstance(items, list) else []

    try:
        report = draft.problems(list_options=list_options, visibility_role_claims=())
    except ValueError as exc:
        raise ApplicationError(
            f"doctor could not run: {exc}", code=VERIFY_FAILED
        ) from exc
    problems = list(report.problems)
    checked = dict(report.checked)
    unvalidated = list(report.unvalidated)

    assignees = [
        v
        for v in wire.values()
        if isinstance(v, dict)
        and v.get("Kind") == "Resource"
        and v.get("ValueType") == "AppRole"
        and v.get("Value")
    ]
    checked["members"] = len(assignees)
    members_found: int | None = None
    member_error: str | None = None
    if assignees:
        try:
            roster = await flow.get_members(app_id, _TEMPLATE_KIND, flow_id)
        except ApplicationError as exc:
            member_error = exc.message
            unvalidated.append(
                f"membership of {len(assignees)} AppRole assignee(s) NOT "
                f"validated — the live member roster could not be read "
                f"({member_error}); a flow with assignees and an EMPTY roster "
                "fails publish with a bare metadata error (CLAUDE.md > Members "
                "first), and this run cannot tell you which case this is — "
                "re-run forge_doctor, or read the roster with "
                "forge_member_batch's own report"
            )
        else:
            members_found = len(roster)
            if not roster:
                problems.append(
                    f"flow has {len(assignees)} AppRole assignee(s) but ZERO "
                    "members — publish fails with a bare metadata error "
                    "(CLAUDE.md > Members first: members before assignees, "
                    "every time; grant them with forge_member_batch)"
                )

    return {
        "flow_id": flow_id,
        "ok": not problems,
        "problems": problems,
        "checked": checked,
        "unvalidated": unvalidated,
        "unvalidatable_scripts": report.unvalidatable_scripts,
        "list_ids_checked": sorted(list_options),
        "list_fetch_errors": list_errors,
        "members_found": members_found,
        "member_fetch_error": member_error,
    }


async def abandon(
    app: AppRepository,
    app_id: str,
    role_id: str | None,
    message: str,
    code: str,
) -> ApplicationError:
    """Best-effort archive+delete the half-built application (and its created
    AppRole), then build the exception the caller should raise.

    A failed `forge_create_template_app` run must never leave a half-built
    application in the tenant (CLAUDE.md > Build order). Never itself raises
    on a cleanup failure -- that would replace the ORIGINAL failure with a
    cleanup one; the cleanup's own outcome is folded into the returned
    exception's message instead, exactly as the old `_abandon` closure did.

    Args:
        app: The application/app-role port.
        app_id: The half-built application's id.
        role_id: The AppRole `create_app_role` minted, or `None` when the run
            failed before that step.
        message: The ORIGINAL failure's own message.
        code: The ORIGINAL failure's own `ApplicationError.code`.

    Returns:
        The `ApplicationError` the caller must `raise`, its message carrying
        both the original failure and the cleanup outcome.
    """
    deleted = True
    verified = False
    error_note: str | None = None
    try:
        await app.delete_application(app_id, archive_first=True)
    except ApplicationError as exc:
        deleted = False
        error_note = exc.message
    else:
        try:
            listed = await app.list_applications()
            verified = not any(
                isinstance(a, dict) and a.get("_id") == app_id for a in listed
            )
        except ApplicationError as exc:
            error_note = exc.message

    outcome = (
        "deleted+verified"
        if verified
        else "deleted, NOT verified"
        if deleted
        else "NOT deleted"
    )
    notes = [f"app {app_id} {outcome}"]
    if error_note:
        notes.append(error_note)
    if role_id is not None:
        try:
            await app.delete_app_role(role_id)
        except ApplicationError as exc:
            if not verified:
                notes.append(f"role {role_id} delete failed: {exc.message}")

    return ApplicationError(f"{message} [cleanup: {'; '.join(notes)}]", code=code)


async def run_step[T](
    app: AppRepository, app_id: str, role_id: str | None, coro: Awaitable[T]
) -> T:
    """Await one `forge_create_template_app` step; on any `ApplicationError`
    (a `RepositoryError` included -- it is one), abandon the half-built
    application and re-raise with the cleanup outcome folded in.

    Args:
        app: The application/app-role port (the one `abandon` cleans up on).
        app_id: The half-built application's id.
        role_id: The AppRole `create_app_role` minted, or `None` before that
            step has run.
        coro: The one step to await.

    Returns:
        Whatever `coro` returns.

    Raises:
        ApplicationError: `coro` raised one; the cleanup outcome is folded
            into its message (`abandon`'s own `code` is reused).
    """
    try:
        return await coro
    except ApplicationError as exc:
        raise await abandon(app, app_id, role_id, exc.message, exc.code) from exc


__all__ = [
    "abandon",
    "doctor_report",
    "run_step",
]
