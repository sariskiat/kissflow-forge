"""Request DTO for `kf_create_process`."""

from __future__ import annotations

from pydantic import BaseModel

from app.application.models.requests.flow._field_spec_in import FieldSpecIn


class KfCreateProcessRequest(BaseModel):
    """`kf_create_process`'s arguments, the app id already resolved.

    `fields` is `_field_spec_in.FieldSpecIn` -- the same DTO
    `kf_apply_field_change`/`forge_apply_fields` use (`brief_stage_d_common.md`
    review, fix 4) -- rather than a second, ad hoc `FieldSpecInput` that used
    a bare `FieldType` enum (no `kf_list_field_types`/`forge_capabilities`/
    ADR-0004 text on an unknown type) and read an explicit `required: null`
    as a validation failure instead of `False`.

    Attributes:
        name: The new process's display name.
        steps: The UserTask step names, used only when `from_template` is
            `False`.
        fields: The fields to add once the scaffold is in place.
        publish: Publish the process once the fields are verified.
        from_template: Clone the process-template identity shell instead of
            the bare scaffold.
        app_id: The resolved app id: the tool's own `app_id` argument, else
            `settings.kf_app`, else `""`.
    """

    name: str
    steps: list[str]
    fields: list[FieldSpecIn]
    publish: bool = False
    from_template: bool = True
    app_id: str
