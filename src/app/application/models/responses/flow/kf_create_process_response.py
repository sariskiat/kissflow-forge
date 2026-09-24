"""Response DTO for `kf_create_process`."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, SerializerFunctionWrapHandler, model_serializer


class KfCreateProcessResponse(BaseModel):
    """`kf_create_process`'s success result (the former `ProcessCreateReport`).

    Attributes:
        flow_id: The new process's id.
        added: Field names newly created.
        skipped: Field names already present and identical (idempotent
            no-op).
        verified: Requested field names confirmed present by read-back.
        missing: Requested field names absent on read-back.
        changed_ignored: Field names that already existed with different
            attributes -- requested but not applied.
        collateral: Always empty for this tool; kept for shape parity with
            the former `ApplyReport`.
        remediation: Tool names that could make a `changed_ignored` entry
            happen.
        meta_version: The draft's `_meta_version` after the write.
        published: Whether the process was published.
        from_template: Whether the identity shell was cloned.
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
            created, before the scaffold was written (spec G11's additive
            field).
    """

    flow_id: str
    added: list[str]
    skipped: list[str]
    verified: list[str]
    missing: list[str]
    changed_ignored: list[str]
    collateral: list[str]
    remediation: list[str]
    meta_version: str | None
    published: bool
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
        `ProcessCreateReport.as_tool_result()` did (it only ever set the key,
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
