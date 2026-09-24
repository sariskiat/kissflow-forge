"""Direct unit tests for a representative sample of `app.domain.entities._flow_ops`.

The bulk of this private module's coverage is already indirect, through every
`FlowDraft` method's own tests in `test_flow_draft.py` (each method delegates
straight to one of these functions). This file adds DIRECT tests for the
small, pure, standalone helpers that are easiest to pin in isolation and are
not otherwise exercised on their own: id minting, the row-grid tiler, the
dangling-reference sweep, and the workflow walk. `nodes_of_kind` is the one
PUBLIC name this module exports for `infrastructure/kissflow/client.py` to
import directly (G9 review: it used to reach the private `_kind`); the other
former private helper client.py imported, the style-wire normalizer, moved to
`app.domain.value_objects.style.style_wire_value` (see test_style.py there)
since it carries no node-graph or entity state of its own.
"""

from __future__ import annotations

from app.domain.entities._flow_ops import (
    ROW_UNITS,
    _build_goto_gate,
    _build_workflow,
    _field_delete_blockers,
    _model_id,
    _new_id,
    _now,
    _remove_condition,
    _rewire_condition,
    _sweep_dangling,
    _tile_into_rows,
    _walk_workflow,
    _write_style_props,
    nodes_of_kind,
    validate_layout_spans,
)


def test_model_id_returns_the_root_key() -> None:
    draft = {"Root": "M1", "M1": {"Id": "M1", "Kind": "Model"}}

    assert _model_id(draft) == "M1"


def test_model_id_raises_on_a_missing_root() -> None:
    import pytest

    with pytest.raises(ValueError, match="Root"):
        _model_id({"not_a_flow": True})


def test_model_id_raises_when_root_points_at_nothing() -> None:
    import pytest

    with pytest.raises(ValueError, match="Root"):
        _model_id({"Root": "M1"})


def test_new_id_is_deterministic() -> None:
    a = _new_id("Field", "M1", 0, "Ticket No")
    b = _new_id("Field", "M1", 0, "Ticket No")

    assert a == b
    assert a.startswith("Field_")


def test_new_id_differs_on_any_input_changing() -> None:
    base = _new_id("Field", "M1", 0, "Ticket No")

    assert _new_id("Column", "M1", 0, "Ticket No") != base
    assert _new_id("Field", "M2", 0, "Ticket No") != base
    assert _new_id("Field", "M1", 1, "Ticket No") != base
    assert _new_id("Field", "M1", 0, "Other Name") != base


def test_tile_into_rows_packs_three_per_row() -> None:
    cols = [f"Column_{i}" for i in range(7)]

    rows = _tile_into_rows(cols)

    assert len(rows) == 3  # 3 + 3 + 1
    assert [c for c, _s, _e in rows[0]] == cols[:3]
    assert rows[0] == [("Column_0", 0, 2), ("Column_1", 2, 4), ("Column_2", 4, 6)]
    assert rows[-1] == [("Column_6", 0, 2)]


def test_tile_into_rows_empty_input_is_no_rows() -> None:
    assert _tile_into_rows([]) == []


def test_now_returns_a_millisecond_iso_timestamp() -> None:
    ts = _now()

    assert ts.endswith("Z")
    assert "T" in ts
    assert len(ts) == len("2026-01-01T00:00:00.000Z")


def test_write_style_props_merges_and_removes_none() -> None:
    node: dict = {"Value": {"Section.Bg.Color": {"ref": "Color.Info.300"}}}

    _write_style_props(node, {"Section.Fg.Color": "Color.Dark.900"})
    assert node["Value"] == {
        "Section.Bg.Color": {"ref": "Color.Info.300"},
        "Section.Fg.Color": {"ref": "Color.Dark.900"},
    }

    _write_style_props(node, {"Section.Bg.Color": None, "Section.Fg.Color": None})
    assert "Value" not in node, "an emptied Value is removed, not left as {}"


def test_sweep_dangling_drops_a_backref_to_a_missing_node() -> None:
    draft = {
        "Column_1": {
            "Id": "Column_1",
            "Kind": "Column",
            "Column::Permission": ["Permission_gone", "Permission_still_here"],
        },
        "Permission_still_here": {"Id": "Permission_still_here", "Kind": "Permission"},
    }

    _sweep_dangling(draft)

    assert draft["Column_1"]["Column::Permission"] == ["Permission_still_here"]


def test_sweep_dangling_drops_the_whole_key_when_every_target_is_gone() -> None:
    draft = {
        "Column_1": {
            "Id": "Column_1",
            "Kind": "Column",
            "Column::Permission": ["Permission_gone"],
        },
    }

    _sweep_dangling(draft)

    assert "Column::Permission" not in draft["Column_1"]


def test_sweep_dangling_leaves_non_relation_lists_alone() -> None:
    draft = {
        "Permission_1": {
            "Id": "Permission_1",
            "Kind": "Permission",
            "Permission": ["Editable"],  # a plain data list, no "::" -- not a ref
        },
    }

    _sweep_dangling(draft)

    assert draft["Permission_1"]["Permission"] == ["Editable"]


def test_nodes_of_kind_filters_by_the_kind_key() -> None:
    draft = {
        "Field_1": {"Id": "Field_1", "Kind": "Field"},
        "Column_1": {"Id": "Column_1", "Kind": "Column"},
        "Field_2": {"Id": "Field_2", "Kind": "Field"},
        "not_a_node": "just a string",
    }

    assert set(nodes_of_kind(draft, "Field")) == {"Field_1", "Field_2"}


def test_walk_workflow_positions_the_root_chain_in_order() -> None:
    draft = {
        "PD1": {
            "Id": "PD1",
            "Kind": "ProcessDef",
            "WorkflowType": "Sequence",
            "ProcessDef::Activity": ["A1", "A2", "A3"],
        },
        "A1": {"Id": "A1", "Kind": "Activity"},
        "A2": {"Id": "A2", "Kind": "Activity"},
        "A3": {"Id": "A3", "Kind": "Activity"},
    }

    pos, branch = _walk_workflow(draft)

    assert pos == {"A1": 0, "A2": 1, "A3": 2}
    assert branch == {"A1": None, "A2": None, "A3": None}


def test_walk_workflow_shares_the_parallels_own_index_across_every_branch() -> None:
    draft = {
        "PD1": {
            "Id": "PD1",
            "Kind": "ProcessDef",
            "WorkflowType": "Sequence",
            "ProcessDef::Activity": ["A1", "Par"],
        },
        "A1": {"Id": "A1", "Kind": "Activity"},
        "Par": {
            "Id": "Par",
            "Kind": "Activity",
            "NodeType": "Parallel",
            "Activity::ProcessDef": ["BranchA", "BranchB"],
        },
        "BranchA": {
            "Id": "BranchA",
            "Kind": "ProcessDef",
            "ProcessDef::Activity": ["A2"],
        },
        "BranchB": {
            "Id": "BranchB",
            "Kind": "ProcessDef",
            "ProcessDef::Activity": ["A3"],
        },
        "A2": {"Id": "A2", "Kind": "Activity"},
        "A3": {"Id": "A3", "Kind": "Activity"},
    }

    pos, branch = _walk_workflow(draft)

    assert pos["A2"] == pos["A3"] == pos["Par"] == 1
    assert branch["A2"] == "BranchA"
    assert branch["A3"] == "BranchB"
    assert branch["Par"] is None


def test_walk_workflow_raises_when_there_is_no_single_root_processdef() -> None:
    import pytest

    with pytest.raises(ValueError, match="exactly one root ProcessDef"):
        _walk_workflow({})


def test_row_units_is_six() -> None:
    # ROW_UNITS is re-exported publicly off FlowDraft too (see test_flow_draft.py);
    # pinned here as well since every tiling helper in this module is built on it.
    assert ROW_UNITS == 6


# --- G9 review: refusal-message word-glue regression tests ------------------------
#
# The E501 reflow that split these f-strings across lines dropped the trailing
# space at several implicit-concatenation boundaries. Each test below pins the
# exact rendered sentence -- with the space -- at every boundary this task repaired.


def test_validate_layout_spans_message_on_a_double_placement() -> None:
    import pytest

    layout = {"Section": [[("f1", 0, 2)], [("f1", 2, 4)]]}

    with pytest.raises(ValueError) as exc_info:
        validate_layout_spans(layout)

    message = str(exc_info.value)
    assert "and again at 'Section' row 1" in message
    assert "so the second placement leaves that Column" in message
    assert "its own Row back-ref names only one" in message


def test_validate_layout_spans_message_on_an_out_of_range_span() -> None:
    import pytest

    layout = {"Section": [[("f1", 0, 10)]]}

    with pytest.raises(ValueError) as exc_info:
        validate_layout_spans(layout)

    message = str(exc_info.value)
    assert "row 0 at (Start=0, End=10)" in message
    assert "a 6-unit grid, so every span must satisfy" in message


def test_field_delete_blockers_message() -> None:
    from app.domain.entities.flow_draft import FlowDraft
    from app.domain.value_objects.field_spec import FieldSpec
    from app.domain.value_objects.field_type import FieldType

    wire = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Form"},
    }
    wire = (
        FlowDraft.from_wire(wire)
        .apply_changes(
            [
                FieldSpec(name="Total", type=FieldType.NUMBER),
                FieldSpec(name="Qty", type=FieldType.NUMBER),
            ]
        )
        .to_wire()
    )
    wire = (
        FlowDraft.from_wire(wire)
        .set_field_computed("Total", {"fn": "concatenate", "args": [{"field": "Qty"}]})
        .to_wire()
    )

    blockers = _field_delete_blockers(wire, fields=("Qty",))

    assert len(blockers) == 1
    assert "survives this delete" in blockers[0]
    assert "goto gate or another field's computed formula" in blockers[0]


def test_build_workflow_message_on_a_duplicate_branch_name() -> None:
    import pytest

    branch = ("Approve", [("Review", None)])
    parallels = [
        (("Fork1", [branch]), 0),
        (("Fork2", [branch]), 0),
    ]

    with pytest.raises(ValueError) as exc_info:
        _build_workflow({}, steps=[], parallels=parallels)

    message = str(exc_info.value)
    assert "so two branches sharing a name would collide" in message
    assert "silently overwriting one branch's ProcessDef" in message
    assert "make the branch-local rework-loop derivation ambiguous" in message
    assert "refusing rather than silently overwriting" in message


def test_remove_condition_message_on_a_property_owned_expression() -> None:
    import pytest

    draft = {"Expr1": {"Id": "Expr1", "Kind": "Expression", "Property": "SeqPrefix"}}

    with pytest.raises(ValueError) as exc_info:
        _remove_condition(draft, expression_id="Expr1")

    message = str(exc_info.value)
    assert "value-generator prefix, not a branch/goto condition" in message
    assert "remove_condition only removes ProcessDef or Activity conditions" in message


def test_build_goto_gate_message_on_a_non_boolean_field() -> None:
    import pytest

    draft = {
        "Act1": {"Id": "Act1", "Kind": "Activity"},
        "Field1": {"Id": "Field1", "Kind": "Field", "Type": "Select"},
    }

    with pytest.raises(ValueError) as exc_info:
        _build_goto_gate(draft, goto_activity_id="Act1", field_id="Field1")

    message = str(exc_info.value)
    assert "not Boolean — gate polarity rule: never gate a loop" in message
    assert "only ever on a Boolean (CLAUDE.md Gate polarity)" in message


def test_rewire_condition_message_on_a_property_owned_expression() -> None:
    import pytest

    draft = {
        "Expr1": {"Id": "Expr1", "Kind": "Expression", "Property": "SeqPrefix"},
        "Field1": {"Id": "Field1", "Kind": "Field"},
    }

    with pytest.raises(ValueError) as exc_info:
        _rewire_condition(draft, expression_id="Expr1", new_field_id="Field1")

    message = str(exc_info.value)
    assert "value-generator prefix, not a branch/goto condition" in message
    assert "rewire_condition only rewires ProcessDef or Activity conditions" in message


def _minimal_condition_draft(owner_key: str, owner_id: str) -> dict:
    return {
        "Expr1": {
            "Id": "Expr1",
            "Kind": "Expression",
            owner_key: owner_id,
            "Expression::Node": ["Root1"],
        },
        "Root1": {
            "Id": "Root1",
            "Kind": "Node",
            "Node::Node": ["FieldNode1", "LitNode1"],
        },
        "FieldNode1": {
            "Id": "FieldNode1",
            "Kind": "Node",
            "Type": "Field",
            "Field": "OldField",
        },
        "LitNode1": {"Id": "LitNode1", "Kind": "Node", "Type": "Static"},
    }


def test_rewire_condition_message_on_a_non_boolean_goto_target() -> None:
    import pytest

    draft = _minimal_condition_draft("Activity", "Act1")
    draft["NewField"] = {"Id": "NewField", "Kind": "Field", "Type": "Text"}

    with pytest.raises(ValueError) as exc_info:
        _rewire_condition(draft, expression_id="Expr1", new_field_id="NewField")

    message = str(exc_info.value)
    assert "not Boolean — gate polarity rule: a goto condition" in message
    assert "may only be rewired onto a Boolean field" in message


def test_rewire_condition_message_on_an_uncaptured_branch_type() -> None:
    import pytest

    draft = _minimal_condition_draft("ProcessDef", "PD1")
    draft["NewField"] = {"Id": "NewField", "Kind": "Field", "Type": "Number"}

    with pytest.raises(ValueError) as exc_info:
        _rewire_condition(draft, expression_id="Expr1", new_field_id="NewField")

    message = str(exc_info.value)
    assert (
        "no captured wire DataType for a branch-condition string comparison" in message
    )
    assert "(captured: ['Select', 'Text'])" in message
