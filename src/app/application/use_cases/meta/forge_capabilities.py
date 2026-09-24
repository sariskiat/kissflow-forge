"""app.application.use_cases.meta.forge_capabilities — the `forge_capabilities` use
case.
"""

from __future__ import annotations

from app.application.interfaces.docs import DocsReader
from app.application.models.requests.meta.forge_capabilities_request import (
    ForgeCapabilitiesRequest,
)
from app.application.models.responses.meta.forge_capabilities_response import (
    ForgeCapabilitiesResponse,
)


class ForgeCapabilities:
    """Search the capability-doc index: `DocsReader.capabilities(query)`, wrapped into
    its response DTO -- the full index for an empty query, the matching entries for a
    search, exactly as today's `search_capabilities` split them."""

    def __init__(self, docs: DocsReader) -> None:
        """Build the use case around its one port.

        Args:
            docs: The offline playbook/capability-doc reader.
        """
        self._docs = docs

    async def execute(
        self, request: ForgeCapabilitiesRequest
    ) -> ForgeCapabilitiesResponse:
        """Search, or index, the capability docs.

        Args:
            request: The validated `forge_capabilities` request.

        Returns:
            The full index under `index` for an empty query, or the
            matching docs under `entries` for a search, plus every
            frontmatter/shape-link error hit along the way.

        Raises:
            ApplicationError: Raised by the port; propagates unchanged.
        """
        found = await self._docs.capabilities(query=request.query)
        docs = found["docs"]
        errors = found["errors"]
        if request.query:
            return ForgeCapabilitiesResponse(
                query=request.query, count=len(docs), entries=docs, errors=errors
            )
        return ForgeCapabilitiesResponse(
            query=request.query, count=len(docs), index=docs, errors=errors
        )
