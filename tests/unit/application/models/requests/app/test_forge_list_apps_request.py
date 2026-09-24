"""Spec for app.application.models.requests.app.forge_list_apps_request."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.application.models.requests.app.forge_list_apps_request import (
    ForgeListAppsRequest,
)


def test_takes_no_field_at_all() -> None:
    """`forge_list_apps` has no parameter: it needs no app selected, because it is how
    a caller discovers which app id to pass to every other app-scoped tool."""
    assert ForgeListAppsRequest.model_fields == {}
    assert ForgeListAppsRequest().model_dump() == {}


def test_rejects_an_unknown_field() -> None:
    """A tool with no parameter has no field to smuggle an app id through."""
    with pytest.raises(ValidationError):
        ForgeListAppsRequest.model_validate({"app_id": "A1"})
