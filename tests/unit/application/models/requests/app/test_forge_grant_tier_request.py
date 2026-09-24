"""Spec for app.application.models.requests.app.forge_grant_tier_request.

Ports the two "refused loudly before any write" cases from
`tests/test_p4_surface.py` (`test_grant_tier_unknown_kind_rejected_before_any_write`,
`test_grant_tier_unknown_tier_rejected_before_any_write`): both `kind` and `tier` are
closed sets, so a bad value now fails at construction with `pydantic.ValidationError`,
before a use case -- let alone a port call -- ever runs.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.application.models.requests.app.forge_grant_tier_request import (
    ForgeGrantTierRequest,
)


def test_constructs_from_keyword_args() -> None:
    req = ForgeGrantTierRequest(
        kind="process", flow_id="F1", role_id="R1", tier="Manage", app_id="App1"
    )
    assert req.kind == "process"
    assert req.tier == "Manage"


def _raw(**overrides: str) -> dict[str, str]:
    values = {
        "kind": "process",
        "flow_id": "F1",
        "role_id": "R1",
        "tier": "Manage",
        "app_id": "App1",
    }
    values.update(overrides)
    return values


def test_unknown_kind_is_a_validation_error() -> None:
    with pytest.raises(ValidationError):
        ForgeGrantTierRequest.model_validate(_raw(kind="form"))


def test_unknown_tier_is_a_validation_error() -> None:
    with pytest.raises(ValidationError):
        ForgeGrantTierRequest.model_validate(_raw(tier="Superuser"))


def test_a_tier_legal_for_case_but_not_process_still_constructs() -> None:
    """`tier="Read-only"` is a real member of the `Tier` union (legal for
    `kind="case"`), so the DTO alone cannot refuse it for `kind="process"` --
    that combination check is a business rule the use case still owns
    (`app.application.use_cases.app._roles`)."""
    req = ForgeGrantTierRequest(
        kind="process", flow_id="F1", role_id="R1", tier="Read-only", app_id="App1"
    )
    assert req.tier == "Read-only"


def test_model_dump_json_mode_round_trips() -> None:
    original = ForgeGrantTierRequest(
        kind="case", flow_id="F1", role_id="R1", tier="Edit", app_id="App1"
    )
    got = ForgeGrantTierRequest.model_validate(original.model_dump(mode="json"))
    assert got == original
