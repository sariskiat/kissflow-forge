"""Private helper for `forge_doctor` -- fetch the live draft, harvest every Select
field's real list options, and run `FlowDraft.problems()` for real.

Ported from the former `app.infrastructure.kissflow.client.run_doctor`, never
imported from there (Stage D rule). Membership is the one check that cannot
live in the pure domain health check at all -- it is not in the draft --
so it is folded in here, exactly as the old orchestration did.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.application.exceptions import ApplicationError, RepositoryError
from app.application.interfaces.flow import FlowRepository
from app.domain.value_objects.kinds import FlowKind


@dataclass(frozen=True)
class DoctorResult:
    """The read-only health-check audit: every check lands in exactly one bucket."""

    flow_id: str
    ok: bool
    problems: tuple[str, ...]
    checked: dict[str, int]
    unvalidated: tuple[str, ...]
    unvalidatable_scripts: int
    list_ids_checked: tuple[str, ...]
    list_fetch_errors: dict[str, str]
    members_found: int | None
    member_fetch_error: str | None


async def run_doctor(
    flow_repo: FlowRepository,
    *,
    app_id: str,
    flow_id: str,
    kind: FlowKind,
    visibility_role_claims: list[str] | None,
) -> DoctorResult:
    """Fetch the LIVE draft, harvest every Select field's real list options, and run
    `FlowDraft.problems()` for real -- the read-only diagnostic behind `forge_doctor`.

    A list whose items fetch fails is recorded in `list_fetch_errors` (never
    silently dropped) and simply excluded from `list_options`, so any branch
    literal that depended on it reports as `unvalidated` rather than falsely
    `ok`. A flow with AppRole assignees and an EMPTY live roster fails the
    audit (CLAUDE.md > Members first); a roster this call could not read
    lands in `member_fetch_error` and in `unvalidated`, never counted as
    populated.

    Args:
        flow_repo: The flow port.
        app_id: The application the flow belongs to.
        flow_id: The flow's id.
        kind: The flow kind.
        visibility_role_claims: The spec's role-scoped visibility claims,
            one sentence each -- always a problem (role-scoped visibility is
            API-impossible).

    Returns:
        The full doctor audit.

    Raises:
        ApplicationError: The draft has no valid `Root` key
            (`code="VERIFY_FAILED"`).
    """
    draft = await flow_repo.get_draft(app_id, kind, flow_id)
    wire = draft.to_wire()

    list_ids = sorted(
        {
            v.get("ReferredList")
            for v in wire.values()
            if isinstance(v, dict)
            and v.get("Kind") == "Field"
            and v.get("Type") == "Select"
            and v.get("ReferredList")
        }
    )
    list_options: dict[str, list[str]] = {}
    list_errors: dict[str, str] = {}
    for list_id in list_ids:
        try:
            items = await flow_repo.get_list_items(app_id, list_id)
        except RepositoryError as exc:
            list_errors[list_id] = exc.message
            continue
        list_options[list_id] = list(items) if isinstance(items, list) else []

    try:
        report = draft.problems(
            list_options=list_options,
            visibility_role_claims=visibility_role_claims or (),
        )
    except ValueError as exc:
        raise ApplicationError(
            f"doctor could not run: {exc}", code="VERIFY_FAILED"
        ) from exc

    problems = list(report.problems)
    checked = dict(report.checked)
    unvalidated = list(report.unvalidated)

    # The blind spot the graph cannot close: an AppRole assignee with nobody in the
    # role.
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
            roster = await flow_repo.get_members(app_id, kind, flow_id)
        except RepositoryError as exc:
            member_error = exc.message
            unvalidated.append(
                f"membership of {len(assignees)} AppRole assignee(s) NOT validated — "
                f"the live member roster could not be read ({member_error}); a flow "
                f"with assignees and an EMPTY roster fails publish with a bare "
                f"metadata error (CLAUDE.md > Members first), and this run cannot "
                f"tell you which case this is — re-run forge_doctor, or read the "
                f"roster with forge_member_batch's own report"
            )
        else:
            members_found = len(roster)
            if not roster:
                problems.append(
                    f"flow has {len(assignees)} AppRole assignee(s) but ZERO members — "
                    f"publish fails with a bare metadata error (CLAUDE.md > Members "
                    f"first: members before assignees, every time; grant them with "
                    f"forge_member_batch)"
                )

    return DoctorResult(
        flow_id=flow_id,
        ok=not problems,
        problems=tuple(problems),
        checked=checked,
        unvalidated=tuple(unvalidated),
        unvalidatable_scripts=report.unvalidatable_scripts,
        # only the lists whose options were actually fetched -- a list whose fetch
        # failed sits in `list_fetch_errors` instead, never here (former
        # `client.run_doctor`: `sorted(list_options)`).
        list_ids_checked=tuple(sorted(list_options)),
        list_fetch_errors=list_errors,
        members_found=members_found,
        member_fetch_error=member_error,
    )
