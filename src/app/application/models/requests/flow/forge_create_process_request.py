"""Request DTO for `forge_create_process`."""

from __future__ import annotations

from pydantic import BaseModel


class ForgeCreateProcessRequest(BaseModel):
    """`forge_create_process`'s arguments, the app id already resolved.

    Attributes:
        name: The new process's display name.
        publish: Publish the process once the scaffold is verified.
        from_template: Clone the process-template identity shell instead of
            the bare single-placeholder-step scaffold.
        app_id: The resolved app id: the tool's own `app_id` argument, else
            `settings.kf_app`, else `""`.
    """

    name: str
    publish: bool = False
    from_template: bool = True
    app_id: str
