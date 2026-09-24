"""Spec for app.application.models.requests.app.forge_create_template_app_request."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.application.models.requests.app.forge_create_template_app_request import (
    ForgeCreateTemplateAppRequest,
)


def test_carries_the_name_the_only_argument() -> None:
    req = ForgeCreateTemplateAppRequest(name="Sample Template App")
    assert req.model_dump() == {"name": "Sample Template App"}


def test_rejects_a_missing_name() -> None:
    with pytest.raises(ValidationError):
        ForgeCreateTemplateAppRequest.model_validate({})


def test_is_frozen() -> None:
    req = ForgeCreateTemplateAppRequest(name="Sample Template App")
    with pytest.raises(ValidationError):
        req.name = "Other"  # type: ignore[misc]  # ty: ignore[invalid-assignment]
