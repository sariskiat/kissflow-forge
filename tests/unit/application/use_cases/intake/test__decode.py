"""Tests for `app.application.use_cases.intake._decode.spec_or_blank`."""

from __future__ import annotations

from tests.fakes.intake_specs import full_spec

from app.application.models.requests.intake.app_spec import AppSpec, blank_spec
from app.application.use_cases.intake._decode import spec_or_blank


def test_none_returns_a_blank_spec() -> None:
    got = spec_or_blank(None)
    assert got == blank_spec()
    assert isinstance(got, AppSpec)
    assert got.approved is False
    assert len(got.gaps()) == 11


def test_a_real_spec_passes_through_unchanged() -> None:
    spec = full_spec()
    assert spec_or_blank(spec) is spec
