"""Exercise every forge_*/kf_* tool on the deployed Kissflow Forge MCP server.

This is the delivery artifact that proves the deployed server can run every one of the
61 tools listed in Appendix A of `docs/specs/refactor-to-mcp-boilerplate.md` against a
real (or existing) app on the Kissflow dev tenant. It is a standalone client: it drives
the server the way any other MCP client would, over `fastmcp.Client`, and never imports
`app.*` — the server under test is a black box here.

Usage::

    uv run scripts/exercise_every_tool.py --url http://localhost:8080/mcp
    uv run scripts/exercise_every_tool.py --stdio-docker my-image:latest --env-file .env
    uv run scripts/exercise_every_tool.py --app-id <existing app id> --user-query "Jane"

See `docs/notes/exercise-every-tool.md` for the full walkthrough (building the image,
running the container, reading `exercise_log.json`).

Safety, as hard code paths rather than comments (CLAUDE.md's group-notification
warning):

- `forge_add_role_users` is never called with `groups`/`confirm_group_notification`
  — those two names do not appear anywhere in this file's argument construction. It
  is called with `user_query` when `--user-query` is given, and is otherwise
  recorded `skipped`: there is no route on this 61-tool surface that discovers an
  existing human member of a role without one (`forge_list_app_roles` never returns
  `Members`).
- `forge_delete_flow` / `forge_delete_app_role` / `forge_delete_fields` only ever
  target ids this same run created earlier (tracked on `Context`); nothing
  pre-existing is ever deleted.
- `forge_sweep` is read-only and may run at any scope.
- `forge_copilot_ask` sends exactly one harmless, static message about the app this
  run itself created.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from dotenv import dotenv_values
from fastmcp import Client
from fastmcp.client.transports import StdioTransport, StreamableHttpTransport

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENV_FILE = REPO_ROOT / ".env"
DEFAULT_URL = "http://localhost:8080/mcp"
DEFAULT_LOG_PATH = Path("exercise_log.json")
FIXTURE_SPEC_PATH = REPO_ROOT / "tests" / "fixtures" / "app_spec_golden" / "linear.json"
CALL_TIMEOUT_SECONDS = 120.0
DEPENDENCY_SKIP_PREFIX = "upstream dependency missing:"

# The two HTTP header names the deployed server reads the caller's Kissflow key
# pair off (`app.infrastructure.kissflow.credentials`). Never read here — only
# referenced by name.
KEY_ID_HEADER = "X-Access-Key-Id"
KEY_SECRET_HEADER = "X-Access-Key-Secret"
KEY_ID_ENV = "KF_DEV_ACCESS_KEY_ID"
KEY_SECRET_ENV = "KF_DEV_ACCESS_KEY_SECRET"

# Appendix A of docs/specs/refactor-to-mcp-boilerplate.md, 61 tools, 9 families.
# This is the one authoritative source both `build_plan()` and its own tests check
# against.
APPENDIX_A_TOOLS: frozenset[str] = frozenset(
    {
        # flow (25)
        "forge_add_field_validation",
        "forge_add_goto_gate",
        "forge_add_sequence_number",
        "forge_add_table",
        "forge_apply_fields",
        "forge_apply_layout",
        "forge_build_workflow",
        "forge_create_flow",
        "forge_create_list",
        "forge_create_process",
        "forge_delete_fields",
        "forge_delete_flow",
        "forge_doctor",
        "forge_publish",
        "forge_rename_fields",
        "forge_set_branch_conditions",
        "forge_set_events",
        "forge_set_required",
        "forge_set_styles",
        "forge_set_visibility",
        "kf_apply_field_change",
        "kf_create_process",
        "kf_get_flow_schema",
        "kf_publish",
        "kf_set_step_visibility",
        # app (14)
        "forge_add_member_roles",
        "forge_add_role_users",
        "forge_create_app",
        "forge_create_app_role",
        "forge_create_template_app",
        "forge_delete_app_role",
        "forge_grant_tier",
        "forge_list_app_roles",
        "forge_list_apps",
        "forge_member_batch",
        "forge_publish_app",
        "forge_set_role_preference",
        "forge_share_report",
        "forge_sweep",
        # page (3)
        "forge_build_page",
        "forge_create_page",
        "forge_set_navigation",
        # dataset (1)
        "forge_dataset_records",
        # item (1)
        "forge_simulate_case",
        # copilot (2)
        "forge_copilot_ask",
        "forge_copilot_check",
        # intake (9)
        "forge_apply_revisions",
        "forge_approve_spec",
        "forge_compare_to_spec",
        "forge_intake_questions",
        "forge_plan_app",
        "forge_request_confirmation",
        "forge_update_spec",
        "kf_plan_field_change",
        "kf_plan_step_visibility",
        # design (3)
        "forge_render_flow_diagram",
        "forge_render_mockups",
        "forge_render_schema_diagram",
        # meta (3)
        "forge_capabilities",
        "forge_playbook",
        "kf_list_field_types",
    }
)

# Names built on the main process, reused across every step that touches it, so a
# rename in one place propagates everywhere at once.
FIELD_TICKET_NO = "Ticket No"
FIELD_DETAILS = "Details"
FIELD_DETAILS_RENAMED = "Exercise Description"
FIELD_DUE_DATE = "Due Date"
FIELD_ROUTE = "Route"
FIELD_NEEDS_REWORK = "Needs Rework"
FIELD_SCRATCH = "Scratch Note"
FIELD_SEQUENCE = "Ticket ID"
SECTION_TICKET_INFO = "Ticket Info"
SECTION_ROUTING = "Routing"
STEP_START = "Start"
STEP_REVIEW = "Review"
STEP_STANDARD_REVIEW = "Standard Review"
STEP_STANDARD_APPROVE = "Standard Approve"
STEP_EXPRESS_APPROVE = "Express Approve"
BRANCH_STANDARD = "Standard"
BRANCH_EXPRESS = "Express"
PARALLEL_NAME = "Route Decision"
TABLE_NAME = "Line Items"


# =====================================================================================
# Plan primitives. A `Step` is a static tool name plus a `decide(ctx)` function
# chosen at execution time: either `Call(arguments)` (send it) or `Skip(reason)`
# (log it, never call it). `build_plan()` is pure and needs no client/ctx to
# construct, so the tool-name coverage can be checked offline, with no network and
# no fake client at all.
# =====================================================================================


@dataclass(frozen=True)
class Call:
    """A decision to invoke a tool.

    Attributes:
        arguments: The MCP tool-call arguments, exactly as sent over the wire.
    """

    arguments: dict[str, Any]


@dataclass(frozen=True)
class Skip:
    """A decision to record a tool as skipped without calling it.

    Attributes:
        reason: Why this tool cannot run this call, echoed into the log row.
    """

    reason: str


Decision = Call | Skip


@dataclass(frozen=True)
class Step:
    """One planned tool invocation.

    Attributes:
        tool: The MCP tool name. Must be a member of `APPENDIX_A_TOOLS`.
        decide: Given the current `Context`, returns the `Call`/`Skip` decision.
        after: Given the context and the tool's successful result data, updates the
            context in place and returns the subset of ids worth recording on the log
            row (e.g. `{"app_id": "..."}`). Only invoked on an `ok` outcome.
    """

    tool: str
    decide: Callable[[Context], Decision]
    after: Callable[[Context, Any], dict[str, str]] = field(
        default=lambda ctx, data: {}
    )


@dataclass
class Context:
    """Mutable run state: every id a later step needs from an earlier one.

    Attributes:
        args: The parsed CLI arguments.
        base: A per-run unique name prefix, so re-running never collides with a
            previous run's objects.
        fixture_patch: The complete `AppSpec` fixture (minus `approved`), used to build
            a gap-free spec for the offline intake/design pipeline.
    """

    args: argparse.Namespace
    base: str
    fixture_patch: dict[str, Any]
    app_id: str | None = None
    app_created_by_script: bool = False
    template_flow_id: str | None = None
    throwaway_app_id: str | None = None
    role_a_id: str | None = None
    role_b_id: str | None = None
    main_process_id: str | None = None
    secondary_process_id: str | None = None
    dataset_id: str | None = None
    list_flow_id: str | None = None
    page_id: str | None = None
    conversation_id: str | None = None
    spec_v1: dict[str, Any] | None = None
    spec_v2: dict[str, Any] | None = None
    approved_spec: dict[str, Any] | None = None
    digest: str | None = None
    approval_token: str | None = None
    # Populated by unlogged plumbing reads in `run_plan` (never their own log row --
    # `kf_get_flow_schema` has exactly one logged row elsewhere), so the two OFFLINE
    # dry-run tools below preview a REAL draft instead of a hand-built stub.
    secondary_draft: dict[str, Any] | None = None
    main_draft: dict[str, Any] | None = None
    copilot_ask_pending: bool = False

    @property
    def role_a_name(self) -> str:
        """The display name of the role created for tier/preference/user demos."""
        return f"{self.base}-RoleA"

    @property
    def role_b_name(self) -> str:
        """The display name of the role granted onto the main process's workflow."""
        return f"{self.base}-RoleB"


def _call(**kwargs: Any) -> Decision:
    """Build a `Call` decision from keyword arguments (drops nothing, adds nothing)."""
    return Call(dict(kwargs))


def _require(ctx: Context, **required: Any) -> str | None:
    """Return a skip reason naming the first falsy prerequisite, or `None` if all
    are set.

    Args:
        ctx: The current context (unused directly; kept for a uniform call shape).
        **required: Label -> value pairs. A falsy value fails the check.

    Returns:
        A human-readable skip reason, or `None` when every value is truthy.
    """
    del ctx
    for label, value in required.items():
        if not value:
            return (
                f"upstream dependency missing: {label!r} was not produced by an "
                f"earlier step in this run"
            )
    return None


# =====================================================================================
# Bucket A -- meta (3 tools). No app, no credentials-dependent state, no prior step.
# =====================================================================================


def _decide_forge_capabilities(ctx: Context) -> Decision:
    del ctx
    return _call(query="")


def _decide_forge_playbook(ctx: Context) -> Decision:
    del ctx
    return _call()


def _decide_kf_list_field_types(ctx: Context) -> Decision:
    del ctx
    return _call()


# =====================================================================================
# Bucket B -- the offline intake/design pipeline (9 tools). Fully stateless: every call
# passes the spec dict in and reads the next one out of the previous result.
# =====================================================================================


def _decide_forge_intake_questions(ctx: Context) -> Decision:
    del ctx
    return _call(spec=None, limit=4)


def _after_forge_intake_questions(ctx: Context, data: Any) -> dict[str, str]:
    del ctx, data
    return {}


def _decide_forge_update_spec(ctx: Context) -> Decision:
    patch = {k: v for k, v in ctx.fixture_patch.items() if k != "approved"}
    return _call(spec=None, patch=patch)


def _after_forge_update_spec(ctx: Context, data: Any) -> dict[str, str]:
    ctx.spec_v1 = data.get("spec") if isinstance(data, dict) else None
    return {}


def _decide_forge_render_flow_diagram(ctx: Context) -> Decision:
    missing = _require(ctx, spec_v1=ctx.spec_v1)
    if missing:
        return Skip(missing)
    return _call(spec=ctx.spec_v1, out_dir=None)


def _decide_forge_render_schema_diagram(ctx: Context) -> Decision:
    missing = _require(ctx, spec_v1=ctx.spec_v1)
    if missing:
        return Skip(missing)
    return _call(spec=ctx.spec_v1, out_dir=None)


def _decide_forge_render_mockups(ctx: Context) -> Decision:
    missing = _require(ctx, spec_v1=ctx.spec_v1)
    if missing:
        return Skip(missing)
    return _call(spec=ctx.spec_v1, out_dir=None)


def _decide_forge_apply_revisions(ctx: Context) -> Decision:
    missing = _require(ctx, spec_v1=ctx.spec_v1)
    if missing:
        return Skip(missing)
    assert ctx.spec_v1 is not None  # narrowed by _require above
    app_name = ctx.spec_v1.get("app_name", "App")
    revisions = {"app_name": f"{app_name} (exercised)"}
    return _call(spec=ctx.spec_v1, revisions=revisions)


def _after_forge_apply_revisions(ctx: Context, data: Any) -> dict[str, str]:
    ctx.spec_v2 = data.get("spec") if isinstance(data, dict) else None
    return {}


def _decide_forge_request_confirmation(ctx: Context) -> Decision:
    missing = _require(ctx, spec_v2=ctx.spec_v2)
    if missing:
        return Skip(missing)
    return _call(spec=ctx.spec_v2, out_dir=None)


def _after_forge_request_confirmation(ctx: Context, data: Any) -> dict[str, str]:
    digest = data.get("digest") if isinstance(data, dict) else None
    ctx.digest = digest
    return {"digest": digest} if digest else {}


def _decide_forge_approve_spec(ctx: Context) -> Decision:
    missing = _require(ctx, spec_v2=ctx.spec_v2, digest=ctx.digest)
    if missing:
        return Skip(missing)
    return _call(spec=ctx.spec_v2, digest=ctx.digest, decision="approve")


def _after_forge_approve_spec(ctx: Context, data: Any) -> dict[str, str]:
    if not isinstance(data, dict):
        return {}
    ctx.approved_spec = data.get("spec")
    ctx.approval_token = data.get("approval_token")
    return {}


def _decide_forge_plan_app(ctx: Context) -> Decision:
    missing = _require(
        ctx, approved_spec=ctx.approved_spec, approval_token=ctx.approval_token
    )
    if missing:
        return Skip(missing)
    return _call(spec=ctx.approved_spec, approval_token=ctx.approval_token)


# =====================================================================================
# Bucket C -- the app (3 tools).
# =====================================================================================


def _decide_forge_list_apps(ctx: Context) -> Decision:
    del ctx
    return _call()


def _decide_forge_create_template_app(ctx: Context) -> Decision:
    if ctx.args.app_id:
        return Skip(
            "an existing app was given via --app-id; forge_create_template_app is "
            "not needed to bootstrap the app for this run"
        )
    return _call(name=f"{ctx.base}-App")


def _after_forge_create_template_app(ctx: Context, data: Any) -> dict[str, str]:
    if not isinstance(data, dict):
        return {}
    ctx.app_id = data.get("app_id")
    ctx.app_created_by_script = bool(ctx.app_id)
    ctx.template_flow_id = data.get("flow_id")
    ids: dict[str, str] = {}
    if ctx.app_id:
        ids["app_id"] = ctx.app_id
    if ctx.template_flow_id:
        ids["template_flow_id"] = ctx.template_flow_id
    return ids


def _decide_forge_create_app(ctx: Context) -> Decision:
    return _call(name=f"{ctx.base}-Throwaway-App")


def _after_forge_create_app(ctx: Context, data: Any) -> dict[str, str]:
    app_id = data.get("app_id") if isinstance(data, dict) else None
    ctx.throwaway_app_id = app_id
    return {"throwaway_app_id": app_id} if app_id else {}


# =====================================================================================
# Bucket D -- role prep (1 tool). Needs only the app.
# =====================================================================================


def _decide_forge_create_app_role(ctx: Context) -> Decision:
    missing = _require(ctx, app_id=ctx.app_id)
    if missing:
        return Skip(missing)
    return _call(name=ctx.role_a_name, app_id=ctx.app_id)


def _after_forge_create_app_role(ctx: Context, data: Any) -> dict[str, str]:
    role_id = data.get("role_id") if isinstance(data, dict) else None
    ctx.role_a_id = role_id
    return {"role_a_id": role_id} if role_id else {}


# =====================================================================================
# Bucket E -- a process (1 tool).
# =====================================================================================


def _decide_forge_create_process(ctx: Context) -> Decision:
    missing = _require(ctx, app_id=ctx.app_id)
    if missing:
        return Skip(missing)
    return _call(name=f"{ctx.base}-Process", app_id=ctx.app_id)


def _after_forge_create_process(ctx: Context, data: Any) -> dict[str, str]:
    flow_id = data.get("flow_id") if isinstance(data, dict) else None
    ctx.main_process_id = flow_id
    return {"main_process_id": flow_id} if flow_id else {}


# =====================================================================================
# Bucket F -- the kf_* secondary flow (4 tools), fully self-contained on its own
# throwaway process so it never entangles with the main process's own build below.
# =====================================================================================

_KF_SECONDARY_FIELDS: list[dict[str, Any]] = [
    {"name": "Note", "type": "Text", "required": False}
]
_KF_SECONDARY_CHANGE: list[dict[str, Any]] = [
    {"name": "Extra Note", "type": "Text", "required": False}
]


def _decide_kf_create_process(ctx: Context) -> Decision:
    missing = _require(ctx, app_id=ctx.app_id)
    if missing:
        return Skip(missing)
    return _call(
        name=f"{ctx.base}-KfProcess",
        steps=["Draft", "Review"],
        fields=_KF_SECONDARY_FIELDS,
        publish=False,
        from_template=False,
        app_id=ctx.app_id,
    )


def _after_kf_create_process(ctx: Context, data: Any) -> dict[str, str]:
    flow_id = data.get("flow_id") if isinstance(data, dict) else None
    ctx.secondary_process_id = flow_id
    return {"secondary_process_id": flow_id} if flow_id else {}


def _decide_kf_plan_field_change(ctx: Context) -> Decision:
    missing = _require(
        ctx,
        secondary_process_id=ctx.secondary_process_id,
        secondary_draft=ctx.secondary_draft,
    )
    if missing:
        return Skip(missing)
    return _call(draft=ctx.secondary_draft, changes=_KF_SECONDARY_CHANGE)


def _decide_kf_apply_field_change(ctx: Context) -> Decision:
    missing = _require(ctx, secondary_process_id=ctx.secondary_process_id)
    if missing:
        return Skip(missing)
    return _call(
        flow_kind="process",
        flow_id=ctx.secondary_process_id,
        changes=_KF_SECONDARY_CHANGE,
        publish=False,
        app_id=ctx.app_id,
    )


def _decide_kf_publish(ctx: Context) -> Decision:
    missing = _require(ctx, secondary_process_id=ctx.secondary_process_id)
    if missing:
        return Skip(missing)
    return _call(
        flow_kind="process", flow_id=ctx.secondary_process_id, app_id=ctx.app_id
    )


# =====================================================================================
# Bucket G -- members (2 tools). Members before assignees, per CLAUDE.md > Members
# first.
# =====================================================================================


def _decide_forge_add_member_roles(ctx: Context) -> Decision:
    missing = _require(ctx, app_id=ctx.app_id, main_process_id=ctx.main_process_id)
    if missing:
        return Skip(missing)
    return _call(
        target_flow_id=ctx.main_process_id,
        roles={"new": ctx.role_b_name},
        kind="process",
        app_id=ctx.app_id,
    )


def _after_forge_add_member_roles(ctx: Context, data: Any) -> dict[str, str]:
    if not isinstance(data, dict):
        return {}
    resolved = data.get("resolved") or {}
    role_id = resolved.get(ctx.role_b_name) if isinstance(resolved, dict) else None
    ctx.role_b_id = role_id
    return {"role_b_id": role_id} if role_id else {}


def _decide_forge_member_batch(ctx: Context) -> Decision:
    missing = _require(ctx, app_id=ctx.app_id, main_process_id=ctx.main_process_id)
    if missing:
        return Skip(missing)
    return _call(
        target_flow_id=ctx.main_process_id,
        source_flow_id=ctx.template_flow_id,
        kind="process",
        app_id=ctx.app_id,
    )


# =====================================================================================
# Bucket H -- add_role_users, tier, preference (3 tools). The workflow assignee
# role gets the user grant; tier and preference stay on role_a.
# =====================================================================================


def _decide_forge_add_role_users(ctx: Context) -> Decision:
    if not ctx.args.user_query:
        return Skip(
            "no --user-query given, and no MCP-visible route exists to discover an "
            "existing human member of a role on a fresh app without one "
            "(forge_list_app_roles exposes no Members, and a groups grant is refused "
            "by hard rule) -- pass --user-query '<name or email>' to exercise this tool"
        )
    missing = _require(ctx, role_b_id=ctx.role_b_id)
    if missing:
        return Skip(missing)
    return _call(
        role_id=ctx.role_b_id, user_query=ctx.args.user_query, app_id=ctx.app_id
    )


def _decide_forge_grant_tier(ctx: Context) -> Decision:
    missing = _require(
        ctx,
        role_a_id=ctx.role_a_id,
        main_process_id=ctx.main_process_id,
        app_id=ctx.app_id,
    )
    if missing:
        return Skip(missing)
    return _call(
        kind="process",
        flow_id=ctx.main_process_id,
        role_id=ctx.role_a_id,
        tier="Manage",
        app_id=ctx.app_id,
    )


def _decide_forge_set_role_preference(ctx: Context) -> Decision:
    missing = _require(ctx, role_a_id=ctx.role_a_id, app_id=ctx.app_id)
    if missing:
        return Skip(missing)
    return _call(
        role_id=ctx.role_a_id,
        default_page="Default",
        default_navigation="Default",
        app_id=ctx.app_id,
    )


# =====================================================================================
# Bucket I -- fields, layout, table, sequence, validation (5 tools) on the main process.
# =====================================================================================

_MAIN_FIELDS: list[dict[str, Any]] = [
    {"name": FIELD_TICKET_NO, "type": "Text", "required": True},
    {"name": FIELD_DETAILS, "type": "Textarea", "required": False},
    {"name": FIELD_DUE_DATE, "type": "Date", "required": False},
    {"name": FIELD_ROUTE, "type": "Text", "required": False},
    {"name": FIELD_NEEDS_REWORK, "type": "Boolean", "required": False},
    {"name": FIELD_SCRATCH, "type": "Text", "required": False},
]
_MAIN_SECTIONS: dict[str, list[str]] = {
    SECTION_TICKET_INFO: [
        FIELD_TICKET_NO,
        FIELD_DETAILS,
        FIELD_DUE_DATE,
        FIELD_SCRATCH,
    ],
    SECTION_ROUTING: [FIELD_ROUTE, FIELD_NEEDS_REWORK],
}
_MAIN_LAYOUT: dict[str, list[list[list[Any]]]] = {
    SECTION_TICKET_INFO: [
        [[FIELD_TICKET_NO, 0, 3], [FIELD_DUE_DATE, 3, 6]],
        [[FIELD_DETAILS, 0, 6]],
        [[FIELD_SCRATCH, 0, 3]],
    ],
    SECTION_ROUTING: [[[FIELD_ROUTE, 0, 3], [FIELD_NEEDS_REWORK, 3, 6]]],
}
_MAIN_LAYOUT_DESCRIPTIONS: dict[str, str] = {
    SECTION_TICKET_INFO: "Basic ticket identification",
    SECTION_ROUTING: "Routing decision fields",
}
_MAIN_TABLE_COLUMNS: list[list[Any]] = [["Item", "Text"], ["Qty", "Number"]]
_MAIN_VALIDATION: dict[str, list[list[str]]] = {FIELD_TICKET_NO: [["MAX_LENGTH", "50"]]}
_MAIN_OWNERS: dict[str, list[str]] = {
    SECTION_TICKET_INFO: [STEP_START],
    SECTION_ROUTING: [STEP_START, STEP_REVIEW],
}
_MAIN_FIELD_OWNERS: dict[str, list[str]] = {
    FIELD_NEEDS_REWORK: [STEP_REVIEW, STEP_STANDARD_REVIEW]
}


def _decide_forge_apply_fields(ctx: Context) -> Decision:
    missing = _require(ctx, main_process_id=ctx.main_process_id)
    if missing:
        return Skip(missing)
    return _call(
        flow_id=ctx.main_process_id,
        fields=_MAIN_FIELDS,
        sections=_MAIN_SECTIONS,
        kind="process",
        publish=False,
        app_id=ctx.app_id,
    )


def _decide_forge_apply_layout(ctx: Context) -> Decision:
    missing = _require(ctx, main_process_id=ctx.main_process_id)
    if missing:
        return Skip(missing)
    return _call(
        flow_id=ctx.main_process_id,
        layout=_MAIN_LAYOUT,
        descriptions=_MAIN_LAYOUT_DESCRIPTIONS,
        kind="process",
        publish=False,
        app_id=ctx.app_id,
    )


def _decide_forge_add_table(ctx: Context) -> Decision:
    missing = _require(ctx, main_process_id=ctx.main_process_id)
    if missing:
        return Skip(missing)
    return _call(
        flow_id=ctx.main_process_id,
        name=TABLE_NAME,
        columns=_MAIN_TABLE_COLUMNS,
        kind="process",
        publish=False,
        app_id=ctx.app_id,
    )


def _decide_forge_add_sequence_number(ctx: Context) -> Decision:
    missing = _require(ctx, main_process_id=ctx.main_process_id)
    if missing:
        return Skip(missing)
    return _call(
        flow_id=ctx.main_process_id,
        field_name=FIELD_SEQUENCE,
        section_name=SECTION_TICKET_INFO,
        prefix="TCK-",
        padding="0001",
        step_activity_name=STEP_START,
        kind="process",
        publish=False,
        app_id=ctx.app_id,
    )


def _decide_forge_add_field_validation(ctx: Context) -> Decision:
    missing = _require(ctx, main_process_id=ctx.main_process_id)
    if missing:
        return Skip(missing)
    return _call(
        flow_id=ctx.main_process_id,
        rules=_MAIN_VALIDATION,
        kind="process",
        publish=False,
        app_id=ctx.app_id,
    )


def _decide_forge_set_required(ctx: Context) -> Decision:
    missing = _require(ctx, main_process_id=ctx.main_process_id)
    if missing:
        return Skip(missing)
    return _call(
        flow_id=ctx.main_process_id,
        required=[FIELD_TICKET_NO],
        kind="process",
        publish=False,
        app_id=ctx.app_id,
    )


def _decide_forge_rename_fields(ctx: Context) -> Decision:
    missing = _require(ctx, main_process_id=ctx.main_process_id)
    if missing:
        return Skip(missing)
    return _call(
        flow_id=ctx.main_process_id,
        renames={FIELD_DETAILS: FIELD_DETAILS_RENAMED},
        kind="process",
        publish=False,
        app_id=ctx.app_id,
    )


# =====================================================================================
# Bucket J -- workflow, gates, branch conditions (3 tools).
# =====================================================================================


def _decide_forge_build_workflow(ctx: Context) -> Decision:
    missing = _require(ctx, main_process_id=ctx.main_process_id)
    if missing:
        return Skip(missing)
    steps = [[STEP_START, ctx.role_b_id], [STEP_REVIEW, ctx.role_b_id]]
    parallel = {
        "name": PARALLEL_NAME,
        "branches": [
            [
                BRANCH_STANDARD,
                [
                    [STEP_STANDARD_REVIEW, ctx.role_b_id],
                    [STEP_STANDARD_APPROVE, ctx.role_b_id],
                ],
            ],
            [BRANCH_EXPRESS, [[STEP_EXPRESS_APPROVE, ctx.role_b_id]]],
        ],
    }
    roles = {ctx.role_b_id: ctx.role_b_name} if ctx.role_b_id else None
    step_meta = {STEP_REVIEW: {"description": "Review the ticket before routing"}}
    return _call(
        flow_id=ctx.main_process_id,
        steps=steps,
        parallel=parallel,
        parallel_after=1,
        roles=roles,
        step_meta=step_meta,
        kind="process",
        publish=False,
        app_id=ctx.app_id,
    )


def _decide_forge_add_goto_gate(ctx: Context) -> Decision:
    missing = _require(ctx, main_process_id=ctx.main_process_id)
    if missing:
        return Skip(missing)
    return _call(
        flow_id=ctx.main_process_id,
        target_activity_name=STEP_STANDARD_REVIEW,
        field_name=FIELD_NEEDS_REWORK,
        branch_name=BRANCH_STANDARD,
        kind="process",
        publish=False,
        app_id=ctx.app_id,
    )


def _decide_forge_set_branch_conditions(ctx: Context) -> Decision:
    missing = _require(ctx, main_process_id=ctx.main_process_id)
    if missing:
        return Skip(missing)
    return _call(
        flow_id=ctx.main_process_id,
        field_name=FIELD_ROUTE,
        branch_literals={BRANCH_STANDARD: "standard", BRANCH_EXPRESS: "express"},
        kind="process",
        publish=False,
        app_id=ctx.app_id,
    )


# =====================================================================================
# Bucket K -- visibility, dry run then two writers (3 tools).
# =====================================================================================


def _decide_kf_plan_step_visibility(ctx: Context) -> Decision:
    missing = _require(
        ctx, main_process_id=ctx.main_process_id, main_draft=ctx.main_draft
    )
    if missing:
        return Skip(missing)
    return _call(draft=ctx.main_draft, owners=_MAIN_OWNERS)


def _decide_kf_set_step_visibility(ctx: Context) -> Decision:
    missing = _require(ctx, main_process_id=ctx.main_process_id)
    if missing:
        return Skip(missing)
    return _call(
        flow_id=ctx.main_process_id,
        owners=_MAIN_OWNERS,
        publish=False,
        app_id=ctx.app_id,
    )


def _decide_forge_set_visibility(ctx: Context) -> Decision:
    missing = _require(ctx, main_process_id=ctx.main_process_id)
    if missing:
        return Skip(missing)
    return _call(
        flow_id=ctx.main_process_id,
        owners=_MAIN_OWNERS,
        field_owners=_MAIN_FIELD_OWNERS,
        kind="process",
        publish=False,
        app_id=ctx.app_id,
    )


# =====================================================================================
# Bucket L -- events, styles (2 tools). Styles carries the main process's own publish.
# =====================================================================================


def _decide_forge_set_events(ctx: Context) -> Decision:
    missing = _require(ctx, main_process_id=ctx.main_process_id)
    if missing:
        return Skip(missing)
    events = {FIELD_ROUTE: [[None, f"kf.form.getField('{FIELD_ROUTE}')"]]}
    return _call(
        flow_id=ctx.main_process_id,
        events=events,
        kind="process",
        publish=False,
        app_id=ctx.app_id,
    )


def _decide_forge_set_styles(ctx: Context) -> Decision:
    missing = _require(ctx, main_process_id=ctx.main_process_id)
    if missing:
        return Skip(missing)
    styles = {SECTION_TICKET_INFO: {"Section.Bg.Color": "Color.Info.300"}}
    return _call(
        flow_id=ctx.main_process_id,
        styles=styles,
        kind="process",
        publish=True,
        app_id=ctx.app_id,
    )


# =====================================================================================
# Bucket M -- doctor, compare (2 tools).
# =====================================================================================


def _decide_forge_doctor(ctx: Context) -> Decision:
    missing = _require(ctx, main_process_id=ctx.main_process_id)
    if missing:
        return Skip(missing)
    return _call(flow_id=ctx.main_process_id, kind="process", app_id=ctx.app_id)


def _decide_forge_compare_to_spec(ctx: Context) -> Decision:
    missing = _require(
        ctx, main_process_id=ctx.main_process_id, approved_spec=ctx.approved_spec
    )
    if missing:
        return Skip(missing)
    return _call(
        flow_id=ctx.main_process_id,
        spec=ctx.approved_spec,
        kind="process",
        app_id=ctx.app_id,
    )


# =====================================================================================
# Bucket N -- the one logged schema read.
# =====================================================================================


def _decide_kf_get_flow_schema(ctx: Context) -> Decision:
    missing = _require(ctx, main_process_id=ctx.main_process_id)
    if missing:
        return Skip(missing)
    return _call(flow_kind="process", flow_id=ctx.main_process_id, app_id=ctx.app_id)


# =====================================================================================
# Bucket O -- page, navigation, publish (4 tools).
# =====================================================================================


def _decide_forge_create_page(ctx: Context) -> Decision:
    missing = _require(ctx, app_id=ctx.app_id)
    if missing:
        return Skip(missing)
    return _call(app_id=ctx.app_id, name=f"{ctx.base}-Page", publish=False)


def _after_forge_create_page(ctx: Context, data: Any) -> dict[str, str]:
    page_id = data.get("page_id") if isinstance(data, dict) else None
    ctx.page_id = page_id
    return {"page_id": page_id} if page_id else {}


def _decide_forge_build_page(ctx: Context) -> Decision:
    missing = _require(ctx, app_id=ctx.app_id, page_id=ctx.page_id)
    if missing:
        return Skip(missing)
    steps = [
        {
            "kind": "widget",
            "kwargs": {
                "container_id": "Container001",
                "widget": "general/button",
                "config": {},
            },
        }
    ]
    return _call(
        app_id=ctx.app_id, page_id=ctx.page_id, steps=steps, publish=False, op=None
    )


def _decide_forge_set_navigation(ctx: Context) -> Decision:
    missing = _require(ctx, app_id=ctx.app_id, page_id=ctx.page_id)
    if missing:
        return Skip(missing)
    return _call(
        app_id=ctx.app_id,
        page_id=ctx.page_id,
        label=f"{ctx.base}-Page",
        unify=True,
        sweep=False,
        publish=False,
    )


def _decide_forge_publish(ctx: Context) -> Decision:
    missing = _require(ctx, app_id=ctx.app_id, page_id=ctx.page_id)
    if missing:
        return Skip(missing)
    return _call(kind="page", flow_id=ctx.page_id, app_id=ctx.app_id)


# =====================================================================================
# Bucket P -- a word list (1 tool). Standalone, never wired into a Select.
# =====================================================================================


def _decide_forge_create_list(ctx: Context) -> Decision:
    missing = _require(ctx, app_id=ctx.app_id)
    if missing:
        return Skip(missing)
    return _call(
        name=f"{ctx.base}-Colors",
        values=["Red", "Green", "Blue"],
        app_id=ctx.app_id,
    )


def _after_forge_create_list(ctx: Context, data: Any) -> dict[str, str]:
    list_id = data.get("list_id") if isinstance(data, dict) else None
    ctx.list_flow_id = list_id
    return {"list_id": list_id} if list_id else {}


# =====================================================================================
# Bucket Q -- a dataset and its records (2 tools).
# =====================================================================================


def _decide_forge_create_flow(ctx: Context) -> Decision:
    missing = _require(ctx, app_id=ctx.app_id)
    if missing:
        return Skip(missing)
    return _call(
        kind="dataset", name=f"{ctx.base}-Dataset", extra=None, app_id=ctx.app_id
    )


def _after_forge_create_flow(ctx: Context, data: Any) -> dict[str, str]:
    flow_id = data.get("flow_id") if isinstance(data, dict) else None
    ctx.dataset_id = flow_id
    return {"dataset_id": flow_id} if flow_id else {}


def _decide_forge_dataset_records(ctx: Context) -> Decision:
    missing = _require(ctx, dataset_id=ctx.dataset_id)
    if missing:
        return Skip(missing)
    return _call(
        flow_id=ctx.dataset_id,
        op="create",
        record={"Name": f"{ctx.base}-Record-1"},
        record_id=None,
        app_id=ctx.app_id,
    )


# =====================================================================================
# Bucket R -- sweep and the copilot pair (3 tools).
# =====================================================================================


def _decide_forge_sweep(ctx: Context) -> Decision:
    missing = _require(ctx, app_id=ctx.app_id)
    if missing:
        return Skip(missing)
    return _call(scope="flows", app_id=ctx.app_id)


def _decide_forge_copilot_ask(ctx: Context) -> Decision:
    missing = _require(ctx, app_id=ctx.app_id)
    if missing:
        return Skip(missing)
    message = (
        "This is an automated tool-exercise run over MCP. No change is requested; "
        "this message only confirms the copilot channel on the app this run created "
        "is reachable."
    )
    return _call(app_id=ctx.app_id, message=message, expect=None)


def _after_forge_copilot_ask(ctx: Context, data: Any) -> dict[str, str]:
    conversation_id = data.get("conversation_id") if isinstance(data, dict) else None
    status = data.get("status") if isinstance(data, dict) else None
    ctx.conversation_id = conversation_id
    ctx.copilot_ask_pending = (
        not conversation_id
        and isinstance(data, dict)
        and isinstance(status, str)
        and (status == "pending" or status.startswith("pending:"))
    )
    return {"conversation_id": conversation_id} if conversation_id else {}


def _decide_forge_copilot_check(ctx: Context) -> Decision:
    missing = _require(ctx, app_id=ctx.app_id)
    if missing:
        return Skip(missing)
    if ctx.copilot_ask_pending and not ctx.conversation_id:
        return Skip(
            "forge_copilot_ask is pending with no conversation_id; "
            "forge_copilot_check is intentionally skipped"
        )
    missing = _require(ctx, conversation_id=ctx.conversation_id)
    if missing:
        return Skip(missing)
    return _call(
        app_id=ctx.app_id,
        conversation_id=ctx.conversation_id,
        baseline_inventory=None,
    )


# =====================================================================================
# Bucket S -- the simulated case (1 tool). Only Text/Boolean fills, to keep the fill
# audit clear of any field-type-specific formatting risk this script cannot debug live.
# =====================================================================================


def _decide_forge_simulate_case(ctx: Context) -> Decision:
    missing = _require(ctx, main_process_id=ctx.main_process_id)
    if missing:
        return Skip(missing)
    steps = [
        {
            "name": STEP_START,
            "values": {FIELD_TICKET_NO: "TCK-EX-0001"},
            "reject": False,
            "comment": "exercise script initial submit",
        },
        {
            "name": STEP_REVIEW,
            "values": {FIELD_ROUTE: "standard", FIELD_NEEDS_REWORK: False},
            "reject": False,
            "comment": "exercise script review",
        },
    ]
    return _call(flow_id=ctx.main_process_id, steps=steps, app_id=ctx.app_id)


# =====================================================================================
# Bucket T -- role listing, app publish (2 tools).
# =====================================================================================


def _decide_forge_list_app_roles(ctx: Context) -> Decision:
    missing = _require(ctx, app_id=ctx.app_id)
    if missing:
        return Skip(missing)
    return _call(app_id=ctx.app_id)


def _decide_forge_publish_app(ctx: Context) -> Decision:
    missing = _require(ctx, app_id=ctx.app_id)
    if missing:
        return Skip(missing)
    return _call(app_id=ctx.app_id)


# =====================================================================================
# Bucket U -- deletes of throwaway objects, last. Every id here was produced by an
# earlier step in THIS SAME run; nothing pre-existing is ever named.
# =====================================================================================


def _decide_forge_delete_fields(ctx: Context) -> Decision:
    missing = _require(ctx, main_process_id=ctx.main_process_id)
    if missing:
        return Skip(missing)
    return _call(
        flow_id=ctx.main_process_id,
        fields=[FIELD_SCRATCH],
        tables=[TABLE_NAME],
        kind="process",
        publish=False,
        app_id=ctx.app_id,
    )


def _decide_forge_delete_app_role(ctx: Context) -> Decision:
    missing = _require(ctx, role_a_id=ctx.role_a_id)
    if missing:
        return Skip(missing)
    return _call(role_id=ctx.role_a_id, app_id=ctx.app_id)


def _decide_forge_delete_flow(ctx: Context) -> Decision:
    missing = _require(ctx, throwaway_app_id=ctx.throwaway_app_id)
    if missing:
        return Skip(missing)
    return _call(kind="application", flow_id=ctx.throwaway_app_id)


def _decide_forge_share_report(ctx: Context) -> Decision:
    del ctx
    return Skip(
        "forge_share_report needs a report id, and no tool on this 61-tool surface "
        "creates or discovers a flow report id -- this run has nothing to pass"
    )


def build_plan() -> list[Step]:
    """Build the ordered, static list of all 61 planned tool invocations.

    Pure: touches no network, no client, no context. `[s.tool for s in build_plan()]`
    covers every name in `APPENDIX_A_TOOLS` exactly once, which is checked by
    `tests/unit/scripts/test_exercise_every_tool.py` without any fake client at all.

    Returns:
        The plan, in build order (CLAUDE.md's own order): meta, the offline intake/
        design pipeline, the app, roles, a process, fields through styles, publish,
        doctor, a page, a word list, a dataset, the copilot pair, a simulated case,
        and the deletes of throwaway objects last.
    """
    plan = [
        Step("forge_capabilities", _decide_forge_capabilities),
        Step("forge_playbook", _decide_forge_playbook),
        Step("kf_list_field_types", _decide_kf_list_field_types),
        Step(
            "forge_intake_questions",
            _decide_forge_intake_questions,
            _after_forge_intake_questions,
        ),
        Step("forge_update_spec", _decide_forge_update_spec, _after_forge_update_spec),
        Step("forge_render_flow_diagram", _decide_forge_render_flow_diagram),
        Step("forge_render_schema_diagram", _decide_forge_render_schema_diagram),
        Step("forge_render_mockups", _decide_forge_render_mockups),
        Step(
            "forge_apply_revisions",
            _decide_forge_apply_revisions,
            _after_forge_apply_revisions,
        ),
        Step(
            "forge_request_confirmation",
            _decide_forge_request_confirmation,
            _after_forge_request_confirmation,
        ),
        Step(
            "forge_approve_spec", _decide_forge_approve_spec, _after_forge_approve_spec
        ),
        Step("forge_plan_app", _decide_forge_plan_app),
        Step("forge_list_apps", _decide_forge_list_apps),
        Step(
            "forge_create_template_app",
            _decide_forge_create_template_app,
            _after_forge_create_template_app,
        ),
        Step("forge_create_app", _decide_forge_create_app, _after_forge_create_app),
        Step(
            "forge_create_app_role",
            _decide_forge_create_app_role,
            _after_forge_create_app_role,
        ),
        Step(
            "forge_create_process",
            _decide_forge_create_process,
            _after_forge_create_process,
        ),
        Step("kf_create_process", _decide_kf_create_process, _after_kf_create_process),
        Step("kf_plan_field_change", _decide_kf_plan_field_change),
        Step("kf_apply_field_change", _decide_kf_apply_field_change),
        Step("kf_publish", _decide_kf_publish),
        Step(
            "forge_add_member_roles",
            _decide_forge_add_member_roles,
            _after_forge_add_member_roles,
        ),
        Step("forge_member_batch", _decide_forge_member_batch),
        Step("forge_add_role_users", _decide_forge_add_role_users),
        Step("forge_grant_tier", _decide_forge_grant_tier),
        Step("forge_set_role_preference", _decide_forge_set_role_preference),
        Step("forge_apply_fields", _decide_forge_apply_fields),
        Step("forge_apply_layout", _decide_forge_apply_layout),
        Step("forge_add_table", _decide_forge_add_table),
        Step("forge_add_sequence_number", _decide_forge_add_sequence_number),
        Step("forge_add_field_validation", _decide_forge_add_field_validation),
        Step("forge_set_required", _decide_forge_set_required),
        Step("forge_rename_fields", _decide_forge_rename_fields),
        Step("forge_build_workflow", _decide_forge_build_workflow),
        Step("forge_add_goto_gate", _decide_forge_add_goto_gate),
        Step("forge_set_branch_conditions", _decide_forge_set_branch_conditions),
        Step("kf_plan_step_visibility", _decide_kf_plan_step_visibility),
        Step("kf_set_step_visibility", _decide_kf_set_step_visibility),
        Step("forge_set_visibility", _decide_forge_set_visibility),
        Step("forge_set_events", _decide_forge_set_events),
        Step("forge_set_styles", _decide_forge_set_styles),
        Step("forge_doctor", _decide_forge_doctor),
        Step("forge_compare_to_spec", _decide_forge_compare_to_spec),
        Step("kf_get_flow_schema", _decide_kf_get_flow_schema),
        Step("forge_create_page", _decide_forge_create_page, _after_forge_create_page),
        Step("forge_build_page", _decide_forge_build_page),
        Step("forge_set_navigation", _decide_forge_set_navigation),
        Step("forge_publish", _decide_forge_publish),
        Step("forge_create_list", _decide_forge_create_list, _after_forge_create_list),
        Step("forge_create_flow", _decide_forge_create_flow, _after_forge_create_flow),
        Step("forge_dataset_records", _decide_forge_dataset_records),
        Step("forge_sweep", _decide_forge_sweep),
        Step("forge_copilot_ask", _decide_forge_copilot_ask, _after_forge_copilot_ask),
        Step("forge_copilot_check", _decide_forge_copilot_check),
        Step("forge_simulate_case", _decide_forge_simulate_case),
        Step("forge_list_app_roles", _decide_forge_list_app_roles),
        Step("forge_publish_app", _decide_forge_publish_app),
        Step("forge_delete_fields", _decide_forge_delete_fields),
        Step("forge_delete_app_role", _decide_forge_delete_app_role),
        Step("forge_delete_flow", _decide_forge_delete_flow),
        Step("forge_share_report", _decide_forge_share_report),
    ]
    return plan


# =====================================================================================
# Transport, credentials, and the log row shape.
# =====================================================================================


def build_http_headers(key_id: str, key_secret: str) -> dict[str, str]:
    """Build the two Kissflow key-pair request headers for the streamable-http
    transport.

    Never logs, prints, or otherwise echoes either value -- the caller owns that
    discipline too, but this function itself touches no I/O at all.

    Args:
        key_id: The Kissflow access-key id.
        key_secret: The Kissflow access-key secret.

    Returns:
        A dict with exactly the two headers the server's
        `app.infrastructure.kissflow.credentials.caller_keys` reads in HTTP mode.
    """
    return {KEY_ID_HEADER: key_id, KEY_SECRET_HEADER: key_secret}


def resolve_key_pair(env_file: Path | None = None) -> tuple[str, str]:
    """Resolve the Kissflow key pair from the environment, falling back to `.env`.

    Args:
        env_file: The `.env`-style file to read with `dotenv_values` when
            `KF_DEV_ACCESS_KEY_ID`/`KF_DEV_ACCESS_KEY_SECRET` are not already set in
            the process environment. Defaults to the repo-root `.env`.

    Returns:
        The `(key_id, key_secret)` pair.

    Raises:
        SystemExit: Neither the environment nor the env file has both values. The
            message names the two variable names only, never a value.
    """
    key_id = os.environ.get(KEY_ID_ENV)
    key_secret = os.environ.get(KEY_SECRET_ENV)
    if not key_id or not key_secret:
        values = dotenv_values(env_file or DEFAULT_ENV_FILE)
        key_id = key_id or values.get(KEY_ID_ENV)
        key_secret = key_secret or values.get(KEY_SECRET_ENV)
    if not key_id or not key_secret:
        raise SystemExit(
            f"{KEY_ID_ENV} / {KEY_SECRET_ENV} are not set in the environment or in "
            f"{env_file or DEFAULT_ENV_FILE}"
        )
    return key_id, key_secret


def build_client(args: argparse.Namespace) -> Client:
    """Build the `fastmcp.Client` for the transport the CLI flags selected.

    Args:
        args: The parsed CLI arguments (`--url`, `--stdio-docker`, `--env-file`).

    Returns:
        An unconnected `Client`; the caller opens it with `async with client:`.
    """
    if args.stdio_docker:
        env_file = args.env_file or DEFAULT_ENV_FILE
        transport = StdioTransport(
            command="docker",
            args=[
                "run",
                "-i",
                "--rm",
                "--env-file",
                str(env_file),
                "-e",
                "MCP_HTTP=",
                args.stdio_docker,
            ],
        )
        return Client(transport, init_timeout=60)
    key_id, key_secret = resolve_key_pair(args.env_file)
    headers = build_http_headers(key_id, key_secret)
    transport = StreamableHttpTransport(url=args.url, headers=headers)
    return Client(transport)


Outcome = Literal["ok", "error", "skipped"]


def _as_dict(value: Any) -> dict[str, Any] | None:
    """Convert an MCP result payload to a plain dictionary when it has one.

    FastMCP exposes typed success payloads through ``CallToolResult.data``. A
    Pydantic ``BaseModel`` or ``RootModel[dict]`` is not itself a mapping, so
    callbacks that read ids from ``data`` would otherwise see an empty result.
    Keep the conversion local to this black-box client and leave non-mapping
    payloads (such as list responses) untouched by returning ``None``.

    Args:
        value: The value returned in ``CallToolResult.data`` or
            ``structured_content``.

    Returns:
        A new plain dictionary, or ``None`` when the payload is not a mapping.
    """
    if isinstance(value, Mapping):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if not callable(model_dump):
        return None
    try:
        dumped = model_dump(mode="json")
    except Exception:  # noqa: BLE001 -- malformed payload must not abort logging
        return None
    return dict(dumped) if isinstance(dumped, Mapping) else None


def _result_as_dict(result: Any) -> dict[str, Any] | None:
    """Extract a dictionary from an MCP result, with a structured fallback.

    FastMCP may expose a non-mapping response wrapper through ``data`` while
    retaining the plain response dictionary in ``structured_content``. Use
    ``data`` when it is a mapping or typed model, then fall back when it is not.

    Args:
        result: An MCP ``CallToolResult``-like object.

    Returns:
        A plain response dictionary, or ``None`` when neither result field is one.
    """
    data = _as_dict(getattr(result, "data", None))
    if data is not None:
        return data
    return _as_dict(getattr(result, "structured_content", None))


def _result_error_message(result: Any) -> str:
    """Extract a tool error from structured data or the first text content block.

    FastMCP puts some ``CallToolResult`` errors only in ``content`` while leaving
    both ``data`` and ``structured_content`` empty. The server masks credentials
    before returning those messages, so recording the text does not add transport
    secrets to this log.

    Args:
        result: An MCP ``CallToolResult``-like object.

    Returns:
        The structured error text, first text content, or a stable fallback.
    """
    data = _result_as_dict(result)
    if data is not None:
        error = data.get("error")
        if error:
            return str(error)
    content = getattr(result, "content", None)
    if isinstance(content, list):
        for block in content:
            text = getattr(block, "text", None)
            if isinstance(text, str) and text:
                return text
            if isinstance(block, Mapping):
                text = block.get("text")
                if isinstance(text, str) and text:
                    return text
    return "tool reported isError"


@dataclass
class LogRow:
    """One row of the exercise log: one tool, one outcome, never a secret.

    Attributes:
        name: The MCP tool name.
        arguments: The exact arguments sent (or that would have been sent, for a
            skipped step) -- never includes a credential; the key pair travels as
            transport headers/env, never as a tool argument.
        outcome: `"ok"`, `"error"`, or `"skipped"`.
        error: The error message, only set when `outcome == "error"`.
        skip_reason: Why this step was skipped, only set when `outcome == "skipped"`.
        duration_seconds: Wall-clock time spent in the call. `0.0` for a skip.
        ids: The ids this call produced, e.g. `{"app_id": "..."}`.
    """

    name: str
    arguments: dict[str, Any]
    outcome: Outcome
    error: str | None
    skip_reason: str | None
    duration_seconds: float
    ids: dict[str, str]


async def _peek_draft(
    client: Client, flow_id: str, app_id: str | None
) -> dict[str, Any] | None:
    """Read a flow's live draft for internal plan bookkeeping.

    Deliberately NOT a logged plan step -- `kf_get_flow_schema` has exactly one
    logged row elsewhere (Appendix A coverage is one row per TOOL NAME, not one row
    per wire call). Used only to give the two offline dry-run tools
    (`kf_plan_field_change`, `kf_plan_step_visibility`) a real draft to preview.

    Args:
        client: The connected MCP client.
        flow_id: The process id to read.
        app_id: The owning application id.

    Returns:
        The draft dict, or `None` on any failure (the dependent step then skips
        itself via `_require` rather than previewing garbage).
    """
    try:
        result = await client.call_tool(
            "kf_get_flow_schema",
            {"flow_kind": "process", "flow_id": flow_id, "app_id": app_id},
            raise_on_error=False,
            timeout=CALL_TIMEOUT_SECONDS,
        )
    except Exception:  # noqa: BLE001 -- plumbing read, never fatal to the run
        return None
    if result.is_error:
        return None
    return _result_as_dict(result)


async def run_plan(client: Client, ctx: Context, plan: list[Step]) -> list[LogRow]:
    """Execute every step of `plan` in order against `client`, updating `ctx`.

    Never raises on a single tool's failure -- every outcome, including a raised
    exception, becomes one `LogRow` and the run continues to the next step, so one
    bad call never hides the other 60.

    Args:
        client: A `Client` already inside its `async with` block (connected).
        ctx: The mutable run context; steps read and write it via `decide`/`after`.
        plan: The ordered steps to run, as returned by `build_plan()`.

    Returns:
        One `LogRow` per step, in plan order.
    """
    rows: list[LogRow] = []
    for step in plan:
        if step.tool == "kf_plan_field_change" and ctx.secondary_process_id:
            ctx.secondary_draft = await _peek_draft(
                client, ctx.secondary_process_id, ctx.app_id
            )
        if step.tool == "kf_plan_step_visibility" and ctx.main_process_id:
            ctx.main_draft = await _peek_draft(client, ctx.main_process_id, ctx.app_id)

        decision = step.decide(ctx)
        if isinstance(decision, Skip):
            rows.append(
                LogRow(
                    name=step.tool,
                    arguments={},
                    outcome="skipped",
                    error=None,
                    skip_reason=decision.reason,
                    duration_seconds=0.0,
                    ids={},
                )
            )
            continue

        started = time.monotonic()
        try:
            result = await client.call_tool(
                step.tool,
                decision.arguments,
                raise_on_error=False,
                timeout=CALL_TIMEOUT_SECONDS,
            )
        except Exception as exc:  # noqa: BLE001 -- record it, never abort the run
            duration = time.monotonic() - started
            rows.append(
                LogRow(
                    name=step.tool,
                    arguments=decision.arguments,
                    outcome="error",
                    error=f"{type(exc).__name__}: {exc}",
                    skip_reason=None,
                    duration_seconds=duration,
                    ids={},
                )
            )
            continue
        duration = time.monotonic() - started

        if result.is_error:
            rows.append(
                LogRow(
                    name=step.tool,
                    arguments=decision.arguments,
                    outcome="error",
                    error=_result_error_message(result),
                    skip_reason=None,
                    duration_seconds=duration,
                    ids={},
                )
            )
            continue

        data = _result_as_dict(result)
        ids = step.after(ctx, data) if data is not None else {}
        rows.append(
            LogRow(
                name=step.tool,
                arguments=decision.arguments,
                outcome="ok",
                error=None,
                skip_reason=None,
                duration_seconds=duration,
                ids=ids,
            )
        )
    return rows


async def _silent_delete(client: Client, tool: str, arguments: dict[str, Any]) -> None:
    """Best-effort teardown call, outside the 61-row plan.

    Never raises and never touches the log -- final cleanup of throwaway objects is
    housekeeping, not part of the tool-exercise deliverable. Failures are printed to
    stderr so a re-run's leftovers are visible without polluting `exercise_log.json`.

    Args:
        client: The connected MCP client.
        tool: The tool to call (`forge_delete_flow` or `forge_delete_app_role`).
        arguments: The arguments for that call.
    """
    try:
        result = await client.call_tool(
            tool, arguments, raise_on_error=False, timeout=CALL_TIMEOUT_SECONDS
        )
    except Exception as exc:  # noqa: BLE001 -- best effort, never fatal
        print(f"[cleanup] {tool}({arguments}) raised {exc!r}", file=sys.stderr)
        return
    if result.is_error:
        print(f"[cleanup] {tool}({arguments}) reported an error", file=sys.stderr)


async def final_cleanup(client: Client, ctx: Context) -> None:
    """Remove every throwaway object this run created that the 61-step plan did not.

    Two tiers, both hard-coded to ids `ctx` itself recorded earlier in this run:

    - The `kf_create_process` secondary flow is always removed -- it exists only to
      exercise `kf_create_process`/`kf_apply_field_change`/`kf_publish` in isolation
      and carries nothing worth keeping.
    - The primary app's own contents (page, dataset, list, main process, and the
      workflow-assigned role) are removed only when `--cleanup` was given AND this
      run created the app itself -- an app passed via `--app-id` is never touched,
      matching "nothing outside the new app is deleted".

    Args:
        client: The connected MCP client.
        ctx: The run context, read for every id that might need deleting.
    """
    if ctx.secondary_process_id:
        await _silent_delete(
            client,
            "forge_delete_flow",
            {
                "kind": "process",
                "flow_id": ctx.secondary_process_id,
                "app_id": ctx.app_id,
            },
        )

    if not (ctx.args.cleanup and ctx.app_created_by_script and ctx.app_id):
        return

    for kind, flow_id in (
        ("page", ctx.page_id),
        ("dataset", ctx.dataset_id),
        ("list", ctx.list_flow_id),
        ("process", ctx.main_process_id),
    ):
        if flow_id:
            await _silent_delete(
                client,
                "forge_delete_flow",
                {"kind": kind, "flow_id": flow_id, "app_id": ctx.app_id},
            )
    if ctx.role_b_id:
        await _silent_delete(
            client,
            "forge_delete_app_role",
            {"role_id": ctx.role_b_id, "app_id": ctx.app_id},
        )
    await _silent_delete(
        client, "forge_delete_flow", {"kind": "application", "flow_id": ctx.app_id}
    )


# =====================================================================================
# Output: the table, the summary line, and `exercise_log.json`.
# =====================================================================================


def format_table(rows: list[LogRow]) -> str:
    """Render a fixed-width text table of every row, for a human scanning the run.

    Args:
        rows: The rows to render, in plan order.

    Returns:
        The table as one multi-line string, no trailing newline.
    """
    header = f"{'tool':<32}{'outcome':<9}{'seconds':>8}  detail"
    lines = [header, "-" * len(header)]
    for row in rows:
        detail = row.error or row.skip_reason or ""
        if len(detail) > 60:
            detail = detail[:57] + "..."
        lines.append(
            f"{row.name:<32}{row.outcome:<9}{row.duration_seconds:>8.2f}  {detail}"
        )
    return "\n".join(lines)


def summary_line(rows: list[LogRow]) -> str:
    """Build the one-line summary: `"<n> ok, <n> error, <n> skipped of <total>"`.

    Args:
        rows: The rows to summarize.

    Returns:
        The summary line.
    """
    ok = sum(1 for r in rows if r.outcome == "ok")
    error = sum(1 for r in rows if r.outcome == "error")
    skipped = sum(1 for r in rows if r.outcome == "skipped")
    return f"{ok} ok, {error} error, {skipped} skipped of {len(rows)}"


def rows_to_log(rows: list[LogRow]) -> dict[str, Any]:
    """Build the JSON-serializable document written to `exercise_log.json`.

    Args:
        rows: The rows to serialize, in plan order.

    Returns:
        A dict with `"rows"` (one entry per tool, in plan order) and `"summary"`
        (the ok/error/skipped/total counts).
    """
    ok = sum(1 for r in rows if r.outcome == "ok")
    error = sum(1 for r in rows if r.outcome == "error")
    skipped = sum(1 for r in rows if r.outcome == "skipped")
    return {
        "rows": [
            {
                "name": r.name,
                "arguments": r.arguments,
                "outcome": r.outcome,
                "error": r.error,
                "skip_reason": r.skip_reason,
                "duration_seconds": r.duration_seconds,
                "ids": r.ids,
            }
            for r in rows
        ],
        "summary": {
            "ok": ok,
            "error": error,
            "skipped": skipped,
            "total": len(rows),
        },
    }


def write_log(path: Path, rows: list[LogRow]) -> None:
    """Write `exercise_log.json` to `path`.

    Args:
        path: The destination file path.
        rows: The rows to serialize.
    """
    path.write_text(json.dumps(rows_to_log(rows), indent=2, sort_keys=True) + "\n")


def _run_has_failure(rows: list[LogRow]) -> bool:
    """Return whether a run has a tool error or an unmet plan dependency.

    Intentional skips remain valid. A dependency skip means an earlier response
    failed to provide state required by a later tool, so treating that run as
    successful would hide a broken chain of calls.
    """
    return any(
        row.outcome == "error"
        or (
            row.outcome == "skipped"
            and (row.skip_reason or "").startswith(DEPENDENCY_SKIP_PREFIX)
        )
        for row in rows
    )


# =====================================================================================
# CLI.
# =====================================================================================


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the command line.

    Args:
        argv: The argument vector, or `None` to read `sys.argv[1:]`.

    Returns:
        The parsed namespace.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Exercise every forge_*/kf_* MCP tool against a new (or existing) "
            "application on the Kissflow dev tenant."
        )
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help=f"streamable-http server URL (default: {DEFAULT_URL})",
    )
    parser.add_argument(
        "--stdio-docker",
        metavar="IMAGE",
        default=None,
        help="run the server as 'docker run -i --rm --env-file <path> "
        "-e MCP_HTTP= <IMAGE>' over stdio, instead of --url",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help="env file for the http-mode dotenv fallback and for --stdio-docker's "
        "own --env-file (default: <repo root>/.env)",
    )
    parser.add_argument(
        "--app-id",
        default=None,
        help="use an existing application instead of creating one",
    )
    keep_group = parser.add_mutually_exclusive_group()
    keep_group.add_argument(
        "--keep",
        action="store_true",
        default=False,
        help="leave the created application in place (default behavior)",
    )
    keep_group.add_argument(
        "--cleanup",
        action="store_true",
        default=False,
        help="delete the application this run created, at the end",
    )
    parser.add_argument(
        "--user-query",
        default=None,
        help="a name/email substring of a real Kissflow user, for forge_add_role_users",
    )
    parser.add_argument(
        "--log-path",
        type=Path,
        default=DEFAULT_LOG_PATH,
        help=f"where to write the JSON log (default: {DEFAULT_LOG_PATH})",
    )
    return parser.parse_args(argv)


def load_fixture_spec() -> dict[str, Any]:
    """Load the gap-free `AppSpec` fixture used to drive the offline intake/design
    pipeline (`tests/fixtures/app_spec_golden/linear.json`).

    Returns:
        The fixture as a plain dict.

    Raises:
        SystemExit: The fixture file is missing.
    """
    if not FIXTURE_SPEC_PATH.is_file():
        raise SystemExit(f"missing fixture spec: {FIXTURE_SPEC_PATH}")
    return json.loads(FIXTURE_SPEC_PATH.read_text())


def build_context(args: argparse.Namespace) -> Context:
    """Build the initial run `Context` from parsed CLI arguments.

    Args:
        args: The parsed CLI arguments.

    Returns:
        A fresh `Context`, seeded with `--app-id` when given and a per-run unique
        name prefix otherwise used to name every object this run creates.
    """
    run_tag = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    ctx = Context(
        args=args,
        base=f"ExerciseTool-{run_tag}",
        fixture_patch=load_fixture_spec(),
    )
    if args.app_id:
        ctx.app_id = args.app_id
        ctx.app_created_by_script = False
    return ctx


async def _run_async(args: argparse.Namespace) -> list[LogRow]:
    """Build the client, run the whole plan, and tear down throwaway objects.

    Args:
        args: The parsed CLI arguments.

    Returns:
        The rows produced by `run_plan`.
    """
    ctx = build_context(args)
    plan = build_plan()
    client = build_client(args)
    async with client:
        rows = await run_plan(client, ctx, plan)
        await final_cleanup(client, ctx)
    return rows


def main(argv: list[str] | None = None) -> int:
    """Entry point: parse args, run the plan, print the table, write the log.

    Args:
        argv: The argument vector, or `None` to read `sys.argv[1:]`.

    Returns:
        `0` when every tool is `ok` or intentionally `skipped`; `1` when any
        tool errored or a later tool was skipped because an earlier dependency
        was missing.
    """
    args = parse_args(argv)
    rows = asyncio.run(_run_async(args))
    print(format_table(rows))
    print(summary_line(rows))
    write_log(args.log_path, rows)
    return 1 if _run_has_failure(rows) else 0


if __name__ == "__main__":
    sys.exit(main())
