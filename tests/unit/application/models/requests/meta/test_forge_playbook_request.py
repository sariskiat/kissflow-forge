"""Spec for app.application.models.requests.meta.forge_playbook_request."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.application.models.requests.meta.forge_playbook_request import (
    ForgePlaybookRequest,
)


def test_defaults_to_the_builder_playbook() -> None:
    """A no-argument call must keep returning the builder playbook."""
    assert ForgePlaybookRequest().model_dump() == {"skill": "builder"}


@pytest.mark.parametrize("skill", ["builder", "design", "usage"])
def test_accepts_each_served_skill_name(skill: str) -> None:
    assert ForgePlaybookRequest.model_validate({"skill": skill}).skill == skill


@pytest.mark.parametrize("skill", ["Builder", "deploy", "../CLAUDE", ""])
def test_rejects_a_name_outside_the_closed_set(skill: str) -> None:
    """The name picks a file, so anything outside the allowlist is refused here."""
    with pytest.raises(ValidationError):
        ForgePlaybookRequest.model_validate({"skill": skill})


def test_rejects_an_unknown_key() -> None:
    with pytest.raises(ValidationError):
        ForgePlaybookRequest.model_validate({"query": "x"})
