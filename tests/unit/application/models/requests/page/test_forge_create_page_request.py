"""Spec for app.application.models.requests.page.forge_create_page_request."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.application.models.requests.page.forge_create_page_request import (
    ForgeCreatePageRequest,
)


def test_constructs_from_the_minimal_shape() -> None:
    req = ForgeCreatePageRequest(app_id="A1", name="Sample Page")
    assert req.app_id == "A1"
    assert req.name == "Sample Page"
    assert req.publish is False


def test_publish_is_settable() -> None:
    req = ForgeCreatePageRequest(app_id="A1", name="Sample Page", publish=True)
    assert req.publish is True


def test_rejects_a_missing_app_id() -> None:
    with pytest.raises(ValidationError):
        ForgeCreatePageRequest.model_validate({"name": "Sample Page"})


def test_rejects_a_missing_name() -> None:
    with pytest.raises(ValidationError):
        ForgeCreatePageRequest.model_validate({"app_id": "A1"})


def test_is_frozen() -> None:
    req = ForgeCreatePageRequest(app_id="A1", name="Sample Page")
    with pytest.raises(ValidationError):
        req.name = "Other"  # type: ignore[misc]  # ty: ignore[invalid-assignment]
