"""Tests for `ForgeRequestConfirmation`, ported from `tests/test_p3_surface.py`'s
`forge_request_confirmation` coverage (Stage D group 8; the tool moved from
`app.infrastructure.mcp.server.forge_request_confirmation`).

Fix 4 (spec G13 Q1) moved the actual file write to the `FileArtifactWriter`
adapter -- this use case is now tested against the `FakeArtifactWriter`, never
the real filesystem.
"""

from __future__ import annotations

from typing import Any

import pytest
from tests.fakes.artifacts import FakeArtifactWriter
from tests.fakes.intake_specs import full_spec

from app.application.models.requests.intake.forge_intake_questions_request import (
    ForgeIntakeQuestionsRequest,
)
from app.application.models.requests.intake.forge_request_confirmation_request import (  # noqa: E501
    ForgeRequestConfirmationRequest,
)
from app.application.use_cases.design._artifacts import content_digest
from app.application.use_cases.intake.forge_intake_questions import (
    ForgeIntakeQuestions,
)
from app.application.use_cases.intake.forge_request_confirmation import (
    ForgeRequestConfirmation,
)

_FULL_WIRE = full_spec(approved=False).model_dump(mode="json")


@pytest.mark.asyncio
async def test_returns_digest_paths_and_questions(tmp_path: Any) -> None:
    artifacts = FakeArtifactWriter()
    use_case = ForgeRequestConfirmation(artifacts)
    request = ForgeRequestConfirmationRequest(spec=_FULL_WIRE, out_dir=str(tmp_path))
    got = await use_case.execute(request)

    assert len(got.digest) == 64  # sha256 hexdigest
    assert set(got.artifact_paths) == {
        "flow_diagram.drawio",
        "schema_diagram.drawio",
        "design.html",
    }
    for name, path in got.artifact_paths.items():
        assert path.startswith(str(tmp_path)), f"{name}: out_dir must actually be used"
        assert path.endswith(name)
    assert len(got.questions) > 0
    assert got.gaps == [] and got.blocking_gaps == []  # the fixture is complete

    digest = content_digest(request.spec)
    assert {call[2]["filename"] for call in artifacts.calls} == set(got.artifact_paths)
    for _, _, kwargs in artifacts.calls:
        assert kwargs["app_name"] == request.spec.app_name
        assert kwargs["digest"] == digest
        assert kwargs["out_dir"] == str(tmp_path)
        assert len(kwargs["content"]) > 0
    design_call = next(
        call for call in artifacts.calls if call[2]["filename"] == "design.html"
    )
    assert "<!doctype html>" in design_call[2]["content"]


@pytest.mark.asyncio
async def test_digest_changes_when_spec_content_changes(tmp_path: Any) -> None:
    use_case = ForgeRequestConfirmation(FakeArtifactWriter())
    a = await use_case.execute(
        ForgeRequestConfirmationRequest(spec=_FULL_WIRE, out_dir=str(tmp_path))
    )
    renamed = {**_FULL_WIRE, "app_name": "A Different Name"}
    b = await use_case.execute(
        ForgeRequestConfirmationRequest(spec=renamed, out_dir=str(tmp_path))
    )
    assert a.digest != b.digest


@pytest.mark.asyncio
async def test_on_a_blank_spec_still_signals_the_gaps(tmp_path: Any) -> None:
    """The exact scenario the review caught: confirming a blank spec used
    to return success with three artifacts written and 10 blocking gaps
    with nothing in the result saying so."""
    blank = (await ForgeIntakeQuestions().execute(ForgeIntakeQuestionsRequest())).spec
    use_case = ForgeRequestConfirmation(FakeArtifactWriter())
    got = await use_case.execute(
        ForgeRequestConfirmationRequest(spec=blank, out_dir=str(tmp_path))
    )
    assert len(got.blocking_gaps) == 10
    assert len(got.gaps) == 11
