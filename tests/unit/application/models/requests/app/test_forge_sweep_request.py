"""Spec for app.application.models.requests.app.forge_sweep_request.

Ports `tests/test_p4_surface.py::test_sweep_unknown_scope_rejected`: the old
`run_sweep` refused an unknown scope at run time; the scope is now the closed
`SweepScope` literal on the DTO, so the same bad input fails with `ValidationError`
before any use case runs (the shape check lives in the DTO only).
"""

from __future__ import annotations

from typing import get_args

import pytest
from pydantic import ValidationError

from app.application.models.requests.app.forge_sweep_request import ForgeSweepRequest
from app.domain.value_objects.kinds import SweepScope


def test_carries_scope_and_app_id() -> None:
    req = ForgeSweepRequest(scope="flows", app_id="A1")
    assert req.scope == "flows" and req.app_id == "A1"


@pytest.mark.parametrize("scope", get_args(SweepScope))
def test_accepts_every_scope_of_the_closed_set(scope: str) -> None:
    req = ForgeSweepRequest.model_validate({"scope": scope, "app_id": "A1"})
    assert req.scope == scope


def test_unknown_scope_rejected() -> None:
    with pytest.raises(ValidationError):
        ForgeSweepRequest.model_validate({"scope": "everything", "app_id": "A1"})


def test_is_frozen() -> None:
    req = ForgeSweepRequest(scope="apps", app_id="A1")
    with pytest.raises(ValidationError):
        req.scope = "all"  # type: ignore[misc]  # ty: ignore[invalid-assignment]
