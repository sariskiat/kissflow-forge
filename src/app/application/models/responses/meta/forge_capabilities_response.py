"""app.application.models.responses.meta.forge_capabilities_response — the DTO for
`forge_capabilities`'s result: today's `search_capabilities()` success dict, minus
`isError` (spec G13). An empty query dumps `index`; a non-empty query dumps `entries`
-- the same one-of-two shape `search_capabilities` returns today, never both keys at
once.
"""

from __future__ import annotations

from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    SerializerFunctionWrapHandler,
    model_serializer,
    model_validator,
)


class ForgeCapabilitiesResponse(BaseModel):
    """One `forge_capabilities` result: the index (empty query) or the matching
    entries (non-empty query), plus every parse/link error hit along the way."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    query: str
    count: int
    index: list[dict[str, Any]] | None = None
    entries: list[dict[str, Any]] | None = None
    errors: list[str]

    @model_validator(mode="after")
    def _exactly_one_listing(self) -> ForgeCapabilitiesResponse:
        """Refuse a response that carries both or neither of `index`/`entries`.

        Returns:
            This response, unchanged, when exactly one of the two is set.

        Raises:
            ValueError: Both, or neither, of `index`/`entries` is `None`.
        """
        if (self.index is None) == (self.entries is None):
            raise ValueError("exactly one of `index` or `entries` must be set")
        return self

    @model_serializer(mode="wrap")
    def _drop_the_unset_listing(
        self, handler: SerializerFunctionWrapHandler
    ) -> dict[str, Any]:
        """Serialize with only the listing key that is actually set.

        Args:
            handler: Pydantic's own default serializer for this model.

        Returns:
            The default field-order dump, minus whichever of `index`/
            `entries` is `None` -- today's dict never carried both keys.
        """
        data = handler(self)
        if self.index is None:
            data.pop("index", None)
        else:
            data.pop("entries", None)
        return data
