"""Spec for app.application.use_cases.meta.forge_capabilities.

The use case builds the response from the `DocsReader` port's plain data (spec G13):
`count` is the number of docs, and the docs go under `index` for an empty query and
under `entries` for a search -- today's two payload shapes, minus `isError`.
`tests/test_capabilities.py`'s assertions run through the port on the real docs in
`tests/unit/infrastructure/test_capabilities.py`, which also proves this use case over
the real adapter equals the old payload for five queries.
"""

from __future__ import annotations

from typing import Any

import pytest
from tests.fakes.docs import FakeDocsReader

from app.application.exceptions import ApplicationError
from app.application.models.requests.meta.forge_capabilities_request import (
    ForgeCapabilitiesRequest,
)
from app.application.use_cases.meta.forge_capabilities import ForgeCapabilities

_CURRENCY = {"id": "field.currency", "name": "Currency", "status": "wire-proven"}
_LIST = {"id": "field.list", "name": "List", "status": "claimed"}


def _fake(docs: list[dict[str, Any]], errors: list[str]) -> FakeDocsReader:
    fake = FakeDocsReader()
    fake.results["capabilities"] = [{"docs": docs, "errors": errors}]
    return fake


@pytest.mark.asyncio
async def test_an_empty_query_returns_the_full_index() -> None:
    fake = _fake([_CURRENCY, _LIST], [])

    resp = await ForgeCapabilities(fake).execute(ForgeCapabilitiesRequest())

    assert resp.model_dump(mode="json") == {
        "query": "",
        "count": 2,
        "index": [_CURRENCY, _LIST],
        "errors": [],
    }
    assert fake.calls == [("capabilities", (), {"query": ""})]


@pytest.mark.asyncio
async def test_a_query_returns_its_matches_as_entries() -> None:
    fake = _fake([_CURRENCY], [])

    resp = await ForgeCapabilities(fake).execute(
        ForgeCapabilitiesRequest(query="currency")
    )

    assert resp.model_dump(mode="json") == {
        "query": "currency",
        "count": 1,
        "entries": [_CURRENCY],
        "errors": [],
    }
    assert fake.calls == [("capabilities", (), {"query": "currency"})]


@pytest.mark.asyncio
async def test_a_query_with_no_matches_returns_empty_entries_not_an_error() -> None:
    resp = await ForgeCapabilities(_fake([], [])).execute(
        ForgeCapabilitiesRequest(query="no-such-capability-xyz-000")
    )

    assert resp.count == 0
    assert resp.entries == []
    assert resp.index is None


@pytest.mark.asyncio
async def test_the_port_errors_reach_the_response_never_silently_dropped() -> None:
    """A doc whose frontmatter fails to parse lands in `errors` (output-invariant
    audit), next to the docs that did parse."""
    errors = ["broken.md: frontmatter is not a mapping"]

    resp = await ForgeCapabilities(_fake([_CURRENCY], errors)).execute(
        ForgeCapabilitiesRequest()
    )

    assert resp.errors == errors
    assert resp.count == 1


@pytest.mark.asyncio
async def test_an_application_error_from_the_port_propagates_unchanged() -> None:
    class _FailingDocs(FakeDocsReader):
        async def capabilities(self, query: str = "") -> dict[str, Any]:
            raise ApplicationError("docs unavailable", code="REPOSITORY_ERROR")

    with pytest.raises(ApplicationError) as info:
        await ForgeCapabilities(_FailingDocs()).execute(ForgeCapabilitiesRequest())

    assert info.value.code == "REPOSITORY_ERROR"
