"""Private helper for `forge_delete_flow` -- archive+delete a flow, a page or an
application, verified via the appropriate LIST route, never the delete
response alone.

Ported from the former `app.infrastructure.kissflow.client.delete_anything`,
never imported from there (Stage D rule). Validation (an empty `app_id` for
`kind="page"`, or no app selected at all) lives in the use case's own
`execute()`, not here -- this module only dispatches by kind and reads the
list-route back.
"""

from __future__ import annotations

from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Any

from app.application.exceptions import RepositoryError
from app.application.interfaces.app import AppRepository
from app.application.interfaces.flow import FlowRepository
from app.application.interfaces.page import PageRepository
from app.application.use_cases.flow._fields import raise_if_write_failed
from app.domain.value_objects.kinds import AnyFlowKind, DeleteKind


@dataclass(frozen=True)
class DeleteResult:
    """Whether the target was deleted, and whether the read-back confirms it."""

    kind: str
    id: str
    deleted: bool
    verified: bool


async def delete_anything(
    flow_repo: FlowRepository,
    app_repo: AppRepository,
    page_repo: PageRepository,
    *,
    kind: DeleteKind,
    flow_id: str,
    app_id: str,
) -> DeleteResult:
    """Archive+delete a flow (process/form/case/list/dataset), a page, or an
    application, verifying deletion via the appropriate LIST route.

    Args:
        flow_repo: The flow port.
        app_repo: The app port.
        page_repo: The page port.
        kind: What to delete.
        flow_id: The target's id (for `kind="application"`, the app id
            itself).
        app_id: The application the target belongs to. Unused for
            `kind="application"`.

    Returns:
        Whether the delete landed, confirmed by a fresh list read.

    Raises:
        ApplicationError: The pre-delete list read or the delete call
            failed (raised by the port as `RepositoryError`, nothing landed),
            or the delete landed but the verifying list read failed or still
            lists the target (`code="VERIFY_FAILED"`).
    """
    if kind == "page":
        await page_repo.list_pages(app_id)  # write-order invariant: a read first
        await page_repo.delete_page(app_id, flow_id)
        listed = await _read_back(page_repo.list_pages(app_id), kind, flow_id)
        verified = not any(
            isinstance(p, dict) and p.get("_id") == flow_id for p in listed
        )
        _require_verified(kind, flow_id, verified)
        return DeleteResult(kind=kind, id=flow_id, deleted=True, verified=verified)

    if kind == "application":
        await app_repo.list_applications()  # write-order invariant: a read first
        await app_repo.delete_application(flow_id, archive_first=True)
        listed = await _read_back(app_repo.list_applications(), kind, flow_id)
        verified = not any(
            isinstance(a, dict) and a.get("_id") == flow_id for a in listed
        )
        _require_verified(kind, flow_id, verified)
        return DeleteResult(kind=kind, id=flow_id, deleted=True, verified=verified)

    any_kind: AnyFlowKind = kind  # "form" | "process" | "case" | "list" | "dataset"
    listed = await flow_repo.list_flows(
        app_id, any_kind
    )  # write-order invariant: a read first
    archive_first = True
    if kind == "process":
        archive_first = _process_needs_archive(listed, flow_id)
    await flow_repo.delete_flow(app_id, any_kind, flow_id, archive_first=archive_first)
    still = await _read_back(flow_repo.list_flows(app_id, any_kind), kind, flow_id)
    verified = not any(isinstance(f, dict) and f.get("_id") == flow_id for f in still)
    _require_verified(kind, flow_id, verified)
    return DeleteResult(kind=kind, id=flow_id, deleted=True, verified=verified)


def _process_needs_archive(listed: list[dict[str, Any]], flow_id: str) -> bool:
    """Return whether a process delete must issue the archive request first.

    A retry can reach this point after the archive request succeeded but the
    delete request timed out. Kissflow rejects a second archive request for
    that already archived process, so only the exact ``Archived`` status skips
    it. Every other status, including a missing or unexpected status, keeps the
    archive request enabled and lets Kissflow decide whether the delete is
    valid.

    Args:
        listed: The process records returned by the pre-delete list read.
        flow_id: The process id being deleted.

    Returns:
        ``False`` only when the matching record is exactly ``Archived``.
    """
    matching = next(
        (
            flow
            for flow in listed
            if isinstance(flow, dict) and flow.get("_id") == flow_id
        ),
        None,
    )
    return not (matching is not None and matching.get("Status") == "Archived")


async def _read_back(
    listing: Awaitable[list[dict[str, Any]]], kind: str, flow_id: str
) -> list[dict[str, Any]]:
    """Run the verifying list read that follows a delete call that succeeded.

    A failure here is not "nothing landed": the delete call already
    succeeded. The message says so, so a caller does not delete again blind.
    The former client returned `deleted: True, verified: False` for a page or
    an application here, and left `verified` True for a flow; a verify that
    never ran is never reported as verified.

    Args:
        listing: The pending list read.
        kind: What was deleted (named in the message).
        flow_id: The target's id (named in the message).

    Returns:
        The listed records.

    Raises:
        ApplicationError: The list read failed (`code="VERIFY_FAILED"`).
    """
    try:
        return await listing
    except RepositoryError as exc:
        raise_if_write_failed(
            published=False,
            list_read_failed=(
                f"delete {kind} {flow_id!r}: the delete call succeeded but the "
                f"verifying list read failed: {exc.message}",
            ),
        )
        raise AssertionError("unreachable") from exc  # pragma: no cover


def _require_verified(kind: str, flow_id: str, verified: bool) -> None:
    """Refuse a delete whose read-back could not confirm removal -- lesson 7: a
    deleted-but-unverified target is a failed write, never a success with
    `verified: False` (matching the former dict shape's own `"isError": not
    verified`).

    Args:
        kind: What was deleted (named in the message).
        flow_id: The target's id (named in the message).
        verified: Whether the read-back confirmed removal.

    Raises:
        ApplicationError: `verified` is `False` (`code="VERIFY_FAILED"`).
    """
    if not verified:
        raise_if_write_failed(
            published=False,
            surviving=(
                f"delete {kind} {flow_id!r}: the delete call succeeded but the "
                f"read-back list still shows it",
            ),
        )
