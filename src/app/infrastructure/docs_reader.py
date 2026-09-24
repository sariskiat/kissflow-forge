"""DocsReaderAdapter — implements the `DocsReader` port over today's filesystem readers.

`read_playbook` and `find_capabilities` are the two plain-data reads (spec G13); this
adapter puts the `DocsReader` port in front of them. Both do blocking filesystem I/O (a
capability-doc search parses every doc's YAML frontmatter, about 40 ms), so each call
runs in a worker thread via `asyncio.to_thread` instead of blocking the event loop the
way the old synchronous FastMCP tools never had to worry about (FastMCP ran them in its
own threadpool).
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.application.interfaces.docs import DocsReader
from app.infrastructure.capabilities import find_capabilities
from app.infrastructure.playbook import read_playbook


class DocsReaderAdapter(DocsReader):
    """Implements `DocsReader` over `read_playbook`/`find_capabilities`, each run in a
    worker thread."""

    async def playbook(self) -> dict[str, str]:
        """See `DocsReader.playbook`."""
        return await asyncio.to_thread(read_playbook)

    async def capabilities(self, query: str = "") -> dict[str, Any]:
        """See `DocsReader.capabilities`."""
        return await asyncio.to_thread(find_capabilities, query)
