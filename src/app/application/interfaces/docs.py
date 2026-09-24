"""DocsReader — the port over the two offline, filesystem-backed doc reads (the `meta`
family).

`playbook()` reads the vendored builder playbook, and `capabilities(query)` searches
the capability docs. Neither touches Kissflow or the network. Both return plain data,
never an `isError` payload: the meta use cases build their responses from it (spec
G13). The adapter is `infrastructure/docs_reader.py`, over `infrastructure/playbook.py`
and `infrastructure/capabilities.py`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class DocsReader(ABC):
    """The two offline doc reads: the vendored builder playbook, and the capability-doc
    index."""

    @abstractmethod
    async def playbook(self) -> dict[str, str]:
        """Return the vendored builder playbook.

        Returns:
            `{"text": ..., "source": ...}`: the playbook's full text, never blank,
            and its path relative to the repo root.

        Raises:
            ApplicationError: `code=NOT_FOUND` when the vendored file is missing
                ("vendored playbook not found at <source>") or its text is blank
                ("vendored playbook is empty at <source>").
        """
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    async def capabilities(self, query: str = "") -> dict[str, Any]:
        """Search the capability-doc index.

        Args:
            query: Empty for the full index; non-empty to match against a
                doc's id/name/ui_path/status/body (case-insensitive substring).

        Returns:
            `{"docs": [...], "errors": [...]}`. For an empty `query`, one index
            row per doc: `id`, `name`, `status`, `modules`. For a non-empty
            `query`, one full entry per matching doc: those four, then
            `ui_path`, `params`, `body`, and `shapes` (each linked
            `shapes/*.json` parsed inline, keyed by its repo-relative path).
            `errors` names every doc whose frontmatter failed to parse and
            every linked shape that does not resolve or is not valid JSON.
        """
        raise NotImplementedError  # pragma: no cover
