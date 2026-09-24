"""Response DTO for `forge_create_flow`."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, SerializerFunctionWrapHandler, model_serializer


class ForgeCreateFlowResponse(BaseModel):
    """`forge_create_flow`'s success result (the former `FlowCreateReport`).

    Attributes:
        kind: The flow kind created.
        flow_id: The new flow's id.
        name: The flow's display name.
        status: The flow's status (`"Draft"` for process/form, the born-live
            status for list/dataset/case).
        born_live: Whether this kind has no draft/publish split.
        from_template: Whether the identity shell was cloned (`kind`
            `"process"` only).
        template_sections: Section names the scaffold put on the flow.
        template_required_fields: Required field names the scaffold put on
            the flow.
        template_steps: Step names the scaffold put on the flow.
        template_read_error: Set when the scaffold inventory read-back
            failed; the three `template_*` buckets above are then empty
            because nothing was read, not because the shell brought
            nothing in.
        note: A human-readable summary of the `template_*` buckets, or
            `None` when neither `from_template` nor `template_read_error`
            applies.
        snapshot_version: The draft version read right after the flow was
            created, before any scaffold was written (spec G11's additive
            field; `None` for a born-live kind).
    """

    kind: str
    flow_id: str
    name: str
    status: str | None
    born_live: bool
    from_template: bool
    template_sections: list[str]
    template_required_fields: list[str]
    template_steps: list[str]
    template_read_error: str | None
    note: str | None = None
    snapshot_version: str | None = None

    @model_serializer(mode="wrap")
    def _drop_empty_note(
        self, handler: SerializerFunctionWrapHandler
    ) -> dict[str, Any]:
        """Leave `note` out of the payload when it is `None`, as the former
        `FlowCreateReport.as_tool_result()` did (it only ever set the key,
        never set it to `None`).

        Args:
            handler: The default field-by-field serializer.

        Returns:
            The serialized payload, with `note` dropped when empty.
        """
        data = handler(self)
        if data.get("note") is None:
            data.pop("note", None)
        return data
