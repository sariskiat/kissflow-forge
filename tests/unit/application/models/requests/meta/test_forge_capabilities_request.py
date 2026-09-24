"""Spec for app.application.models.requests.meta.forge_capabilities_request."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.application.models.requests.meta.forge_capabilities_request import (
    ForgeCapabilitiesRequest,
)


def test_query_defaults_to_empty_for_the_full_index() -> None:
    assert ForgeCapabilitiesRequest().query == ""


def test_carries_the_query() -> None:
    assert ForgeCapabilitiesRequest(query="field.currency").query == "field.currency"


@pytest.mark.parametrize("query", [5, None, ["field"]])
def test_rejects_a_query_that_is_not_a_string(query: object) -> None:
    with pytest.raises(ValidationError):
        ForgeCapabilitiesRequest.model_validate({"query": query})


def test_rejects_an_unknown_key() -> None:
    with pytest.raises(ValidationError):
        ForgeCapabilitiesRequest.model_validate({"query": "x", "limit": 3})


def test_is_frozen() -> None:
    req = ForgeCapabilitiesRequest(query="x")
    with pytest.raises(ValidationError):
        req.query = "y"  # type: ignore[misc]  # ty: ignore[invalid-assignment]
