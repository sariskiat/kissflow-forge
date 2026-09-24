"""Spec for app.application.models.requests.page.forge_build_page_request.

Replaces the old inline `server.py` check (`(op is None) == (steps is None)`)
and the `'steps' entry requires 'page_id'` check with a `model_validator`,
same messages, now raising `ValidationError`.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.application.models.requests.page.forge_build_page_request import (
    ForgeBuildPageRequest,
)


def test_op_entry_constructs() -> None:
    req = ForgeBuildPageRequest(app_id="A1", op={"name": "Ops Home"})
    assert req.op == {"name": "Ops Home"}
    assert req.steps is None
    assert req.page_id is None


def test_steps_entry_constructs() -> None:
    req = ForgeBuildPageRequest(
        app_id="A1",
        page_id="Page_1",
        steps=[{"kind": "container", "kwargs": {"parent_id": "Container001"}}],
    )
    assert req.steps is not None
    assert req.steps[0].kind == "container"
    assert req.op is None


def test_rejects_neither_op_nor_steps() -> None:
    with pytest.raises(ValidationError, match="pass exactly one of 'op'"):
        ForgeBuildPageRequest(app_id="A1")


def test_rejects_both_op_and_steps() -> None:
    with pytest.raises(ValidationError, match="pass exactly one of 'op'"):
        ForgeBuildPageRequest(
            app_id="A1",
            op={"name": "Ops Home"},
            page_id="Page_1",
            steps=[{"kind": "container", "kwargs": {}}],
        )


def test_rejects_steps_with_no_page_id() -> None:
    with pytest.raises(ValidationError, match="'steps' entry requires 'page_id'"):
        ForgeBuildPageRequest(app_id="A1", steps=[{"kind": "container", "kwargs": {}}])


def test_a_step_missing_kind_names_its_index_and_a_correct_shape() -> None:
    """Restores `app.application.tools.coerce_page_steps`'s own text
    (review fix 3), lost when `PageBuildStepIn`'s generic Pydantic message
    replaced it -- pinned pre-refactor by
    `tests/test_mcp_boundary.py:630-639`."""
    with pytest.raises(ValidationError) as exc_info:
        ForgeBuildPageRequest(app_id="A1", page_id="P", steps=[{"kwargs": {}}])

    msg = str(exc_info.value)
    assert "steps[0]['kind']" in msg
    assert "correct shape:" in msg


def test_a_step_that_is_not_an_object_names_its_index() -> None:
    with pytest.raises(ValidationError) as exc_info:
        ForgeBuildPageRequest(app_id="A1", page_id="P", steps=["nope"])

    assert "steps[0]" in str(exc_info.value)


def test_steps_not_a_list_names_the_parameter() -> None:
    with pytest.raises(ValidationError) as exc_info:
        ForgeBuildPageRequest.model_validate(
            {"app_id": "A1", "page_id": "P", "steps": "nope"}
        )

    msg = str(exc_info.value)
    assert "steps:" in msg
    assert "correct shape:" in msg


def test_defaults_match_the_old_tool_parameters() -> None:
    req = ForgeBuildPageRequest(app_id="A1", op={"name": "Ops Home"})
    assert req.page_id is None
    assert req.steps is None
    assert req.publish is False


def test_is_frozen() -> None:
    req = ForgeBuildPageRequest(app_id="A1", op={"name": "Ops Home"})
    with pytest.raises(ValidationError):
        req.publish = True  # type: ignore[misc]  # ty: ignore[invalid-assignment]
