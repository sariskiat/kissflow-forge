"""`app.application.use_cases.flow._gates`: ported from `tests/test_client.py`'s
`_parallel_branches`/`_resolve_activity_by_name` coverage, now raising
`ApplicationError` instead of returning `Err` (spec G6's mapping for
`Err("verify")`; spec G11, Stage D group `d3_flow_workflow`)."""

from __future__ import annotations

import pytest

from app.application.exceptions import VERIFY_FAILED, ApplicationError
from app.application.use_cases.flow._gates import (
    _describe_owner,
    _parallel_branches,
    _resolve_activity_by_name,
)
from app.domain.entities.flow_draft import FlowDraft


def _bare_process_draft(version: str = "v1") -> dict:
    return {
        "Root": "M1",
        "_meta_version": version,
        "M1": {"Id": "M1", "Kind": "Model", "Name": "P", "FlowType": "Process"},
    }


def _process_with_branches() -> dict:
    return (
        FlowDraft.from_wire(_bare_process_draft())
        .build_workflow(
            [("Intake", None)],
            parallel=(
                "Route",
                [
                    ("Branch A", [("Shared Step", None)]),
                    ("Branch B", [("Shared Step", None)]),
                ],
            ),
            parallel_after=0,
        )
        .to_wire()
    )


def test_parallel_branches_maps_name_to_process_def_id() -> None:
    wire = _process_with_branches()
    branches = _parallel_branches(wire)
    assert set(branches) == {"Branch A", "Branch B"}


def test_parallel_branches_raises_when_there_is_no_gateway_at_all() -> None:
    wire = (
        FlowDraft.from_wire(_bare_process_draft())
        .ensure_process_def(("Review",))
        .to_wire()
    )
    with pytest.raises(ApplicationError) as exc_info:
        _parallel_branches(wire)
    assert exc_info.value.code == VERIFY_FAILED
    assert "exactly one Parallel gateway" in exc_info.value.message


def test_parallel_branches_raises_on_a_duplicate_branch_name() -> None:
    """`build_workflow` itself refuses to ever WRITE two same-named branches --
    this guards a hand-edited or externally-modified draft that got one anyway."""
    wire = _process_with_branches()
    branch_b_pd_id = next(
        v["Id"]
        for v in wire.values()
        if isinstance(v, dict)
        and v.get("Kind") == "ProcessDef"
        and v.get("Name") == "Branch B"
    )
    wire[branch_b_pd_id]["Name"] = "Branch A"

    with pytest.raises(ApplicationError) as exc_info:
        _parallel_branches(wire)
    assert exc_info.value.code == VERIFY_FAILED
    assert "ambiguous branch name" in exc_info.value.message


def test_resolve_activity_by_name_finds_the_one_match() -> None:
    wire = _process_with_branches()
    activity_id = _resolve_activity_by_name(wire, "Intake")
    assert wire[activity_id]["Name"] == "Intake"


def test_resolve_activity_by_name_raises_on_no_match() -> None:
    wire = _process_with_branches()
    with pytest.raises(ApplicationError) as exc_info:
        _resolve_activity_by_name(wire, "Nope")
    assert exc_info.value.code == VERIFY_FAILED
    assert "no workflow step named" in exc_info.value.message


def test_resolve_activity_by_name_raises_on_ambiguity_naming_every_branch() -> None:
    wire = _process_with_branches()
    with pytest.raises(ApplicationError) as exc_info:
        _resolve_activity_by_name(wire, "Shared Step")
    message = exc_info.value.message
    assert exc_info.value.code == VERIFY_FAILED
    assert "ambiguous" in message
    assert "Branch A" in message and "Branch B" in message
    assert "branch_name" in message


def test_ambiguous_message_uses_an_em_dash_not_a_double_hyphen() -> None:
    """Restores the old refusal's exact punctuation (brief_d13_fix.md fix 5):
    `is ambiguous -- it exists in` must read `is ambiguous — it exists in`."""
    wire = _process_with_branches()
    with pytest.raises(ApplicationError) as exc_info:
        _resolve_activity_by_name(wire, "Shared Step")
    assert "is ambiguous — it exists in" in exc_info.value.message
    assert "is ambiguous -- it exists in" not in exc_info.value.message


def test_resolve_activity_by_name_scoped_to_one_process_def_is_unambiguous() -> None:
    wire = _process_with_branches()
    branches = _parallel_branches(wire)
    activity_id = _resolve_activity_by_name(
        wire, "Shared Step", process_def_id=branches["Branch A"]
    )
    assert wire[activity_id]["ProcessDef"] == branches["Branch A"]


def test_describe_owner_names_the_root_chain() -> None:
    wire = _process_with_branches()
    root_pd_id = next(
        k
        for k, v in wire.items()
        if isinstance(v, dict)
        and v.get("Kind") == "ProcessDef"
        and v.get("WorkflowType") == "Sequence"
    )
    assert _describe_owner(wire, root_pd_id) == "the root chain"


def test_describe_owner_falls_back_to_the_raw_id() -> None:
    assert _describe_owner({}, "NotARealId") == "ProcessDef 'NotARealId'"
