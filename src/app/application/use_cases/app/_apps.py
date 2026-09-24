"""app.application.use_cases.app._apps — pure/shared helpers for the app-family
"apps" tools: `forge_create_app`, `forge_publish_app`, and (imported)
`forge_create_template_app`, which reuses both verified-create and
verified-publish for its own account and application-level steps.

Ported from `app.infrastructure.kissflow.client.create_application_verified` /
`publish_application_verified` (Stage D group 6, app family).
"""

from __future__ import annotations

from typing import Any

from app.application.exceptions import VERIFY_FAILED, ApplicationError
from app.application.interfaces.app import AppRepository


async def create_application_verified(app: AppRepository, name: str) -> str:
    """Create a NEW application and verify it via `list_applications` (never the
    create response alone -- THE RULE).

    A `list_applications` read runs FIRST, ahead of the create itself: this
    account-level create has no application yet to read, so that leading call
    exists only to satisfy the write-order invariant every write use case
    follows (`app.application.use_cases.flow._write_order`'s own module
    docstring) -- its own result is unused.

    Args:
        app: The application/app-role port.
        name: The new application's display name.

    Returns:
        The new application's id, once it has verified on the list read-back.

    Raises:
        ApplicationError: The created id did not verify on the read-back
            (`code=VERIFY_FAILED`). A `RepositoryError` from either port call
            (for example the platform's own `FlowNameAlreadyExists`)
            propagates unchanged.
    """
    await app.list_applications()
    new_id = await app.create_application(name)
    listed = await app.list_applications()
    verified = any(isinstance(a, dict) and a.get("_id") == new_id for a in listed)
    if not verified:
        raise ApplicationError(
            f"created application {new_id!r} did not verify on the application "
            "list read-back",
            code=VERIFY_FAILED,
        )
    return new_id


async def publish_application_verified(
    app: AppRepository, app_id: str
) -> tuple[str | None, str | None, str | None, str | None]:
    """Publish an application's draft to live, WITH a genuine post-publish
    read-back (THE RULE: a 200 from publish proves nothing by itself).

    A `get_app_draft` read runs FIRST, ahead of the publish itself, to
    satisfy the write-order invariant (publish carries no version-gated
    payload of its own) -- its `_meta_version` is this call's own
    `snapshot_version` (`forge_publish`'s `kind="application"` arm reads the
    same way, `use_cases/flow/forge_publish.py`); the SECOND read, after
    publish, is the real read-back this function otherwise reports.

    Args:
        app: The application/app-role port.
        app_id: The application's id.

    Returns:
        `(runtime_id, meta_version, note, snapshot_version)`: the fresh
        `_meta_version`, any `Runtime_`-prefixed node id found on the draft
        (⚠️ UNCAPTURED on this tenant -- `None` with `note` stating so when
        absent, never guessed), `note` itself (`None` when a `Runtime_` node
        was found), and the PRE-publish read's own `_meta_version`.

    Raises:
        ApplicationError: The publish itself succeeded but the read-back
            failed (`code=VERIFY_FAILED`, naming the read failure). A
            `RepositoryError` from the publish call itself propagates
            unchanged.
    """
    pre_draft = await app.get_app_draft(app_id)
    snapshot_version = pre_draft.version
    await app.publish_app(app_id)
    try:
        draft = await app.get_app_draft(app_id)
    except ApplicationError as exc:
        raise ApplicationError(
            f"publish succeeded but read-back failed: {exc.message}",
            code=VERIFY_FAILED,
        ) from exc
    wire: dict[str, Any] = draft.to_wire()
    runtime_id = next(
        (k for k in wire if isinstance(k, str) and k.startswith("Runtime_")), None
    )
    note = (
        None
        if runtime_id
        else (
            "no Runtime_-prefixed node observed on the app draft read-back — that "
            "shape is unconfirmed on this tenant; ponytail: not verified live yet, "
            "do not treat absence as proof either way"
        )
    )
    return runtime_id, wire.get("_meta_version"), note, snapshot_version
