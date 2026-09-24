"""`ForgeBuildWorkflowRequest`: shape validation replacing the old
`app.application.tools.coerce_workflow_steps`/`coerce_parallel` (spec G10)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.application.models.requests.flow.forge_build_workflow_request import (
    ForgeBuildWorkflowRequest,
)


def test_defaults_match_the_old_tool_signature() -> None:
    req = ForgeBuildWorkflowRequest(flow_id="F1", steps=[["Draft", "Role_A"]])
    assert req.flow_id == "F1"
    assert req.steps == [("Draft", "Role_A")]
    assert req.parallel is None
    assert req.parallel_after is None
    assert req.roles is None
    assert req.step_meta is None
    assert req.kind == "process"
    assert req.publish is False
    assert req.app_id == ""


def test_steps_coerces_a_list_of_lists_into_tuples() -> None:
    req = ForgeBuildWorkflowRequest(
        flow_id="F1", steps=[["Draft", "Role_A"], ["Review", None]]
    )
    assert req.steps == [("Draft", "Role_A"), ("Review", None)]


def test_parallel_object_reshapes_into_the_gateway_tuple() -> None:
    req = ForgeBuildWorkflowRequest(
        flow_id="F1",
        steps=[["Intake", None]],
        parallel={
            "name": "Route",
            "branches": [
                ["Standard", [["Approve", None]]],
                ["Express", [["Fast Approve", None]]],
            ],
        },
    )
    assert req.parallel == (
        "Route",
        [
            ("Standard", [("Approve", None)]),
            ("Express", [("Fast Approve", None)]),
        ],
    )


def test_a_step_pair_with_only_one_element_is_rejected() -> None:
    """The old boundary case, `steps: [["Approve"]]` -- missing the role slot."""
    with pytest.raises(ValidationError, match="steps"):
        ForgeBuildWorkflowRequest(flow_id="F", steps=[["Approve"]])


def test_a_blank_step_name_is_rejected() -> None:
    """Restores the old `app.application.tools._shape_error` text: the index
    path (`steps[0][0]`) and the correct-shape example (brief_d13_fix.md fix
    6)."""
    with pytest.raises(ValidationError) as exc_info:
        ForgeBuildWorkflowRequest(flow_id="F1", steps=[["   ", None]])
    message = str(exc_info.value)
    assert "steps[0][0]" in message
    assert "Manager Approve" in message


def test_a_non_string_role_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ForgeBuildWorkflowRequest(
            flow_id="F1",
            steps=[["Draft", 42]],  # ty: ignore[invalid-argument-type]
        )


def test_a_parallel_object_with_no_name_is_rejected() -> None:
    """The old boundary case, `MALFORMED_PARALLEL` -- a `parallel` object missing its
    own `name` key."""
    with pytest.raises(ValidationError, match="parallel"):
        ForgeBuildWorkflowRequest(
            flow_id="F",
            steps=[["Approve", None]],
            parallel={"branches": [["B", [["S", None]]]]},
        )


def test_a_blank_branch_name_is_rejected() -> None:
    """Restores the index path (`parallel['branches'][0][0]`) and the
    correct-shape example (brief_d13_fix.md fix 6)."""
    with pytest.raises(ValidationError) as exc_info:
        ForgeBuildWorkflowRequest(
            flow_id="F1",
            steps=[],
            parallel={"name": "Route", "branches": [["   ", [["S", None]]]]},
        )
    message = str(exc_info.value)
    assert "parallel['branches'][0][0]" in message
    assert '"name": "Route"' in message


def test_a_blank_step_name_inside_a_branch_is_rejected() -> None:
    """Restores the index path (`parallel['branches'][0][1][0][0]`), using the
    STEP example (not the parallel one) -- the same as the old
    `_coerce_step_pairs`, called with its own `_STEPS_EXAMPLE` regardless of
    the caller (brief_d13_fix.md fix 6)."""
    with pytest.raises(ValidationError) as exc_info:
        ForgeBuildWorkflowRequest(
            flow_id="F1",
            steps=[],
            parallel={"name": "Route", "branches": [["Branch A", [["  ", None]]]]},
        )
    message = str(exc_info.value)
    assert "parallel['branches'][0][1][0][0]" in message
    assert "Manager Approve" in message


def test_a_blank_gateway_name_is_rejected() -> None:
    """Restores the index path (`parallel['name']`) and the correct-shape
    example (brief_d13_fix.md fix 6)."""
    with pytest.raises(ValidationError) as exc_info:
        ForgeBuildWorkflowRequest(
            flow_id="F1", steps=[], parallel={"name": "  ", "branches": []}
        )
    message = str(exc_info.value)
    assert "parallel['name']" in message
    assert '"name": "Route"' in message


def test_an_empty_parallel_dict_means_no_gateway() -> None:
    """The old tool passed `parallel or None` before `coerce_parallel` ever ran, so
    `parallel={}` meant "no gateway", not a validation error."""
    req = ForgeBuildWorkflowRequest(flow_id="F1", steps=[["Draft", None]], parallel={})
    assert req.parallel is None


def test_a_non_dict_parallel_shape_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ForgeBuildWorkflowRequest(flow_id="F1", steps=[], parallel=["not", "a dict"])


def test_a_missing_required_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ForgeBuildWorkflowRequest(steps=[])  # ty: ignore[missing-argument]
