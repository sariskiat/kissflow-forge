"""Spec for app.application.models.responses.meta.forge_capabilities_response."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.application.models.responses.meta.forge_capabilities_response import (
    ForgeCapabilitiesResponse,
)

_ROW = {"id": "field.currency", "name": "Currency", "status": "wire-proven"}


def _response(**overrides: Any) -> ForgeCapabilitiesResponse:
    base: dict[str, Any] = {"query": "", "count": 1, "index": [_ROW], "errors": []}
    base.update(overrides)
    return ForgeCapabilitiesResponse.model_validate(base)


def test_an_index_dumps_as_the_old_empty_query_dict_minus_is_error() -> None:
    """Empty query: today's dict was `{query, count, index, errors, isError}`."""
    dumped = _response().model_dump(mode="json")

    assert dumped == {"query": "", "count": 1, "index": [_ROW], "errors": []}
    assert list(dumped) == ["query", "count", "index", "errors"]


def test_a_search_dumps_as_the_old_query_dict_minus_is_error() -> None:
    """Non-empty query: today's dict was `{query, count, entries, errors, isError}`."""
    resp = _response(query="currency", index=None, entries=[_ROW], errors=["x.md: bad"])

    dumped = resp.model_dump(mode="json")

    assert dumped == {
        "query": "currency",
        "count": 1,
        "entries": [_ROW],
        "errors": ["x.md: bad"],
    }
    assert list(dumped) == ["query", "count", "entries", "errors"]


def test_an_empty_listing_still_dumps_its_key() -> None:
    """No match is `entries: []`, not a missing key -- the old dict always had it."""
    resp = _response(query="zzz", count=0, index=None, entries=[])

    assert resp.model_dump(mode="json")["entries"] == []


@pytest.mark.parametrize(
    "listing",
    [
        {"index": None, "entries": None},
        {"index": [_ROW], "entries": [_ROW]},
    ],
)
def test_carries_exactly_one_listing(listing: dict[str, Any]) -> None:
    with pytest.raises(ValidationError, match="exactly one of `index` or `entries`"):
        _response(**listing)


def test_rejects_an_unknown_key() -> None:
    with pytest.raises(ValidationError):
        _response(isError=False)


def test_is_frozen() -> None:
    resp = _response()
    with pytest.raises(ValidationError):
        resp.count = 2  # type: ignore[misc]  # ty: ignore[invalid-assignment]
