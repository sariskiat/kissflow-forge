"""Spec for app.application.models.requests.meta.kf_list_field_types_request."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.application.models.requests.meta.kf_list_field_types_request import (
    KfListFieldTypesRequest,
)


def test_constructs_with_no_fields() -> None:
    """`kf_list_field_types` takes no parameters, so its request carries none."""
    assert KfListFieldTypesRequest().model_dump() == {}


def test_rejects_an_unknown_key() -> None:
    with pytest.raises(ValidationError):
        KfListFieldTypesRequest.model_validate({"query": "x"})
