"""Spec for app.application.models.requests.page.forge_set_navigation_request."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.application.models.requests.page.forge_set_navigation_request import (
    ForgeSetNavigationRequest,
)


def test_constructs_from_the_minimal_shape() -> None:
    req = ForgeSetNavigationRequest(app_id="A1", page_id="Page_1", label="Sample Tab")
    assert req.app_id == "A1"
    assert req.page_id == "Page_1"
    assert req.label == "Sample Tab"
    assert req.unify is True
    assert req.sweep is False
    assert req.publish is False


def test_every_field_is_settable() -> None:
    req = ForgeSetNavigationRequest(
        app_id="A1",
        page_id="Page_1",
        label="Sample Tab",
        unify=False,
        sweep=True,
        publish=True,
    )
    assert req.unify is False
    assert req.sweep is True
    assert req.publish is True


def test_rejects_a_missing_page_id() -> None:
    with pytest.raises(ValidationError):
        ForgeSetNavigationRequest.model_validate(
            {"app_id": "A1", "label": "Sample Tab"}
        )


def test_rejects_a_missing_label() -> None:
    with pytest.raises(ValidationError):
        ForgeSetNavigationRequest.model_validate({"app_id": "A1", "page_id": "Page_1"})


def test_is_frozen() -> None:
    req = ForgeSetNavigationRequest(app_id="A1", page_id="Page_1", label="Sample Tab")
    with pytest.raises(ValidationError):
        req.label = "Other"  # type: ignore[misc]  # ty: ignore[invalid-assignment]
