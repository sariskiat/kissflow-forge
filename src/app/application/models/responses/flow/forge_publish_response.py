"""Response DTO for `forge_publish`."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, SerializerFunctionWrapHandler, model_serializer


class ForgePublishResponse(BaseModel):
    """`forge_publish`'s success result.

    Attributes:
        kind: What was published.
        id: The target's id (for `kind="application"`, the app id itself).
        published: Always `True` on success.
        status: The flow's own metadata status, read back after publish
            (only for `kind` in `"form"`/`"process"`/`"case"`; `None` for
            `"page"`/`"application"`, which carry no such read-back today,
            and left out of the payload entirely -- the old dict never had
            the key for those two kinds).
        snapshot_version: The draft version read before publishing (spec
            G11's additive field).
    """

    kind: str
    id: str
    published: bool
    status: str | None = None
    snapshot_version: str | None = None

    @model_serializer(mode="wrap")
    def _drop_empty_status(
        self, handler: SerializerFunctionWrapHandler
    ) -> dict[str, Any]:
        """Leave `status` out of the payload when it is `None` (`kind` in
        `"page"`/`"application"`) -- the old dict never carried that key for
        those two kinds. A flow (`"process"`/`"form"`/`"case"`) whose status
        read-back does not confirm `"Live"` is a raised failure, never a
        success response with `status=None` (rule 7), so `None` here always
        means "no such key on the old dict", never "the read-back failed".

        Args:
            handler: The default field-by-field serializer.

        Returns:
            The serialized payload, with `status` dropped when empty.
        """
        data = handler(self)
        if data.get("status") is None:
            data.pop("status", None)
        return data
