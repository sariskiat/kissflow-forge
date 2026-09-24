"""`app.application.use_cases.flow._workflow`: ported from
`tests/test_client.py`'s `_sequence_step_stamps` coverage (spec G11, Stage D
group `d3_flow_workflow`)."""

from __future__ import annotations

from tests.synthetic import synthetic_process_draft

from app.application.use_cases.flow._workflow import _sequence_step_stamps
from app.domain.entities.flow_draft import FlowDraft


def _first_section_and_step(draft: dict) -> tuple[str, str]:
    section = next(
        v["Name"]
        for v in draft.values()
        if isinstance(v, dict)
        and v.get("Kind") == "Column"
        and v.get("Type") == "Section"
        and v.get("Name")
    )
    step = next(
        v["Name"]
        for v in draft.values()
        if isinstance(v, dict)
        and v.get("Kind") == "Activity"
        and v.get("NodeType") == "UserTask"
    )
    return section, step


def test_resolves_a_live_stamp_to_its_step_name() -> None:
    draft = synthetic_process_draft()
    section, step = _first_section_and_step(draft)
    with_seq = (
        FlowDraft.from_wire(draft)
        .add_sequence_number("Case ID", section, "CS-", "0001", step)
        .to_wire()
    )

    stamps = _sequence_step_stamps(with_seq)
    assert stamps["Case ID"] == step


def test_a_stamp_pointing_at_no_real_activity_resolves_to_none() -> None:
    """A dangling Step property (the activity id it holds is not a node in this
    draft) is THE deterministic publish failure this exists to surface, not to
    hide."""
    draft = synthetic_process_draft()
    section, step = _first_section_and_step(draft)
    with_seq = FlowDraft.from_wire(draft).add_sequence_number(
        "Case ID", section, "CS-", "0001", step
    )
    wire = with_seq.to_wire()
    for node in wire.values():
        if (
            isinstance(node, dict)
            and node.get("Kind") == "Field"
            and node.get("Type") == "SequenceNumber"
        ):
            for pid in node.get("Field::Property") or []:
                prop = wire.get(pid)
                if isinstance(prop, dict) and prop.get("Name") == "Step":
                    prop["Value"] = "Activity_does_not_exist"

    stamps = _sequence_step_stamps(wire)
    assert stamps["Case ID"] is None


def test_a_draft_with_no_sequence_number_field_returns_an_empty_map() -> None:
    stamps = _sequence_step_stamps(synthetic_process_draft())
    assert stamps == {}
