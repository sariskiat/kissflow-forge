"""app.application.use_cases.meta.forge_playbook — the `forge_playbook` use case."""

from __future__ import annotations

from app.application.interfaces.docs import DocsReader
from app.application.models.requests.meta.forge_playbook_request import (
    ForgePlaybookRequest,
)
from app.application.models.responses.meta.forge_playbook_response import (
    ForgePlaybookResponse,
)


class ForgePlaybook:
    """Serve the vendored builder playbook over MCP: `DocsReader.playbook()`, wrapped
    into its response DTO."""

    def __init__(self, docs: DocsReader) -> None:
        """Build the use case around its one port.

        Args:
            docs: The offline playbook/capability-doc reader.
        """
        self._docs = docs

    async def execute(self, request: ForgePlaybookRequest) -> ForgePlaybookResponse:
        """Read the vendored playbook and report its size.

        Args:
            request: The validated `forge_playbook` request (no fields).

        Returns:
            The playbook text, its character count, and its repo-relative
            source path.

        Raises:
            ApplicationError: `code=NOT_FOUND` when the vendored file is
                missing or blank (raised by the port; propagates unchanged).
        """
        del request
        found = await self._docs.playbook()
        return ForgePlaybookResponse(
            text=found["text"], chars=len(found["text"]), source=found["source"]
        )
