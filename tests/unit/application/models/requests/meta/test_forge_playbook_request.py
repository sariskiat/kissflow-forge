"""Spec for app.application.models.requests.meta.forge_playbook_request."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.application.models.requests.meta.forge_playbook_request import (
    ForgePlaybookRequest,
)


def test_constructs_with_no_fields() -> None:
    """`forge_playbook` takes no parameters, so its request carries none."""
    assert ForgePlaybookRequest().model_dump() == {}


def test_rejects_an_unknown_key() -> None:
    with pytest.raises(ValidationError):
        ForgePlaybookRequest.model_validate({"query": "x"})
