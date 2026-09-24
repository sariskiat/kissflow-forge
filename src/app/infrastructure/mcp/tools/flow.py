"""The flow-family tool module (fields, structure, workflow, lifecycle).

`register(mcp)` wires every flow-family tool onto the new, thin server (spec
G12). Each work group below is its own function, filled independently in
Stage D by the flow family writer. `ruff format` caps blank lines at two, so
the distance between groups below is a comment block, not blank padding --
either way, two writers filling different groups produce a diff-clean
merge, since neither one's edit region reaches the other's.

Every name a `_register_*` group's own `@mcp.tool` functions use in a
parameter or return annotation (never one used only inside a lambda/call
body) must be a MODULE-level import, not a local one: `from __future__
import annotations` (above) stores every annotation as a string, and
FastMCP/Pydantic resolve that string against the function's own
`__globals__` -- the module's namespace -- when it builds the tool's input
schema. A name a nested function's closure could see at call time is
invisible to that later, string-based resolution, so a local import inside
a `_register_*` function raises `NameError` the first time `create_server()`
runs, not at import time (verified against `_register_structure`'s own
tools, spec G12/Stage D). Each `_register_*` group therefore adds its own
imports here, sorted alongside the others.

Import each request/response DTO and use case from its own module, as the
other groups do. `tests/test_mcp_surface.py` skips `from`/`import` lines when
it scans this tree for tool citations, so a module path named after its tool
is not read as one.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastmcp import Context, FastMCP
from pydantic import Field

from app.application.models.requests.flow.forge_add_field_validation_request import (
    ForgeAddFieldValidationRequest,
)
from app.application.models.requests.flow.forge_add_goto_gate_request import (
    ForgeAddGotoGateRequest,
)
from app.application.models.requests.flow.forge_add_sequence_number_request import (
    ForgeAddSequenceNumberRequest,
)
from app.application.models.requests.flow.forge_add_table_request import (
    ForgeAddTableRequest,
)
from app.application.models.requests.flow.forge_apply_fields_request import (
    ForgeApplyFieldsRequest,
)
from app.application.models.requests.flow.forge_apply_layout_request import (
    ForgeApplyLayoutRequest,
)
from app.application.models.requests.flow.forge_build_workflow_request import (
    ForgeBuildWorkflowRequest,
)
from app.application.models.requests.flow.forge_create_flow_request import (
    ForgeCreateFlowRequest,
)
from app.application.models.requests.flow.forge_create_list_request import (
    ForgeCreateListRequest,
)
from app.application.models.requests.flow.forge_create_process_request import (
    ForgeCreateProcessRequest,
)
from app.application.models.requests.flow.forge_delete_fields_request import (
    ForgeDeleteFieldsRequest,
)
from app.application.models.requests.flow.forge_delete_flow_request import (
    ForgeDeleteFlowRequest,
)
from app.application.models.requests.flow.forge_doctor_request import (
    ForgeDoctorRequest,
)
from app.application.models.requests.flow.forge_publish_request import (
    ForgePublishRequest,
)
from app.application.models.requests.flow.forge_rename_fields_request import (
    ForgeRenameFieldsRequest,
)
from app.application.models.requests.flow.forge_set_branch_conditions_request import (
    ForgeSetBranchConditionsRequest,
)
from app.application.models.requests.flow.forge_set_events_request import (
    ForgeSetEventsRequest,
)
from app.application.models.requests.flow.forge_set_required_request import (
    ForgeSetRequiredRequest,
)
from app.application.models.requests.flow.forge_set_styles_request import (
    ForgeSetStylesRequest,
)
from app.application.models.requests.flow.forge_set_visibility_request import (
    ForgeSetVisibilityRequest,
)
from app.application.models.requests.flow.kf_apply_field_change_request import (
    KfApplyFieldChangeRequest,
)
from app.application.models.requests.flow.kf_create_process_request import (
    KfCreateProcessRequest,
)
from app.application.models.requests.flow.kf_get_flow_schema_request import (
    KfGetFlowSchemaRequest,
)
from app.application.models.requests.flow.kf_publish_request import KfPublishRequest
from app.application.models.requests.flow.kf_set_step_visibility_request import (
    KfSetStepVisibilityRequest,
)
from app.application.models.responses.flow.forge_add_field_validation_response import (
    ForgeAddFieldValidationResponse,
)
from app.application.models.responses.flow.forge_add_goto_gate_response import (
    ForgeAddGotoGateResponse,
)
from app.application.models.responses.flow.forge_add_sequence_number_response import (
    ForgeAddSequenceNumberResponse,
)
from app.application.models.responses.flow.forge_add_table_response import (
    ForgeAddTableResponse,
)
from app.application.models.responses.flow.forge_apply_fields_response import (
    ForgeApplyFieldsResponse,
)
from app.application.models.responses.flow.forge_apply_layout_response import (
    ForgeApplyLayoutResponse,
)
from app.application.models.responses.flow.forge_build_workflow_response import (
    ForgeBuildWorkflowResponse,
)
from app.application.models.responses.flow.forge_create_flow_response import (
    ForgeCreateFlowResponse,
)
from app.application.models.responses.flow.forge_create_list_response import (
    ForgeCreateListResponse,
)
from app.application.models.responses.flow.forge_create_process_response import (
    ForgeCreateProcessResponse,
)
from app.application.models.responses.flow.forge_delete_fields_response import (
    ForgeDeleteFieldsResponse,
)
from app.application.models.responses.flow.forge_delete_flow_response import (
    ForgeDeleteFlowResponse,
)
from app.application.models.responses.flow.forge_doctor_response import (
    ForgeDoctorResponse,
)
from app.application.models.responses.flow.forge_publish_response import (
    ForgePublishResponse,
)
from app.application.models.responses.flow.forge_rename_fields_response import (
    ForgeRenameFieldsResponse,
)
from app.application.models.responses.flow.forge_set_branch_conditions_response import (
    ForgeSetBranchConditionsResponse,
)
from app.application.models.responses.flow.forge_set_events_response import (
    ForgeSetEventsResponse,
)
from app.application.models.responses.flow.forge_set_required_response import (
    ForgeSetRequiredResponse,
)
from app.application.models.responses.flow.forge_set_styles_response import (
    ForgeSetStylesResponse,
)
from app.application.models.responses.flow.forge_set_visibility_response import (
    ForgeSetVisibilityResponse,
)
from app.application.models.responses.flow.kf_apply_field_change_response import (
    KfApplyFieldChangeResponse,
)
from app.application.models.responses.flow.kf_create_process_response import (
    KfCreateProcessResponse,
)
from app.application.models.responses.flow.kf_get_flow_schema_response import (
    KfGetFlowSchemaResponse,
)
from app.application.models.responses.flow.kf_publish_response import (
    KfPublishResponse,
)
from app.application.models.responses.flow.kf_set_step_visibility_response import (
    KfSetStepVisibilityResponse,
)
from app.application.use_cases.flow.forge_add_field_validation import (
    ForgeAddFieldValidation,
)
from app.application.use_cases.flow.forge_add_goto_gate import ForgeAddGotoGate
from app.application.use_cases.flow.forge_add_sequence_number import (
    ForgeAddSequenceNumber,
)
from app.application.use_cases.flow.forge_add_table import ForgeAddTable
from app.application.use_cases.flow.forge_apply_fields import ForgeApplyFields
from app.application.use_cases.flow.forge_apply_layout import ForgeApplyLayout
from app.application.use_cases.flow.forge_build_workflow import ForgeBuildWorkflow
from app.application.use_cases.flow.forge_create_flow import ForgeCreateFlow
from app.application.use_cases.flow.forge_create_list import ForgeCreateList
from app.application.use_cases.flow.forge_create_process import ForgeCreateProcess
from app.application.use_cases.flow.forge_delete_fields import ForgeDeleteFields
from app.application.use_cases.flow.forge_delete_flow import ForgeDeleteFlow
from app.application.use_cases.flow.forge_doctor import ForgeDoctor
from app.application.use_cases.flow.forge_publish import ForgePublish
from app.application.use_cases.flow.forge_rename_fields import ForgeRenameFields
from app.application.use_cases.flow.forge_set_branch_conditions import (
    ForgeSetBranchConditions,
)
from app.application.use_cases.flow.forge_set_events import ForgeSetEvents
from app.application.use_cases.flow.forge_set_required import ForgeSetRequired
from app.application.use_cases.flow.forge_set_styles import ForgeSetStyles
from app.application.use_cases.flow.forge_set_visibility import ForgeSetVisibility
from app.application.use_cases.flow.kf_apply_field_change import KfApplyFieldChange
from app.application.use_cases.flow.kf_create_process import KfCreateProcess
from app.application.use_cases.flow.kf_get_flow_schema import KfGetFlowSchema
from app.application.use_cases.flow.kf_publish import KfPublish
from app.application.use_cases.flow.kf_set_step_visibility import KfSetStepVisibility
from app.domain.value_objects.kinds import (
    CreateFlowKind,
    DataKind,
    DeleteKind,
    FlowKind,
    FlowKindArg,
    PublishKind,
    SchemaKind,
)
from app.infrastructure.mcp.tools import _shared
from app.infrastructure.mcp.tools._shared import (
    LIVE_ADD_ONCE,
    LIVE_REPLACE,
    run_use_case,
)


def register(mcp: FastMCP) -> None:
    """Register every flow-family tool.

    Args:
        mcp: The server `create_server()` is building.
    """
    _register_fields(mcp)
    _register_structure(mcp)
    _register_workflow(mcp)
    _register_lifecycle(mcp)


def _register_fields(mcp: FastMCP) -> None:
    """Field tools: apply a field change, add fields and sections, re-place fields on
    the grid, delete fields and tables, rename fields, set required fields
    (`kf_apply_field_change`, `forge_apply_fields`, `forge_apply_layout`,
    `forge_delete_fields`, `forge_rename_fields`, `forge_set_required`). Filled by
    Stage D group 1."""

    @mcp.tool(title="Add fields to a flow", annotations=_shared.LIVE_ADD)
    async def kf_apply_field_change(
        flow_kind: DataKind,
        flow_id: str,
        changes: list[dict[str, Any]],
        publish: bool = False,
        app_id: str | None = None,
        *,
        ctx: Context,
    ) -> KfApplyFieldChangeResponse:
        """LIVE write (dev only): add fields to a flow, verify by read-back, optionally publish.

        Idempotent — a field whose name already exists is skipped, never duplicated. Aborts with a
        conflict if the draft changed since it was read. Show kf_plan_field_change to a human first.

        `flow_kind="dataset"` (a dataform) is supported — field writes produce the identical node
        shapes as form/process and this engine's `apply_fields` is live-proven unmodified on that kind
        (docs/capabilities/module.dataform.md, #50). Leave `publish` False for it: a dataform's draft
        IS live and its publish route 404s.
        """  # noqa: E501
        return await _shared.run_use_case(
            ctx,
            build_request=lambda: KfApplyFieldChangeRequest(
                flow_kind=flow_kind,
                flow_id=flow_id,
                changes=changes,
                publish=publish,
                app_id=ctx.lifespan_context["settings"].resolve_app_id(app_id),
            ),
            build_use_case=lambda resources: KfApplyFieldChange(resources.flow),
        )

    @mcp.tool(title="Add fields and sections", annotations=_shared.LIVE_REPLACE)
    async def forge_apply_fields(
        flow_id: str,
        fields: list[dict[str, Any]],
        sections: dict[str, list[str]] | None = None,
        validation: dict[str, list[dict[str, str]]] | None = None,
        computed: dict[str, dict[str, Any]] | None = None,
        conditional_visibility: dict[str, dict[str, str]] | None = None,
        kind: DataKind = "process",
        publish: bool = False,
        app_id: str | None = None,
        *,
        ctx: Context,
    ) -> ForgeApplyFieldsResponse:
        """LIVE write (dev only, KF_APP): add fields to a flow AND lay them out into named sections
        AND (optionally) attach validation/computed/conditional-visibility, in ONE guarded write — the
        build-doctrine "offer the whole field", not bolted on afterward. `sections` maps a section
        title to the field names it should hold — a PARTIAL statement, not the whole layout: a field
        already in an EXISTING section that you don't name here keeps its current section, so adding
        one new field to one existing section never dumps every other field into a trailing "Other"
        section. Only a field in no current section and named in no group falls to "Other" — nothing
        is ever dropped from the layout. Only the sections named in `sections` change: every other
        section keeps its exact layout (grids, help text, hidden flag), and a field already in its
        named section stays where it is. Idempotent on the fields (a name that already exists is
        skipped, never duplicated).

        Each field dict in `fields` also accepts an optional `default_value` (folds into the Field's
        own `DefaultValue` key — a static literal, or the platform's relative-date keyword `"Today"`
        on a Date field — never guess the casing, read it).

        A `"type": "Select"` field REQUIRES `referred_list` — the id of the list flow its options
        live in (make it first with forge_create_list, then pass its id here). A Select with no list
        is a dropdown bound to nothing: it writes 200 and publish then dies 500 MetadataError with no
        diagnostics at all, so it is refused here instead, before any write.

        `validation` maps a field NAME to `[{"operator": "MAX_LENGTH", "rhs": "10",
        "error_message": "optional human text"}, ...]` (docs/capabilities/config.validation.md — wire-
        proven operators: MAX_LENGTH, CONTAINS, GREATER_THAN, AFTER; everything else is Q&A-claimed
        only, verify live before trusting it). `computed` maps a field NAME to a formula AST
        `{"fn": "concatenate", "args": [{"static": "BR-"}, {"field": "Source Number"}]}`
        (docs/capabilities/config.computed.md — the FOURTH Expression owner, Field itself; runtime
        evaluation is UNVERIFIED, graph landing only). `conditional_visibility` maps a field NAME to
        `{"trigger_field": <other field name>, "operator": "EQUAL_TO", "rhs": "true"}`
        (docs/capabilities/config.conditional-visibility.md — the ColumnVisibility Criteria family;
        runtime toggle behavior is graph-verified only, not walked live). Every layer is independently
        read-back verified; a `missing` in any of them marks the whole result `isError`.

        DESTRUCTIVE on the LAYOUT whenever `sections` is given: the regroup REBUILDS every section's
        rows at a uniform width, so a custom grid an earlier forge_apply_layout wrote does not survive
        one call here. Every pre-existing field that actually moved is named in `collateral` with its
        old and new coordinates, and `remediation` names forge_apply_layout — that is what the
        destructive annotation on this tool is about.

        `kind="dataset"` (a dataform) is supported: field writes produce the identical node shapes as
        form/process and this engine's own apply_fields is live-proven unmodified on that kind
        (docs/capabilities/module.dataform.md, #50). Leave `publish` False for it — a dataform's draft
        IS live and its publish route 404s. A word `list` is not a field-bearing flow and is not
        accepted here at all.
        """  # noqa: E501
        return await _shared.run_use_case(
            ctx,
            build_request=lambda: ForgeApplyFieldsRequest(
                flow_id=flow_id,
                fields=fields,
                sections=sections,
                validation=validation,
                computed=computed,
                conditional_visibility=conditional_visibility,
                kind=kind,
                publish=publish,
                app_id=ctx.lifespan_context["settings"].resolve_app_id(app_id),
            ),
            build_use_case=lambda resources: ForgeApplyFields(resources.flow),
        )

    @mcp.tool(title="Re-place fields on the grid", annotations=_shared.LIVE_REPLACE)
    async def forge_apply_layout(
        flow_id: str,
        layout: dict[str, list[list[list[Any]]]],
        descriptions: dict[str, str] | None = None,
        kind: FlowKindArg = "process",
        publish: bool = False,
        app_id: str | None = None,
        *,
        ctx: Context,
    ) -> ForgeApplyLayoutResponse:
        """LIVE write (dev only, KF_APP): re-place every field at EXACT grid coordinates.

        `layout` is `{section_name: [[(field_name, Start, End), ...], ...]}` — one inner list per Row,
        top-to-bottom; each tuple puts one field column at those 6-unit-grid coordinates. The engine
        rebuilds only Row nodes (Field/Column ids and their Permission/Event back-refs survive). A
        field or section named in `layout` but absent from the draft is a hard error, so a stale layout
        never silently drops a field. Call after forge_apply_fields whenever the auto-tile (3-per-row)
        is not the desired layout. Always writes (a re-layout is a real change even with no new fields).

        `descriptions` optionally sets each section's `Description` (plain string OR a serialized
        rich-text doc) in the SAME write — apply it together with the layout, not as a separate call.
        """  # noqa: E501
        return await _shared.run_use_case(
            ctx,
            build_request=lambda: ForgeApplyLayoutRequest(
                flow_id=flow_id,
                layout=layout,
                descriptions=descriptions,
                kind=kind,
                publish=publish,
                app_id=ctx.lifespan_context["settings"].resolve_app_id(app_id),
            ),
            build_use_case=lambda resources: ForgeApplyLayout(resources.flow),
        )

    @mcp.tool(title="Delete fields and tables", annotations=_shared.LIVE_REPLACE_ONCE)
    async def forge_delete_fields(
        flow_id: str,
        fields: list[str] | None = None,
        tables: list[str] | None = None,
        kind: FlowKindArg = "process",
        publish: bool = False,
        app_id: str | None = None,
        *,
        ctx: Context,
    ) -> ForgeDeleteFieldsResponse:
        """LIVE write (dev only, KF_APP): DELETE form fields and/or child tables by NAME, with the
        whole cluster swept — the field's Column, its per-step Permissions, its Events, its query
        definition, its computed formula, its validation and conditional-visibility rules.

        Read-back verified the INVERTED way: success is the name being ABSENT afterwards, so the
        audit buckets are `deleted` and `surviving` (a name still present after the write is the loud
        failure). Refuses BEFORE any write when something that SURVIVES still points at what is going
        — another field's formula, a branch condition, a conditional-visibility trigger, an event
        script naming the id — because a dangling scalar reference publishes 500 with zero
        diagnostics; the refusal names the reference and the tool that clears it. Refuses the whole
        batch if any one name is unknown, so a typo deletes nothing.

        Pass a raw node id instead of a name to disambiguate: names are NOT unique across a form and
        its child tables, and every field carrying the name is deleted otherwise.
        """  # noqa: E501
        return await _shared.run_use_case(
            ctx,
            build_request=lambda: ForgeDeleteFieldsRequest(
                flow_id=flow_id,
                fields=fields,
                tables=tables,
                kind=kind,
                publish=publish,
                app_id=ctx.lifespan_context["settings"].resolve_app_id(app_id),
            ),
            build_use_case=lambda resources: ForgeDeleteFields(resources.flow),
        )

    @mcp.tool(title="Rename fields", annotations=_shared.LIVE_REPLACE_ONCE)
    async def forge_rename_fields(
        flow_id: str,
        renames: dict[str, str],
        kind: FlowKindArg = "process",
        publish: bool = False,
        app_id: str | None = None,
        *,
        ctx: Context,
    ) -> ForgeRenameFieldsResponse:
        """LIVE write (dev only, KF_APP): RENAME form fields, `{current name: new name}`.

        The cheap, safe fix for a wrong field name: the node id never changes, so per-step
        Permissions, `Field::Event` and any already-submitted data stay attached — a delete-and-
        recreate silently orphans all three. Only ROOT-model fields are renamed; a child-table column
        keeps its name. Read-back verifies BOTH halves of each rename (the new name present AND the
        old one gone), so a half-applied rename can never read as success. An unknown or ambiguous
        name, or a new name that already exists on the form, is refused before any write.
        """  # noqa: E501
        return await _shared.run_use_case(
            ctx,
            build_request=lambda: ForgeRenameFieldsRequest(
                flow_id=flow_id,
                renames=renames,
                kind=kind,
                publish=publish,
                app_id=ctx.lifespan_context["settings"].resolve_app_id(app_id),
            ),
            build_use_case=lambda resources: ForgeRenameFields(resources.flow),
        )

    @mcp.tool(title="Set required fields", annotations=_shared.LIVE_REPLACE)
    async def forge_set_required(
        flow_id: str,
        required: list[str],
        kind: FlowKindArg = "process",
        publish: bool = False,
        app_id: str | None = None,
        *,
        ctx: Context,
    ) -> ForgeSetRequiredResponse:
        """LIVE write (dev only, KF_APP): set which ROOT-model fields are Required.

        SET semantics, not a patch — every root field NOT listed comes back optional, so pass the
        WHOLE required set, not just the additions. The fields that lose the flag are reported in
        `cleared` rather than changing silently. Read-back verifies the flag on every root field, not
        only the named ones.

        Refuses before any write to mark a computed or SequenceNumber field Required: nobody can type
        that value, so the step becomes permanently unsubmittable and nothing downstream can move
        either (CLAUDE.md Visibility). Unknown names are refused too, so a typo cannot silently leave
        a field un-required.
        """  # noqa: E501
        return await _shared.run_use_case(
            ctx,
            build_request=lambda: ForgeSetRequiredRequest(
                flow_id=flow_id,
                required=required,
                kind=kind,
                publish=publish,
                app_id=ctx.lifespan_context["settings"].resolve_app_id(app_id),
            ),
            build_use_case=lambda resources: ForgeSetRequired(resources.flow),
        )


# ============================================================================
# _register_fields ends above this block; _register_structure starts below it.
# This block is spacing, not documentation: it exists only so that a writer
# filling _register_fields and a writer filling _register_structure touch
# lines far enough apart that git merges their two changes without a
# conflict. Do not delete it to "clean up" the file -- shrinking it defeats
# its one purpose. Twenty-plus lines, deliberately, matching every other
# group boundary in this file and its eight siblings under
# infrastructure/mcp/tools/.
#
# kissflow-forge builds Kissflow apps through the undocumented internal
# /flow + /metadata builder API. Every write here is read-verify-write with
# a post-write read-back audit (see CLAUDE.md > Write path). An HTTP 200 and
# a clean publish prove nothing about whether the flow actually works (see
# CLAUDE.md > THE RULE) -- the only reliable oracle is a UI-built artifact
# to diff against. Run forge_doctor after every edit that lands here.
# ============================================================================


def _resolved_app_id(app_id: str | None, ctx: Context) -> str:
    """Resolve the app id one structure-tool call targets.

    Args:
        app_id: The tool's own `app_id` parameter, or `None`.
        ctx: The tool's `Context`, carrying `ctx.lifespan_context["settings"]`.

    Returns:
        `Settings.resolve_app_id(app_id)`: `app_id`, else the single-app
        default, else `""` -- an empty app id is a use-case-level refusal
        (`code=REFUSED`), not a tool-level one.
    """
    settings = ctx.lifespan_context["settings"]
    return settings.resolve_app_id(app_id)


def _register_structure(mcp: FastMCP) -> None:
    """Structure tools: add a child table, add a sequence number field, add field
    validation, set section styles, set field events (`forge_add_table`,
    `forge_add_sequence_number`, `forge_add_field_validation`, `forge_set_styles`,
    `forge_set_events`). Filled by Stage D group 2."""

    @mcp.tool(title="Add child table", annotations=_shared.LIVE_ADD)
    async def forge_add_table(
        flow_id: str,
        name: str,
        columns: list[list[Any]],
        max_rows: int | None = None,
        allow_import: bool = False,
        kind: FlowKind = "process",
        publish: bool = False,
        after_section: str | None = None,
        app_id: str | None = None,
        *,
        ctx: Context,
    ) -> ForgeAddTableResponse:
        """LIVE write (dev only, KF_APP): add a child table (a nested Model hosted by a Column, per
        CLAUDE.md "A TABLE is a nested Model, not a field type"). `columns` is `[[name, type], ...]` or
        `[[name, type, options], ...]` where `options` is an opt-in per-column dict written verbatim onto
        the Field node (e.g. `{"Decimalpoint": 0}` for an integer-only Number). `max_rows` writes
        Kissflow's NATIVE row cap (no client-side enforcement needed). Idempotent — a table already named
        `name` is a no-op (no second PUT). `after_section` places the host row directly after that
        Section's root row — REQUIRED when the table has a banner section, or the stranded banner breaks
        the whole form's render (CLAUDE.md > Tables).

        A `"Select"` column REQUIRES the list its options live in, exactly as a root field does in
        forge_apply_fields — name it in that column's own options dict, `[<column name>, "Select",
        {"ReferredList": "<list id>"}]`, after making the list with forge_create_list. A Select with no
        list is a dropdown bound to nothing: it writes 200 and publish then dies 500 MetadataError with
        no diagnostics at all, so it is refused here instead, before any write.
        """  # noqa: E501
        return await _shared.run_use_case(
            ctx,
            build_request=lambda: ForgeAddTableRequest(
                flow_id=flow_id,
                name=name,
                columns=columns,
                max_rows=max_rows,
                allow_import=allow_import,
                kind=kind,
                publish=publish,
                after_section=after_section,
                app_id=_resolved_app_id(app_id, ctx),
            ),
            build_use_case=lambda resources: ForgeAddTable(flow=resources.flow),
        )

    @mcp.tool(title="Add sequence number field", annotations=_shared.LIVE_ADD)
    async def forge_add_sequence_number(
        flow_id: str,
        field_name: str,
        section_name: str,
        prefix: str,
        padding: str,
        step_activity_name: str,
        start: int = 0,
        end: int = 2,
        kind: FlowKind = "process",
        publish: bool = False,
        app_id: str | None = None,
        *,
        ctx: Context,
    ) -> ForgeAddSequenceNumberResponse:
        """LIVE write (dev only, KF_APP): add an auto-numbered item-id field (`Type:"SequenceNumber"`)
        in its own hidden row at the end of `section_name` (CLAUDE.md "SequenceNumber = auto-numbered
        item id"). The host column is `IsHidden:true` and carries NO per-step Permissions. The
        `prefix` (e.g. "REQ-") is the literal concatenated onto every stamped number; `padding`
        (e.g. "0001") zero-pads it; `step_activity_name` (e.g. "Start") is the activity NAME where the
        runtime stamps the sequence — resolved by name since rebuild activity ids differ from any
        oracle's. `start`/`end` are the 6-unit grid coords of the hidden column. Idempotent. Call this
        AFTER forge_apply_layout so the section's rows are already placed.
        """  # noqa: E501
        return await _shared.run_use_case(
            ctx,
            build_request=lambda: ForgeAddSequenceNumberRequest(
                flow_id=flow_id,
                field_name=field_name,
                section_name=section_name,
                prefix=prefix,
                padding=padding,
                step_activity_name=step_activity_name,
                start=start,
                end=end,
                kind=kind,
                publish=publish,
                app_id=_resolved_app_id(app_id, ctx),
            ),
            build_use_case=lambda resources: ForgeAddSequenceNumber(
                flow=resources.flow
            ),
        )

    @mcp.tool(title="Add field validation", annotations=_shared.LIVE_ADD)
    async def forge_add_field_validation(
        flow_id: str,
        rules: dict[str, list[list[str]]],
        kind: FlowKind = "process",
        publish: bool = False,
        app_id: str | None = None,
        *,
        ctx: Context,
    ) -> ForgeAddFieldValidationResponse:
        """LIVE write (dev only, KF_APP): attach per-field validation rules. `rules` is
        `{field_name: [[operator, value], ...]}`, e.g. `{"meeting link": [["CONTAINS", "microsoft"]]}`.
        Each rule is a flat Condition (Operator + literal RHSValue) under the field's one Criteria node
        (CLAUDE.md F7 — no formula/Expression AST, just a Condition per rule). Idempotent on
        (field, operator, value); a second rule on the same field appends to the existing Criteria.
        """  # noqa: E501
        return await _shared.run_use_case(
            ctx,
            build_request=lambda: ForgeAddFieldValidationRequest(
                flow_id=flow_id,
                rules=rules,
                kind=kind,
                publish=publish,
                app_id=_resolved_app_id(app_id, ctx),
            ),
            build_use_case=lambda resources: ForgeAddFieldValidation(
                flow=resources.flow
            ),
        )

    @mcp.tool(title="Set section styles", annotations=_shared.LIVE_REPLACE)
    async def forge_set_styles(
        flow_id: str,
        styles: dict[str, dict[str, Any]],
        kind: FlowKind = "process",
        publish: bool = False,
        root_style: dict[str, Any] | None = None,
        hint_text_position: str | None = None,
        app_id: str | None = None,
        *,
        ctx: Context,
    ) -> ForgeSetStylesResponse:
        """LIVE write (dev only, KF_APP): colour sections AND (optionally) the root Model's own
        Appearance/Style chain (#11). `styles` maps a section NAME to {property: value}; a value is
        a bare design-token string (wrapped as {"ref": token}), an explicit {"ref": ...} or
        {"value": ...} dict written verbatim, or null (property removed — back to the theme
        default). `root_style` takes the same shape for the ROOT chain; `hint_text_position` sets
        HintTextPosition on the root Appearance (oracle: "Icon"). On a FORM colours are TOKEN REFS,
        never hex — CLAUDE.md warns tokens are UNVALIDATED by the API and fail silently at render if
        wrong, so only pass one read off the live oracle (Color.Info.300, Color.Secondary.Ten.800,
        Color.Primary.500, Color.Transparent) or the builder's own dropdown.
        """  # noqa: E501
        return await _shared.run_use_case(
            ctx,
            build_request=lambda: ForgeSetStylesRequest(
                flow_id=flow_id,
                styles=styles,
                kind=kind,
                publish=publish,
                root_style=root_style,
                hint_text_position=hint_text_position,
                app_id=_resolved_app_id(app_id, ctx),
            ),
            build_use_case=lambda resources: ForgeSetStyles(flow=resources.flow),
        )

    @mcp.tool(title="Set field events", annotations=_shared.LIVE_REPLACE)
    async def forge_set_events(
        flow_id: str,
        events: dict[str, list[list[str | None]]],
        kind: FlowKind = "process",
        publish: bool = False,
        app_id: str | None = None,
        *,
        ctx: Context,
    ) -> ForgeSetEventsResponse:
        """LIVE write (dev only, KF_APP): attach SDK field events (the script-based computation
        mechanism — see CLAUDE.md Field events). `events` maps a field NAME to
        `[[trigger, script], ...]`.

        **Pass `null` for the trigger and it is DERIVED from the source field's live type**, which is
        the recommended call: the trigger is a FUNCTION of that type (Select fires `onClick`, Date and
        Number fire `onSelect`, Text/Textarea fire `onChange`), and a hand-picked wrong one writes
        fine, publishes fine, and simply never fires — invisible to every later check. A stated
        trigger that disagrees with the derived one is REFUSED, naming both; so is an event on any of
        the FIVE types this engine refuses outright — Attachment, Image, Signature, SequenceNumber,
        Geolocation (`app.domain.value_objects.field_type.NO_EVENT_FIELD_TYPES`, which this
        refusal reads directly). CLAUDE.md
        names a SIXTH event-less type on the PLATFORM, Rich text, and this engine deliberately does NOT
        refuse it: its wire shape is uncaptured and its inferred shape is Textarea + AllowFormatting —
        indistinguishable from a plain Textarea, which legitimately fires onChange — so refusing on
        that guess would block a real capability (doctrine: never invent a rule for an uncaptured
        shape). The result's `unverified` bucket names any trigger whose (type -> trigger) pair is
        family-inferred rather than live-confirmed.

        The editor's own two parse rules are enforced offline before any write: no top-level `await`
        (wrap in `(async () => {...})();`), and no `KFSDK` reference (only `kf` is injected).
        """  # noqa: E501
        return await _shared.run_use_case(
            ctx,
            build_request=lambda: ForgeSetEventsRequest(
                flow_id=flow_id,
                events=events,
                kind=kind,
                publish=publish,
                app_id=_resolved_app_id(app_id, ctx),
            ),
            build_use_case=lambda resources: ForgeSetEvents(flow=resources.flow),
        )


# ============================================================================
# _register_structure ends above this block; _register_workflow starts below
# it. This block is spacing, not documentation: it exists only so that a
# writer filling _register_structure and a writer filling _register_workflow
# touch lines far enough apart that git merges their two changes without a
# conflict. Do not delete it to "clean up" the file -- shrinking it defeats
# its one purpose. Twenty-plus lines, deliberately, matching every other
# group boundary in this file and its eight siblings under
# infrastructure/mcp/tools/.
#
# A Parallel gateway built in the workflow step is UNCONDITIONAL -- every
# branch always runs -- until its branch conditions attach (see CLAUDE.md >
# Conditional routing). A goto-task loop condition is gated on a Boolean,
# fail-closed (see CLAUDE.md > Gate polarity). A per-branch goto gate is
# placed last within its own branch, never cross-branch.
# ============================================================================


def _register_workflow(mcp: FastMCP) -> None:
    """Workflow and visibility tools: rebuild the workflow, add a loop-back gate, set
    branch conditions, rebuild step visibility (`forge_build_workflow`,
    `forge_add_goto_gate`, `forge_set_branch_conditions`, `forge_set_visibility`,
    `kf_set_step_visibility`). Filled by Stage D group 3."""

    @mcp.tool(title="Rebuild workflow", annotations=LIVE_REPLACE)
    async def forge_build_workflow(
        flow_id: str,
        steps: list[list[Any]],
        parallel: dict[str, Any] | None = None,
        parallel_after: int | None = None,
        roles: dict[str, str] | None = None,
        step_meta: dict[str, dict[str, Any]] | None = None,
        kind: FlowKindArg = "process",
        publish: bool = False,
        app_id: str | None = None,
        *,
        ctx: Context,
    ) -> ForgeBuildWorkflowResponse:
        """LIVE write (dev only, KF_APP): replace the WHOLE workflow — Start -> steps ->
        [optional Parallel branches] -> End. `steps` is `[[name, role_id_or_null], ...]`. `roles` maps
        a role id to its display name (used to label each step's Resource/assignee). `parallel`, when
        given, is `{"name": <parallel node name>, "branches": [[branch_name, [[step, role], ...]], ...]}`,
        inserted after `parallel_after` (0-indexed into `steps`).

        `step_meta` (opt-in) maps a step NAME to `{"suspended": bool, "description": str}` (either key
        optional). `suspended` writes `IsSuspended`+`SuspendedAt` — the step is SKIPPED at runtime, the
        slimming-without-stranding lever (CLAUDE.md "IsSuspended"). `description` is the step's prose.

        DESTRUCTIVE: every existing Activity/ProcessDef/Resource/Permission on the flow is replaced
        (CLAUDE.md "build_workflow DELETES every Permission"). Callers MUST re-run
        forge_set_visibility immediately after this.
        """  # noqa: E501
        settings = ctx.lifespan_context["settings"]
        resolved_app_id = settings.resolve_app_id(app_id)
        return await run_use_case(
            ctx,
            build_request=lambda: ForgeBuildWorkflowRequest(
                flow_id=flow_id,
                steps=steps,
                parallel=parallel,
                parallel_after=parallel_after,
                roles=roles,
                step_meta=step_meta,
                kind=kind,
                publish=publish,
                app_id=resolved_app_id,
            ),
            build_use_case=lambda resources: ForgeBuildWorkflow(resources.flow),
        )

    @mcp.tool(title="Add loop-back gate", annotations=LIVE_ADD_ONCE)
    async def forge_add_goto_gate(
        flow_id: str,
        target_activity_name: str,
        field_name: str,
        branch_name: str | None = None,
        kind: FlowKindArg = "process",
        publish: bool = False,
        app_id: str | None = None,
        *,
        ctx: Context,
    ) -> ForgeAddGotoGateResponse:
        """LIVE write (dev only, KF_APP): add a backward-jump GotoTask targeting the step named
        `target_activity_name`, gated on the Boolean field named `field_name` (condition
        `<field> = false()`). Gate polarity is enforced (CLAUDE.md Gate polarity): only a Boolean may
        gate a loop, never an optional Select — rejected offline, before any write, if `field_name`
        is not Type Boolean.

        `branch_name`, when given, scopes `target_activity_name` to ONE branch of the flow's single
        Parallel gateway (built via forge_build_workflow's `parallel`) and pins the new GotoTask
        inside that SAME branch's own chain, last within it — the per-branch loop shape a working
        conditional-routing app uses (CLAUDE.md Workflow: a GotoTask never crosses branches; a target
        resolved to a step outside the named branch is rejected offline, before any write). Required
        whenever `target_activity_name` is not unique across branches; omit it for a plain root-chain
        (or otherwise unambiguous) target — unchanged from before this parameter existed.
        """  # noqa: E501
        settings = ctx.lifespan_context["settings"]
        resolved_app_id = settings.resolve_app_id(app_id)
        return await run_use_case(
            ctx,
            build_request=lambda: ForgeAddGotoGateRequest(
                flow_id=flow_id,
                target_activity_name=target_activity_name,
                field_name=field_name,
                branch_name=branch_name,
                kind=kind,
                publish=publish,
                app_id=resolved_app_id,
            ),
            build_use_case=lambda resources: ForgeAddGotoGate(resources.flow),
        )

    @mcp.tool(title="Set branch conditions", annotations=LIVE_REPLACE)
    async def forge_set_branch_conditions(
        flow_id: str,
        field_name: str,
        branch_literals: dict[str, str],
        kind: FlowKindArg = "process",
        publish: bool = False,
        app_id: str | None = None,
        *,
        ctx: Context,
    ) -> ForgeSetBranchConditionsResponse:
        """LIVE write (dev only, KF_APP): make an existing Parallel's branches CONDITIONAL — each
        branch named in `branch_literals` fires only when the field named `field_name` equals that
        branch's literal (a ProcessDef-owned Expression, `<field> = "<literal>"` — CLAUDE.md
        Expressions). This is the centerpiece of service-tier/triage/approval-routing workflows: a
        forge_build_workflow `parallel` gateway is an UNCONDITIONAL and-fork on its own (every branch
        always runs) until this tool attaches the deciding condition to each one.

        Requires the flow to have exactly ONE Parallel gateway. Every literal is validated against the
        deciding field's REAL live list options — when it is a Select backed by a ReferredList — before
        any write (CLAUDE.md's own war story: a branch that never fired over one mis-cased literal). A
        Text-typed deciding field has no list to validate against and is written as given. Idempotent
        per branch: re-running with a changed literal REPLACES that branch's condition rather than
        accumulating a second one; a branch not named in `branch_literals` is left untouched.

        ⚠️ FAIL-OPEN HAZARD (CLAUDE.md > Conditional routing, verified live 2026-08-07): a value that
        matches NO branch's condition does not park and does not error — the item silently skips the
        WHOLE Parallel and completes with zero work done. The result's `uncovered` list names every
        real Select option (when the deciding field is one) that, after this write, no branch on the
        gateway claims — across the WHOLE gateway, not just the branches this call touched. `uncovered`
        is never an error on its own (a caller may genuinely want an ending value) — it is stated so it
        is never discovered later, exactly the failure mode Gate polarity already warns about for a
        loop, now for a switch.
        """  # noqa: E501
        settings = ctx.lifespan_context["settings"]
        resolved_app_id = settings.resolve_app_id(app_id)
        return await run_use_case(
            ctx,
            build_request=lambda: ForgeSetBranchConditionsRequest(
                flow_id=flow_id,
                field_name=field_name,
                branch_literals=branch_literals,
                kind=kind,
                publish=publish,
                app_id=resolved_app_id,
            ),
            build_use_case=lambda resources: ForgeSetBranchConditions(resources.flow),
        )

    @mcp.tool(
        title="Rebuild step visibility (sections + fields)", annotations=LIVE_REPLACE
    )
    async def forge_set_visibility(
        flow_id: str,
        owners: dict[str, list[str]],
        field_owners: dict[str, list[str]] | None = None,
        kind: FlowKindArg = "process",
        publish: bool = False,
        include_pairs: Annotated[
            bool,
            Field(
                description=(
                    "Return every (column, activity) permission pair in full, resolved "
                    "to field/section/step names, instead of the bounded counts + "
                    "by_section/by_step rollups. The default already lists every "
                    "`missing` pair in full and states how many entries it summarised."
                )
            ),
        ] = False,
        app_id: str | None = None,
        *,
        ctx: Context,
    ) -> ForgeSetVisibilityResponse:
        """LIVE write (dev only, KF_APP): rebuild a process's per-step visibility. `owners` maps a
        section NAME to the step names that own it — Editable there, Hidden before, ReadOnly after
        (section-level). DESTRUCTIVE: every existing Permission on the flow is replaced. Re-run this
        after ANY forge_build_workflow call — build_workflow wipes the whole matrix.

        `field_owners`, when given, is the FIELD-LEVEL lever some apps use instead of (or on top of)
        section-level owners: a section that only HIDES, with editability expressed per field. Maps a
        FIELD NAME to the step names where that one field is Editable; that field gets its own matrix
        row (Editable at the named steps, Hidden in sibling branches the field is not editable in,
        ReadOnly elsewhere) overriding its section's default. Fields not named keep their section's
        matrix. Branch-aware: a branch-private field stays Hidden across a whole sibling branch, not
        ReadOnly-after-last-editable — the case the section rule alone gets wrong.

        A section or step name in `owners` that is not on the live flow is refused before any write,
        naming the available set; so is a field name in `field_owners`.

        ⚠️ `uncovered_sections` names every section this matrix leaves editable at NO step — the
        same shape forge_set_branch_conditions' `uncovered` has, and never folded into `isError`
        (leaving a section alone can be deliberate). It exists because the DEFAULT
        forge_create_process(from_template=True) injects sections a caller did not ask for and cannot
        name in `owners`, so the matrix is incomplete from the first write and doctor only says
        "section 'System' is never editable at any live step" two steps later.

        RESULT SIZE: the audit is one (column, activity) PAIR per field per step and stays complete on
        every bucket, but the PAYLOAD states counts plus `by_section` / `by_step` rollups and every
        `missing` pair in full, all resolved to field/section/step NAMES. One live call over 37 columns
        x 6 activities used to echo all 222 opaque `Column_x@Activity_y` pairs TWICE (~15k tokens) to
        say "222 written, 0 missing". `summarised` always states how many entries the counts stand in
        for; `include_pairs=True` returns every one of them, named.
        """  # noqa: E501
        settings = ctx.lifespan_context["settings"]
        resolved_app_id = settings.resolve_app_id(app_id)
        return await run_use_case(
            ctx,
            build_request=lambda: ForgeSetVisibilityRequest(
                flow_id=flow_id,
                owners=owners,
                field_owners=field_owners,
                kind=kind,
                publish=publish,
                include_pairs=include_pairs,
                app_id=resolved_app_id,
            ),
            build_use_case=lambda resources: ForgeSetVisibility(resources.flow),
        )

    @mcp.tool(title="Rebuild step visibility (sections)", annotations=LIVE_REPLACE)
    async def kf_set_step_visibility(
        flow_id: str,
        owners: dict[str, list[str]],
        publish: bool = False,
        include_pairs: Annotated[
            bool,
            Field(
                description=(
                    "Return every (column, activity) permission pair in full, resolved "
                    "to field/section/step names, instead of the bounded counts + "
                    "by_section/by_step rollups. The default already lists every "
                    "`missing` pair in full and states how many entries it summarised."
                )
            ),
        ] = False,
        app_id: str | None = None,
        *,
        ctx: Context,
    ) -> KfSetStepVisibilityResponse:
        """LIVE write (dev only): rebuild a process's per-step section visibility.

        A section is Editable at the steps that own it, Hidden before them, ReadOnly after. Kissflow has
        no section-level permission, so this writes one Permission node per (field column x step).
        DESTRUCTIVE: every existing Permission on the flow is replaced. Snapshot the draft first.

        A section or step name in `owners` that is not on the live flow is refused before any write,
        naming the available set — a typo on a DESTRUCTIVE rebuild used to be dropped silently, which
        left that section editable at no step at all.

        The result states pair COUNTS plus per-section/per-step rollups and an `uncovered_sections`
        bucket, not the raw (column, activity) id list — same bounded presentation as
        forge_set_visibility, see its docstring. `include_pairs=True` returns every pair, named.
        """  # noqa: E501
        settings = ctx.lifespan_context["settings"]
        resolved_app_id = settings.resolve_app_id(app_id)
        return await run_use_case(
            ctx,
            build_request=lambda: KfSetStepVisibilityRequest(
                flow_id=flow_id,
                owners=owners,
                publish=publish,
                include_pairs=include_pairs,
                app_id=resolved_app_id,
            ),
            build_use_case=lambda resources: KfSetStepVisibility(resources.flow),
        )


# ============================================================================
# _register_workflow ends above this block; _register_lifecycle starts below
# it. This block is spacing, not documentation: it exists only so that a
# writer filling _register_workflow and a writer filling _register_lifecycle
# touch lines far enough apart that git merges their two changes without a
# conflict. Do not delete it to "clean up" the file -- shrinking it defeats
# its one purpose. Twenty-plus lines, deliberately, matching every other
# group boundary in this file and its eight siblings under
# infrastructure/mcp/tools/.
#
# Members exist before anything else gets built on top, or every later
# publish involving assignees fails (see CLAUDE.md > Members first). A
# rebuild of the workflow silently deletes every Permission -- the
# visibility matrix step runs again after one (see CLAUDE.md > Visibility).
# ============================================================================


def _register_lifecycle(mcp: FastMCP) -> None:
    """Lifecycle tools: kf_get_flow_schema, kf_create_process, kf_publish,
    forge_create_process, forge_create_list, forge_publish, forge_doctor,
    forge_delete_flow, forge_create_flow. Filled by the flow family writer
    (Stage D)."""

    @mcp.tool(title="Read flow draft", annotations=_shared.LIVE_READ)
    async def kf_get_flow_schema(
        flow_kind: SchemaKind,
        flow_id: str,
        app_id: str | None = None,
        *,
        ctx: Context,
    ) -> KfGetFlowSchemaResponse:
        """Read a flow's DRAFT graph from the dev tenant. Read-only. `flow_kind` is
        "process"/"form"/"case"/"dataset" (a flow — `flow_id` is the flow id) or "page" (needs
        `app_id`, `flow_id` is the page id — a page draft lives under its owning application, never a
        hard-coded KF_APP default; see CLAUDE.md Pages). `app_id` is ignored for every other kind.

        "dataset" (a dataform) reads the same `/metadata/2/{acct}/dataset/{id}/draft` route the record
        tools already use — its draft IS its live version, there is no publish split
        (docs/capabilities/module.dataform.md). A word `list` has no draft graph at all and is not
        readable here; use forge_sweep(scope="lists") for the inventory.
        """  # noqa: E501
        return await _shared.run_use_case(
            ctx,
            build_request=lambda: KfGetFlowSchemaRequest(
                flow_kind=flow_kind,
                flow_id=flow_id,
                app_id=ctx.lifespan_context["settings"].resolve_app_id(app_id),
                app_id_given=bool(app_id),
            ),
            build_use_case=lambda resources: KfGetFlowSchema(
                resources.flow, resources.page
            ),
        )

    @mcp.tool(title="Create process with fields", annotations=_shared.LIVE_ADD_ONCE)
    async def kf_create_process(
        name: str,
        steps: list[str],
        fields: list[dict[str, Any]],
        publish: bool = False,
        from_template: bool = True,
        app_id: str | None = None,
        *,
        ctx: Context,
    ) -> KfCreateProcessResponse:
        """LIVE (dev only): create a NEW process from zero — workflow steps + fields — and verify it.

        `from_template=True` (default, issue #59) scaffolds by cloning the process-template identity
        shell (shapes/process_template_identity_shell.json) instead of a bare `steps`-driven scaffold —
        `steps` is then ignored; rebuild the real workflow with forge_build_workflow afterward. Pass
        `from_template=False` for the old behavior: Start, one UserTask per `steps` entry, Completed.
        A failed run cleans up after itself and leaves no half-built process behind.

        ⚠️ The report's `template_sections` / `template_required_fields` / `template_steps` name
        everything the shell brought in that you did not ask for — see forge_create_process's own
        description for why that matters before the first forge_set_visibility call.
        """  # noqa: E501
        settings = ctx.lifespan_context["settings"]
        return await _shared.run_use_case(
            ctx,
            build_request=lambda: KfCreateProcessRequest(
                name=name,
                steps=steps,
                fields=fields,
                publish=publish,
                from_template=from_template,
                app_id=settings.resolve_app_id(app_id),
            ),
            build_use_case=lambda resources: KfCreateProcess(
                resources.flow, settings.resolve_process_template_path()
            ),
        )

    @mcp.tool(title="Publish flow", annotations=_shared.LIVE_ADD)
    async def kf_publish(
        flow_kind: FlowKindArg,
        flow_id: str,
        app_id: str | None = None,
        *,
        ctx: Context,
    ) -> KfPublishResponse:
        """LIVE publish (dev only): compile the flow's draft graph to its live version."""  # noqa: E501
        return await _shared.run_use_case(
            ctx,
            build_request=lambda: KfPublishRequest(
                flow_kind=flow_kind,
                flow_id=flow_id,
                app_id=ctx.lifespan_context["settings"].resolve_app_id(app_id),
            ),
            build_use_case=lambda resources: KfPublish(resources.flow),
        )

    @mcp.tool(title="Create process shell", annotations=_shared.LIVE_ADD_ONCE)
    async def forge_create_process(
        name: str,
        publish: bool = False,
        from_template: bool = True,
        app_id: str | None = None,
        *,
        ctx: Context,
    ) -> ForgeCreateProcessResponse:
        """LIVE (dev only): create a new PROCESS shell — a scaffolded, publishable draft.

        `app_id` picks which application to build in (defaults to the session app / KF_APP env).
        `from_template=True` (default, issue #59 — "every process starts from a structure-clone")
        builds the FULL production process template (shapes/process_template_full.json, built by
        scripts/deidentify_template.py): every field with its real field id, the formulas, validations,
        conditional visibility and lookups, the layout, and the "Manager Approve" workflow. Its
        approver is the AppRole "<name> Role" in `app_id` (reused if it exists, else created), granted
        as a flow member first; add users to it (forge_add_role_users) before anyone can submit. A
        configured KF_PROCESS_TEMPLATE shell is cloned instead.
        forge_build_workflow replaces the workflow wholesale once the real one is designed. Pass
        `from_template=False` for the old bare single-placeholder-step scaffold. Follow with
        forge_apply_fields, forge_add_table, forge_build_workflow, etc. A failed run cleans up after
        itself (create_process archives+deletes the half-built process rather than leaving it behind).

        ⚠️ THE DEFAULT IS NOT EMPTY, and the report now says so: `template_sections`,
        `template_required_fields` and `template_steps` name everything the template put on the flow,
        read back off the live draft. This used to be all empty tuples, which is a trap — the template
        injects sections a caller cannot name in forge_set_visibility's `owners` because they did not
        know the sections existed, so the visibility matrix is incomplete from the very first write
        and doctor only reports it two steps later ("section 'System' is never editable at any live
        step"). COVER every listed section in your `owners` map, and cover every listed Required
        field's own section at a step where it is Editable, or that step can never be submitted.
        """  # noqa: E501
        settings = ctx.lifespan_context["settings"]
        return await _shared.run_use_case(
            ctx,
            build_request=lambda: ForgeCreateProcessRequest(
                name=name,
                publish=publish,
                from_template=from_template,
                app_id=settings.resolve_app_id(app_id),
            ),
            build_use_case=lambda resources: ForgeCreateProcess(
                resources.flow, settings.resolve_process_template_path(), resources.app
            ),
        )

    @mcp.tool(title="Create or set word list", annotations=_shared.LIVE_REPLACE)
    async def forge_create_list(
        name: str,
        values: list[str],
        app_id: str | None = None,
        *,
        ctx: Context,
    ) -> ForgeCreateListResponse:
        """LIVE write (dev only, KF_APP): create-or-reuse a word list by NAME and SET its item
        values (#13, routes probed live 2026-08-12). A list is born LIVE — no publish step. Items
        use REPLACE semantics (the whole array is set each call), so re-running is idempotent.
        Point a Select at it afterwards via forge_apply_fields' `referred_list` (proven end to end:
        a real value persists on an item, a value outside the list PUTs 200 and silently clears the
        field — CLAUDE.md's Select discard rule, which is why values are read back and audited
        here).

        ⚠️ Lists holding personal data stay HUMAN-MADE (PDPA, decisions D2/D9) and this tool has NO
        way to tell — it sees a name and an array of strings, nothing else. The gate is the PLAN's,
        not this tool's: `app.application.intake.compile` still emits a `create_list` op for a
        `personal_data` list (values and all, so nothing is silently dropped) and marks it
        "HUMAN-GATED (personal_data, PDPA)" in that op's own `why`. READ the `why` before executing a
        create_list op — a human must create/verify that list in the builder UI. An earlier version of
        this line claimed the spec path would not compile such a list into this tool at all; it
        does, and believing otherwise would have let an agent execute exactly the op the plan gated.
        """  # noqa: E501
        return await _shared.run_use_case(
            ctx,
            build_request=lambda: ForgeCreateListRequest(
                name=name,
                values=values,
                app_id=ctx.lifespan_context["settings"].resolve_app_id(app_id),
            ),
            build_use_case=lambda resources: ForgeCreateList(resources.flow),
        )

    @mcp.tool(title="Publish", annotations=_shared.LIVE_ADD)
    async def forge_publish(
        kind: PublishKind,
        flow_id: str,
        app_id: str | None = None,
        *,
        ctx: Context,
    ) -> ForgePublishResponse:
        """LIVE publish (dev only, KF_APP): compile a draft to its live version. `kind` is
        "process"/"form"/"case" (a flow — `flow_id` is the flow id), "page" (needs `app_id`,
        `flow_id` is the page id), or "application" (`flow_id` is the app id).

        For a flow (process/form/case), the result includes a read-back `status` field from the
        flow's OWN metadata record (`GET /flow/2/{acct}/{kind}/{id}`, distinct from the draft graph)
        — never trust the publish response alone (CLAUDE.md "THE RULE"); `isError` is set if the
        read-back status is not "Live".
        """  # noqa: E501
        return await _shared.run_use_case(
            ctx,
            build_request=lambda: ForgePublishRequest(
                kind=kind,
                flow_id=flow_id,
                app_id=ctx.lifespan_context["settings"].resolve_app_id(app_id),
                app_id_given=bool(app_id),
            ),
            build_use_case=lambda resources: ForgePublish(
                resources.flow, resources.page, resources.app
            ),
        )

    @mcp.tool(title="Run doctor", annotations=_shared.LIVE_READ)
    async def forge_doctor(
        flow_id: str,
        kind: FlowKindArg = "process",
        visibility_role_claims: list[str] | None = None,
        app_id: str | None = None,
        *,
        ctx: Context,
    ) -> ForgeDoctorResponse:
        """Read-only health check (dev only, KF_APP): fetch the LIVE draft, harvest every Select
        field's REAL list options (CLAUDE.md: "never guess a literal — read it"), and run
        verify.doctor for real. Run this after ANY builder edit; `ok: true` and `problems: []` mean
        clean. A list whose items fetch fails is recorded in `list_fetch_errors`, never silently
        dropped from the audit. Pass the plan's doctor-op `visibility_role_claims` through verbatim
        — each claim FAILs the audit (role-scoped visibility is API-impossible, #6/ADR-0004).

        Also reads the flow's LIVE member roster — the one condition the offline graph can never see,
        because membership is not in the draft at all. A flow with AppRole assignees and an EMPTY
        roster FAILs the audit (`members` bucket, `members_found`): that is a documented bare-metadata
        publish failure (CLAUDE.md Members first). A roster this tool could not read lands in
        `member_fetch_error` and in `unvalidated`, and is never counted as populated — an unreadable
        roster is UNKNOWN, not a clean bill of health.
        """  # noqa: E501
        return await _shared.run_use_case(
            ctx,
            build_request=lambda: ForgeDoctorRequest(
                flow_id=flow_id,
                kind=kind,
                visibility_role_claims=visibility_role_claims,
                app_id=ctx.lifespan_context["settings"].resolve_app_id(app_id),
            ),
            build_use_case=lambda resources: ForgeDoctor(resources.flow),
        )

    @mcp.tool(
        title="Delete flow, page or application", annotations=_shared.LIVE_REPLACE_ONCE
    )
    async def forge_delete_flow(
        kind: DeleteKind,
        flow_id: str,
        app_id: str | None = None,
        *,
        ctx: Context,
    ) -> ForgeDeleteFlowResponse:
        """LIVE (dev only): archive+delete a flow (process/form/case/list/dataset), a PAGE (needs
        `app_id`), or an APPLICATION (`kind="application"`, `flow_id` is the app id). Verifies deletion
        via the appropriate LIST route, never the delete response alone — CLAUDE.md Page CRUD: a page
        DELETE returns `{"status":"success"}` for ANY id, even a bogus one, and its draft GET still
        200s afterward (storage lingers).

        `kind` is the DELETE set, deliberately wider than forge_publish's: `list` and `dataset` are
        born LIVE and cannot be published, but they are ordinary `/flow/2/{acct}/{kind}/{id}` records
        and delete + re-list exactly like the other three. They are also the two kinds
        forge_create_flow mints most freely, so leaving them out left an agent able to create a
        dataform it could never clean up. Only `process` is archived first (400 KISSFLOW_ERROR_04602
        otherwise); every other kind deletes directly.
        """  # noqa: E501
        return await _shared.run_use_case(
            ctx,
            build_request=lambda: ForgeDeleteFlowRequest(
                kind=kind,
                flow_id=flow_id,
                app_id=ctx.lifespan_context["settings"].resolve_app_id(app_id),
                app_id_given=bool(app_id),
            ),
            build_use_case=lambda resources: ForgeDeleteFlow(
                resources.flow, resources.app, resources.page
            ),
        )

    @mcp.tool(title="Create flow", annotations=_shared.LIVE_ADD_ONCE)
    async def forge_create_flow(
        kind: CreateFlowKind,
        name: str,
        extra: dict[str, Any] | None = None,
        app_id: str | None = None,
        *,
        ctx: Context,
    ) -> ForgeCreateFlowResponse:
        """LIVE (dev only, KF_APP): unified create for `kind` in process|form|list|dataset|case.
        process/form start Draft (build fields/workflow next); list/dataset/case are born LIVE, no
        publish step. `kind="case"` (a board) REQUIRES `extra={"item_type": "Board"|"Case", "prefix":
        <short string>}` — refused loudly before any write when either is missing (the write API
        itself 400s MissingRequiredFieldError on either omission).

        `kind="process"` clones the identity shell by default (`extra={"from_template": False}` opts
        out) and the report names what that brought in under `template_sections` /
        `template_required_fields` / `template_steps` — see forge_create_process for why an `owners`
        map that cannot name those sections breaks the visibility matrix on the first write. All
        three are read off the LIVE flow after the write, never off the payload that was sent; when
        that read fails, `template_read_error` says so and the buckets are empty because nothing was
        READ, not because the shell brought nothing in.
        """  # noqa: E501
        settings = ctx.lifespan_context["settings"]
        return await _shared.run_use_case(
            ctx,
            build_request=lambda: ForgeCreateFlowRequest(
                kind=kind,
                name=name,
                extra=extra,
                app_id=settings.resolve_app_id(app_id),
            ),
            build_use_case=lambda resources: ForgeCreateFlow(
                resources.flow, settings.resolve_process_template_path()
            ),
        )
