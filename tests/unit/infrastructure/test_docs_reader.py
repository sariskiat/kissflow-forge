"""`DocsReaderAdapter`: the `DocsReader` port over `read_playbook` and
`find_capabilities`, each run in a worker thread."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest

import app.infrastructure.docs_reader as docs_reader_module
from app.application.exceptions import NOT_FOUND, ApplicationError
from app.application.interfaces.docs import DocsReader
from app.domain.value_objects.kinds import PlaybookName
from app.infrastructure.capabilities import find_capabilities
from app.infrastructure.docs_reader import DocsReaderAdapter
from app.infrastructure.playbook import PLAYBOOKS, read_playbook


def test_implements_the_docs_reader_port() -> None:
    assert isinstance(DocsReaderAdapter(), DocsReader)


@pytest.mark.asyncio
async def test_playbook_returns_what_read_playbook_reads() -> None:
    assert await DocsReaderAdapter().playbook() == read_playbook()


@pytest.mark.asyncio
@pytest.mark.parametrize("skill", ["builder", "design", "usage"])
async def test_each_skill_name_reads_its_own_vendored_file(
    skill: PlaybookName,
) -> None:
    out = await DocsReaderAdapter().playbook(skill)
    assert out == read_playbook(PLAYBOOKS[skill])


@pytest.mark.asyncio
async def test_capabilities_returns_what_find_capabilities_finds() -> None:
    adapter = DocsReaderAdapter()
    assert await adapter.capabilities() == find_capabilities()
    assert await adapter.capabilities("workflow") == find_capabilities("workflow")


@pytest.mark.asyncio
async def test_a_not_found_playbook_propagates_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing(path: Path) -> dict[str, str]:
        del path
        raise ApplicationError("vendored playbook not found at x", code=NOT_FOUND)

    monkeypatch.setattr(docs_reader_module, "read_playbook", missing)

    with pytest.raises(ApplicationError) as info:
        await DocsReaderAdapter().playbook()
    assert info.value.code == NOT_FOUND
    assert info.value.message == "vendored playbook not found at x"


@pytest.mark.asyncio
async def test_both_reads_run_off_the_event_loop_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A capability search parses every doc's YAML (about 40 ms). The old sync tools
    ran in FastMCP's threadpool; the async adapter must not block the loop instead."""
    seen: dict[str, int] = {}

    def playbook(path: Path) -> dict[str, str]:
        del path
        seen["playbook"] = threading.get_ident()
        return {"text": "t", "source": "s"}

    def capabilities(query: str) -> dict[str, Any]:
        seen["capabilities"] = threading.get_ident()
        return {"docs": [], "errors": [], "query": query}

    monkeypatch.setattr(docs_reader_module, "read_playbook", playbook)
    monkeypatch.setattr(docs_reader_module, "find_capabilities", capabilities)
    adapter = DocsReaderAdapter()

    assert await adapter.playbook() == {"text": "t", "source": "s"}
    assert await adapter.capabilities("q") == {"docs": [], "errors": [], "query": "q"}

    loop_thread = threading.get_ident()
    assert seen["playbook"] != loop_thread
    assert seen["capabilities"] != loop_thread
