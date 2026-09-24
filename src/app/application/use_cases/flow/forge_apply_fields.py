"""app.application.use_cases.flow.forge_apply_fields — add fields, lay them into
sections, and attach validation/computed/conditional-visibility, in one guarded
read-verify-write.

Ported from `app.infrastructure.kissflow.client.apply_fields_full` (Stage D group 1).
"""

from __future__ import annotations

from typing import Any

from app.application.exceptions import VERIFY_FAILED, ApplicationError
from app.application.interfaces.flow import FlowRepository
from app.application.models.requests.flow.forge_apply_fields_request import (
    ForgeApplyFieldsRequest,
)
from app.application.models.responses.flow.forge_apply_fields_response import (
    ForgeApplyFieldsResponse,
)
from app.application.use_cases.flow._fields import (
    changed_ignored,
    field_spec_from,
    layout_collateral,
    raise_if_write_failed,
    require_app_id,
)
from app.application.use_cases.flow._write_order import WriteOrder
from app.domain.entities.flow_draft import FlowDraft


class ForgeApplyFields:
    """Use case behind the `forge_apply_fields` tool."""

    def __init__(self, flow: FlowRepository) -> None:
        """Build the use case.

        Args:
            flow: The flow/process/form/case/list port.
        """
        self._flow = flow

    async def execute(
        self, request: ForgeApplyFieldsRequest
    ) -> ForgeApplyFieldsResponse:
        """Run one `forge_apply_fields` call: snapshot, apply every requested layer
        offline, guarded write, read-back verify each layer, optional publish.

        Args:
            request: The validated request.

        Returns:
            The output-invariant audit of what happened, across all four
            layers (fields, validation, computed, conditional visibility) --
            only when every layer verified clean (rule 7: a write that did
            not fully land is a failure, never a success response with the
            failure sitting inside a bucket).

        Raises:
            ApplicationError: `request.app_id` is empty (`REFUSED`); the
                offline change set was rejected (`VERIFY_FAILED`); publish
                was requested for a kind with no publish route
                (`VERIFY_FAILED`); any layer came back `missing` on
                read-back, or a requested change was ignored
                (`VERIFY_FAILED`, naming the bucket, its items and whether
                anything published). A `RepositoryError` from the port (a
                read, write or conflict failure) propagates unchanged.
        """
        require_app_id(request.app_id)
        specs = [field_spec_from(f) for f in request.fields]
        groups = (
            list(request.sections.items()) if request.sections is not None else None
        )
        validations = request.validation or {}
        computed = request.computed or {}
        conditional = request.conditional_visibility or {}

        order = WriteOrder[FlowDraft](
            get=lambda: self._flow.get_draft(
                request.app_id, request.kind, request.flow_id
            ),
            put=lambda new, expect_version: self._flow.put_draft(
                request.app_id, request.kind, request.flow_id, new, expect_version
            ),
            version_of=lambda draft: draft.version,
        )
        snapshot = await order.snapshot()
        before_draft = snapshot.to_wire()
        before_names = snapshot.field_names()
        requested = [s.name for s in specs]
        ignored = changed_ignored(before_draft, specs)
        skipped = tuple(
            n for n in requested if n in before_names and n not in ignored.names
        )

        try:
            new_flow = snapshot.apply_changes(specs)
            if groups:
                new_flow = new_flow.place_in_sections(groups)
            for fname, rules in validations.items():
                for rule in rules:
                    new_flow = new_flow.add_field_validation(
                        fname,
                        rule["operator"],
                        rule["rhs"],
                        error_message=rule.get("error_message"),
                    )
            for fname, formula in computed.items():
                new_flow = new_flow.set_field_computed(fname, formula)
            for fname, cond in conditional.items():
                new_flow = new_flow.set_conditional_visibility(
                    fname, cond["trigger_field"], cond["operator"], cond["rhs"]
                )
        except (ValueError, NotImplementedError, KeyError) as exc:
            raise ApplicationError(
                f"offline apply rejected the change set: {exc}",
                code=VERIFY_FAILED,
            ) from exc

        added = tuple(n for n in requested if n not in before_names)
        if added or groups or validations or computed or conditional:
            await order.apply(new_flow)

        read_back = await order.read_back()
        after_draft = read_back.to_wire()
        live_names = read_back.field_names()
        verified = tuple(
            n for n in requested if n in live_names and n not in ignored.names
        )
        missing = tuple(n for n in requested if n not in live_names)
        collateral = layout_collateral(before_draft, after_draft, exclude=added)

        by_name: dict[str, dict[str, Any]] = {
            v.get("Name"): v
            for v in after_draft.values()
            if isinstance(v, dict) and v.get("Kind") == "Field"
        }

        val_verified: list[str] = []
        val_missing: list[str] = []
        for fname, rules in validations.items():
            fld = by_name.get(fname, {})
            live_rules: set[tuple[str, str]] = set()
            for cid in fld.get("FieldValidation::Criteria") or []:
                criteria = after_draft.get(cid, {}).get("Criteria::Condition") or []
                for condid in criteria:
                    c = after_draft.get(condid, {})
                    if isinstance(c.get("Operator"), str):
                        live_rules.add((c["Operator"], str(c.get("RHSValue"))))
            for rule in rules:
                key = f"{fname}:{rule['operator']}:{rule['rhs']}"
                (
                    val_verified
                    if (rule["operator"], rule["rhs"]) in live_rules
                    else val_missing
                ).append(key)

        computed_verified = tuple(
            n for n in computed if by_name.get(n, {}).get("Field::Expression")
        )
        computed_missing = tuple(n for n in computed if n not in computed_verified)

        cond_verified: list[str] = []
        cond_missing: list[str] = []
        for fname in conditional:
            fld = by_name.get(fname, {})
            col_id = fld.get("Column")
            col = after_draft.get(col_id, {}) if isinstance(col_id, str) else {}
            (
                cond_verified if col.get("ColumnVisibility::Criteria") else cond_missing
            ).append(fname)

        published = False
        all_ok = not (
            missing
            or ignored.entries
            or val_missing
            or computed_missing
            or cond_missing
        )
        if request.publish and all_ok:
            if request.kind not in ("form", "process", "case"):
                raise ApplicationError(
                    f"{request.kind!r} has no publish route. Its draft is "
                    "already live. A publish request returns HTTP 404. Call "
                    "this tool again with publish=False.",
                    code=VERIFY_FAILED,
                )
            await self._flow.publish(request.app_id, request.kind, request.flow_id)
            published = True

        remediation = list(ignored.remediation) + (
            ["forge_apply_layout"] if collateral else []
        )
        raise_if_write_failed(
            published=published,
            missing=missing,
            changed_ignored=ignored.entries,
            validations_missing=val_missing,
            computed_missing=computed_missing,
            conditional_missing=cond_missing,
            collateral=collateral,
            remediation=remediation,
        )

        return ForgeApplyFieldsResponse(
            flow_id=request.flow_id,
            added=list(added),
            skipped=list(skipped),
            verified=list(verified),
            missing=list(missing),
            changed_ignored=list(ignored.entries),
            collateral=list(collateral),
            remediation=remediation,
            validations_verified=list(val_verified),
            validations_missing=list(val_missing),
            computed_verified=list(computed_verified),
            computed_missing=list(computed_missing),
            conditional_verified=list(cond_verified),
            conditional_missing=list(cond_missing),
            meta_version=read_back.version,
            published=published,
            snapshot_version=order.snapshot_version,
        )
