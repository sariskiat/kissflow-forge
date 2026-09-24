"""Spec for app.application.models.responses.meta.kf_list_field_types_response."""

from __future__ import annotations

from app.application.models.responses.meta.kf_list_field_types_response import (
    KfListFieldTypesResponse,
)


def test_model_dump_equals_the_wrapped_list_exactly() -> None:
    resp = KfListFieldTypesResponse(["Text", "Boolean", "Select"])

    dumped = resp.model_dump(mode="json")

    assert dumped == ["Text", "Boolean", "Select"]


def test_an_empty_list_still_dumps_as_an_empty_list() -> None:
    assert KfListFieldTypesResponse([]).model_dump(mode="json") == []
