"""Spec for app.application.models.responses.meta.forge_playbook_response."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.application.models.responses.meta.forge_playbook_response import (
    ForgePlaybookResponse,
)

_SOURCE = "skills/kissflow-forge-builder/SKILL.md"


def test_model_dump_json_mode_matches_the_old_success_dict_minus_is_error() -> None:
    """Today's `load_playbook()` success dict was `{isError, text, chars, source}`."""
    resp = ForgePlaybookResponse(text="# THE RULE\n", chars=11, source=_SOURCE)

    dumped = resp.model_dump(mode="json")

    assert dumped == {"text": "# THE RULE\n", "chars": 11, "source": _SOURCE}
    assert list(dumped) == ["text", "chars", "source"]


def test_every_field_is_required() -> None:
    with pytest.raises(ValidationError):
        ForgePlaybookResponse.model_validate({"text": "t", "source": _SOURCE})


def test_rejects_an_unknown_key() -> None:
    with pytest.raises(ValidationError):
        ForgePlaybookResponse.model_validate(
            {"text": "t", "chars": 1, "source": _SOURCE, "isError": False}
        )


def test_is_frozen() -> None:
    resp = ForgePlaybookResponse(text="t", chars=1, source=_SOURCE)
    with pytest.raises(ValidationError):
        resp.text = "u"  # type: ignore[misc]  # ty: ignore[invalid-assignment]
