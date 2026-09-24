"""Unit tests for app.domain.entities.flow_draft.FlowDraft.

Merged (G9b) from the pre-refactor test_graph.py, test_expr.py and
test_verify.py (the FlowDraft-method parts; `expression_owner`'s own tests
live in tests/unit/domain/value_objects/test_expression.py) and
test_section_layout.py (`FlowDraft.section_layout()`'s own fact-base pin).
Every assertion moved verbatim; only the call convention changed, from a
bare `graph.fn(draft, ...)` / `expr.fn(draft, ...)` / `verify.doctor(draft)`
to `FlowDraft.from_wire(draft).fn(...)`. The round-trip invariant over every
JSON file in tests/fixtures/*.json and shapes/*.json, from_wire's defensive
copy, to_wire's defensive copy, the `version` read and frozen-ness (this
module's own original tests) come first, unchanged.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import os
import pathlib
import subprocess
import sys
from typing import Any

import pytest

from app.domain.entities.flow_draft import (
    FIELD_SPAN,
    ROW_UNITS,
    DoctorReport,
    FlowDraft,
    field_override_matrix,
    progressive_matrix,
    validate_layout_spans,
)
from app.domain.value_objects.expression import expression_owner
from app.domain.value_objects.field_spec import FieldSpec
from app.domain.value_objects.field_type import FieldType, Visibility

# `tests/synthetic.py` is a shared fixture-builder every top-level test module reaches
# via pytest's own rootdir insertion. This module sits three directories deeper
# (tests/unit/domain/entities/), past the point where that chain runs out
# (tests/unit/ carries no __init__.py yet -- G14 owns adding the rest of that
# chain), so it is not on sys.path by that mechanism. Added explicitly, once,
# rather than duplicating synthetic.py's fixtures here.
_TESTS_ROOT = pathlib.Path(__file__).resolve().parents[3]
if str(_TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TESTS_ROOT))

from synthetic import OWNERS, synthetic_process_draft, with_goto_and_event  # noqa: E402

Draft = dict[str, Any]


# =====================================================================================
# FlowDraft.from_wire / to_wire / version / frozen-ness (original G9-step-0 tests)
# =====================================================================================


ROOT = pathlib.Path(__file__).resolve().parents[4]


def _json_files() -> list[pathlib.Path]:
    fixtures = sorted((ROOT / "tests" / "fixtures").glob("*.json"))
    shapes = sorted((ROOT / "shapes").glob("*.json"))
    return fixtures + shapes


_FILES = _json_files()
_IDS = [str(p.relative_to(ROOT)) for p in _FILES]


def test_json_files_found() -> None:
    # Guards every parametrized case below against silently collecting zero
    # cases if the globs ever stop matching anything.
    assert len(_FILES) > 0


@pytest.mark.parametrize("path", _FILES, ids=_IDS)
def test_round_trip_is_byte_equal(path: pathlib.Path) -> None:
    with path.open(encoding="utf-8") as f:
        d = json.load(f)

    assert json.dumps(FlowDraft.from_wire(d).to_wire()) == json.dumps(d)


def test_from_wire_copies_its_input() -> None:
    wire = {"Field_Sample01": {"Name": "original"}}
    draft = FlowDraft.from_wire(wire)

    wire["Field_Sample01"]["Name"] = "mutated"
    wire["Field_Sample02"] = {"Name": "added after the call"}

    assert draft.nodes == {"Field_Sample01": {"Name": "original"}}


def test_to_wire_returns_a_copy() -> None:
    draft = FlowDraft.from_wire({"Field_Sample01": {"Name": "original"}})
    wire = draft.to_wire()

    wire["Field_Sample01"]["Name"] = "mutated"
    wire["Field_Sample02"] = {"Name": "added after the call"}

    assert draft.nodes == {"Field_Sample01": {"Name": "original"}}


def test_version_reads_meta_version() -> None:
    draft = FlowDraft.from_wire({"_meta_version": "17"})

    assert draft.version == "17"


def test_version_is_none_when_the_graph_carries_none() -> None:
    draft = FlowDraft.from_wire({"Field_Sample01": {"Name": "original"}})

    assert draft.version is None


def test_is_frozen() -> None:
    draft = FlowDraft.from_wire({})

    with pytest.raises(dataclasses.FrozenInstanceError):
        draft.nodes = {"changed": True}  # ty: ignore[invalid-assignment]


# =====================================================================================
# graph.py -> FlowDraft (moved from test_graph.py)
# =====================================================================================


FIXTURE = _TESTS_ROOT / "fixtures" / "form_draft.json"
MODEL_ID = "TestForm_x001"


def _load() -> dict:
    return json.loads(FIXTURE.read_text())


def test_add_field_creates_valid_wired_node():
    draft = _load()
    before = set(draft[MODEL_ID]["Model::Field"])

    new = (
        FlowDraft.from_wire(draft)
        .apply_changes([FieldSpec(name="Notes", type=FieldType.TEXT, required=False)])
        .to_wire()
    )

    added = set(new[MODEL_ID]["Model::Field"]) - before
    assert len(added) == 1, "exactly one new field id registered on the model"
    fid = added.pop()

    node = new[fid]
    assert node["Kind"] == "Field"
    assert node["Type"] == "Text"
    assert node["Name"] == "Notes"
    assert node.get("Required") is False

    # wired into a real Field column
    col = new[node["Column"]]
    assert col["Kind"] == "Column" and col["Type"] == "Field"
    assert fid in col["Column::Field"]

    # original field untouched
    assert new["field_fullname_a001"]["Name"] == "Full Name"


def test_add_field_roundtrips_through_parse():
    new = (
        FlowDraft.from_wire(_load())
        .apply_changes([FieldSpec(name="Notes", type=FieldType.TEXT)])
        .to_wire()
    )
    fields = FlowDraft.from_wire(new).parse_draft()
    assert any(f.name == "Notes" and f.type == FieldType.TEXT for f in fields)


def test_input_not_mutated():
    draft = _load()
    _ = (
        FlowDraft.from_wire(draft)
        .apply_changes([FieldSpec(name="Notes", type=FieldType.TEXT)])
        .to_wire()
    )
    assert draft[MODEL_ID]["Model::Field"] == ["field_fullname_a001"], (
        "apply_changes must not mutate its input"
    )


def test_user_field_gets_a_querydefinition_sibling():
    """A bare Field{Type:"User"} blocks publish (KISSFLOW_ERROR_04211, #59).
    apply_changes must mint the sibling QueryDefinition and cross-link it, so the
    batch publishes."""
    new = (
        FlowDraft.from_wire(_load())
        .apply_changes([FieldSpec(name="Assigned To", type=FieldType.USER)])
        .to_wire()
    )
    fid = next(
        k for k, v in new.items() if isinstance(v, dict) and v.get("Type") == "User"
    )
    field = new[fid]
    qids = field["Field::QueryDefinition"]
    assert len(qids) == 1
    qd = new[qids[0]]
    assert qd["Kind"] == "QueryDefinition"
    assert qd["FlowType"] == "User" and qd["LHSModel"] == "User"
    assert qd["Field"] == fid  # back-ref points home
    assert (
        "LHSModel" not in field
    )  # LHSModel belongs on the QueryDefinition, not the Field


def test_user_field_lhsmodel_override_lands_on_the_querydefinition():
    new = (
        FlowDraft.from_wire(_load())
        .apply_changes(
            [
                FieldSpec(
                    name="Employee",
                    type=FieldType.USER,
                    options={"LHSModel": "_employee"},
                )
            ],
        )
        .to_wire()
    )
    fid = next(
        k for k, v in new.items() if isinstance(v, dict) and v.get("Type") == "User"
    )
    qd = new[new[fid]["Field::QueryDefinition"][0]]
    assert qd["LHSModel"] == "_employee"
    assert "LHSModel" not in new[fid]


def test_unknown_type_rejected_before_mutation():
    draft = _load()
    with pytest.raises((ValueError, TypeError, KeyError)):
        bad = FieldSpec(name="Bad", type="Frobnicate")  # ty: ignore[invalid-argument-type]  # invalid type may raise here...
        FlowDraft.from_wire(draft).apply_changes(
            [bad]
        ).to_wire()  # ...or here; either way, rejected


def test_bare_process_gets_a_processdef_scaffold() -> None:
    """A bare process draft is unwritable (HTTP 500) until it has a ProcessDef.

    See FINDINGS.md.
    """

    bare = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "P", "FlowType": "Process"},
    }
    got = FlowDraft.from_wire(bare).ensure_process_def(("Submit", "Review")).to_wire()

    pd_id = got["M1"]["RootProcessDef"]
    assert got["M1"]["Model::ProcessDef"] == [pd_id]
    pd = got[pd_id]
    assert pd["Kind"] == "ProcessDef" and pd["WorkflowType"] == "Sequence"

    acts = [got[a] for a in pd["ProcessDef::Activity"]]
    # order IS the workflow: Start, one UserTask per step, Completed
    assert [a["NodeType"] for a in acts] == [
        "StartEvent",
        "UserTask",
        "UserTask",
        "EndEvent",
    ]
    assert [a["Name"] for a in acts] == ["Start", "Submit", "Review", "Completed"]
    assert all(a["ProcessDef"] == pd_id for a in acts)
    assert "Root" in bare and len(bare) == 2, "input draft must not be mutated"


def test_ensure_process_def_is_idempotent() -> None:

    bare = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "P", "FlowType": "Process"},
    }
    once = FlowDraft.from_wire(bare).ensure_process_def(("Submit",)).to_wire()
    twice = FlowDraft.from_wire(once).ensure_process_def(("Submit",)).to_wire()
    assert twice == once, "re-scaffolding an existing process must change nothing"


def test_process_needs_at_least_one_step() -> None:
    import pytest

    bare = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "P", "FlowType": "Process"},
    }
    with pytest.raises(ValueError):
        FlowDraft.from_wire(bare).ensure_process_def(()).to_wire()


def test_fields_can_be_added_on_top_of_a_scaffolded_process() -> None:

    from app.domain.value_objects.field_spec import FieldSpec
    from app.domain.value_objects.field_type import FieldType

    bare = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "P", "FlowType": "Process"},
    }
    got = (
        FlowDraft.from_wire(
            FlowDraft.from_wire(bare).ensure_process_def(("Submit",)).to_wire()
        )
        .apply_changes(
            [FieldSpec(name="Title", type=FieldType.TEXT)],
        )
        .to_wire()
    )
    assert "Title" in FlowDraft.from_wire(got).field_names()
    assert got["M1"]["RootProcessDef"], "scaffold must survive a field add"


def test_every_flow_gets_an_appearance_node() -> None:
    """Without Model::Appearance the BUILDER renders "There was an error / Reload"
    (live, 2026-08-03).
    The API accepts and publishes a flow without it, so only the UI catches this — hence
    the test.
    """

    from app.domain.value_objects.field_spec import FieldSpec
    from app.domain.value_objects.field_type import FieldType

    bare = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Form"},
    }
    got = (
        FlowDraft.from_wire(bare)
        .apply_changes([FieldSpec(name="A", type=FieldType.TEXT)])
        .to_wire()
    )

    app_ids = got["M1"]["Model::Appearance"]
    assert len(app_ids) == 1
    appearance = got[app_ids[0]]
    assert appearance["Kind"] == "Appearance" and appearance["Model"] == "M1"
    style = got[appearance["Appearance::Style"][0]]
    assert style["Kind"] == "Style" and style["Appearance"] == app_ids[0]


def test_scaffolded_process_has_appearance_and_button_row() -> None:

    bare = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "P", "FlowType": "Process"},
    }
    m = FlowDraft.from_wire(bare).ensure_process_def(("Submit",)).to_wire()["M1"]
    assert m["Model::Appearance"] and m["Button::Row"], (
        "the builder UI needs both to render"
    )


# ---- clone_template_shell (issue #59 — process-template identity/initiate shell)
# -------------


def _bare_process() -> dict:
    return {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "P", "FlowType": "Process"},
    }


def test_clone_template_shell_grafts_identity_fields_and_manager_approve() -> None:

    got = FlowDraft.from_wire(_bare_process()).clone_template_shell().to_wire()
    m = got["M1"]

    assert m["RootProcessDef"], (
        "clone must scaffold a real ProcessDef, same contract as ensure_process_def"
    )
    field_ids = m.get("Model::Field", [])
    assert len(field_ids) == 28, "the identity/initiate shell carries 28 fields"
    names = {got[fid]["Name"] for fid in field_ids}
    assert "Manager Display Name" in names
    # "Branch" is a BARE name now. It used to ship as "Branch (TODO: was a Reference
    # field ...)" — a developer note published as a user-facing label on every
    # from_template=True process. The reconnect notes live in the shape's own `notes`;
    # verify.doctor rule 7c flags any that come back.
    assert "Branch" in names
    assert not any("TODO:" in n for n in names), sorted(
        n for n in names if "TODO:" in n
    )

    pd = got[m["RootProcessDef"]]
    acts = [got[a] for a in pd["ProcessDef::Activity"]]
    assert [a["NodeType"] for a in acts] == ["StartEvent", "UserTask", "EndEvent"]
    assert acts[1]["Name"] == "Manager Approve"


def test_clone_template_shell_has_a_complete_style_chain() -> None:

    got = FlowDraft.from_wire(_bare_process()).clone_template_shell().to_wire()
    m = got["M1"]
    app_ids = m["Model::Appearance"]
    assert len(app_ids) == 1
    appearance = got[app_ids[0]]
    assert appearance["Kind"] == "Appearance" and appearance["Model"] == "M1"
    style_ids = appearance["Appearance::Style"]
    assert len(style_ids) == 1, (
        "an EMPTY Appearance::Style breaks render just as badly as a missing chain"
    )
    style = got[style_ids[0]]
    assert style["Kind"] == "Style" and style["Appearance"] == app_ids[0]
    assert m["Button::Row"], "the builder UI needs Button::Row too"


def test_clone_template_shell_is_idempotent() -> None:

    once = FlowDraft.from_wire(_bare_process()).clone_template_shell().to_wire()
    twice = FlowDraft.from_wire(once).clone_template_shell().to_wire()
    assert twice == once, (
        "re-cloning onto an already-scaffolded process must change nothing"
    )


def test_clone_template_shell_does_not_mutate_input() -> None:

    bare = _bare_process()
    _ = FlowDraft.from_wire(bare).clone_template_shell().to_wire()
    assert bare == {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "P", "FlowType": "Process"},
    }


def test_two_independent_clones_never_collide_ids() -> None:

    a = FlowDraft.from_wire(_bare_process()).clone_template_shell().to_wire()
    b = FlowDraft.from_wire(_bare_process()).clone_template_shell().to_wire()
    overlap = (set(a) & set(b)) - {"Root", "M1"}
    assert not overlap, f"two from_template clones minted colliding ids: {overlap}"


def test_clone_template_shell_missing_template_file_raises() -> None:

    with pytest.raises(ValueError):
        FlowDraft.from_wire(_bare_process()).clone_template_shell(
            template_path="/no/such/file.json"
        ).to_wire()


def test_clone_template_shell_template_path_override(tmp_path) -> None:
    """G9b: the domain reads no environment variable (code_architecture.md — domain is
    stdlib-only, no env reads). The old KF_PROCESS_TEMPLATE fallback this test used to
    cover moved to infrastructure; `template_path` is the surviving, still-domain-level
    lever for a custom template, so this pins that instead."""

    custom = tmp_path / "tiny_template.json"
    custom.write_text(
        json.dumps(
            {
                "kind": "Model",
                "description": "d",
                "source_capture": "x.json",
                "notes": [],
                "template": {
                    "Model_Sample01": {
                        "Id": "Model_Sample01",
                        "Kind": "Model",
                        "Model::Row": [],
                        "Model::Field": ["Field_Sample01"],
                        "Model::ProcessDef": ["ProcessDef_Sample01"],
                        "RootProcessDef": "ProcessDef_Sample01",
                        "Button::Row": [],
                    },
                    "Field_Sample01": {
                        "Id": "Field_Sample01",
                        "Kind": "Field",
                        "Type": "Text",
                        "Model": "Model_Sample01",
                        "Name": "Tiny Field",
                    },
                    "ProcessDef_Sample01": {
                        "Id": "ProcessDef_Sample01",
                        "Kind": "ProcessDef",
                        "WorkflowType": "Sequence",
                        "Model": "Model_Sample01",
                        "ProcessDef::Activity": ["Activity_Sample01"],
                    },
                    "Activity_Sample01": {
                        "Id": "Activity_Sample01",
                        "Kind": "Activity",
                        "NodeType": "StartEvent",
                        "Name": "Start",
                        "ProcessDef": "ProcessDef_Sample01",
                    },
                },
            }
        )
    )
    got = (
        FlowDraft.from_wire(_bare_process())
        .clone_template_shell(template_path=str(custom))
        .to_wire()
    )
    m = got["M1"]
    assert len(m["Model::Field"]) == 1
    assert got[m["Model::Field"][0]]["Name"] == "Tiny Field"


def test_existing_appearance_is_not_duplicated() -> None:

    from app.domain.value_objects.field_spec import FieldSpec
    from app.domain.value_objects.field_type import FieldType

    draft = {
        "Root": "M1",
        "M1": {
            "Id": "M1",
            "Kind": "Model",
            "Name": "F",
            "FlowType": "Form",
            "Model::Appearance": ["Appearance_existing"],
        },
        "Appearance_existing": {
            "Id": "Appearance_existing",
            "Kind": "Appearance",
            "Model": "M1",
        },
    }
    got = (
        FlowDraft.from_wire(draft)
        .apply_changes([FieldSpec(name="A", type=FieldType.TEXT)])
        .to_wire()
    )
    assert got["M1"]["Model::Appearance"] == ["Appearance_existing"]


def test_columns_tile_the_row_grid_and_never_overflow() -> None:
    """A Row is a 6-unit grid holding 3 field columns. Overflowing it breaks the BUILDER
    render.
    Regression: 17 columns once landed in ONE Row on a live process, all at Start=0, and
    the flow stopped rendering entirely ("There was an error / Reload").
    """
    from app.domain.value_objects.field_spec import FieldSpec
    from app.domain.value_objects.field_type import FieldType

    bare = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Form"},
    }
    got = (
        FlowDraft.from_wire(bare)
        .apply_changes(
            [FieldSpec(name=f"f{i}", type=FieldType.TEXT) for i in range(17)]
        )
        .to_wire()
    )

    per_row = ROW_UNITS // FIELD_SPAN
    rows = [n for n in got.values() if isinstance(n, dict) and n.get("Kind") == "Row"]
    checked = 0
    for row in rows:
        cols = [got[c] for c in (row.get("Row::Column") or [])]
        if not cols or any(c.get("Type") != "Field" for c in cols):
            continue  # the section's own row carries a single (0,6) Section column
        checked += 1
        assert len(cols) <= per_row, (
            f"row holds {len(cols)} columns, grid fits {per_row}"
        )
        # slots tile the grid edge to edge, no overlaps, no gaps, never past ROW_UNITS
        assert [(c["Start"], c["End"]) for c in cols] == [
            (i * FIELD_SPAN, (i + 1) * FIELD_SPAN) for i in range(len(cols))
        ]
        assert all(c["End"] <= ROW_UNITS for c in cols)

    field_cols = [
        n
        for n in got.values()
        if isinstance(n, dict)
        and n.get("Kind") == "Column"
        and n.get("Type") == "Field"
    ]
    assert len(field_cols) == 17, "every field still gets its own column"
    assert checked >= 6, (
        "17 fields at 3 per row must span at least 6 rows, not pile into one"
    )


def test_field_nodes_carry_the_model_backreference() -> None:
    """Every field Kissflow writes has Model + CreatedAt. Without Model the BUILDER
    won't render.
    Caught by diffing an API-built process against a UI-built COPY of it (2026-08-03):
    the API accepted and published fields with no Model, so only the builder exposed the
    defect.
    """

    from app.domain.value_objects.field_spec import FieldSpec
    from app.domain.value_objects.field_type import FieldType

    bare = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Form"},
    }
    got = (
        FlowDraft.from_wire(bare)
        .apply_changes([FieldSpec(name="A", type=FieldType.TEXT)])
        .to_wire()
    )
    fields = [
        n for n in got.values() if isinstance(n, dict) and n.get("Kind") == "Field"
    ]

    assert len(fields) == 1
    assert fields[0]["Model"] == "M1"
    assert fields[0]["CreatedAt"].endswith("Z")
    assert fields[0]["Id"].startswith("Field_"), (
        "Kissflow's own node ids are capitalised"
    )


def test_per_type_defaults_match_what_the_builder_writes() -> None:

    from app.domain.value_objects.field_spec import FieldSpec
    from app.domain.value_objects.field_type import FieldType

    bare = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Form"},
    }
    got = (
        FlowDraft.from_wire(bare)
        .apply_changes(
            [
                FieldSpec(name="notes", type=FieldType.TEXTAREA),
                FieldSpec(name="amount", type=FieldType.NUMBER),
                FieldSpec(name="file", type=FieldType.ATTACHMENT),
                FieldSpec(name="plain", type=FieldType.TEXT),
            ],
        )
        .to_wire()
    )
    by_name = {
        n["Name"]: n
        for n in got.values()
        if isinstance(n, dict) and n.get("Kind") == "Field"
    }

    # Number carries the builder's own defaults; the oracle has them too.
    assert (
        by_name["amount"]["DefaultValue"] == "0"
        and by_name["amount"]["Decimalpoint"] == "2"
    )
    # Textarea AllowFormatting and Attachment CaptureOnly are OPT-IN now: the UI-built
    # oracle carries neither key on a fresh field, so a default of False was an extra
    # key it did not have.
    assert "AllowFormatting" not in by_name["notes"]
    assert "CaptureOnly" not in by_name["file"]
    # a plain Text field gets no type-specific extras
    assert not {"AllowFormatting", "Decimalpoint", "CaptureOnly"} & set(
        by_name["plain"]
    )


def test_field_options_pass_through_verbatim_to_the_node() -> None:
    """Opt-in per-type keys (AllowFormatting/CaptureOnly) land on the Field node as
    given.
    The oracle has TWO Textarea populations: plain ones OMIT AllowFormatting, canvas
    ones carry `AllowFormatting=False`. Default-omit handles the first; opt-in options
    handle the second.
    """

    from app.domain.value_objects.field_spec import FieldSpec
    from app.domain.value_objects.field_type import FieldType

    bare = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Form"},
    }
    got = (
        FlowDraft.from_wire(bare)
        .apply_changes(
            [
                FieldSpec(
                    name="canvas",
                    type=FieldType.TEXTAREA,
                    options={"AllowFormatting": False},
                ),
                FieldSpec(name="plain", type=FieldType.TEXTAREA),
                FieldSpec(
                    name="upload",
                    type=FieldType.ATTACHMENT,
                    options={"CaptureOnly": False},
                ),
            ],
        )
        .to_wire()
    )
    by_name = {
        n["Name"]: n
        for n in got.values()
        if isinstance(n, dict) and n.get("Kind") == "Field"
    }
    assert by_name["canvas"]["AllowFormatting"] is False
    assert "AllowFormatting" not in by_name["plain"]  # default stays omit
    assert by_name["upload"]["CaptureOnly"] is False


def _draft_with_fields(*names: str) -> dict:
    d = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Form"},
    }

    from app.domain.value_objects.field_spec import FieldSpec
    from app.domain.value_objects.field_type import FieldType

    return (
        FlowDraft.from_wire(d)
        .apply_changes([FieldSpec(name=n, type=FieldType.TEXT) for n in names])
        .to_wire()
    )


def test_regroup_puts_each_field_in_its_named_section() -> None:

    got = (
        FlowDraft.from_wire(_draft_with_fields("a", "b", "c", "d"))
        .regroup_into_sections(
            [("Step 1", ["a", "b"]), ("Step 2", ["c", "d"])],
        )
        .to_wire()
    )

    placed: dict[str, list[str]] = {}
    for top in got["M1"]["Model::Row"]:
        sec = got[got[top]["Row::Column"][0]]
        names = []
        for r in sec["Column::Row"]:
            for c in got[r]["Row::Column"]:
                names += [got[f]["Name"] for f in got[c]["Column::Field"]]
        placed[sec["Name"]] = names

    assert placed == {"Step 1": ["a", "b"], "Step 2": ["c", "d"]}


def test_regroup_creates_an_empty_banner_section_in_place() -> None:
    """An empty `names` group is a banner section (header + description, no fields).
    It must be created (not skipped) and keep its position in `plan`, so a banner
    placed between two field sections lands between them in Model::Row — learned
    from the golden FDE-Log banner."""

    got = (
        FlowDraft.from_wire(_draft_with_fields("a", "b"))
        .regroup_into_sections(
            [("Before", ["a"]), ("Banner", []), ("After", ["b"])],
        )
        .to_wire()
    )
    sections = [got[got[t]["Row::Column"][0]]["Name"] for t in got["M1"]["Model::Row"]]
    assert sections == ["Before", "Banner", "After"], sections
    banner = got[got[got["M1"]["Model::Row"][1]]["Row::Column"][0]]
    assert banner["Type"] == "Section" and banner["Name"] == "Banner"
    assert banner["Column::Row"] == [], "a banner section has no field rows"


def test_regroup_never_drops_an_unlisted_field() -> None:

    got = (
        FlowDraft.from_wire(_draft_with_fields("a", "b", "orphan"))
        .regroup_into_sections([("Step 1", ["a", "b"])])
        .to_wire()
    )
    assert "orphan" in FlowDraft.from_wire(got).field_names()
    sections = [got[got[t]["Row::Column"][0]]["Name"] for t in got["M1"]["Model::Row"]]
    assert "Other" in sections, "unlisted fields must still be laid out somewhere"


def test_regroup_preserves_field_and_column_ids() -> None:
    """Rebuilding layout must not re-mint Field/Column ids.

    Per-step Permissions reference them.
    """

    before = _draft_with_fields("a", "b")
    ids = {
        n["Name"]: (n["Id"], n["Column"])
        for n in before.values()
        if isinstance(n, dict) and n.get("Kind") == "Field"
    }
    after = (
        FlowDraft.from_wire(before).regroup_into_sections([("S", ["a", "b"])]).to_wire()
    )
    ids2 = {
        n["Name"]: (n["Id"], n["Column"])
        for n in after.values()
        if isinstance(n, dict) and n.get("Kind") == "Field"
    }
    assert ids == ids2


def test_regroup_still_respects_the_row_grid() -> None:

    names = [f"f{i}" for i in range(10)]
    got = (
        FlowDraft.from_wire(_draft_with_fields(*names))
        .regroup_into_sections([("Big", names)])
        .to_wire()
    )
    for n in got.values():
        if isinstance(n, dict) and n.get("Kind") == "Row" and n.get("Column"):
            cols = [got[c] for c in n["Row::Column"]]
            assert len(cols) <= ROW_UNITS // FIELD_SPAN
            assert [(c["Start"], c["End"]) for c in cols] == [
                (i * FIELD_SPAN, (i + 1) * FIELD_SPAN) for i in range(len(cols))
            ]


def test_apply_exact_layout_places_fields_at_stated_coordinates() -> None:
    """The 'I know where every field goes' API: caller states (Start, End) per field,
    engine obeys exactly — full-width, half, and a lone right-aligned field (the
    case auto-tile gets wrong)."""

    base = (
        FlowDraft.from_wire(_draft_with_fields("a", "b", "c", "d"))
        .regroup_into_sections([("S", ["a", "b", "c", "d"])])
        .to_wire()
    )
    layout = {
        "S": [
            [("a", 0, 3), ("b", 3, 6)],  # 2-per-row
            [("c", 0, 6)],  # full-width
            [("d", 3, 6)],  # lone, right-aligned
        ]
    }
    got = FlowDraft.from_wire(base).apply_exact_layout(layout).to_wire()
    sec = next(
        v for v in got.values() if isinstance(v, dict) and v.get("Type") == "Section"
    )
    col_name = {
        f["Column"]: f["Name"]
        for f in got.values()
        if isinstance(f, dict) and f.get("Kind") == "Field"
    }
    rows = [got[r] for r in sec["Column::Row"]]
    assert len(rows) == 3
    coords = {
        col_name[c]: (got[c]["Start"], got[c]["End"])
        for r in rows
        for c in r["Row::Column"]
    }
    assert coords == {"a": (0, 3), "b": (3, 6), "c": (0, 6), "d": (3, 6)}


def test_apply_exact_layout_preserves_field_and_column_ids() -> None:
    """Like regroup, an exact re-layout must not re-mint ids.

    Permissions/Events reference them.
    """

    before = (
        FlowDraft.from_wire(_draft_with_fields("a", "b"))
        .regroup_into_sections([("S", ["a", "b"])])
        .to_wire()
    )
    ids = {
        n["Name"]: (n["Id"], n["Column"])
        for n in before.values()
        if isinstance(n, dict) and n.get("Kind") == "Field"
    }
    after = (
        FlowDraft.from_wire(before)
        .apply_exact_layout({"S": [[("a", 0, 3), ("b", 3, 6)]]})
        .to_wire()
    )
    ids2 = {
        n["Name"]: (n["Id"], n["Column"])
        for n in after.values()
        if isinstance(n, dict) and n.get("Kind") == "Field"
    }
    assert ids == ids2


def test_apply_exact_layout_detaches_a_field_pulled_from_an_unnamed_section() -> None:
    """A field whose current section is NOT named in the layout must leave its old
    row behind: keeping the column listed in both the old section's row and the
    new one is the one-column-two-rows corruption doctor rule 8b exists to flag."""

    base = (
        FlowDraft.from_wire(_draft_with_fields("a", "b"))
        .regroup_into_sections([("A", ["a"]), ("B", ["b"])])
        .to_wire()
    )
    got = (
        FlowDraft.from_wire(base)
        .apply_exact_layout({"B": [[("a", 0, 3), ("b", 3, 6)]]})
        .to_wire()
    )

    owners: dict[str, list[str]] = {}
    for rid, node in got.items():
        if isinstance(node, dict) and node.get("Kind") == "Row":
            for cid in node.get("Row::Column") or []:
                owners.setdefault(cid, []).append(rid)
    assert all(len(rows) == 1 for rows in owners.values()), (
        f"a column is listed by more than one row: {owners}"
    )
    sec_a = next(
        v
        for v in got.values()
        if isinstance(v, dict) and v.get("Type") == "Section" and v.get("Name") == "A"
    )
    for rid in sec_a.get("Column::Row") or []:
        assert rid in got, f"section A lists a row that no longer exists: {rid}"
        assert got[rid].get("Row::Column"), f"section A keeps an emptied row: {rid}"


def _section_rows(
    draft: dict, section_name: str = "S"
) -> list[list[tuple[str, int, int]]]:
    """One inner list per Row of the named section: `(field name, Start, End)` in row
    order.
    Reads the ROW nodes' own `Row::Column` lists, never the draft's dict insertion order
    — the latter is stable regardless and hides an unordered leftover pack completely.
    """
    sec = next(
        v
        for v in draft.values()
        if isinstance(v, dict)
        and v.get("Type") == "Section"
        and v.get("Name") == section_name
    )
    col_name = {
        f["Column"]: f["Name"]
        for f in draft.values()
        if isinstance(f, dict) and f.get("Kind") == "Field"
    }
    return [
        [
            (col_name[c], draft[c]["Start"], draft[c]["End"])
            for c in draft[rid]["Row::Column"]
        ]
        for rid in sec["Column::Row"]
    ]


def test_apply_exact_layout_keeps_unlisted_fields_in_a_trailing_row() -> None:
    """A partial layout spec never drops a field off the form — leftovers go in a
    trailing row, in the section's pre-existing order, tiled on the grid (not
    merely 'present in some order')."""

    base = (
        FlowDraft.from_wire(_draft_with_fields("a", "b", "c"))
        .regroup_into_sections([("S", ["a", "b", "c"])])
        .to_wire()
    )
    got = (
        FlowDraft.from_wire(base).apply_exact_layout({"S": [[("a", 0, 6)]]}).to_wire()
    )  # b and c not named
    assert _section_rows(got) == [
        [("a", 0, 6)],
        [("b", 0, 2), ("c", 2, 4)],  # the trailing leftover row, in the order they sat
    ]


def test_apply_exact_layout_leftovers_never_run_off_the_grid() -> None:
    """#F1: a partial layout is the DOCUMENTED usage, and 5 leftovers used to run off
    the end.
    The old packer added FIELD_SPAN per leftover with no cap, emitting a column at (6,8)
    — one past the 6-unit row — and then one at (8,6) with End < Start. Either breaks
    rendering for the WHOLE flow (CLAUDE.md > Node-graph invariants), from the normal
    path, on 6 ordinary fields.
    """

    names = [
        "Ticket No",
        "Contact Date",
        "Problem",
        "Unit Serial",
        "Urgency",
        "Outcome",
    ]
    base = (
        FlowDraft.from_wire(_draft_with_fields(*names))
        .regroup_into_sections([("Big", names)])
        .to_wire()
    )
    got = (
        FlowDraft.from_wire(base)
        .apply_exact_layout({"Big": [[("Ticket No", 0, ROW_UNITS)]]})
        .to_wire()
    )

    rows = _section_rows(got, "Big")
    assert rows == [
        [("Ticket No", 0, 6)],
        [("Contact Date", 0, 2), ("Problem", 2, 4), ("Unit Serial", 4, 6)],
        [("Urgency", 0, 2), ("Outcome", 2, 4)],
    ]
    for row in rows:  # the invariant itself, stated independently
        assert len(row) <= 3
        for name, start, end in row:
            assert 0 <= start < end <= ROW_UNITS, (name, start, end)


def test_apply_exact_layout_leftover_order_is_deterministic() -> None:
    """The leftovers used to be read out of a `set[str]`, and Python randomizes
    string hashing per process — the SAME input produced a different field order
    on every run. The order must be the section's own pre-existing row/column
    order: the order the user already sees on the form."""

    names = [
        "Ticket No",
        "Contact Date",
        "Problem",
        "Unit Serial",
        "Urgency",
        "Outcome",
    ]
    base = (
        FlowDraft.from_wire(_draft_with_fields(*names))
        .regroup_into_sections([("Big", names)])
        .to_wire()
    )
    spec = {"Big": [[("Ticket No", 0, 6)]]}

    runs = [
        _section_rows(
            FlowDraft.from_wire(base).apply_exact_layout(spec).to_wire(), "Big"
        )
        for _ in range(8)
    ]
    assert all(r == runs[0] for r in runs), runs

    leftover_order = [n for row in runs[0][1:] for n, _, _ in row]
    assert leftover_order == names[1:], (
        "leftovers must keep the section's existing field order"
    )


def test_apply_exact_layout_leftover_order_survives_a_different_hash_seed() -> None:
    """The set-iteration bug is invisible within one process — hashing is randomized
    per PROCESS. Run the same input under two different PYTHONHASHSEEDs and demand
    the same field order."""

    # UP031 stays: the generated source below is full of dict/set literals, so .format()
    # would read every `{` as a placeholder and corrupt the program it builds.
    src = (  # noqa: UP031
        "import json,sys;"
        "sys.path.insert(0, %r);"  # noqa: UP031
        "from app.domain.entities.flow_draft import FlowDraft;"
        "from app.domain.value_objects.field_spec import FieldSpec;"
        "from app.domain.value_objects.field_type import FieldType;"
        "names=['Ticket No','Contact Date','Problem','Unit Serial',"
        "'Urgency','Outcome'];"
        "d={'Root':'M1','M1':{'Id':'M1','Kind':'Model','Name':'F','FlowType':'Form'}};"
        "flow=FlowDraft.from_wire(d)"
        ".apply_changes([FieldSpec(name=n,type=FieldType.TEXT) for n in names])"
        ".regroup_into_sections([('Big',names)])"
        ".apply_exact_layout({'Big':[[('Ticket No',0,6)]]});"
        "g=flow.to_wire();"
        "sec=next(v for v in g.values() if isinstance(v,dict) "
        "and v.get('Type')=='Section');"
        "cn={f['Column']:f['Name'] for f in g.values() "
        "    if isinstance(f,dict) and f.get('Kind')=='Field'};"
        "print(json.dumps([[cn[c] for c in g[r]['Row::Column']] "
        "for r in sec['Column::Row']]))"
    ) % str(pathlib.Path(__file__).resolve().parents[4] / "src")

    outs = []
    for seed in ("1", "424242"):
        env = {**os.environ, "PYTHONHASHSEED": seed}
        outs.append(
            subprocess.run(
                [sys.executable, "-c", src],
                check=True,
                env=env,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
    assert outs[0] == outs[1], outs
    assert json.loads(outs[0]) == [
        ["Ticket No"],
        ["Contact Date", "Problem", "Unit Serial"],
        ["Urgency", "Outcome"],
    ]


def test_apply_exact_layout_rejects_a_span_off_the_end_of_the_grid() -> None:
    """A Row is a 6-unit grid; End past it breaks rendering for the whole flow.

    Refuse it.
    """
    import pytest

    base = (
        FlowDraft.from_wire(_draft_with_fields("a", "b"))
        .regroup_into_sections([("S", ["a", "b"])])
        .to_wire()
    )
    with pytest.raises(ValueError, match=r"'a'.*Start=0, End=99.*6-unit"):
        FlowDraft.from_wire(base).apply_exact_layout({"S": [[("a", 0, 99)]]}).to_wire()


def test_apply_exact_layout_rejects_a_negative_start() -> None:
    import pytest

    base = (
        FlowDraft.from_wire(_draft_with_fields("a"))
        .regroup_into_sections([("S", ["a"])])
        .to_wire()
    )
    with pytest.raises(ValueError, match=r"'a'.*Start=-1"):
        FlowDraft.from_wire(base).apply_exact_layout({"S": [[("a", -1, 2)]]}).to_wire()


def test_apply_exact_layout_rejects_an_inverted_span() -> None:
    """End <= Start is the shape the old leftover packer emitted itself, e.g. (8, 6)."""
    import pytest

    base = (
        FlowDraft.from_wire(_draft_with_fields("a"))
        .regroup_into_sections([("S", ["a"])])
        .to_wire()
    )
    with pytest.raises(ValueError, match=r"'a'.*Start=4, End=2"):
        FlowDraft.from_wire(base).apply_exact_layout({"S": [[("a", 4, 2)]]}).to_wire()

    with pytest.raises(
        ValueError, match=r"'a'.*Start=2, End=2"
    ):  # zero-width is equally illegal
        FlowDraft.from_wire(base).apply_exact_layout({"S": [[("a", 2, 2)]]}).to_wire()


def test_apply_exact_layout_rejects_two_overlapping_spans_in_one_row() -> None:
    """Two columns cannot share a unit — the same overflow class, stated per-row."""
    import pytest

    base = (
        FlowDraft.from_wire(_draft_with_fields("a", "b"))
        .regroup_into_sections([("S", ["a", "b"])])
        .to_wire()
    )
    with pytest.raises(ValueError, match=r"overlaps 'b'.*with 'a'"):
        FlowDraft.from_wire(base).apply_exact_layout(
            {"S": [[("a", 0, 4), ("b", 2, 6)]]}
        ).to_wire()

    # the SAME two spans on two different rows are perfectly legal
    ok = (
        FlowDraft.from_wire(base)
        .apply_exact_layout({"S": [[("a", 0, 4)], [("b", 2, 6)]]})
        .to_wire()
    )
    assert _section_rows(ok) == [[("a", 0, 4)], [("b", 2, 6)]]


def test_apply_exact_layout_rejects_the_same_field_placed_twice() -> None:
    """D8(a): a Column belongs to exactly ONE Row. Naming a field twice used to be
    accepted, and the draft it produced had one Column in two Rows' `Row::Column`
    while the Column's own `Row` back-ref named only the last — a corruption the
    doctor's geometry rule cannot see, because it groups BY that back-ref and the
    duplicate shows up once per group."""
    import pytest

    base = (
        FlowDraft.from_wire(_draft_with_fields("a", "b"))
        .regroup_into_sections([("S", ["a", "b"])])
        .to_wire()
    )
    with pytest.raises(ValueError, match=r"'a'.*twice"):
        FlowDraft.from_wire(base).apply_exact_layout(
            {"S": [[("a", 0, 6)], [("a", 0, 6)]]}
        ).to_wire()


def test_apply_exact_layout_rejects_the_same_field_placed_in_two_sections() -> None:
    """The duplicate is illegal across the WHOLE spec, not just within one row: a
    field has one Column, so two sections claiming it is the same
    one-column-two-rows corruption."""
    import pytest

    base = (
        FlowDraft.from_wire(_draft_with_fields("a", "b"))
        .regroup_into_sections([("S1", ["a"]), ("S2", ["b"])])
        .to_wire()
    )
    with pytest.raises(ValueError, match=r"'a'.*twice"):
        FlowDraft.from_wire(base).apply_exact_layout(
            {"S1": [[("a", 0, 6)]], "S2": [[("a", 0, 6)]]}
        ).to_wire()


def _prod_capture_widest_row() -> list[tuple[int, int]]:
    """The (Start, End) spans of the WIDEST row in
    shapes/process_template_identity_shell.json — read out of the shape file
    itself so this test can never drift from the capture it cites."""
    import json as _json

    shape = _json.loads(
        (ROOT / "shapes" / "process_template_identity_shell.json").read_text(
            encoding="utf-8"
        )
    )["template"]
    rows = [
        [
            (shape[c]["Start"], shape[c]["End"])
            for c in v.get("Row::Column") or []
            if shape.get(c, {}).get("Type") == "Field"
        ]
        for v in shape.values()
        if isinstance(v, dict) and v.get("Kind") == "Row"
    ]
    return max(rows, key=len)


def test_layout_guard_accepts_the_four_column_row_the_prod_capture_proves() -> None:
    """G3, replacing a refusal the repo has a capture AGAINST (doctrine #10). The
    write guard used to cap a caller-stated row at 3 columns, calling a 4th
    "render-breaking" — but shapes/process_template_identity_shell.json,
    de-identified off a REAL PUBLISHED production template, carries exactly that
    geometry ((0,2) (2,4) (4,5) (5,6)) and renders. `verify.doctor` already
    refused to assert a count bound for that reason; the WRITE guard asserting the
    opposite was the same repo contradicting itself. What stays enforced is what
    the capture actually backs: in-grid, disjoint, one column to one Row."""

    spans = _prod_capture_widest_row()
    assert len(spans) >= 4, (
        "fixture drift: the shipped shell no longer has its 4-column row"
    )

    names = [f"f{i}" for i in range(len(spans))]
    row = [(n, s, e) for n, (s, e) in zip(names, spans, strict=True)]
    validate_layout_spans({"S": [row]})  # pure guard: must not raise

    base = (
        FlowDraft.from_wire(_draft_with_fields(*names))
        .regroup_into_sections([("S", names)])
        .to_wire()
    )
    got = FlowDraft.from_wire(base).apply_exact_layout({"S": [row]}).to_wire()
    assert _section_rows(got)[0] == row, "the production geometry must land verbatim"


def test_layout_guard_still_refuses_what_the_capture_does_back() -> None:
    """The count bound is gone; the capture-backed invariants are NOT. Six 1-unit
    columns are fine (in-grid, disjoint, that is the whole rule), an overlap is
    refused, and off-grid is refused."""
    import pytest

    names = [f"f{i}" for i in range(6)]
    validate_layout_spans({"S": [[(n, i, i + 1) for i, n in enumerate(names)]]})

    with pytest.raises(ValueError, match="disjoint"):
        validate_layout_spans({"S": [[("a", 0, 4), ("b", 2, 6)]]})
    with pytest.raises(ValueError, match=r"0 <= Start < End <= 6"):
        validate_layout_spans({"S": [[("a", 0, 7)]]})


def test_apply_exact_layout_rejects_a_bad_span_before_touching_the_draft() -> None:
    """Pure-function discipline: a rejected spec leaves the draft byte-identical —
    the validation runs before the deepcopy, so a later section's bad row cannot
    half-apply an earlier one."""
    import copy as _copy

    import pytest

    base = (
        FlowDraft.from_wire(_draft_with_fields("a", "b"))
        .regroup_into_sections([("S1", ["a"]), ("S2", ["b"])])
        .to_wire()
    )
    snapshot = _copy.deepcopy(base)
    with pytest.raises(ValueError, match="S2"):
        FlowDraft.from_wire(base).apply_exact_layout(
            {"S1": [[("a", 0, 6)]], "S2": [[("b", 0, 7)]]}
        ).to_wire()
    assert base == snapshot


def test_apply_exact_layout_raises_on_a_field_not_in_the_draft() -> None:
    """Fail loud: a stale layout naming a deleted field must not silently drop it."""
    import pytest

    base = (
        FlowDraft.from_wire(_draft_with_fields("a"))
        .regroup_into_sections([("S", ["a"])])
        .to_wire()
    )
    with pytest.raises(ValueError, match="ghost"):
        FlowDraft.from_wire(base).apply_exact_layout(
            {"S": [[("ghost", 0, 6)]]}
        ).to_wire()


def test_apply_exact_layout_sets_section_descriptions() -> None:
    """`descriptions` lands a plain string OR a serialized rich-text doc on the
    section, same write as the row rebuild (the builder writes the latter for
    formatted text; both coexist live)."""

    base = (
        FlowDraft.from_wire(_draft_with_fields("a"))
        .regroup_into_sections([("S", ["a"])])
        .to_wire()
    )
    rich = '[{"type":"paragraph","nodes":[{"type":"bold"}]}]'
    got = (
        FlowDraft.from_wire(base)
        .apply_exact_layout({"S": [[("a", 0, 6)]]}, descriptions={"S": rich})
        .to_wire()
    )
    sec = next(
        v for v in got.values() if isinstance(v, dict) and v.get("Type") == "Section"
    )
    assert sec["Description"] == rich


def test_build_workflow_sweeps_dangling_permission_backrefs() -> None:
    """Columns hold Column::Permission back-refs. Leaving them dangling breaks PUBLISH.
    Live symptom (a live process, 2026-08-03): draft PUT returned 200, publish returned
    a bare MetadataError, and 6 Columns still referenced deleted Permission nodes.
    """

    draft = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "P", "FlowType": "Process"},
        "Column_1": {
            "Id": "Column_1",
            "Kind": "Column",
            "Type": "Field",
            "Column::Field": ["F1"],
            "Column::Permission": ["Permission_old"],
        },
        "F1": {
            "Id": "F1",
            "Kind": "Field",
            "Type": "Text",
            "Name": "a",
            "Column": "Column_1",
        },
        "Permission_old": {
            "Id": "Permission_old",
            "Kind": "Permission",
            "Column": "Column_1",
            "Activity": "Activity_old",
        },
        "Activity_old": {
            "Id": "Activity_old",
            "Kind": "Activity",
            "NodeType": "UserTask",
            "Name": "gone",
            "ProcessDef": "ProcessDef_old",
        },
        "ProcessDef_old": {
            "Id": "ProcessDef_old",
            "Kind": "ProcessDef",
            "ProcessDef::Activity": ["Activity_old"],
        },
    }
    got = FlowDraft.from_wire(draft).build_workflow([("New Step", None)]).to_wire()

    assert "Column::Permission" not in got["Column_1"], (
        "dead back-ref must be swept, not left"
    )
    assert got["F1"]["Column"] == "Column_1", (
        "fields and columns survive a workflow rebuild"
    )

    ids = set(got)
    for node in got.values():
        if not isinstance(node, dict):
            continue
        for key, val in node.items():
            if key == "Id" or not isinstance(val, list):
                continue
            for ref in val:
                if isinstance(ref, str) and ref.split("_")[0] in {
                    "Activity",
                    "ProcessDef",
                    "Resource",
                    "Permission",
                }:
                    assert ref in ids, (
                        f"{node['Id']}.{key} still points at missing {ref}"
                    )


def test_sweep_clears_orphans_left_by_an_earlier_partial_write() -> None:
    """Sweeping must key off "target absent", not "I deleted it".

    Drafts arrive already dirty.
    """

    draft = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "P", "FlowType": "Process"},
        # Permission_ghost was deleted by a PREVIOUS run; only the back-ref survived
        "Column_1": {
            "Id": "Column_1",
            "Kind": "Column",
            "Type": "Field",
            "Column::Field": ["F1"],
            "Column::Permission": ["Permission_ghost"],
        },
        "F1": {
            "Id": "F1",
            "Kind": "Field",
            "Type": "Text",
            "Name": "a",
            "Column": "Column_1",
        },
    }
    got = FlowDraft.from_wire(draft).build_workflow([("Step", None)]).to_wire()
    assert "Column::Permission" not in got["Column_1"]
    assert got["F1"]["Name"] == "a"


# ---- add_goto_task
# ---------------------------------------------------------------------------- Node G
# (P2 server surface) needs a real builder for the GotoTask edge node itself: everything
# else in this module only ever produces a straight-line/parallel chain, and
# expr.build_goto_gate only ATTACHES a condition to an already-existing GotoTask
# (tests/test_expr.py's own draft_with_bare_goto fixture hand-builds one by raw dict
# surgery for exactly that reason). This is that missing builder, shape pinned against
# shapes/goto_task.json.


def _process_with_review_step() -> tuple[dict, str, str]:
    """A minimal scaffolded process with one real step named "Review". Returns
    (draft, pd_id, review_activity_id)."""

    bare = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "P", "FlowType": "Process"},
    }
    draft = FlowDraft.from_wire(bare).ensure_process_def(("Review",)).to_wire()
    pd_id = draft["M1"]["RootProcessDef"]
    review_id = next(
        a for a in draft[pd_id]["ProcessDef::Activity"] if draft[a]["Name"] == "Review"
    )
    return draft, pd_id, review_id


def test_add_goto_task_wires_backward_jump_and_backref() -> None:

    draft, pd_id, review_id = _process_with_review_step()
    got, goto_id = FlowDraft.from_wire(draft).add_goto_task(
        target_activity_id=review_id
    )
    got = got.to_wire()

    goto = got[goto_id]
    assert goto["Kind"] == "Activity" and goto["NodeType"] == "GotoTask"
    assert goto["Goto"] == review_id
    assert goto["ProcessDef"] == pd_id
    assert goto["Name"] == "Goto-Review", (
        "default name follows the UI convention Goto-<target>"
    )
    assert goto_id in got[review_id]["Goto::Activity"]
    assert goto_id.startswith("Activity_"), (
        "platform-prefixed id, like every node this module mints"
    )
    # carries no Permission-eligible surface of its own (verify.py excludes GotoTask
    # entirely)
    assert "Activity::Permission" not in goto


def test_add_goto_task_sits_before_a_trailing_end_event_not_after() -> None:
    """Live-proven 2026-08-06 (see this function's own docstring correction): a chain
    ending in a real EndEvent must get the GotoTask inserted BEFORE it, not
    appended strictly last — PUTting it strictly last (after the EndEvent too) is
    REJECTED live with 400 InvalidArguments."""

    draft, pd_id, review_id = _process_with_review_step()
    got, goto_id = FlowDraft.from_wire(draft).add_goto_task(
        target_activity_id=review_id
    )
    got = got.to_wire()

    chain = got[pd_id]["ProcessDef::Activity"]
    names = [got[a]["Name"] for a in chain]
    assert names == ["Start", "Review", "Goto-Review", "Completed"], (
        "goto must land last among the REAL activities but BEFORE the terminal EndEvent"
    )
    assert chain[-2] == goto_id, (
        "the SECOND-to-last chain entry must be the goto id itself"
    )
    assert got[chain[-1]]["NodeType"] == "EndEvent", (
        "the EndEvent must stay genuinely last"
    )


def test_add_goto_task_appends_plainly_when_the_chain_has_no_trailing_end_event() -> (
    None
):
    """The fallback path — a chain with no EndEvent at all (matches
    shapes/goto_task.json's own minimal 2-activity capture) — still just appends,
    exactly as originally captured."""

    draft = {
        "Root": "M1",
        "M1": {
            "Id": "M1",
            "Kind": "Model",
            "Name": "P",
            "FlowType": "Process",
            "RootProcessDef": "PD1",
            "Model::ProcessDef": ["PD1"],
        },
        "PD1": {
            "Id": "PD1",
            "Kind": "ProcessDef",
            "WorkflowType": "Sequence",
            "ProcessDef::Activity": ["A1"],
        },
        "A1": {
            "Id": "A1",
            "Kind": "Activity",
            "NodeType": "UserTask",
            "Name": "Sample Rework Step",
            "ProcessDef": "PD1",
        },
    }
    got, goto_id = FlowDraft.from_wire(draft).add_goto_task(target_activity_id="A1")
    got = got.to_wire()
    assert got["PD1"]["ProcessDef::Activity"] == ["A1", goto_id]


def test_add_goto_task_accepts_an_explicit_name() -> None:

    draft, _pd_id, review_id = _process_with_review_step()
    got, goto_id = FlowDraft.from_wire(draft).add_goto_task(
        target_activity_id=review_id, name="Rework Loop"
    )
    got = got.to_wire()
    assert got[goto_id]["Name"] == "Rework Loop"


def test_add_goto_task_unknown_activity_rejected() -> None:

    draft, _pd_id, _review_id = _process_with_review_step()
    before = copy.deepcopy(draft)
    with pytest.raises(ValueError):
        FlowDraft.from_wire(draft).add_goto_task(
            target_activity_id="Activity_DoesNotExist99"
        )
    assert draft == before


def test_add_goto_task_input_not_mutated() -> None:

    draft, _pd_id, review_id = _process_with_review_step()
    before = copy.deepcopy(draft)
    FlowDraft.from_wire(draft).add_goto_task(target_activity_id=review_id)
    assert draft == before


def test_add_goto_task_is_idempotent_on_rerun() -> None:

    draft, pd_id, review_id = _process_with_review_step()
    once, goto_id_1 = FlowDraft.from_wire(draft).add_goto_task(
        target_activity_id=review_id
    )
    twice, goto_id_2 = once.add_goto_task(target_activity_id=review_id)
    twice = twice.to_wire()

    assert goto_id_1 == goto_id_2, (
        "the id is deterministic on the target, like every id this module mints"
    )
    chain = twice[pd_id]["ProcessDef::Activity"]
    assert chain.count(goto_id_1) == 1, (
        "re-running must not duplicate the GotoTask in the chain"
    )
    assert twice[review_id]["Goto::Activity"].count(goto_id_1) == 1, (
        "back-ref must not duplicate either"
    )


# ---- add_goto_task — branch_process_def_id (Node M, conditional routing)
# --------------------- The oracle app's own two GotoTasks each sit LAST within their
# own branch ProcessDef, targeting an early step of that SAME branch (CLAUDE.md
# Workflow). Before this parameter, the chain that hosts a new GotoTask was always
# DERIVED from the target's own ProcessDef, with no way for a caller to say which chain
# they actually meant — reproduced live 2026-08-07 (node M): a target 2 root steps
# before a 2-branch Parallel landed the GotoTask after the LAST root-chain activity, not
# scoped to either branch. `branch_process_def_id` closes that by PINNING and VALIDATING
# the intended chain.


def _process_with_parallel_branches() -> tuple[dict, str, str, str]:
    """2 root steps -> a 2-branch Parallel (2 steps each) -> End. Returns (draft,
    root_pd_id, branch_a_pd_id, branch_b_pd_id)."""

    bare = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "P", "FlowType": "Process"},
    }
    draft = (
        FlowDraft.from_wire(bare)
        .build_workflow(
            [("Root Step 1", None), ("Root Step 2", None)],
            parallel=(
                "Fork",
                [
                    ("Branch A", [("A1", None), ("A2", None)]),
                    ("Branch B", [("B1", None), ("B2", None)]),
                ],
            ),
            parallel_after=1,
        )
        .to_wire()
    )
    root_pd_id = draft["M1"]["RootProcessDef"]
    branch_a_pd_id = next(
        v["Id"]
        for v in draft.values()
        if isinstance(v, dict)
        and v.get("Kind") == "ProcessDef"
        and v.get("Name") == "Branch A"
    )
    branch_b_pd_id = next(
        v["Id"]
        for v in draft.values()
        if isinstance(v, dict)
        and v.get("Kind") == "ProcessDef"
        and v.get("Name") == "Branch B"
    )
    return draft, root_pd_id, branch_a_pd_id, branch_b_pd_id


def test_add_goto_task_branch_process_def_id_lands_inside_that_branch_not_root() -> (
    None
):

    draft, root_pd_id, branch_a_pd_id, _branch_b_pd_id = (
        _process_with_parallel_branches()
    )
    a1_id = next(
        a
        for a in draft[branch_a_pd_id]["ProcessDef::Activity"]
        if draft[a]["Name"] == "A1"
    )

    got, goto_id = FlowDraft.from_wire(draft).add_goto_task(
        target_activity_id=a1_id, branch_process_def_id=branch_a_pd_id
    )
    got = got.to_wire()

    assert got[goto_id]["ProcessDef"] == branch_a_pd_id
    branch_a_chain = got[branch_a_pd_id]["ProcessDef::Activity"]
    assert branch_a_chain[-1] == goto_id, "GotoTask must sit LAST within its own branch"
    assert [got[a]["Name"] for a in branch_a_chain] == ["A1", "A2", "Goto-A1"]
    # the root chain and the sibling branch must be completely untouched
    root_chain_names = [got[a]["Name"] for a in got[root_pd_id]["ProcessDef::Activity"]]
    assert root_chain_names == ["Start", "Root Step 1", "Root Step 2", "Fork", "End"]


def test_add_goto_task_branch_pd_id_matches_default_when_target_already_in_branch(
    monkeypatch,
) -> None:
    """Passing the target's OWN branch explicitly must be byte-identical to omitting
    the param — the validation is a no-op when the caller's assumption was already
    correct."""
    from app.domain.entities import _flow_ops

    # Freeze _now: the two add_goto_task calls below each stamp CreatedAt from a LIVE
    # millisecond clock, so straddling a ms boundary would make them differ on that one
    # incidental key (~3% of runs) — nothing to do with the branch-resolution logic this
    # test actually asserts.
    monkeypatch.setattr(_flow_ops, "_now", lambda: "2026-08-12T00:00:00.000Z")

    draft, _root_pd_id, branch_a_pd_id, _branch_b_pd_id = (
        _process_with_parallel_branches()
    )
    a1_id = next(
        a
        for a in draft[branch_a_pd_id]["ProcessDef::Activity"]
        if draft[a]["Name"] == "A1"
    )

    with_branch, goto_id_1 = FlowDraft.from_wire(draft).add_goto_task(
        target_activity_id=a1_id, branch_process_def_id=branch_a_pd_id
    )
    without_branch, goto_id_2 = FlowDraft.from_wire(draft).add_goto_task(
        target_activity_id=a1_id
    )

    assert goto_id_1 == goto_id_2
    assert with_branch == without_branch


def test_add_goto_task_branch_process_def_id_rejects_target_outside_that_branch() -> (
    None
):
    """THE reproduced gap: a target OUTSIDE the named branch (here, a shared
    root-chain step before the Parallel) must be a loud, pre-write ValueError —
    never a silent misplacement into the wrong chain (which, for a root-chain
    target, used to mean landing after the LAST root-chain activity, evaluated
    once for the whole item instead of scoped to one branch)."""

    draft, root_pd_id, branch_a_pd_id, _branch_b_pd_id = (
        _process_with_parallel_branches()
    )
    root_step_2_id = next(
        a
        for a in draft[root_pd_id]["ProcessDef::Activity"]
        if draft[a]["Name"] == "Root Step 2"
    )
    before = copy.deepcopy(draft)

    with pytest.raises(ValueError, match="never cross-branch"):
        FlowDraft.from_wire(draft).add_goto_task(
            target_activity_id=root_step_2_id,
            branch_process_def_id=branch_a_pd_id,
        )
    assert draft == before


def test_add_goto_task_branch_process_def_id_rejects_target_in_sibling_branch() -> None:

    draft, _root_pd_id, branch_a_pd_id, branch_b_pd_id = (
        _process_with_parallel_branches()
    )
    b1_id = next(
        a
        for a in draft[branch_b_pd_id]["ProcessDef::Activity"]
        if draft[a]["Name"] == "B1"
    )
    before = copy.deepcopy(draft)

    with pytest.raises(ValueError):
        FlowDraft.from_wire(draft).add_goto_task(
            target_activity_id=b1_id, branch_process_def_id=branch_a_pd_id
        )
    assert draft == before


def test_add_goto_task_branch_process_def_id_rejects_unknown_process_def() -> None:

    draft, _root_pd_id, branch_a_pd_id, _branch_b_pd_id = (
        _process_with_parallel_branches()
    )
    a1_id = next(
        a
        for a in draft[branch_a_pd_id]["ProcessDef::Activity"]
        if draft[a]["Name"] == "A1"
    )
    before = copy.deepcopy(draft)

    with pytest.raises(ValueError):
        FlowDraft.from_wire(draft).add_goto_task(
            target_activity_id=a1_id,
            branch_process_def_id="ProcessDef_DoesNotExist99",
        )
    assert draft == before


def test_add_goto_task_root_chain_behavior_unchanged_when_a_parallel_also_exists() -> (
    None
):
    """A root-chain target with NO branch_process_def_id must still behave exactly
    like the pre-existing (pre-node-M) root-chain tests, even in a draft that ALSO
    has a Parallel — the new parameter must never change default behavior just
    because branches exist elsewhere."""

    draft, root_pd_id, _branch_a_pd_id, _branch_b_pd_id = (
        _process_with_parallel_branches()
    )
    root_step_1_id = next(
        a
        for a in draft[root_pd_id]["ProcessDef::Activity"]
        if draft[a]["Name"] == "Root Step 1"
    )

    got, goto_id = FlowDraft.from_wire(draft).add_goto_task(
        target_activity_id=root_step_1_id
    )
    got = got.to_wire()

    assert got[goto_id]["ProcessDef"] == root_pd_id
    chain = got[root_pd_id]["ProcessDef::Activity"]
    names = [got[a]["Name"] for a in chain]
    # last among the REAL activities, but before the trailing EndEvent — same rule as
    # ever
    assert names == [
        "Start",
        "Root Step 1",
        "Root Step 2",
        "Fork",
        "Goto-Root Step 1",
        "End",
    ]
    assert got[chain[-1]]["NodeType"] == "EndEvent"


# ---- build_workflow — N sequential Parallel gateways (S2, ticket #33)
# ------------------------ build_workflow used to support at most one Parallel gateway
# via `parallel`/`parallel_after`. `parallels` generalizes that to a list of
# `(parallel_spec, after_index)` pairs, and adds an explicit branch-name-uniqueness
# check (a branch id is a hash of (model, kind, index, name), so two branches sharing a
# name would otherwise collide silently).


def test_build_workflow_two_sequential_parallels() -> None:

    bare = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "P", "FlowType": "Process"},
    }
    got = (
        FlowDraft.from_wire(bare)
        .build_workflow(
            [("S1", None), ("S2", None)],
            parallels=[
                (("Fork1", [("A", [("A1", None)]), ("B", [("B1", None)])]), 0),
                (("Fork2", [("C", [("C1", None)]), ("D", [("D1", None)])]), 1),
            ],
        )
        .to_wire()
    )

    root_pd_id = got["M1"]["RootProcessDef"]
    root_chain = got[root_pd_id]["ProcessDef::Activity"]
    root_names = [got[a]["Name"] for a in root_chain]
    assert root_names == ["Start", "S1", "Fork1", "S2", "Fork2", "End"], (
        "Fork1 sits right after S1, Fork2 right after S2 — root chain order preserved"
    )

    parallel_nodes = [
        n
        for n in got.values()
        if isinstance(n, dict)
        and n.get("Kind") == "Activity"
        and n.get("NodeType") == "Parallel"
    ]
    assert len(parallel_nodes) == 2, "exactly two Parallel gateway Activities"
    assert [n["Name"] for n in parallel_nodes] == ["Fork1", "Fork2"], (
        "Fork1 before Fork2, matching root ProcessDef::Activity order"
    )

    branch_pds = {
        n["Name"]: n
        for n in got.values()
        if isinstance(n, dict)
        and n.get("Kind") == "ProcessDef"
        and n.get("Name") in ("A", "B", "C", "D")
    }
    assert set(branch_pds) == {"A", "B", "C", "D"}
    assert [got[a]["Name"] for a in branch_pds["A"]["ProcessDef::Activity"]] == ["A1"]
    assert [got[a]["Name"] for a in branch_pds["B"]["ProcessDef::Activity"]] == ["B1"]
    assert [got[a]["Name"] for a in branch_pds["C"]["ProcessDef::Activity"]] == ["C1"]
    assert [got[a]["Name"] for a in branch_pds["D"]["ProcessDef::Activity"]] == ["D1"]

    branch_ids = {n["Id"] for n in branch_pds.values()}
    assert len(branch_ids) == 4, "all four branch ProcessDef ids are distinct"


def test_build_workflow_duplicate_branch_name_across_splits_raises() -> None:

    bare = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "P", "FlowType": "Process"},
    }
    with pytest.raises(ValueError, match="Yes"):
        FlowDraft.from_wire(bare).build_workflow(
            [("S1", None), ("S2", None)],
            parallels=[
                (("Fork1", [("Yes", [("A1", None)]), ("No", [("A2", None)])]), 0),
                (("Fork2", [("Yes", [("C1", None)]), ("Maybe", [("D1", None)])]), 1),
            ],
        ).to_wire()


def test_build_workflow_single_parallel_unchanged() -> None:
    """The pre-existing `parallel=`/`parallel_after=` path must produce
    byte-identical output to before — same Parallel count, same branch
    names/steps, same branch id values (100 + b_i)."""
    draft, root_pd_id, branch_a_pd_id, branch_b_pd_id = (
        _process_with_parallel_branches()
    )

    parallel_nodes = [
        n
        for n in draft.values()
        if isinstance(n, dict)
        and n.get("Kind") == "Activity"
        and n.get("NodeType") == "Parallel"
    ]
    assert len(parallel_nodes) == 1
    assert parallel_nodes[0]["Name"] == "Fork"

    root_names = [draft[a]["Name"] for a in draft[root_pd_id]["ProcessDef::Activity"]]
    assert root_names == ["Start", "Root Step 1", "Root Step 2", "Fork", "End"]

    assert [
        draft[a]["Name"] for a in draft[branch_a_pd_id]["ProcessDef::Activity"]
    ] == ["A1", "A2"]
    assert [
        draft[a]["Name"] for a in draft[branch_b_pd_id]["ProcessDef::Activity"]
    ] == ["B1", "B2"]
    assert draft[branch_a_pd_id]["Id"] != draft[branch_b_pd_id]["Id"]


def test_build_workflow_parallel_and_parallels_both_given_raises() -> None:

    bare = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "P", "FlowType": "Process"},
    }
    with pytest.raises(ValueError):
        FlowDraft.from_wire(bare).build_workflow(
            [("S1", None)],
            parallel=("Fork", [("A", [("A1", None)]), ("B", [("B1", None)])]),
            parallel_after=0,
            parallels=[
                (("Fork2", [("C", [("C1", None)]), ("D", [("D1", None)])]), 0),
            ],
        ).to_wire()


def test_add_goto_task_can_pair_with_build_goto_gate_and_reads_clean() -> None:
    """Integration: add_goto_task + expr.build_goto_gate together produce a loop
    verify.doctor accepts, using a REAL Boolean field and a REAL permission matrix
    (not raw dict surgery) — proving the two builders compose into something the
    doctor genuinely calls clean. Permissions are set BEFORE add_goto_task,
    matching CLAUDE.md: a loop added to an already-wired flow."""

    from app.domain.entities.flow_draft import progressive_matrix
    from app.domain.value_objects.field_spec import FieldSpec
    from app.domain.value_objects.field_type import FieldType

    draft, _pd_id, review_id = _process_with_review_step()
    # A real step needs an assignee or doctor (correctly) flags it as a submit-500 —
    # wire one so this assertion tests the goto/gate loop, not the separately-covered
    # assignee rule.
    draft["Resource_ReviewAssignee"] = {
        "Id": "Resource_ReviewAssignee",
        "Kind": "Resource",
        "ValueType": "AppRole",
        "Value": "Role_Test",
        "Activity": review_id,
    }
    draft[review_id]["Activity::Resource"] = ["Resource_ReviewAssignee"]
    draft = (
        FlowDraft.from_wire(draft)
        .apply_changes([FieldSpec(name="Done Flag", type=FieldType.BOOLEAN)])
        .to_wire()
    )
    field_id = next(
        k
        for k, v in draft.items()
        if isinstance(v, dict)
        and v.get("Kind") == "Field"
        and v.get("Name") == "Done Flag"
    )
    section_name = next(
        v["Name"]
        for v in draft.values()
        if isinstance(v, dict)
        and v.get("Kind") == "Column"
        and v.get("Type") == "Section"
    )
    matrix = progressive_matrix(FlowDraft.from_wire(draft), {section_name: ["Start"]})
    draft = FlowDraft.from_wire(draft).set_step_permissions(matrix).to_wire()

    with_goto, goto_id = FlowDraft.from_wire(draft).add_goto_task(
        target_activity_id=review_id
    )
    report_before = with_goto.problems()
    assert any("NO condition" in p for p in report_before.problems), (
        "a bare goto with no condition must loop forever per verify.doctor's own rule"
    )

    gated = with_goto.build_goto_gate(goto_activity_id=goto_id, field_id=field_id)
    assert gated.problems().ok(), gated.problems().problems


def test_field_override_matrix_branch_aware_per_step_rule() -> None:
    """The per-FIELD matrix's branch-aware rule, in one fixture (2 root steps +
    2-branch Parallel + End). A header field (root-owned, no tail edit) is
    ReadOnly through the branches; a verdict field (root-owned, editable at the
    tail End) is Hidden through the branch detour; a branch- private field is
    Hidden on the sibling branch and ReadOnly at the tail. This is the load-
    bearing rule a plain editable-list + the section lever gets wrong — the only
    check left behind for this non-trivial logic."""
    from app.domain.value_objects.field_spec import FieldSpec
    from app.domain.value_objects.field_type import FieldType, Visibility

    draft, _root_pd_id, _branch_a_pd_id, _branch_b_pd_id = (
        _process_with_parallel_branches()
    )
    draft = (
        FlowDraft.from_wire(draft)
        .apply_changes(
            [
                FieldSpec(name="Header", type=FieldType.TEXT),
                FieldSpec(name="Verdict", type=FieldType.TEXT),
                FieldSpec(name="A-only", type=FieldType.TEXT),
            ],
        )
        .to_wire()
    )

    m = field_override_matrix(
        FlowDraft.from_wire(draft),
        {
            "Header": ["Start"],  # root-owned, no tail edit
            "Verdict": ["End"],  # root-owned, editable at tail -> has_tail
            "A-only": ["A1", "A2"],  # branch A only
        },
    )

    def row(fnm: str) -> dict:
        return {draft[a].get("Name"): m[fnm][a] for a in m[fnm]}

    E, R, H = Visibility.EDITABLE, Visibility.READONLY, Visibility.HIDDEN
    # header: Editable at Start, ReadOnly everywhere else, including both branches
    assert row("Header") == {
        "Start": E,
        "Root Step 1": R,
        "Root Step 2": R,
        "A1": R,
        "A2": R,
        "B1": R,
        "B2": R,
        "End": R,
    }
    # verdict: Hidden everywhere except Editable at End (a tail edit hides the branch
    # detour)
    assert row("Verdict") == {
        "Start": H,
        "Root Step 1": H,
        "Root Step 2": H,
        "A1": H,
        "A2": H,
        "B1": H,
        "B2": H,
        "End": E,
    }
    # A-only: Editable in branch A, Hidden on sibling B and pre-branch root, ReadOnly at
    # the tail
    assert row("A-only") == {
        "Start": H,
        "Root Step 1": H,
        "Root Step 2": H,
        "A1": E,
        "A2": E,
        "B1": H,
        "B2": H,
        "End": R,
    }


def test_field_override_matrix_empty_list_is_readonly_everywhere() -> None:
    from app.domain.value_objects.field_spec import FieldSpec
    from app.domain.value_objects.field_type import FieldType, Visibility

    draft, _root, _a, _b = _process_with_parallel_branches()
    draft = (
        FlowDraft.from_wire(draft)
        .apply_changes([FieldSpec(name="Stamp", type=FieldType.TEXT)])
        .to_wire()
    )
    m = field_override_matrix(FlowDraft.from_wire(draft), {"Stamp": []})
    assert set(m["Stamp"].values()) == {Visibility.READONLY}


def test_add_table_per_column_options_override_type_defaults() -> None:
    """A table column may carry opt-in options written verbatim (e.g. an integer-only
    Number with Decimalpoint=0, overriding the Number default of "2"). A bare
    2-tuple column keeps the type default."""

    from app.domain.value_objects.field_type import FieldType

    bare = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Form"},
    }
    got = (
        FlowDraft.from_wire(bare)
        .add_table(
            "Log",
            [
                ("Round", FieldType.NUMBER, {"Decimalpoint": 0}),
                ("Hours", FieldType.NUMBER),  # bare 2-tuple -> default Decimalpoint "2"
            ],
        )
        .to_wire()
    )
    cols = {
        n["Name"]: n
        for n in got.values()
        if isinstance(n, dict) and n.get("Kind") == "Field"
    }
    assert cols["Round"]["Decimalpoint"] == 0  # opt-in overrides the "2" default
    assert cols["Hours"]["Decimalpoint"] == "2"  # default survives untouched


# ---- add_table: the SECOND door onto the bare-Select publish-500
# -------------------------------


def test_add_table_refuses_a_select_child_with_no_referred_list() -> None:
    """G1. `apply_changes` refuses a bare Select (the 2026-08-19 publish-500
    diagnosis), and `add_table` minted the byte-identical `Field{Type:"Select"}`
    with no `ReferredList` and no complaint — the same deterministic publish-500
    through a second door, on a flow `forge_add_table` had just built and
    `verify.doctor` would then flag. ONE rule, both doors: the refusal reuses
    apply_changes' own predicate rather than a second copy that can drift."""
    import pytest

    bare = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Form"},
    }
    with pytest.raises(ValueError) as exc:
        FlowDraft.from_wire(bare).add_table(
            "Items", [("Item", "Text", None), ("Grade", "Select", None)]
        ).to_wire()

    msg = str(exc.value)
    assert "'Grade'" in msg, msg  # NAME the offending child column
    assert "ReferredList" in msg, msg
    # and show the escape hatch that already exists but was named nowhere
    assert "'Grade', 'Select', {'ReferredList':" in msg, msg


def test_add_table_writes_a_select_child_that_names_its_list() -> None:
    """The escape hatch the refusal points at: the child-spec `options` dict already
    passes `ReferredList` through verbatim — a wired table-child Select is legal
    and unchanged."""

    bare = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Form"},
    }
    got = (
        FlowDraft.from_wire(bare)
        .add_table(
            "Items",
            [("Item", "Text", None), ("Grade", "Select", {"ReferredList": "List_G1"})],
        )
        .to_wire()
    )
    (grade,) = [
        n
        for n in got.values()
        if isinstance(n, dict) and n.get("Kind") == "Field" and n.get("Name") == "Grade"
    ]
    assert grade["Type"] == "Select" and grade["ReferredList"] == "List_G1"


def test_add_table_refuses_the_bad_child_before_writing_any_node() -> None:
    """Validation-first, exactly like apply_changes: a table whose LAST column is a
    bare Select must leave the caller's draft byte-identical — a refused spec
    writes nothing at all."""
    import copy as _copy

    import pytest

    draft = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Form"},
    }
    snapshot = _copy.deepcopy(draft)
    with pytest.raises(ValueError, match="'Grade'"):
        FlowDraft.from_wire(draft).add_table(
            "Items", [("Item", "Text", None), ("Grade", "Select", None)]
        ).to_wire()
    assert draft == snapshot


def test_build_workflow_step_meta_writes_suspended_and_description() -> None:
    """step_meta writes IsSuspended+SuspendedAt and Description on the named step; a
    step not in meta gets neither; Start/EndEvent are untouched."""

    bare = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Process"},
    }
    got = (
        FlowDraft.from_wire(bare)
        .build_workflow(
            [("Log it", None), ("Queue", None), ("Decide", None)],
            step_meta={
                "Log it": {
                    "description": "Log the request and who is asking.",
                    "suspended": True,
                },
                "Decide": {"description": "Pick the service level for this case."},
            },
        )
        .to_wire()
    )
    acts = {
        n["Name"]: n
        for n in got.values()
        if isinstance(n, dict) and n.get("Kind") == "Activity" and "Name" in n
    }
    assert acts["Log it"]["IsSuspended"] is True
    assert "SuspendedAt" in acts["Log it"]
    assert acts["Log it"]["Description"] == "Log the request and who is asking."
    assert acts["Decide"]["Description"] == "Pick the service level for this case."
    assert "IsSuspended" not in acts["Queue"]  # meta absent -> no flag
    assert "Description" not in acts["Queue"]
    assert "IsSuspended" not in acts["Start"]  # Start/End never flagged
    assert "Description" not in acts["End"]


def test_add_sequence_number_builds_field_props_expression_and_hidden_column() -> None:
    """add_sequence_number creates the SequenceNumber Field + hidden Column + own Row
    + 3 Property nodes (Padding/Step/PrefixExpression) + Expression + 2 Nodes,
    stamps the Step at the activity resolved by name, and appends the row to the
    named section. Idempotent."""

    from app.domain.value_objects.field_spec import FieldSpec
    from app.domain.value_objects.field_type import FieldType

    bare = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Process"},
    }
    d = (
        FlowDraft.from_wire(bare)
        .apply_changes([FieldSpec(name="a", type=FieldType.TEXT)])
        .to_wire()
    )
    d = FlowDraft.from_wire(d).regroup_into_sections([("S", ["a"])]).to_wire()
    d = FlowDraft.from_wire(d).build_workflow([("Log it", None)]).to_wire()
    got = (
        FlowDraft.from_wire(d)
        .add_sequence_number("running number", "S", "PRE-", "0001", "Start", 0, 2)
        .to_wire()
    )

    start_id = next(
        n["Id"]
        for n in got.values()
        if isinstance(n, dict)
        and n.get("Kind") == "Activity"
        and n.get("Name") == "Start"
    )
    fld = next(
        n
        for n in got.values()
        if isinstance(n, dict)
        and n.get("Kind") == "Field"
        and n.get("Type") == "SequenceNumber"
    )
    assert fld["Name"] == "running number"
    assert fld["Model"] == "M1"
    assert fld["Id"] in got["M1"].get("Model::Field", [])
    assert len(fld["Field::Property"]) == 3

    col = got[fld["Column"]]
    assert col["IsHidden"] is True
    assert (col["Start"], col["End"]) == (0, 2)

    # the section's last row is the sequence-number row, alone
    sec = next(
        v
        for v in got.values()
        if isinstance(v, dict)
        and v.get("Kind") == "Column"
        and v.get("Type") == "Section"
        and v.get("Name") == "S"
    )
    last_row = got[sec["Column::Row"][-1]]
    assert last_row["Row::Column"] == [col["Id"]]

    props = {got[pid]["Name"]: got[pid] for pid in fld["Field::Property"]}
    assert props["Padding"]["Value"] == "0001"
    assert props["Step"]["Value"] == start_id  # resolved by NAME
    expr_id = props["PrefixExpression"]["Property::Expression"][0]
    expr = got[expr_id]
    assert expr["ExpressionStr"] == 'concatenate("PRE-")'
    root_node = expr["Expression::Node"][0]
    assert got[root_node]["Value"] == "concatenate"
    lit_node = got[root_node]["Node::Node"][0]
    assert got[lit_node]["Value"] == "PRE-"

    # idempotent: a second add does not duplicate the field
    again = (
        FlowDraft.from_wire(got)
        .add_sequence_number("running number", "S", "PRE-", "0001", "Start", 0, 2)
        .to_wire()
    )
    seqs = [
        n
        for n in again.values()
        if isinstance(n, dict) and n.get("Type") == "SequenceNumber"
    ]
    assert len(seqs) == 1


def test_add_sequence_number_raises_on_missing_section_and_activity() -> None:
    import pytest

    from app.domain.value_objects.field_spec import FieldSpec
    from app.domain.value_objects.field_type import FieldType

    bare = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Process"},
    }
    d = (
        FlowDraft.from_wire(bare)
        .apply_changes([FieldSpec(name="a", type=FieldType.TEXT)])
        .to_wire()
    )
    d = FlowDraft.from_wire(d).regroup_into_sections([("S", ["a"])]).to_wire()
    d = FlowDraft.from_wire(d).build_workflow([("Log it", None)]).to_wire()
    with pytest.raises(ValueError, match="section"):
        FlowDraft.from_wire(d).add_sequence_number(
            "rn", "Nope", "P-", "0001", "Start"
        ).to_wire()
    with pytest.raises(ValueError, match="activity"):
        FlowDraft.from_wire(d).add_sequence_number(
            "rn", "S", "P-", "0001", "Nope"
        ).to_wire()


def test_add_field_validation_builds_criteria_and_condition() -> None:
    """add_field_validation writes Field --FieldValidation::Criteria--> Criteria
    --Criteria::Condition--> Condition{Operator, RHSValue}; idempotent; a second
    rule appends.
    """

    from app.domain.value_objects.field_spec import FieldSpec
    from app.domain.value_objects.field_type import FieldType

    bare = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Form"},
    }
    d = (
        FlowDraft.from_wire(bare)
        .apply_changes([FieldSpec(name="meeting link", type=FieldType.TEXT)])
        .to_wire()
    )
    got = (
        FlowDraft.from_wire(d)
        .add_field_validation("meeting link", "CONTAINS", "microsoft")
        .to_wire()
    )
    fld = next(
        n
        for n in got.values()
        if isinstance(n, dict)
        and n.get("Kind") == "Field"
        and n.get("Name") == "meeting link"
    )
    assert len(fld["FieldValidation::Criteria"]) == 1
    crit = got[fld["FieldValidation::Criteria"][0]]
    assert crit["FieldValidation"] == fld["Id"]
    assert len(crit["Criteria::Condition"]) == 1
    cond = got[crit["Criteria::Condition"][0]]
    assert cond["Operator"] == "CONTAINS"
    assert cond["RHSValue"] == "microsoft"
    assert cond["HasArguments"] is True

    # idempotent: same rule twice does not duplicate
    again = (
        FlowDraft.from_wire(got)
        .add_field_validation("meeting link", "CONTAINS", "microsoft")
        .to_wire()
    )
    acrit = again[fld["FieldValidation::Criteria"][0]]
    assert len(acrit["Criteria::Condition"]) == 1

    # a second distinct rule appends a Condition to the SAME Criteria
    more = (
        FlowDraft.from_wire(got)
        .add_field_validation("meeting link", "MAX_LENGTH", "200")
        .to_wire()
    )
    mcrit = more[fld["FieldValidation::Criteria"][0]]
    assert len(mcrit["Criteria::Condition"]) == 2
    ops = {more[cid]["Operator"] for cid in mcrit["Criteria::Condition"]}
    assert ops == {"CONTAINS", "MAX_LENGTH"}


def test_add_field_validation_raises_on_missing_field() -> None:
    import pytest

    from app.domain.value_objects.field_spec import FieldSpec
    from app.domain.value_objects.field_type import FieldType

    bare = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Form"},
    }
    d = (
        FlowDraft.from_wire(bare)
        .apply_changes([FieldSpec(name="a", type=FieldType.TEXT)])
        .to_wire()
    )
    with pytest.raises(ValueError, match="field not found"):
        FlowDraft.from_wire(d).add_field_validation("nope", "CONTAINS", "x").to_wire()


def test_add_field_validation_writes_error_message_when_given() -> None:
    """#48/#55: ErrorMessage is a real per-Condition key the platform writes — closes
    the gap docs/capabilities/config.validation.md flags on the engine's own
    docstring."""

    from app.domain.value_objects.field_spec import FieldSpec
    from app.domain.value_objects.field_type import FieldType

    bare = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Form"},
    }
    d = (
        FlowDraft.from_wire(bare)
        .apply_changes([FieldSpec(name="Notes", type=FieldType.TEXT)])
        .to_wire()
    )
    got = (
        FlowDraft.from_wire(d)
        .add_field_validation(
            "Notes", "MAX_LENGTH", "10", error_message="Maximum length is 10 characters"
        )
        .to_wire()
    )
    fld = next(
        n
        for n in got.values()
        if isinstance(n, dict) and n.get("Kind") == "Field" and n.get("Name") == "Notes"
    )
    crit = got[fld["FieldValidation::Criteria"][0]]
    cond = got[crit["Criteria::Condition"][0]]
    assert cond["ErrorMessage"] == "Maximum length is 10 characters"

    # omitted -> the key is simply absent, never written as None
    without = (
        FlowDraft.from_wire(d).add_field_validation("Notes", "CONTAINS", "x").to_wire()
    )
    fld2 = next(
        n
        for n in without.values()
        if isinstance(n, dict) and n.get("Kind") == "Field" and n.get("Name") == "Notes"
    )
    crit2 = without[fld2["FieldValidation::Criteria"][0]]
    cond2 = next(
        without[cid]
        for cid in crit2["Criteria::Condition"]
        if without[cid]["Operator"] == "CONTAINS"
    )
    assert "ErrorMessage" not in cond2


def test_set_field_computed_builds_function_ast_with_field_and_static_args() -> None:
    """#48/#55: the FOURTH Expression owner — Field itself — for a computed formula.
    Root Function node carries NO Syntax key (a prefix call, unlike a branch/goto
    '=' infix root)."""

    from app.domain.value_objects.field_spec import FieldSpec
    from app.domain.value_objects.field_type import FieldType

    bare = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Process"},
    }
    d = (
        FlowDraft.from_wire(bare)
        .apply_changes(
            [
                FieldSpec(name="Computed Sample", type=FieldType.TEXT),
                FieldSpec(name="Source Number", type=FieldType.NUMBER),
            ],
        )
        .to_wire()
    )
    formula = {
        "fn": "concatenate",
        "args": [{"static": "BR-"}, {"field": "Source Number"}],
    }
    got = (
        FlowDraft.from_wire(d).set_field_computed("Computed Sample", formula).to_wire()
    )

    fld = next(
        n
        for n in got.values()
        if isinstance(n, dict)
        and n.get("Kind") == "Field"
        and n.get("Name") == "Computed Sample"
    )
    expr_id = fld["Field::Expression"][0]
    expr = got[expr_id]
    assert expr["Field"] == fld["Id"]
    root_id = expr["Expression::Node"][0]
    root = got[root_id]
    assert root["Type"] == "Function" and root["Value"] == "concatenate"
    assert "Syntax" not in root
    assert root["FieldRefCount"] == 1
    child_types = {got[c]["Type"] for c in root["Node::Node"]}
    assert child_types == {"Static", "Field"}

    src = next(
        n
        for n in got.values()
        if isinstance(n, dict)
        and n.get("Kind") == "Field"
        and n.get("Name") == "Source Number"
    )
    field_node = next(got[c] for c in root["Node::Node"] if got[c]["Type"] == "Field")
    assert field_node["Field"] == src["Id"]
    assert field_node["Id"] in src.get("Field::Node", [])

    # idempotent-ish: a second call REPLACES the expression, never accumulates a second
    # one
    again = (
        FlowDraft.from_wire(got)
        .set_field_computed("Computed Sample", formula)
        .to_wire()
    )
    fld2 = next(
        n
        for n in again.values()
        if isinstance(n, dict)
        and n.get("Kind") == "Field"
        and n.get("Name") == "Computed Sample"
    )
    assert len(fld2["Field::Expression"]) == 1


def test_set_field_computed_raises_on_missing_field_refs() -> None:
    import pytest

    from app.domain.value_objects.field_spec import FieldSpec
    from app.domain.value_objects.field_type import FieldType

    bare = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Process"},
    }
    d = (
        FlowDraft.from_wire(bare)
        .apply_changes([FieldSpec(name="Computed Sample", type=FieldType.TEXT)])
        .to_wire()
    )
    with pytest.raises(ValueError) as exc:
        FlowDraft.from_wire(d).set_field_computed(
            "Computed Sample", {"fn": "concatenate", "args": [{"field": "Nope"}]}
        ).to_wire()
    # The pre-refactor text (kfforge/graph.py @ 2049f6f), byte for byte -- and never
    # the private _set_field_computed a caller cannot import.
    assert "no field named 'Nope' to reference" in str(exc.value)
    assert str(exc.value).startswith("set_field_computed(")
    with pytest.raises(ValueError, match="set_field_computed: field not found"):
        FlowDraft.from_wire(d).set_field_computed(
            "Nope", {"fn": "concatenate", "args": [{"static": "x"}]}
        ).to_wire()


def test_set_field_computed_message_names_the_public_method_on_a_malformed_arg() -> (
    None
):
    """An arg with none of field/static/fn keeps the pre-refactor text
    (`set_field_computed(...)`), never the private `_set_field_computed`."""
    from app.domain.value_objects.field_spec import FieldSpec
    from app.domain.value_objects.field_type import FieldType

    bare = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Process"},
    }
    d = (
        FlowDraft.from_wire(bare)
        .apply_changes([FieldSpec(name="Computed Sample", type=FieldType.TEXT)])
        .to_wire()
    )
    with pytest.raises(ValueError) as exc:
        FlowDraft.from_wire(d).set_field_computed(
            "Computed Sample", {"fn": "concatenate", "args": [{"nonsense": 1}]}
        ).to_wire()
    message = str(exc.value)
    assert "each arg needs one of field/static/fn, got {'nonsense': 1}" in message
    assert message.startswith("set_field_computed(")


def test_set_field_computed_message_names_the_public_method_on_an_empty_fn() -> None:
    """An empty 'fn' string keeps the pre-refactor text
    (`set_field_computed(...)`), never the private `_set_field_computed`."""
    from app.domain.value_objects.field_spec import FieldSpec
    from app.domain.value_objects.field_type import FieldType

    bare = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Process"},
    }
    d = (
        FlowDraft.from_wire(bare)
        .apply_changes([FieldSpec(name="Computed Sample", type=FieldType.TEXT)])
        .to_wire()
    )
    with pytest.raises(ValueError) as exc:
        FlowDraft.from_wire(d).set_field_computed(
            "Computed Sample", {"fn": "", "args": []}
        ).to_wire()
    message = str(exc.value)
    assert "formula needs a non-empty 'fn' string" in message
    assert message.startswith("set_field_computed(")


def test_set_conditional_visibility_builds_columnvisibility_criteria() -> None:
    """#48/#55: the THIRD Criteria owner family — ColumnVisibility. Target hidden by
    default; the trigger Column gets the bidirectional LHSOwnField::Condition
    back-ref."""

    from app.domain.value_objects.field_spec import FieldSpec
    from app.domain.value_objects.field_type import FieldType

    bare = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Form"},
    }
    d = (
        FlowDraft.from_wire(bare)
        .apply_changes(
            [
                FieldSpec(name="Show Details", type=FieldType.BOOLEAN),
                FieldSpec(name="Details", type=FieldType.TEXT),
            ],
        )
        .to_wire()
    )
    got = (
        FlowDraft.from_wire(d)
        .set_conditional_visibility("Details", "Show Details", "EQUAL_TO", "true")
        .to_wire()
    )

    details = next(
        n
        for n in got.values()
        if isinstance(n, dict)
        and n.get("Kind") == "Field"
        and n.get("Name") == "Details"
    )
    target_col = got[details["Column"]]
    assert target_col["IsHidden"] is True
    crit_id = target_col["ColumnVisibility::Criteria"][0]
    crit = got[crit_id]
    assert crit["IsOR"] is False
    cond = got[crit["Criteria::Condition"][0]]
    assert cond["Operator"] == "EQUAL_TO"
    assert cond["HasArguments"] is False
    assert cond["RHSValue"] == "true"

    trigger = next(
        n
        for n in got.values()
        if isinstance(n, dict)
        and n.get("Kind") == "Field"
        and n.get("Name") == "Show Details"
    )
    trigger_col = got[trigger["Column"]]
    assert cond["LHSOwnField"] == trigger_col["Id"]
    assert cond["Id"] in trigger_col.get("LHSOwnField::Condition", [])

    # idempotent-ish: a second call REPLACES the rule, never duplicates it
    again = (
        FlowDraft.from_wire(got)
        .set_conditional_visibility("Details", "Show Details", "EQUAL_TO", "false")
        .to_wire()
    )
    details2 = next(
        n
        for n in again.values()
        if isinstance(n, dict)
        and n.get("Kind") == "Field"
        and n.get("Name") == "Details"
    )
    col2 = again[details2["Column"]]
    assert len(col2["ColumnVisibility::Criteria"]) == 1
    cond2 = again[
        again[col2["ColumnVisibility::Criteria"][0]]["Criteria::Condition"][0]
    ]
    assert cond2["RHSValue"] == "false"


def test_set_conditional_visibility_raises_on_missing_fields() -> None:
    import pytest

    from app.domain.value_objects.field_spec import FieldSpec
    from app.domain.value_objects.field_type import FieldType

    bare = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Form"},
    }
    d = (
        FlowDraft.from_wire(bare)
        .apply_changes([FieldSpec(name="Details", type=FieldType.TEXT)])
        .to_wire()
    )
    with pytest.raises(ValueError, match="trigger field not found"):
        FlowDraft.from_wire(d).set_conditional_visibility(
            "Details", "Nope", "EQUAL_TO", "true"
        ).to_wire()
    with pytest.raises(ValueError, match="set_conditional_visibility: field not found"):
        FlowDraft.from_wire(d).set_conditional_visibility(
            "Nope", "Details", "EQUAL_TO", "true"
        ).to_wire()


def test_add_table_after_section_places_host_adjacent_to_banner() -> None:
    """#10: a table host must be INSERTABLE right after its banner section's root row in
    Model::Row — appending it last strands the empty banner and the whole form fails to
    render (CLAUDE.md > Tables). after_section names the banner; the host lands at
    index(banner_row) + 1, with later sections after it."""

    from app.domain.value_objects.field_spec import FieldSpec
    from app.domain.value_objects.field_type import FieldType

    bare = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Form"},
    }
    draft = (
        FlowDraft.from_wire(bare)
        .apply_changes(
            [
                FieldSpec(name="A", type=FieldType.TEXT),
                FieldSpec(name="B", type=FieldType.TEXT),
            ],
        )
        .to_wire()
    )
    # banner = empty section between two field sections; table must NOT land after
    # "Tail"
    draft = (
        FlowDraft.from_wire(draft)
        .regroup_into_sections([("Head", ["A"]), ("Log Banner", []), ("Tail", ["B"])])
        .to_wire()
    )
    got = (
        FlowDraft.from_wire(draft)
        .add_table("Log", [("Round", FieldType.NUMBER)], after_section="Log Banner")
        .to_wire()
    )

    root_rows = got["M1"]["Model::Row"]
    row_label = {}
    for rid in root_rows:
        cols = got[rid].get("Row::Column", [])
        col = got[cols[0]]
        row_label[rid] = (col.get("Type"), col.get("Name"))
    labels = [row_label[r] for r in root_rows]
    assert labels == [
        ("Section", "Head"),
        ("Section", "Log Banner"),
        ("Model", "Log"),
        ("Section", "Tail"),
    ]


def test_add_table_after_section_unknown_name_raises() -> None:
    import pytest

    from app.domain.value_objects.field_type import FieldType

    bare = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Form"},
    }
    with pytest.raises(ValueError, match="Nope"):
        FlowDraft.from_wire(bare).add_table(
            "Log", [("Round", FieldType.NUMBER)], after_section="Nope"
        ).to_wire()


def _three_section_form() -> dict:

    from app.domain.value_objects.field_spec import FieldSpec
    from app.domain.value_objects.field_type import FieldType

    bare = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Form"},
    }
    d = (
        FlowDraft.from_wire(bare)
        .apply_changes(
            [
                FieldSpec(name="A", type=FieldType.TEXT),
                FieldSpec(name="B", type=FieldType.TEXT),
                FieldSpec(name="C", type=FieldType.TEXT),
            ],
        )
        .to_wire()
    )
    return (
        FlowDraft.from_wire(d)
        .regroup_into_sections([("S1", ["A"]), ("S2", ["B"]), ("S3", ["C"])])
        .to_wire()
    )


def test_set_section_style_full_form_chain_count_is_n_plus_one() -> None:
    """#11: N sections styled + the root Model addressed -> N+1 complete
    Appearance/Style chains (the oracle's 10 = 1 root + 9 sections, expressed here
    as N, not as 10). Every Appearance owns exactly one Style — an empty
    Appearance::Style breaks the whole form's render (CLAUDE.md)."""

    got = (
        FlowDraft.from_wire(_three_section_form())
        .set_section_style(
            {
                name: {"Section.Header.Color": "Color.Secondary.Ten.800"}
                for name in ("S1", "S2", "S3")
            },
            root_style={
                "Form.Field.Color": {"ref": "Color.Primary.500"},
                "Form.Bg.Color": "Color.Transparent",
            },
            hint_text_position="Icon",
        )
        .to_wire()
    )
    apps = {
        k: v
        for k, v in got.items()
        if isinstance(v, dict) and v.get("Kind") == "Appearance"
    }
    stys = {
        k: v for k, v in got.items() if isinstance(v, dict) and v.get("Kind") == "Style"
    }
    assert len(apps) == 4 and len(stys) == 4  # N+1 with N=3
    for a in apps.values():
        assert len(a.get("Appearance::Style") or []) == 1

    root_app_id = (got["M1"].get("Model::Appearance") or [None])[0]
    assert root_app_id is not None, "root Model has no Appearance node"
    root_app = got[root_app_id]
    assert root_app["HintTextPosition"] == "Icon"
    root_style = got[root_app["Appearance::Style"][0]]
    # a bare token string wraps as {"ref": ...}; an explicit {"ref"/"value"} dict passes
    # verbatim
    assert root_style["Value"]["Form.Field.Color"] == {"ref": "Color.Primary.500"}
    assert root_style["Value"]["Form.Bg.Color"] == {"ref": "Color.Transparent"}


def test_set_section_style_accepts_explicit_ref_and_value_dicts() -> None:
    """#11: the {"ref": ...} / {"value": ...} shapes pass through verbatim (the old
    bare-string type rejected them at the tool boundary, so styles never landed at
    all)."""

    got = (
        FlowDraft.from_wire(_three_section_form())
        .set_section_style({"S1": {"Section.Bg.Color": {"value": "#112233"}}})
        .to_wire()
    )
    sec = next(
        v
        for v in got.values()
        if isinstance(v, dict) and v.get("Type") == "Section" and v.get("Name") == "S1"
    )
    style = got[got[sec["Column::Appearance"][0]]["Appearance::Style"][0]]
    assert style["Value"]["Section.Bg.Color"] == {"value": "#112233"}


def test_set_section_style_rejects_unknown_dict_shape() -> None:
    import pytest

    with pytest.raises(ValueError, match="ref"):
        FlowDraft.from_wire(_three_section_form()).set_section_style(
            {"S1": {"Section.Bg.Color": {"nope": "x"}}}
        ).to_wire()


def test_build_workflow_repoints_dangling_sequence_step_stamp() -> None:
    """#18: a SequenceNumber's Step Property holds a SCALAR activity id, which the
    list-only dangling sweep never touches — after a workflow rebuild that shifts
    the stamped step's position it pointed at a deleted Activity, and publish
    500'd MetadataError deterministically (isolated live 2026-08-12 by subsystem
    bisect + a one-key surgical fix). build_workflow must repoint the stamp at the
    rebuilt activity of the SAME NAME (StartEvent when the name is gone), never
    leave the scalar dangling."""

    from app.domain.value_objects.field_spec import FieldSpec
    from app.domain.value_objects.field_type import FieldType

    bare = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "P", "FlowType": "Process"},
    }
    d = (
        FlowDraft.from_wire(bare)
        .apply_changes([FieldSpec(name="A", type=FieldType.TEXT)])
        .to_wire()
    )
    d = FlowDraft.from_wire(d).regroup_into_sections([("Intake", ["A"])]).to_wire()
    d = FlowDraft.from_wire(d).build_workflow([("Review", None)]).to_wire()
    d = (
        FlowDraft.from_wire(d)
        .add_sequence_number("Case ID", "Intake", "CASE-", "0001", "Review")
        .to_wire()
    )
    # rebuild with Review at a NEW position -> new hashed id -> the old stamp target is
    # deleted
    d = (
        FlowDraft.from_wire(d)
        .build_workflow([("Triage", None), ("Review", None)])
        .to_wire()
    )

    step = next(
        v
        for v in d.values()
        if isinstance(v, dict)
        and v.get("Kind") == "Property"
        and v.get("Name") == "Step"
    )
    target = d.get(step.get("Value"))
    assert target is not None, (
        "Step stamp points at a deleted Activity — the publish-500 shape"
    )
    assert target.get("Name") == "Review", (
        "same-name repoint keeps the intended stamp step"
    )

    # name gone entirely -> fall back to the StartEvent, still never dangling
    d2 = FlowDraft.from_wire(d).build_workflow([("Totally Different", None)]).to_wire()
    step2 = next(
        v
        for v in d2.values()
        if isinstance(v, dict)
        and v.get("Kind") == "Property"
        and v.get("Name") == "Step"
    )
    target2 = d2.get(step2.get("Value"))
    assert target2 is not None
    assert target2.get("NodeType") == "StartEvent"


# ---- regroup_into_sections must not corrupt a template-cloned (nested Grid) form
# ------------- The template shell's sections nest fields under Grid-type Columns
# (Section -> Row -> Grid Column -> Row -> Field Column), unlike a plain engine-built
# form (Section -> Row -> Field Column directly). Adding ONE field to an EXISTING
# template section via regroup_into_sections used to (a) leave the old Grid columns
# behind, still pointing at deleted Rows -> dangling refs 137 -> 286 live, and (b) dump
# every OTHER field in that section into a trailing "Other" section since `groups` was
# treated as the complete layout. See CLAUDE.md's own repro write-up.


def _dangling_refs(draft: dict) -> list[str]:
    """Mirror verify.doctor's own dangling-ref rule exactly: every list value under a
    key containing '::' must point at a node that still exists in the draft."""
    problems: list[str] = []
    for nid, node in draft.items():
        if not isinstance(node, dict):
            continue
        for key, val in node.items():
            if not (isinstance(val, list) and "::" in key):
                continue
            for ref in val:
                if isinstance(ref, str) and ref not in draft:
                    problems.append(f"{nid}.{key} -> {ref}")
    return problems


def test_regroup_on_template_shell_adds_field_no_dangling_or_orphaned_grid() -> None:
    """The most natural first build action on a template-cloned process: add ONE
    field to an EXISTING template section, through the same two-step path
    forge_apply_fields uses (apply the field, then regroup with a partial section
    map merged against current membership)."""

    from app.domain.value_objects.field_spec import FieldSpec
    from app.domain.value_objects.field_type import FieldType

    draft = FlowDraft.from_wire(_bare_process()).clone_template_shell().to_wire()
    new = (
        FlowDraft.from_wire(draft)
        .apply_changes([FieldSpec(name="New Field", type=FieldType.TEXT)])
        .to_wire()
    )
    merged = FlowDraft.from_wire(new).merge_groups([("Request Info", ["New Field"])])
    got = FlowDraft.from_wire(new).regroup_into_sections(merged).to_wire()

    assert _dangling_refs(got) == [], (
        "no reference may point at a node the rebuild deleted"
    )

    grid_columns = [
        k
        for k, v in got.items()
        if isinstance(v, dict) and v.get("Kind") == "Column" and v.get("Type") == "Grid"
    ]
    assert grid_columns == [], (
        "the old nested Grid wrapper columns must not survive a regroup"
    )

    # every pre-existing Required field must still live in a REAL named section, never
    # "Other"
    required = {
        v["Name"]
        for v in draft.values()
        if isinstance(v, dict) and v.get("Kind") == "Field" and v.get("Required")
    }
    assert required, "sanity: the template ships Required fields"

    section_of: dict[str, str] = {}
    for _sid, sec in got.items():
        if (
            isinstance(sec, dict)
            and sec.get("Kind") == "Column"
            and sec.get("Type") == "Section"
        ):
            for rid in sec.get("Column::Row") or []:
                for cid in got[rid]["Row::Column"]:
                    for fid in got[cid].get("Column::Field") or []:
                        section_of[got[fid]["Name"]] = sec.get("Name")

    for name in required:
        assert section_of.get(name) not in (None, "Other"), (
            f"required field {name!r} must stay in a real section, not fall to Other"
        )

    # the new field landed exactly where the caller asked
    assert section_of.get("New Field") == "Request Info"


def test_regroup_on_a_plain_engine_built_form_is_unchanged() -> None:
    """Regression guard: a non-nested engine-built form (no Grid wrapper columns)
    must regroup exactly as it did before the template-shell fix."""

    got = (
        FlowDraft.from_wire(_draft_with_fields("a", "b", "c", "d"))
        .regroup_into_sections(
            [("Step 1", ["a", "b"]), ("Step 2", ["c", "d"])],
        )
        .to_wire()
    )

    assert _dangling_refs(got) == []
    placed: dict[str, list[str]] = {}
    for top in got["M1"]["Model::Row"]:
        sec = got[got[top]["Row::Column"][0]]
        names = []
        for r in sec["Column::Row"]:
            for c in got[r]["Row::Column"]:
                names += [got[f]["Name"] for f in got[c]["Column::Field"]]
        placed[sec["Name"]] = names
    assert placed == {"Step 1": ["a", "b"], "Step 2": ["c", "d"]}


def test_regroup_does_not_break_a_table_bearing_flow() -> None:
    """A table host lives in its own root-level Row, outside every Section (CLAUDE.md
    > Tables). regroup_into_sections rebuilds field-layout Rows/Sections; it must
    never delete the table's own host Row or its nested schema Row, and the table
    host Column must survive untouched."""

    from app.domain.value_objects.field_type import FieldType

    draft = (
        FlowDraft.from_wire(_draft_with_fields("A", "B"))
        .regroup_into_sections(
            [("Head", ["A"]), ("Log Banner", []), ("Tail", ["B"])],
        )
        .to_wire()
    )
    draft = (
        FlowDraft.from_wire(draft)
        .add_table("Log", [("Round", FieldType.NUMBER)], after_section="Log Banner")
        .to_wire()
    )

    # add one more field to an existing section on the table-bearing draft, same call
    # shape as the template-shell scenario above

    from app.domain.value_objects.field_spec import FieldSpec

    new = (
        FlowDraft.from_wire(draft)
        .apply_changes([FieldSpec(name="C", type=FieldType.TEXT)])
        .to_wire()
    )
    merged = FlowDraft.from_wire(new).merge_groups([("Head", ["C"])])
    got = FlowDraft.from_wire(new).regroup_into_sections(merged).to_wire()

    assert _dangling_refs(got) == []

    table_hosts = [
        v
        for v in got.values()
        if isinstance(v, dict)
        and v.get("Kind") == "Column"
        and v.get("Type") == "Model"
    ]
    assert len(table_hosts) == 1, (
        "the table host column must survive a regroup untouched"
    )
    host = table_hosts[0]
    assert got.get(host["Row"]) is not None, (
        "the table host's own root Row must survive"
    )
    table_id = host["Column::Model"][0]
    table_model = got[table_id]
    assert table_model["Model::Row"], "the table's own schema Row must survive"
    schema_row_id = table_model["Model::Row"][0]
    assert got.get(schema_row_id) is not None

    # the table host column is still a live root-level row, not folded into any Section
    root_rows = got["M1"]["Model::Row"]
    assert host["Row"] in root_rows


# =====================================================================================
# Field lifecycle (F2): delete_closure / field_delete_blockers / delete_nodes.
# `delete_nodes` had ZERO callers before the client wrappers landed, so its sweep had
# never been exercised against a field carrying any of the CONFIGURATION nodes the
# engine can now attach (query definition, computed formula, validation, conditional
# visibility, sequence properties). Every one of those hangs off the field by a SCALAR
# back-reference, which `_sweep_dangling` is deliberately blind to and which is the
# deterministic publish-500 (#18).
# =====================================================================================


def _scalar_dangling_refs(draft: dict) -> list[str]:
    """Every SCALAR (non-list) value that LOOKS like a node id and points at a node
    that is not in the draft. The exact blind spot
    `_dangling_refs`/`_sweep_dangling` (list-only, by design) cannot see — and the
    one that publishes 500 with zero diagnostics."""
    prefixes = (
        "Field_",
        "Column_",
        "Row_",
        "Permission_",
        "Event_",
        "Expression_",
        "Node_",
        "Criteria_",
        "Condition_",
        "QueryDefinition_",
        "Property_",
        "Activity_",
        "ProcessDef_",
        "Resource_",
        "Model_",
    )
    problems: list[str] = []
    for nid, node in draft.items():
        if not isinstance(node, dict):
            continue
        for key, val in node.items():
            if key == "Id" or not isinstance(val, str):
                continue
            if val.startswith(prefixes) and val not in draft:
                problems.append(f"{nid}.{key} -> {val}")
    return problems


def _form_with(*specs) -> dict:

    d = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Form"},
    }
    return FlowDraft.from_wire(d).apply_changes(list(specs)).to_wire()


def test_delete_nodes_sweeps_a_user_fields_query_definition() -> None:
    """A `User` field's sibling QueryDefinition holds a SCALAR `Field` back-ref. Left
    behind it is an orphan pointing at a dead id — and refusing the delete instead
    would make every User field permanently undeletable, since nothing on the tool
    surface can remove a QueryDefinition."""

    draft = _form_with(FieldSpec(name="Owner", type=FieldType.USER))
    qids = [
        k
        for k, v in draft.items()
        if isinstance(v, dict) and v.get("Kind") == "QueryDefinition"
    ]
    assert len(qids) == 1, (
        "fixture must actually carry the User field's QueryDefinition"
    )

    assert qids[0] in FlowDraft.from_wire(draft).delete_closure(("Owner",))
    got = FlowDraft.from_wire(draft).delete_nodes(("Owner",)).to_wire()
    assert qids[0] not in got
    assert _scalar_dangling_refs(got) == []


def test_delete_nodes_sweeps_the_fields_own_computed_expression_tree() -> None:

    draft = _form_with(
        FieldSpec(name="Total", type=FieldType.NUMBER),
        FieldSpec(name="Qty", type=FieldType.NUMBER),
    )
    draft = (
        FlowDraft.from_wire(draft)
        .set_field_computed(
            "Total",
            {"fn": "concatenate", "args": [{"static": "n="}, {"field": "Qty"}]},
        )
        .to_wire()
    )
    assert any(
        v.get("Kind") == "Expression" for v in draft.values() if isinstance(v, dict)
    )

    got = FlowDraft.from_wire(draft).delete_nodes(("Total",)).to_wire()
    assert not [
        v for v in got.values() if isinstance(v, dict) and v.get("Kind") == "Expression"
    ]
    assert not [
        v for v in got.values() if isinstance(v, dict) and v.get("Kind") == "Node"
    ]
    assert _scalar_dangling_refs(got) == []
    assert "Qty" in {
        v.get("Name")
        for v in got.values()
        if isinstance(v, dict) and v.get("Kind") == "Field"
    }


def test_delete_nodes_sweeps_the_fields_own_validation_criteria_and_conditions() -> (
    None
):

    draft = _form_with(FieldSpec(name="Code", type=FieldType.TEXT))
    draft = (
        FlowDraft.from_wire(draft)
        .add_field_validation("Code", "MAX_LENGTH", "10")
        .to_wire()
    )
    assert any(
        v.get("Kind") == "Condition" for v in draft.values() if isinstance(v, dict)
    )

    got = FlowDraft.from_wire(draft).delete_nodes(("Code",)).to_wire()
    assert not [
        v
        for v in got.values()
        if isinstance(v, dict) and v.get("Kind") in ("Criteria", "Condition")
    ]
    assert _scalar_dangling_refs(got) == []


def test_delete_nodes_sweeps_the_fields_own_conditional_visibility_rule() -> None:
    """Deleting the TARGET of a conditional-visibility rule takes the rule with it —
    and the trigger column's `LHSOwnField::Condition` back-ref is a LIST, so the
    existing sweep clears it."""

    draft = _form_with(
        FieldSpec(name="Reason", type=FieldType.TEXT),
        FieldSpec(name="Flag", type=FieldType.BOOLEAN),
    )
    draft = (
        FlowDraft.from_wire(draft)
        .set_conditional_visibility("Reason", "Flag", "EQUAL_TO", "true")
        .to_wire()
    )

    got = FlowDraft.from_wire(draft).delete_nodes(("Reason",)).to_wire()
    assert not [
        v
        for v in got.values()
        if isinstance(v, dict) and v.get("Kind") in ("Criteria", "Condition")
    ]
    assert _scalar_dangling_refs(got) == []
    assert _dangling_refs(got) == []


def test_delete_nodes_still_sweeps_the_column_and_its_permissions() -> None:
    """Regression net for the ORIGINAL sweep, now that delete_nodes routes through
    delete_closure: the field, its Column and every Permission on that Column
    still go."""

    draft = _form_with(
        FieldSpec(name="a", type=FieldType.TEXT),
        FieldSpec(name="b", type=FieldType.TEXT),
    )
    fid = next(
        k
        for k, v in draft.items()
        if isinstance(v, dict) and v.get("Kind") == "Field" and v.get("Name") == "a"
    )
    col = draft[fid]["Column"]
    draft["Permission_x"] = {
        "Id": "Permission_x",
        "Kind": "Permission",
        "Column": col,
        "Activity": "Activity_1",
        "Permission": "Editable",
    }
    draft[col].setdefault("Column::Permission", []).append("Permission_x")

    got = FlowDraft.from_wire(draft).delete_nodes(("a",)).to_wire()
    assert fid not in got and col not in got and "Permission_x" not in got
    assert "b" in {
        v.get("Name")
        for v in got.values()
        if isinstance(v, dict) and v.get("Kind") == "Field"
    }


def test_delete_nodes_unknown_name_raises_before_any_copy() -> None:

    draft = _form_with(FieldSpec(name="a", type=FieldType.TEXT))
    snapshot = copy.deepcopy(draft)
    with pytest.raises(ValueError, match="no field named 'nope'"):
        FlowDraft.from_wire(draft).delete_nodes(("a", "nope")).to_wire()
    assert draft == snapshot, "a rejected delete must leave the input byte-identical"


def test_field_delete_blockers_is_empty_for_a_plain_field() -> None:

    draft = _form_with(
        FieldSpec(name="a", type=FieldType.TEXT),
        FieldSpec(name="b", type=FieldType.TEXT),
    )
    assert FlowDraft.from_wire(draft).field_delete_blockers(("a",)) == ()


def test_field_delete_blockers_names_a_surviving_formula_that_reads_the_field() -> None:
    """`Total`'s formula reads `Qty` by id through a `Node{Type:"Field"}`. Deleting
    `Qty` leaves that Node holding a dead scalar — and sweeping it would silently
    rewrite Total's formula, a change the caller never asked for. So: refuse, and
    name the remedy."""

    draft = _form_with(
        FieldSpec(name="Total", type=FieldType.NUMBER),
        FieldSpec(name="Qty", type=FieldType.NUMBER),
    )
    draft = (
        FlowDraft.from_wire(draft)
        .set_field_computed("Total", {"fn": "concatenate", "args": [{"field": "Qty"}]})
        .to_wire()
    )

    blockers = FlowDraft.from_wire(draft).field_delete_blockers(("Qty",))
    assert len(blockers) == 1
    assert "'Qty'" in blockers[0] and "Expression" in blockers[0]
    assert FlowDraft.from_wire(draft).field_delete_blockers(("Total",)) == (), (
        "the OWNER of the formula deletes clean"
    )


def test_field_delete_blockers_names_a_conditional_visibility_trigger() -> None:

    draft = _form_with(
        FieldSpec(name="Reason", type=FieldType.TEXT),
        FieldSpec(name="Flag", type=FieldType.BOOLEAN),
    )
    draft = (
        FlowDraft.from_wire(draft)
        .set_conditional_visibility("Reason", "Flag", "EQUAL_TO", "true")
        .to_wire()
    )

    blockers = FlowDraft.from_wire(draft).field_delete_blockers(("Flag",))
    assert len(blockers) == 1 and "TRIGGER" in blockers[0] and "'Flag'" in blockers[0]
    assert FlowDraft.from_wire(draft).field_delete_blockers(("Reason",)) == ()


def test_field_delete_blockers_names_a_surviving_event_script_that_uses_the_id() -> (
    None
):
    """`set_field_events` already refuses a script naming a MISSING field ("breaks
    the WHOLE form at load"). The delete side of the same rule: never create that
    condition either."""

    draft = _form_with(
        FieldSpec(name="Source", type=FieldType.TEXT),
        FieldSpec(name="Target", type=FieldType.TEXT),
    )
    tgt = next(
        k
        for k, v in draft.items()
        if isinstance(v, dict)
        and v.get("Kind") == "Field"
        and v.get("Name") == "Target"
    )
    draft = (
        FlowDraft.from_wire(draft)
        .set_field_events({"Source": [("onChange", f"kf.x('{tgt}');")]})
        .to_wire()
    )

    blockers = FlowDraft.from_wire(draft).field_delete_blockers(("Target",))
    assert len(blockers) == 1 and "Script" in blockers[0] and "'Target'" in blockers[0]
    assert FlowDraft.from_wire(draft).field_delete_blockers(("Source",)) == (), (
        "the event's OWN field deletes clean"
    )


def test_delete_closure_sweeps_table_and_its_cluster() -> None:

    draft = _form_with(FieldSpec(name="Notes", type=FieldType.TEXT))
    draft = (
        FlowDraft.from_wire(draft)
        .add_table("Items", [("Qty", FieldType.NUMBER), ("Desc", FieldType.TEXT)])
        .to_wire()
    )

    host_col = next(
        k
        for k, v in draft.items()
        if isinstance(v, dict)
        and v.get("Kind") == "Column"
        and v.get("Type") == "Model"
        and v.get("Name") == "Items"
    )
    nested_model = draft[host_col]["Column::Model"][0]

    doomed = FlowDraft.from_wire(draft).delete_closure(tables=("Items",))
    assert host_col in doomed
    assert nested_model in doomed
    assert draft[host_col].get("Row") in doomed
    for r in draft[nested_model].get("Model::Row", []):
        assert r in doomed
    for f in draft[nested_model].get("Model::Field", []):
        assert f in doomed
        assert draft[f]["Column"] in doomed

    got = FlowDraft.from_wire(draft).delete_nodes(tables=("Items",)).to_wire()
    assert host_col not in got
    assert nested_model not in got
    assert "Notes" in {
        v.get("Name")
        for v in got.values()
        if isinstance(v, dict) and v.get("Kind") == "Field"
    }
    assert _scalar_dangling_refs(got) == []


def test_delete_closure_unknown_table_raises() -> None:

    draft = _form_with(FieldSpec(name="Notes", type=FieldType.TEXT))
    with pytest.raises(ValueError, match="no table named 'Missing'"):
        FlowDraft.from_wire(draft).delete_closure(tables=("Missing",))


def test_delete_closure_sweeps_sequence_number_property_chain() -> None:

    bare = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Process"},
    }
    d = (
        FlowDraft.from_wire(bare)
        .apply_changes([FieldSpec(name="a", type=FieldType.TEXT)])
        .to_wire()
    )
    d = FlowDraft.from_wire(d).regroup_into_sections([("S", ["a"])]).to_wire()
    d = FlowDraft.from_wire(d).build_workflow([("Log it", None)]).to_wire()
    draft = (
        FlowDraft.from_wire(d)
        .add_sequence_number("running number", "S", "PRE-", "0001", "Start", 0, 2)
        .to_wire()
    )

    prop_ids = [
        k
        for k, v in draft.items()
        if isinstance(v, dict) and v.get("Kind") == "Property"
    ]
    assert len(prop_ids) == 3, "SequenceNumber creates 3 Property nodes"

    doomed = FlowDraft.from_wire(draft).delete_closure(fields=("running number",))
    for pid in prop_ids:
        assert pid in doomed

    got = FlowDraft.from_wire(draft).delete_nodes(fields=("running number",)).to_wire()
    assert not any(
        isinstance(v, dict) and v.get("Kind") == "Property" for v in got.values()
    )
    assert _scalar_dangling_refs(got) == []


def test_delete_closure_resolves_field_by_raw_node_id_and_handles_missing_column() -> (
    None
):

    draft = _form_with(FieldSpec(name="A", type=FieldType.TEXT))
    fid = next(
        k
        for k, v in draft.items()
        if isinstance(v, dict) and v.get("Kind") == "Field" and v.get("Name") == "A"
    )

    # Resolve by raw id
    assert fid in FlowDraft.from_wire(draft).delete_closure(fields=(fid,))

    # Field without a Column
    draft["Field_no_col"] = {
        "Id": "Field_no_col",
        "Kind": "Field",
        "Name": "NoCol",
        "Column": None,
    }
    assert "Field_no_col" in FlowDraft.from_wire(draft).delete_closure(
        fields=("NoCol",)
    )


def test_delete_closure_sweeps_events_and_criteria_with_column_visibility() -> None:

    draft = _form_with(FieldSpec(name="Flag", type=FieldType.BOOLEAN))
    fid = next(
        k
        for k, v in draft.items()
        if isinstance(v, dict) and v.get("Kind") == "Field" and v.get("Name") == "Flag"
    )
    col = draft[fid]["Column"]

    draft["Event_1"] = {
        "Id": "Event_1",
        "Kind": "Event",
        "Field": fid,
        "Type": "onChange",
    }
    draft["Criteria_1"] = {
        "Id": "Criteria_1",
        "Kind": "Criteria",
        "ColumnVisibility": col,
        "Criteria::Condition": ["Condition_1"],
    }
    draft["Condition_1"] = {
        "Id": "Condition_1",
        "Kind": "Condition",
        "Criteria": "Criteria_1",
    }

    # Surviving criteria and property
    draft["Field_surv"] = {
        "Id": "Field_surv",
        "Kind": "Field",
        "Name": "Surv",
        "Column": "Col_surv",
    }
    draft["Property_surv"] = {
        "Id": "Property_surv",
        "Kind": "Property",
        "Field": "Field_surv",
    }
    draft["Criteria_surv"] = {
        "Id": "Criteria_surv",
        "Kind": "Criteria",
        "FieldValidation": "Field_surv",
    }

    doomed = FlowDraft.from_wire(draft).delete_closure(fields=("Flag",))
    assert "Event_1" in doomed
    assert "Criteria_1" in doomed
    assert "Condition_1" in doomed
    assert "Property_surv" not in doomed
    assert "Criteria_surv" not in doomed


def test_delete_closure_table_and_node_tree_edge_cases() -> None:
    from app.domain.entities._flow_ops import _node_tree

    # Test _node_tree with duplicates, missing nodes, and non-string roots
    draft = {
        "N1": {"Id": "N1", "Node::Node": ["N2", "N_missing", "N1"]},
        "N2": {"Id": "N2", "Node::Node": []},
    }
    tree = _node_tree(draft, ["N1", None, 123])
    assert tree == {"N1", "N2"}

    # Test table with non-string row and child field with no column
    table_draft = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "FlowType": "Form"},
        "Col_tbl": {
            "Id": "Col_tbl",
            "Kind": "Column",
            "Type": "Model",
            "Name": "Tbl",
            "Row": None,
            "Column::Model": ["Model_tbl"],
        },
        "Model_tbl": {
            "Id": "Model_tbl",
            "Kind": "Model",
            "Model::Field": ["Field_child"],
        },
        "Field_child": {"Id": "Field_child", "Kind": "Field", "Column": None},
    }
    doomed = FlowDraft.from_wire(table_draft).delete_closure(tables=("Tbl",))
    assert doomed == {"Col_tbl", "Model_tbl", "Field_child"}


# ---- apply_changes: a Select must name the list its options live in
# --------------------------


def test_apply_changes_refuses_a_select_with_no_referred_list() -> None:
    """Rule A′ (2026-08-19 publish-500 diagnosis). A Select's OPTIONS live in a
    separate list flow; minting one with no `ReferredList` is a dropdown bound to
    nothing, which PUTs 200 and dies on publish with a bare MetadataError. The
    `FieldType.USER` branch twenty lines below already refuses/repairs its own
    version of exactly this defect — refuse at compile (ADR-0004), naming the fix,
    rather than writing a field that cannot publish."""
    import pytest

    from app.domain.value_objects.field_spec import FieldSpec
    from app.domain.value_objects.field_type import FieldType

    with pytest.raises(ValueError, match=r"'Urgency'.*referred_list"):
        FlowDraft.from_wire(_load()).apply_changes(
            [FieldSpec(name="Urgency", type=FieldType.SELECT)]
        ).to_wire()


def test_apply_changes_refuses_the_select_before_touching_the_graph() -> None:
    """Validation-first, like every other refusal in apply_changes: a batch whose
    LAST spec is a bare Select must not have written the earlier ones."""
    import copy as _copy

    import pytest

    from app.domain.value_objects.field_spec import FieldSpec
    from app.domain.value_objects.field_type import FieldType

    draft = _load()
    snapshot = _copy.deepcopy(draft)
    with pytest.raises(ValueError, match="referred_list"):
        FlowDraft.from_wire(draft).apply_changes(
            [
                FieldSpec(name="Notes", type=FieldType.TEXT),
                FieldSpec(name="Urgency", type=FieldType.SELECT),
            ],
        ).to_wire()
    assert draft == snapshot


def test_apply_changes_writes_a_wired_select() -> None:

    from app.domain.value_objects.field_spec import FieldSpec
    from app.domain.value_objects.field_type import FieldType

    got = (
        FlowDraft.from_wire(_load())
        .apply_changes(
            [
                FieldSpec(
                    name="Urgency", type=FieldType.SELECT, referred_list="List_Sample01"
                )
            ],
        )
        .to_wire()
    )
    (fld,) = [
        v for v in got.values() if isinstance(v, dict) and v.get("Name") == "Urgency"
    ]
    assert fld["Type"] == "Select" and fld["ReferredList"] == "List_Sample01"


# ---- S2(a) / D10: progressive_matrix DROPPED an unknown name instead of refusing it
# ----------- Two tool descriptions (kf_plan_step_visibility, kf_set_step_visibility)
# already claimed "a section or step name that is not in `draft` is refused as DATA
# here". It was not: an unknown section key matched no Section and simply never
# appeared, and an unknown step name matched no Activity, which read as "nobody owns
# this section" and quietly emitted ReadOnly everywhere — on a DESTRUCTIVE rebuild that
# deletes every Permission first. The name the caller supplied landed in no bucket at
# all (doctrine 2).


def _visibility_draft() -> dict:
    from synthetic import synthetic_process_draft

    return synthetic_process_draft()


def test_progressive_matrix_refuses_a_section_name_that_is_not_on_the_form() -> None:
    from app.domain.entities.flow_draft import progressive_matrix

    with pytest.raises(
        ValueError, match=r"section\(s\) not on this form.*NoSuchSection"
    ):
        progressive_matrix(
            FlowDraft.from_wire(_visibility_draft()), {"NoSuchSection": ["Assess unit"]}
        )


def test_progressive_matrix_refuses_a_step_name_that_is_not_on_the_workflow() -> None:
    from app.domain.entities.flow_draft import progressive_matrix

    with pytest.raises(
        ValueError, match=r"step\(s\) not on this workflow.*Assess Unit"
    ):
        progressive_matrix(
            FlowDraft.from_wire(_visibility_draft()), {"Assessment": ["Assess Unit"]}
        )  # wrong case


def test_the_refusal_names_what_is_actually_available() -> None:
    """A refusal a caller cannot act on is a dead end.

    Both messages list the real set.
    """
    from app.domain.entities.flow_draft import progressive_matrix

    with pytest.raises(ValueError) as sec:
        progressive_matrix(
            FlowDraft.from_wire(_visibility_draft()), {"Intak": ["Start"]}
        )
    assert "Intake" in str(sec.value)

    with pytest.raises(ValueError) as step:
        progressive_matrix(
            FlowDraft.from_wire(_visibility_draft()), {"Intake": ["Strt"]}
        )
    assert "Start" in str(step.value)


def test_a_section_the_owners_map_deliberately_omits_is_still_legal() -> None:
    """The control, and it must pass BOTH before and after the guard: leaving a
    section out of `owners` is the documented unowned case (ReadOnly everywhere),
    NOT an unresolved name. A guard that could not tell the two apart would break
    every real call — the synthetic draft's own "Other" section is deliberately
    unowned."""
    from synthetic import OWNERS

    from app.domain.entities.flow_draft import progressive_matrix

    matrix = progressive_matrix(FlowDraft.from_wire(_visibility_draft()), OWNERS)
    assert "Other" not in OWNERS and "Other" in matrix
    assert set(matrix["Other"].values()) == {Visibility.READONLY}


def test_an_empty_owner_list_is_still_legal() -> None:
    """The other half of the control: `{"Other": []}` names a REAL section with no
    owner. It must stay legal — only an unresolvable NAME is refused, never an
    empty list."""
    from app.domain.entities.flow_draft import progressive_matrix

    matrix = progressive_matrix(FlowDraft.from_wire(_visibility_draft()), {"Other": []})
    assert set(matrix["Other"].values()) == {Visibility.READONLY}


def test_repack_layout_pure_does_not_mutate_input() -> None:
    from synthetic import synthetic_process_draft

    draft = synthetic_process_draft()
    before = copy.deepcopy(draft)
    out = FlowDraft.from_wire(draft).repack_layout().to_wire()
    assert draft == before
    assert out is not draft


def test_repack_layout_default_widths_and_column_stretching() -> None:
    from synthetic import synthetic_process_draft

    draft = synthetic_process_draft()
    repacked = FlowDraft.from_wire(draft).repack_layout().to_wire()

    # In synthetic draft: "Intake" has Ticket No (Text, 3), Contact Date (Date, 3), Unit
    # Serial (Text, 3), Problem (Textarea, 6) Row 0: Ticket No (0, 3), Contact Date (3,
    # 6) Row 1: Unit Serial (0, 6) -> stretched to 6 Row 2: Problem (0, 6)
    intake_sec = next(
        v
        for v in repacked.values()
        if isinstance(v, dict)
        and v.get("Type") == "Section"
        and v.get("Name") == "Intake"
    )
    row_ids = intake_sec["Column::Row"]
    assert len(row_ids) == 3

    r0 = repacked[row_ids[0]]
    assert len(r0["Row::Column"]) == 2
    c0_0, c0_1 = r0["Row::Column"]
    assert (repacked[c0_0]["Start"], repacked[c0_0]["End"]) == (0, 3)
    assert (repacked[c0_1]["Start"], repacked[c0_1]["End"]) == (3, 6)

    r1 = repacked[row_ids[1]]
    assert len(r1["Row::Column"]) == 1
    c1_0 = r1["Row::Column"][0]
    assert (repacked[c1_0]["Start"], repacked[c1_0]["End"]) == (0, 6)

    r2 = repacked[row_ids[2]]
    assert len(r2["Row::Column"]) == 1
    c2_0 = r2["Row::Column"][0]
    assert (repacked[c2_0]["Start"], repacked[c2_0]["End"]) == (0, 6)


def test_repack_layout_custom_widths_and_capping() -> None:
    from synthetic import synthetic_process_draft

    draft = synthetic_process_draft()
    repacked = (
        FlowDraft.from_wire(draft)
        .repack_layout(widths={"Text": 6, "Select": 2, "Uncapped": 10})
        .to_wire()
    )

    # "Wrap-up" has Wrap Summary (Textarea, 6), Outcome (Select, 2), Handoff Owner
    # (Text, 6) Row 0: Wrap Summary (0, 6) Row 1: Outcome (0, 6) -> stretched from 2 to
    # 6 Row 2: Handoff Owner (0, 6)
    wrap_sec = next(
        v
        for v in repacked.values()
        if isinstance(v, dict)
        and v.get("Type") == "Section"
        and v.get("Name") == "Wrap-up"
    )
    row_ids = wrap_sec["Column::Row"]
    assert len(row_ids) == 3


def test_repack_layout_zero_width_column_packs_into_new_row() -> None:
    """A width override of 0 is legal per `widths: dict[str, int] | None` — the
    bootstrap must still open a fresh row for the very first column (`not rows or
    used + w > ROW_UNITS`), never index into an empty `rows` list."""
    from synthetic import synthetic_process_draft

    draft = synthetic_process_draft()
    repacked = FlowDraft.from_wire(draft).repack_layout(widths={"Text": 0}).to_wire()

    # "Intake" has Ticket No (Text->0), Contact Date (Date, 3), Unit Serial (Text->0),
    # Problem (Textarea, 6) Row 0: Ticket No (0, 0), Contact Date (0, 3), Unit Serial
    # (3, 6) -> stretched Row 1: Problem (0, 6)
    intake_sec = next(
        v
        for v in repacked.values()
        if isinstance(v, dict)
        and v.get("Type") == "Section"
        and v.get("Name") == "Intake"
    )
    row_ids = intake_sec["Column::Row"]
    assert len(row_ids) == 2

    r0 = repacked[row_ids[0]]
    assert len(r0["Row::Column"]) == 3
    c0_0, c0_1, c0_2 = r0["Row::Column"]
    assert (repacked[c0_0]["Start"], repacked[c0_0]["End"]) == (0, 0)
    assert (repacked[c0_1]["Start"], repacked[c0_1]["End"]) == (0, 3)
    assert (repacked[c0_2]["Start"], repacked[c0_2]["End"]) == (3, 6)

    r1 = repacked[row_ids[1]]
    assert len(r1["Row::Column"]) == 1


def test_repack_layout_section_and_step_descriptions() -> None:
    from synthetic import synthetic_process_draft

    draft = synthetic_process_draft()
    sec_desc = {"Intake": "Intake Subtitle", "UnmatchedSec": "No-op"}
    step_desc = {"Ticket arrives": "Step 1 Subtitle", "UnmatchedStep": "No-op"}

    repacked = (
        FlowDraft.from_wire(draft)
        .repack_layout(section_descriptions=sec_desc, step_descriptions=step_desc)
        .to_wire()
    )

    intake_sec = next(
        v
        for v in repacked.values()
        if isinstance(v, dict)
        and v.get("Type") == "Section"
        and v.get("Name") == "Intake"
    )
    assert intake_sec.get("Description") == "Intake Subtitle"

    step_node = next(
        v
        for v in repacked.values()
        if isinstance(v, dict)
        and v.get("Kind") == "Activity"
        and v.get("Name") == "Ticket arrives"
    )
    assert step_node.get("Description") == "Step 1 Subtitle"

    other_sec = next(
        v
        for v in repacked.values()
        if isinstance(v, dict)
        and v.get("Type") == "Section"
        and v.get("Name") == "Other"
    )
    assert "Description" not in other_sec


def test_repack_layout_edge_cases_and_unknown_types() -> None:

    # Edge cases:
    # 1. Section with empty Column::Row or None Column::Row
    # 2. Section with Row having empty Row::Column or dangling row id
    # 3. Field without Column reference
    # 4. Column of non-Section type (e.g. Model or Field)
    # 5. Column with unknown field type (falls back to DEFAULT_WIDTH)
    synthetic_draft = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "FlowType": "Process"},
        "Sec_Empty": {
            "Id": "Sec_Empty",
            "Kind": "Column",
            "Type": "Section",
            "Name": "EmptySec",
            "Column::Row": [],
        },
        "Sec_NoneRows": {
            "Id": "Sec_NoneRows",
            "Kind": "Column",
            "Type": "Section",
            "Name": "NoneRowsSec",
            "Column::Row": None,
        },
        "Sec_Dangling": {
            "Id": "Sec_Dangling",
            "Kind": "Column",
            "Type": "Section",
            "Name": "DanglingSec",
            "Column::Row": ["Row_Ghost", "Row_With_Unknown", "Row_Ghost2"],
        },
        "Row_Ghost2": None,
        "Row_With_Unknown": {
            "Id": "Row_With_Unknown",
            "Kind": "Row",
            "Column": "Sec_Dangling",
            "Row::Column": ["Col_Unknown", "Col_NoField"],
        },
        "Col_Unknown": {"Id": "Col_Unknown", "Kind": "Column", "Type": "Field"},
        "Field_Unknown": {
            "Id": "Field_Unknown",
            "Kind": "Field",
            "Type": "CustomUnknownType",
            "Column": "Col_Unknown",
        },
        "Col_NoField": {"Id": "Col_NoField", "Kind": "Column", "Type": "Field"},
        "Field_NoCol": {"Id": "Field_NoCol", "Kind": "Field", "Type": "Text"},
        "Col_Model": {"Id": "Col_Model", "Kind": "Column", "Type": "Model"},
    }

    repacked = FlowDraft.from_wire(synthetic_draft).repack_layout(widths={}).to_wire()
    assert repacked["Sec_Empty"]["Column::Row"] == []
    assert repacked["Sec_NoneRows"]["Column::Row"] == []

    dangling_sec = repacked["Sec_Dangling"]
    assert len(dangling_sec["Column::Row"]) == 1
    new_rid = dangling_sec["Column::Row"][0]
    assert repacked[new_rid]["Row::Column"] == ["Col_Unknown", "Col_NoField"]
    # Unknown field type gets DEFAULT_WIDTH (2), Col_NoField gets DEFAULT_WIDTH (2)
    # Row packing: 2 + 2 = 4 <= 6 -> placed in same row
    # Col_Unknown gets (0, 2), Col_NoField stretched from 2 to 6 -> (2, 6)
    assert (repacked["Col_Unknown"]["Start"], repacked["Col_Unknown"]["End"]) == (0, 2)
    assert (repacked["Col_NoField"]["Start"], repacked["Col_NoField"]["End"]) == (2, 6)


def test_repack_layout_introduces_no_new_doctor_problems() -> None:
    """repack_layout rewrites row/column geometry; nothing it does may make the graph
    less healthy than it already was.
    This assertion used to read `assert report.ok, report.violations` — `ok` is a
    METHOD, so the bare attribute was a bound-method object and always truthy. The test
    therefore passed without ever running the audit, and `violations` (not a field on
    DoctorReport; the field is `problems`) was never evaluated either, because an assert
    only builds its message on failure.
    Calling it revealed the real state: the synthetic fixture carries 13 pre-existing
    problems, all of the form "section X is never editable at any live step" — a
    property of the fixture's permission matrix, not of layout. So absolute cleanliness
    was never the right claim. The DIFFERENTIAL is: repack_layout must add nothing. That
    is what this function is responsible for, and unlike the original it actually
    executes.
    """
    from synthetic import synthetic_process_draft

    draft = synthetic_process_draft()
    before = FlowDraft.from_wire(draft).problems()
    after = FlowDraft.from_wire(
        FlowDraft.from_wire(draft).repack_layout().to_wire()
    ).problems()

    introduced = [p for p in after.problems if p not in before.problems]
    assert not introduced, f"repack_layout introduced new problems: {introduced}"
    # and it must not silently mask one either — the count is stable in both directions
    assert len(after.problems) == len(before.problems), (
        before.problems,
        after.problems,
    )


# =====================================================================================
# section_layout() (moved from test_section_layout.py)
# =====================================================================================


Draft = dict[str, Any]


@pytest.fixture(scope="module")
def draft() -> Draft:
    return synthetic_process_draft()


def _nodes(d: Draft, kind: str) -> dict[str, Any]:
    return {k: v for k, v in d.items() if isinstance(v, dict) and v.get("Kind") == kind}


def _col_of_field(d: Draft, field_name: str) -> str:
    return next(
        v["Column"] for v in _nodes(d, "Field").values() if v.get("Name") == field_name
    )


def _section_id(d: Draft, name: str) -> str:
    return next(
        k
        for k, v in _nodes(d, "Column").items()
        if v.get("Type") == "Section" and v.get("Name") == name
    )


def _section_field_cols(d: Draft, name: str) -> set[str]:
    """Field-type columns directly inside a named Section.

    The layout's own expectation.
    """
    sid = _section_id(d, name)
    return {
        cid
        for rid in (d[sid].get("Column::Row") or [])
        for cid in (d.get(rid) or {}).get("Row::Column") or []
        if d[cid].get("Type") == "Field"
    }


def test_layout_names_every_section(draft: Draft) -> None:
    layout = FlowDraft.from_wire(draft).section_layout()
    assert set(layout.section_id_of_name) == set(OWNERS) | {"Other"}
    for name, sid in layout.section_id_of_name.items():
        assert draft[sid].get("Type") == "Section", name
        assert draft[sid].get("Name") == name


def test_layout_members_are_section_field_columns(draft: Draft) -> None:
    layout = FlowDraft.from_wire(draft).section_layout()
    for name in OWNERS:
        sid = layout.section_id_of_name[name]
        assert set(layout.members[sid]) == _section_field_cols(draft, name), name
    # an unowned trailing section is a member like any other
    other = layout.section_id_of_name["Other"]
    assert set(layout.members[other]) == _section_field_cols(draft, "Other")


def test_owner_section_maps_column_to_its_section(draft: Draft) -> None:
    layout = FlowDraft.from_wire(draft).section_layout()
    assert layout.owner_section(_col_of_field(draft, "Ticket No")) == "Intake"
    assert layout.owner_section(_col_of_field(draft, "Bench Notes")) == "Path B"
    assert layout.owner_section(_col_of_field(draft, "Extra Note")) == "Other"


def test_no_permission_columns_include_hidden_and_sequence(draft: Draft) -> None:
    d = (
        FlowDraft.from_wire(copy.deepcopy(draft))
        .add_sequence_number("Running No", "Intake", "TCK-", "0001", "Ticket arrives")
        .to_wire()
    )
    layout = FlowDraft.from_wire(d).section_layout()
    seq_col = _col_of_field(d, "Running No")
    assert seq_col in layout.no_permission_columns

    d2 = copy.deepcopy(draft)
    hidden_col = _col_of_field(d2, "Extra Note")
    d2[hidden_col]["IsHidden"] = True
    layout2 = FlowDraft.from_wire(d2).section_layout()
    assert hidden_col in layout2.no_permission_columns


def test_table_exclusions_detected(draft: Draft) -> None:
    d = (
        FlowDraft.from_wire(draft)
        .add_table("Line Items", [("SKU", FieldType.TEXT), ("Qty", FieldType.NUMBER)])
        .to_wire()
    )
    layout = FlowDraft.from_wire(d).section_layout()
    host = next(k for k, v in _nodes(d, "Column").items() if v.get("Type") == "Model")
    children = {_col_of_field(d, "SKU"), _col_of_field(d, "Qty")}
    assert host in layout.table_host_columns
    assert children <= layout.table_child_columns
    # a table host column takes no Permission, so it is excluded from the section-member
    # machinery's write targets too (the coverage rule's own subtraction)
    assert host not in layout.no_permission_columns


def test_section_name_beats_same_named_table_host(draft: Draft) -> None:
    # The golden "banner above a same-named table" pattern (CLAUDE.md > Tables): a
    # Section and a table host Model may share a Name. Name resolution must bind the
    # SECTION node, never the empty host column — the e23f8f2 fix's rule, now pinned on
    # the fact base itself.
    collide = "Intake"
    d = (
        FlowDraft.from_wire(draft)
        .add_table(collide, [("SKU", FieldType.TEXT), ("Qty", FieldType.NUMBER)])
        .to_wire()
    )
    layout = FlowDraft.from_wire(d).section_layout()
    assert layout.section_id_of_name[collide] == _section_id(d, collide)
    # the colliding host is still a table host (its own signal is untouched)
    host = next(
        k
        for k, v in _nodes(d, "Column").items()
        if v.get("Type") == "Model" and v.get("Name") == collide
    )
    assert host in layout.table_host_columns


def test_model_name_kept_as_fallback_when_no_section_owns_it(draft: Draft) -> None:
    d = (
        FlowDraft.from_wire(draft)
        .add_table("Line Items", [("SKU", FieldType.TEXT), ("Qty", FieldType.NUMBER)])
        .to_wire()
    )
    layout = FlowDraft.from_wire(d).section_layout()
    host = next(k for k, v in _nodes(d, "Column").items() if v.get("Type") == "Model")
    assert layout.section_id_of_name["Line Items"] == host
    # a Model unit governs exactly its own host column (CLAUDE.md > Tables: the whole
    # table is one unit — and the host takes no Permission, so this row emits nothing at
    # write time)
    assert layout.members[host] == (host,)
    assert layout.owner_section(host) == "Line Items"


def test_owner_section_covers_model_host_nested_inside_a_section(draft: Draft) -> None:
    # The doctor's old secof walk credited a Model host NESTED in a Section's row to
    # that section (the "table nested inside a section" case). owner_section must mirror
    # that: a column directly in a Section's rows belongs to the Section, whatever its
    # Type.
    d = copy.deepcopy(draft)
    host = (
        next(k for k, v in _nodes(d, "Column").items() if v.get("Type") == "Model")
        if any(v.get("Type") == "Model" for v in _nodes(d, "Column").values())
        else None
    )
    if host is None:  # plant a Model column inside the Intake section's first row
        rows = d[_section_id(d, "Intake")].get("Column::Row") or []
        row_id = rows[0]
        host = "Column_FakeTableHost"
        d[host] = {
            "Id": host,
            "Kind": "Column",
            "Type": "Model",
            "Name": "Fake Table",
            "Row": row_id,
            "Column::Model": ["Model_FakeTable"],
        }
        d[row_id]["Row::Column"].append(host)
        d["Model_FakeTable"] = {
            "Id": "Model_FakeTable",
            "Kind": "Model",
            "Name": "Fake Table",
            "Model": d["Root"],
            "Column": host,
        }
    layout = FlowDraft.from_wire(d).section_layout()
    assert layout.owner_section(host) == "Intake"


# =====================================================================================
# verify.doctor -> FlowDraft.problems() (moved from test_verify.py)
# =====================================================================================


Draft = dict[str, Any]


def _nodes_of(draft: Draft, **criteria: Any) -> list[dict[str, Any]]:
    """Every node dict matching all the given key=value criteria — a small lookup
    helper so each seeded-defect test can find the node it needs to mutate without
    repeating a manual scan."""
    return [
        v
        for v in draft.values()
        if isinstance(v, dict) and all(v.get(k) == val for k, val in criteria.items())
    ]


def _section_column_ids(draft: Draft, section_name: str) -> set[str]:
    (sec,) = _nodes_of(draft, Type="Section", Name=section_name)
    return {
        c
        for rid in sec.get("Column::Row") or []
        for c in (draft.get(rid) or {}).get("Row::Column") or []
    }


@pytest.fixture(scope="module")
def clean_draft() -> Draft:
    """A fully-formed process draft that genuinely passes all 5 doctor rules: fields,
    sections, a 3-way parallel workflow, a COMPLETE step-permission matrix —
    including the trailing section `synthetic.py` deliberately leaves unowned, given
    a real owner HERE via the engine's own `progressive_matrix` (not by weakening the
    never-editable rule) — plus one backward loop and one field event layered on top
    by `with_goto_and_event`.
    """
    draft = synthetic_process_draft()
    owners = {**OWNERS, "Other": ["Wrap-up report"]}
    matrix = progressive_matrix(FlowDraft.from_wire(draft), owners)
    permissioned = FlowDraft.from_wire(draft).set_step_permissions(matrix).to_wire()
    return with_goto_and_event(permissioned)


# ---- the clean baseline ------------------------------------------------------


def test_clean_draft_has_no_problems(clean_draft: Draft) -> None:
    report = FlowDraft.from_wire(clean_draft).problems()
    assert isinstance(report, DoctorReport)
    assert report.ok() is True
    assert report.problems == ()
    # deterministic given how the fixture itself is built, independent of synthetic.py's
    # field count: exactly one injected event, one injected goto, zero branch conditions
    # anywhere
    assert report.checked["events"] == 1
    assert report.checked["gotos"] == 1
    assert report.checked["branch_literals"] == 0
    assert report.unvalidated == ()
    assert (
        report.unvalidatable_scripts == 1
    )  # that one event's script can never be FULLY proven
    # weak invariants: just confirm the other rules examined something real
    assert report.checked["sections"] > 0
    assert report.checked["required_fields"] > 0
    assert report.checked["dangling_refs"] > 0
    assert report.checked["permission_pairs"] > 0


def test_missing_root_key_fails_loud() -> None:
    with pytest.raises(ValueError, match="Root"):
        FlowDraft.from_wire({"not_a_flow": True}).problems()


# ---- 1. event scripts referencing a missing node -----------------------------


def test_event_script_missing_field_ref_flagged(clean_draft: Draft) -> None:
    d = copy.deepcopy(clean_draft)
    (event,) = _nodes_of(d, Kind="Event")
    event["Script"] = event["Script"].replace(
        "Field_SampleGate01", "Field_DoesNotExist99"
    )

    report = FlowDraft.from_wire(d).problems()
    assert any("Field_DoesNotExist99" in p for p in report.problems)


def test_event_script_missing_non_field_prefixed_ref_also_flagged(
    clean_draft: Draft,
) -> None:
    """The extraction must span every platform id prefix, not just Field_ — a script
    can just as easily reference a missing Column_/Activity_/... id (hardcode item
    3 in the port)."""
    d = copy.deepcopy(clean_draft)
    (event,) = _nodes_of(d, Kind="Event")
    event["Script"] = event["Script"].replace(
        "Field_SampleGate01", "Column_DoesNotExist99"
    )

    report = FlowDraft.from_wire(d).problems()
    assert any("Column_DoesNotExist99" in p for p in report.problems)


def test_unvalidatable_scripts_zero_when_no_scripts(clean_draft: Draft) -> None:
    """An event with an empty script has nothing to prove or disprove — it must not
    inflate the uncertainty count."""
    d = copy.deepcopy(clean_draft)
    (event,) = _nodes_of(d, Kind="Event")
    event["Script"] = ""

    report = FlowDraft.from_wire(d).problems()
    assert report.unvalidatable_scripts == 0


# ---- 2. branch literal vs list options ---------------------------------------


def test_branch_literal_outside_options_flagged_else_unvalidated(
    clean_draft: Draft,
) -> None:
    d = copy.deepcopy(clean_draft)
    root = d["Root"]
    (branch_pd,) = _nodes_of(d, Kind="ProcessDef", Name="Path A")
    branch_pd_id = branch_pd["Id"]

    # a fresh Select field + branch condition, injected by raw dict surgery (no such
    # branch condition exists in the base synthetic draft to "break" — this test builds
    # one from scratch and shows both the flagged and the honestly-unvalidated outcome)
    d["Field_SvcSample01"] = {
        "Id": "Field_SvcSample01",
        "Kind": "Field",
        "Type": "Select",
        "Name": "Sample Route",
        "Model": root,
        "ReferredList": "List_Sample01",
    }
    d[root].setdefault("Model::Field", []).append("Field_SvcSample01")
    d["Node_BLhs01"] = {
        "Id": "Node_BLhs01",
        "Type": "Field",
        "Field": "Field_SvcSample01",
        "DataType": "String",
        "Node": "Node_BRoot01",
    }
    d["Node_BRhs01"] = {
        "Id": "Node_BRhs01",
        "Type": "Static",
        "Value": "Bogus Option",
        "DataType": "String",
        "Node": "Node_BRoot01",
    }
    d["Node_BRoot01"] = {
        "Id": "Node_BRoot01",
        "Type": "Function",
        "Value": "=",
        "Syntax": "Infix",
        "DataType": "Boolean",
        "Category": "String",
        "Node::Node": ["Node_BLhs01", "Node_BRhs01"],
    }
    d["Expression_SampleBranch01"] = {
        "Id": "Expression_SampleBranch01",
        "Kind": "Expression",
        "ProcessDef": branch_pd_id,
        "ExpressionStr": "sample",
        "Expression::Node": ["Node_BRoot01"],
    }

    flagged = FlowDraft.from_wire(d).problems(
        list_options={"List_Sample01": ["Option A", "Option B"]}
    )
    assert any("Bogus Option" in p for p in flagged.problems)
    assert flagged.unvalidated == ()

    unknown = FlowDraft.from_wire(d).problems(list_options=None)
    assert unknown.problems == ()
    assert any("Bogus Option" in u for u in unknown.unvalidated)


# ---- 2b. GotoTask loop conditions ---------------------------------------------


def test_goto_without_condition_loops_forever(clean_draft: Draft) -> None:
    d = copy.deepcopy(clean_draft)
    (goto,) = _nodes_of(d, NodeType="GotoTask")
    del goto["Activity::Expression"]

    report = FlowDraft.from_wire(d).problems()
    assert any("loops forever" in p for p in report.problems)


def test_goto_gate_on_optional_select_flagged(clean_draft: Draft) -> None:
    d = copy.deepcopy(clean_draft)
    d["Field_SampleGate01"]["Type"] = "Select"  # Required is already False

    report = FlowDraft.from_wire(d).problems()
    assert any("optional Select" in p for p in report.problems)


def test_usertask_without_assignee_flagged(clean_draft: Draft) -> None:
    """A UserTask with no assignee Resource 500s on submit (CLAUDE.md Members first).
    The clean draft has assignees on every step; strip one and the doctor must
    catch it."""
    d = copy.deepcopy(clean_draft)
    tasks = _nodes_of(d, NodeType="UserTask")
    assert tasks, "fixture must have at least one UserTask"
    victim = tasks[0]
    del victim["Activity::Resource"]

    report = FlowDraft.from_wire(d).problems()
    assert any(
        "no AppRole assignee" in p and victim["Name"] in p for p in report.problems
    )


def test_usertask_with_user_typed_assignee_flagged(clean_draft: Draft) -> None:
    """A Resource with ValueType:"User" publishes but is IGNORED at runtime
    (CLAUDE.md Members first) — it reads as assigned yet still 500s on submit, so
    the doctor must still flag it."""
    d = copy.deepcopy(clean_draft)
    victim = _nodes_of(d, NodeType="UserTask")[0]
    (res_id,) = victim["Activity::Resource"]
    d[res_id]["ValueType"] = "User"  # persists + publishes, but runtime ignores it

    report = FlowDraft.from_wire(d).problems()
    assert any(
        "no AppRole assignee" in p and victim["Name"] in p for p in report.problems
    )


def test_suspended_usertask_without_assignee_not_flagged(clean_draft: Draft) -> None:
    """A suspended step is walked past at runtime, so its missing assignee never
    bites — the doctor must NOT flag it (mirrors CLAUDE.md's IsSuspended
    semantics)."""
    d = copy.deepcopy(clean_draft)
    victim = _nodes_of(d, NodeType="UserTask")[0]
    del victim["Activity::Resource"]
    victim["IsSuspended"] = True

    report = FlowDraft.from_wire(d).problems()
    assert not any("has no assignee" in p for p in report.problems)


def test_bare_user_field_flagged(clean_draft: Draft) -> None:
    """A Field{Type:"User"} with no QueryDefinition sibling blocks publish (#59). The
    doctor must catch it before the publish 04211s."""
    d = copy.deepcopy(clean_draft)
    (field_id,) = [
        k for k, v in d.items() if isinstance(v, dict) and v.get("Kind") == "Field"
    ][:1]
    d[field_id]["Type"] = "User"  # make an existing field a bare User field
    d[field_id].pop("Field::QueryDefinition", None)

    report = FlowDraft.from_wire(d).problems()
    assert any("no QueryDefinition sibling" in p for p in report.problems)


# ---- 5. sparse matrix must ignore a table host column ------------------------


def test_table_host_column_is_not_counted_sparse(clean_draft: Draft) -> None:
    # A table HOST column (Type:"Model") takes NO Permission — Kissflow shows/hides the
    # whole table, not its host cell (CLAUDE.md > Tables). set_step_permissions skips
    # hosts by design, so the sparse-matrix rule must NOT demand a Permission per step
    # for the host, or a table-bearing flow with an otherwise-complete matrix reads as
    # "sparse" (host x every step).

    from app.domain.value_objects.field_type import FieldType

    d = (
        FlowDraft.from_wire(synthetic_process_draft())
        .add_table(
            "Line Items",
            [("SKU", FieldType.TEXT), ("Qty", FieldType.NUMBER)],
        )
        .to_wire()
    )
    owners = {**OWNERS, "Other": ["Wrap-up report"]}
    d = (
        FlowDraft.from_wire(d)
        .set_step_permissions(progressive_matrix(FlowDraft.from_wire(d), owners))
        .to_wire()
    )
    report = FlowDraft.from_wire(d).problems()
    assert not any("sparse" in p for p in report.problems), report.problems


# ---- 3. dangling :: references -------------------------------------------------


def test_dangling_list_ref_flagged(clean_draft: Draft) -> None:
    d = copy.deepcopy(clean_draft)
    model = d[d["Root"]]
    model["Model::Field"].append("Field_GhostSample99")

    report = FlowDraft.from_wire(d).problems()
    assert any("Field_GhostSample99" in p for p in report.problems)


# ---- 4. never-editable sections + unsubmittable Required fields ---------------


def test_section_stripped_of_editable_permissions_flagged(clean_draft: Draft) -> None:
    d = copy.deepcopy(clean_draft)
    members = _section_column_ids(d, "Intake")
    flipped = 0
    for v in d.values():
        if (
            isinstance(v, dict)
            and v.get("Kind") == "Permission"
            and v.get("Column") in members
            and v.get("Permission") == "Editable"
        ):
            v["Permission"] = "ReadOnly"
            flipped += 1
    assert flipped > 0, (
        "fixture drift: Intake should have had Editable permissions to strip"
    )

    report = FlowDraft.from_wire(d).problems()
    assert any("section 'Intake' is never editable" in p for p in report.problems)
    # Intake holds two Required fields (Unit Serial, Problem) -> both become
    # unsubmittable
    assert any("Unit Serial" in p and "never editable" in p for p in report.problems)
    assert any("Problem" in p and "never editable" in p for p in report.problems)


# ---- 5. sparse permission matrix -------------------------------------------


def test_sequence_column_not_counted_as_permission_gap(clean_draft: Draft) -> None:
    # CLAUDE.md > Visibility (#9): a SequenceNumber column takes no Permissions, so its
    # absence from the matrix is not a gap — even when the column is not IsHidden.
    d = (
        FlowDraft.from_wire(clean_draft)
        .add_sequence_number("Running No", "Intake", "TCK-", "0001", "Ticket arrives")
        .to_wire()
    )
    (seq_field,) = _nodes_of(d, Kind="Field", Type="SequenceNumber")
    del d[seq_field["Column"]]["IsHidden"]
    report = FlowDraft.from_wire(d).problems()
    assert not any("sparse" in p for p in report.problems)


def test_sparse_permission_matrix_counted(clean_draft: Draft) -> None:
    d = copy.deepcopy(clean_draft)
    doomed = [
        k for k, v in d.items() if isinstance(v, dict) and v.get("Kind") == "Permission"
    ][:5]
    for pid in doomed:
        p = d.pop(pid)
        col = d.get(p["Column"]) or {}
        if "Column::Permission" in col:
            col["Column::Permission"] = [
                x for x in col["Column::Permission"] if x != pid
            ]
        act = d.get(p["Activity"]) or {}
        if "Activity::Permission" in act:
            act["Activity::Permission"] = [
                x for x in act["Activity::Permission"] if x != pid
            ]

    report = FlowDraft.from_wire(d).problems()
    assert any(
        f"sparse: {len(doomed)} (unit, step) pairs unset" in p for p in report.problems
    )


# ---- 6. role-scoped visibility claims (#6, ADR-0004) -----------------------------


def test_role_scoped_visibility_claim_fails_the_doctor(clean_draft: Draft) -> None:
    """A spec claiming role-scoped visibility must FAIL the doctor with a stated
    reason naming the coverage row — API-impossible, refused, never best-effort
    (ADR-0004)."""
    claim = "section 'Repair Cost' at stage 'Review' visible only to role 'Finance'"
    report = FlowDraft.from_wire(clean_draft).problems(visibility_role_claims=(claim,))
    assert report.ok() is False
    assert any(
        claim in p
        and "role-scoped visibility is API-impossible" in p
        and "step-scoped" in p
        and "role-scoped-visibility" in p
        for p in report.problems
    )
    assert report.checked["role_scoped_visibility_claims"] == 1


def test_no_role_claims_leaves_the_doctor_clean(clean_draft: Draft) -> None:
    report = FlowDraft.from_wire(clean_draft).problems()
    assert report.ok() is True
    assert report.checked["role_scoped_visibility_claims"] == 0


def test_doctor_flags_dangling_sequence_step_stamp() -> None:
    """#18: a Step Property whose Value names a nonexistent Activity is THE
    deterministic publish-500 condition; doctor was blind to it (scalar ref, not a
    list ref)."""

    draft = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "P", "FlowType": "Process"},
        "Property_Step1": {
            "Id": "Property_Step1",
            "Kind": "Property",
            "Name": "Step",
            "ValueType": "Value",
            "Value": "Activity_gone",
        },
    }
    rep = FlowDraft.from_wire(draft).problems()
    assert any("Activity_gone" in p and "500" in p for p in rep.problems)
    assert rep.checked["step_stamps"] == 1


# ---- 8. column geometry: a field column off the 6-unit row grid ----------------


def test_column_geometry_is_counted_on_a_clean_draft(clean_draft: Draft) -> None:
    """The rule counts every field column it examined — a rule that fires nothing
    must still prove it LOOKED, or a silently-skipped walk reads exactly like a
    clean bill of health."""
    report = FlowDraft.from_wire(clean_draft).problems()
    assert report.checked["column_geometry"] > 0
    assert not any("row grid" in p or "overlap" in p for p in report.problems), (
        report.problems
    )


@pytest.mark.parametrize(
    ("start", "end", "why"),
    [
        (0, 8, "off the end of the 6-unit row"),
        (-1, 2, "a negative Start"),
        (8, 6, "End < Start, the shape the old leftover packer emitted"),
    ],
)
def test_doctor_flags_a_column_off_the_row_grid(
    clean_draft: Draft, start: int, end: int, why: str
) -> None:
    """The safety net for a draft THIS ENGINE DID NOT BUILD — a human- or
    copilot-built form whose columns overflow one Row breaks rendering for the
    WHOLE flow (CLAUDE.md > Node-graph invariants), and every other rule reads it
    as perfectly healthy."""
    d = copy.deepcopy(clean_draft)
    cid = sorted(_section_column_ids(d, "Intake"))[0]
    d[cid].update({"Start": start, "End": end})

    report = FlowDraft.from_wire(d).problems()
    assert any(
        f"Start={start}, End={end}" in p and "row grid" in p for p in report.problems
    ), (
        why,
        report.problems,
    )


def test_doctor_flags_two_columns_overlapping_in_one_row(clean_draft: Draft) -> None:
    """Two columns cannot share a unit of the 6-unit grid.

    Same render-breaking class, per row.
    """
    d = copy.deepcopy(clean_draft)
    row = next(
        v
        for v in d.values()
        if isinstance(v, dict)
        and v.get("Kind") == "Row"
        and len(v.get("Row::Column") or []) >= 2
        and all((d.get(c) or {}).get("Type") == "Field" for c in v["Row::Column"])
    )
    first, second = row["Row::Column"][:2]
    d[first].update({"Start": 0, "End": 4})
    d[second].update({"Start": 2, "End": 6})

    report = FlowDraft.from_wire(d).problems()
    assert any("overlap" in p and row["Id"] in p for p in report.problems), (
        report.problems
    )


def test_doctor_flags_a_column_with_no_numeric_span(clean_draft: Draft) -> None:
    """A missing Start/End is not a zero.

    The builder cannot place the column at all.
    """
    d = copy.deepcopy(clean_draft)
    cid = sorted(_section_column_ids(d, "Intake"))[0]
    d[cid].pop("Start", None)

    report = FlowDraft.from_wire(d).problems()
    assert any("no numeric grid span" in p for p in report.problems), report.problems


def test_table_child_columns_are_not_flagged_off_the_grid() -> None:
    """A table's child columns are Start=0/End=0 BY DESIGN (CLAUDE.md > Tables: "the
    6-unit row grid does not apply inside a table"). A geometry rule that
    re-derives the grid instead of reading `section_layout`'s fact base
    false-flags every table-bearing flow — including its host row, where every
    child sits in ONE schema Row at identical (0, 0) coordinates."""

    from app.domain.value_objects.field_type import FieldType

    d = (
        FlowDraft.from_wire(synthetic_process_draft())
        .add_table(
            "Line Items",
            [
                ("SKU", FieldType.TEXT),
                ("Qty", FieldType.NUMBER),
                ("Note", FieldType.TEXT),
            ],
        )
        .to_wire()
    )
    owners = {**OWNERS, "Other": ["Wrap-up report"]}
    d = (
        FlowDraft.from_wire(d)
        .set_step_permissions(progressive_matrix(FlowDraft.from_wire(d), owners))
        .to_wire()
    )

    report = FlowDraft.from_wire(d).problems()
    assert not any(
        "row grid" in p or "overlap" in p or "numeric grid span" in p
        for p in report.problems
    ), report.problems
    # ... and the rule genuinely ran: the root form's own columns were still walked
    assert report.checked["column_geometry"] > 0


def test_hidden_sequence_number_column_is_still_checked(clean_draft: Draft) -> None:
    """A hidden column takes no Permission (#9) but is still LAID OUT — it keeps a
    real span, so the geometry rule must not inherit the permission-matrix
    exclusions wholesale."""
    d = (
        FlowDraft.from_wire(copy.deepcopy(clean_draft))
        .add_sequence_number(
            "Case No",
            "Intake",
            prefix="CS-",
            padding="0001",
            step_activity_name="Start",
        )
        .to_wire()
    )
    before = FlowDraft.from_wire(d).problems().checked["column_geometry"]

    (col,) = [
        v
        for v in d.values()
        if isinstance(v, dict)
        and v.get("Kind") == "Column"
        and v.get("IsHidden")
        and v.get("Type") == "Field"
    ]
    col.update({"Start": 0, "End": 9})
    report = FlowDraft.from_wire(d).problems()
    assert before > 0
    assert any("Start=0, End=9" in p for p in report.problems), report.problems


# ---- 7b. a list-backed field bound to NO list --------------------------------


def _bare_field_draft(**field_keys: Any) -> Draft:
    """The smallest draft doctor will run on, carrying ONE field built from
    `field_keys`. Rule 7b needs no layout, no workflow and no permissions, so a
    two-node graph isolates it completely."""
    return {
        "Root": "M1",
        "M1": {
            "Id": "M1",
            "Kind": "Model",
            "Name": "P",
            "FlowType": "Process",
            "Model::Field": ["Field_One01"],
        },
        "Field_One01": {
            "Id": "Field_One01",
            "Kind": "Field",
            "Model": "M1",
            **field_keys,
        },
    }


def test_doctor_flags_a_select_field_with_no_referred_list() -> None:
    """The publish-500 the whole 2026-08-19 diagnosis landed on: a Select is a
    dropdown whose OPTIONS live in a separate list flow, so a Select with no
    `ReferredList` is bound to nothing. PUT 200s, publish dies MetadataError with
    zero diagnostic content — and every other rule reads the flow as perfectly
    healthy, which is the doctrine-#2 hole this closes: the field landed in NO
    bucket at all."""
    rep = FlowDraft.from_wire(
        _bare_field_draft(Type="Select", Name="Urgency")
    ).problems()
    assert any("Urgency" in p and "no ReferredList" in p for p in rep.problems), (
        rep.problems
    )
    assert rep.checked["list_backed_fields"] == 1


def test_doctor_does_not_require_the_referred_list_target_to_be_in_the_draft() -> None:
    """THE false-positive guard. A list is a SEPARATE FLOW, never a node in this
    graph, so a rule of the form `ReferredList not in draft` would fire on every
    correctly wired Select in existence — including every one this engine writes."""
    rep = FlowDraft.from_wire(
        _bare_field_draft(
            Type="Select", Name="Urgency", ReferredList="List_NotInThisDraft"
        )
    ).problems()
    assert rep.problems == ()
    assert rep.checked["list_backed_fields"] == 1


def _table_child_select_draft(**field_keys: Any) -> Draft:
    """A form whose ONE list-backed field is a table CHILD — `add_table`'s own shape
    (host Column{Type:"Model"} -> nested Model -> schema Row -> child
    Column/Field), built by the real function so the fixture cannot drift from
    what the engine writes."""

    bare = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Process"},
    }
    d = (
        FlowDraft.from_wire(bare)
        .add_table("Items", [("Grade", "Select", {"ReferredList": "List_G1"})])
        .to_wire()
    )
    (grade,) = [
        v
        for v in d.values()
        if isinstance(v, dict) and v.get("Kind") == "Field" and v.get("Name") == "Grade"
    ]
    grade.pop("ReferredList")  # a hand-built / template-cloned bare Select
    grade.update(field_keys)
    return d


def test_doctor_remedy_for_a_table_child_names_a_path_that_actually_works() -> None:
    """G2: "a refusal a caller cannot act on is just a dead end" (CLAUDE.md > Members
    first), applied to a remedy. Rule 7b told every caller to "re-apply the field
    with referred_list" — for a table CHILD that returns isError:true with
    `changed_ignored` ("apply_changes only creates"), and its fallback
    (forge_delete_fields + forge_apply_fields) would delete the table column and
    re-add the name as a ROOT form field: a different form. The remedy must name
    the child's own table and the rebuild that really repairs it."""
    rep = FlowDraft.from_wire(_table_child_select_draft()).problems()
    (problem,) = [p for p in rep.problems if "no ReferredList" in p]

    assert "'Grade'" in problem and "'Items'" in problem, problem
    # the path that actually works: mint the list, then REBUILD the table
    assert "forge_delete_fields" in problem and "forge_add_table" in problem, problem
    assert "ReferredList" in problem.split("forge_add_table")[1], problem
    # and the dead end is not advised: the root-field remedy must not appear on a table
    # child
    assert "re-apply the field with referred_list" not in problem, problem


def test_doctor_remedy_for_a_root_field_is_unchanged() -> None:
    """The root-field remedy WAS correct and stays verbatim — the table-child branch
    is an addition, not a rewrite of a working message."""
    rep = FlowDraft.from_wire(
        _bare_field_draft(Type="Select", Name="Urgency")
    ).problems()
    (problem,) = [p for p in rep.problems if "no ReferredList" in p]
    assert "re-apply the field with referred_list" in problem, problem
    assert "forge_add_table" not in problem, problem


@pytest.mark.parametrize(
    ("keys", "flagged"),
    [
        ({"Type": "Select", "Name": "Plain"}, True),
        (
            {"Type": "Select", "Widget": "Radio", "Name": "Radio"},
            True,
        ),  # field_radio.json
        ({"Type": "Multiselect", "Name": "Many"}, True),  # field_multiselect.json
        ({"Type": "Checkbox", "Name": "Ticks"}, True),  # field_checkbox.json
        ({"Type": "Checklist", "Name": "Items"}, True),  # field_checklist.json
        ({"Type": "Text", "Name": "Notes"}, False),  # a branch may test Text
        ({"Type": "Boolean", "Name": "Done"}, False),
        ({"Type": "Select", "Name": "Wired", "ReferredList": "List_X1"}, False),
    ],
)
def test_list_backed_family_is_exactly_the_captured_one(
    keys: dict[str, Any], flagged: bool
) -> None:
    """The family is the set of `Type` strings EVERY capture in shapes/ carries
    `ReferredList` on — never inferred from a field's name, and never widened to
    `Text` (CLAUDE.md documents Text as a legitimate deciding-field type for a
    branch condition)."""
    rep = FlowDraft.from_wire(_bare_field_draft(**keys)).problems()
    assert any("no ReferredList" in p for p in rep.problems) is flagged, rep.problems


def test_clean_draft_has_every_select_wired_to_a_list(clean_draft: Draft) -> None:
    """The engine's own dogfood build must not be the thing rule 7b catches: the
    synthetic draft carries three Selects, and every one of them names a list."""
    rep = FlowDraft.from_wire(clean_draft).problems()
    assert rep.checked["list_backed_fields"] >= 3
    assert not any("no ReferredList" in p for p in rep.problems), rep.problems


# ---- 3c. dangling SCALAR references ------------------------------------------


def test_doctor_flags_a_dangling_scalar_reference() -> None:
    """Rule 3 sweeps `::` LIST refs only; rule 3b guards exactly one scalar
    (`Property{Step}`). Every other scalar owner back-ref was unguarded — the same
    PUT-200/publish-500 class."""
    d = _bare_field_draft(Type="Text", Name="Notes", Column="Column_Gone99")
    rep = FlowDraft.from_wire(d).problems()
    assert any(
        "Column_Gone99" in p and "scalar reference" in p for p in rep.problems
    ), rep.problems
    assert rep.checked["scalar_refs"] > 0


def test_scalar_rule_never_resolves_an_id_shaped_value_that_is_not_a_reference() -> (
    None
):
    """Driven by an explicit (Kind -> keys) ALLOWLIST, never an "looks like an id"
    heuristic. In the real broken draft `Activity.NodeType ==
    "SendBackToInitiator"` is a string that literally equals a node id, and
    `Field.ReferredList` / `Resource.Value` / `Model._application_id` are all
    id-shaped and all resolve to nothing in the draft BY DESIGN."""
    d: Draft = {
        "Root": "M1",
        "M1": {
            "Id": "M1",
            "Kind": "Model",
            "Name": "P",
            "FlowType": "Process",
            "_application_id": "App_Elsewhere01",
        },
        "Field_One01": {
            "Id": "Field_One01",
            "Kind": "Field",
            "Type": "Select",
            "Name": "Pick",
            "Model": "M1",
            "ReferredList": "List_Elsewhere01",
        },
        "Activity_One01": {
            "Id": "Activity_One01",
            "Kind": "Activity",
            "NodeType": "SendBackToInitiator",
            "Name": "Send back",
        },
        "Resource_One01": {
            "Id": "Resource_One01",
            "Kind": "Resource",
            "ValueType": "AppRole",
            "Value": "RoElsewhere01",
        },
    }
    rep = FlowDraft.from_wire(d).problems()
    assert not any("scalar reference" in p for p in rep.problems), rep.problems


def test_scalar_rule_treats_underscore_refs_as_system_fields_not_node_ids() -> None:
    """The platform writes system-field refs with a leading underscore: `Node.Field =
    "_Field_x"` while the node is keyed "Field_x", and `"_created_by"` names a
    system field with NO node at all (both real shapes in
    shapes/process_template_full.json). Neither is a dangling reference — they
    land in their own checked bucket, never in problems."""
    d: Draft = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "P", "FlowType": "Process"},
        "Field_x01": {
            "Id": "Field_x01",
            "Kind": "Field",
            "Type": "Text",
            "Name": "X",
            "Model": "M1",
        },
        "Node_One01": {"Id": "Node_One01", "Kind": "Node", "Field": "_Field_x01"},
        "Node_Two01": {"Id": "Node_Two01", "Kind": "Node", "Field": "_created_by"},
    }
    rep = FlowDraft.from_wire(d).problems()
    assert not any("scalar reference" in p for p in rep.problems), rep.problems
    assert rep.checked["system_scalar_refs"] == 2


def test_transplanted_template_raises_no_scalar_reference_problem() -> None:
    """The regression that shipped: doctor read 11 fabricated 'missing _Field_...'
    problems off the very graph forge_create_template_app had just built and
    published clean."""

    base: Draft = {
        "Root": "M1",
        "_meta_version": "v1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "P", "FlowType": "Process"},
    }
    rep = FlowDraft.from_wire(
        FlowDraft.from_wire(base).transplant_template(app_role=("Ro123", "R")).to_wire()
    ).problems()
    assert not any("scalar reference" in p for p in rep.problems), rep.problems
    assert rep.checked["system_scalar_refs"] > 0


def test_scalar_rule_is_silent_on_the_shipped_template_shell() -> None:
    """The strongest available oracle: the identity shell is a de-identified capture
    of a REAL published production process template. A scalar rule that fires here
    fires on every process this engine builds with `from_template=True` — the
    default."""

    d = (
        FlowDraft.from_wire(
            {
                "Root": "M1",
                "M1": {"Id": "M1", "Kind": "Model", "Name": "P", "FlowType": "Process"},
            }
        )
        .clone_template_shell()
        .to_wire()
    )
    rep = FlowDraft.from_wire(d).problems()
    assert not any("scalar reference" in p for p in rep.problems), rep.problems
    assert rep.checked["scalar_refs"] > 0


# ---- 7c. a shipped TODO placeholder in a user-facing field NAME ---------------


def test_doctor_flags_a_todo_placeholder_shipped_as_a_field_label() -> None:
    d = _bare_field_draft(
        Type="Text",
        Name="Manager User (TODO: was a User field — see field_user_reference)",
    )
    rep = FlowDraft.from_wire(d).problems()
    assert any("TODO placeholder" in p for p in rep.problems), rep.problems
    assert rep.checked["placeholder_names"] == 1


def test_shipped_template_shell_carries_no_todo_placeholder_names() -> None:
    """The real fix for rule 7c is in the SHAPE, not the rule: a developer note must
    never ship as a user-facing label on every from_template=True process."""

    d = (
        FlowDraft.from_wire(
            {
                "Root": "M1",
                "M1": {"Id": "M1", "Kind": "Model", "Name": "P", "FlowType": "Process"},
            }
        )
        .clone_template_shell()
        .to_wire()
    )
    rep = FlowDraft.from_wire(d).problems()
    assert not any("TODO placeholder" in p for p in rep.problems), rep.problems
    assert rep.checked["placeholder_names"] > 0


# ---- 8b. one column claimed by two rows ---------------------------------------


def test_doctor_flags_one_column_claimed_by_two_rows(clean_draft: Draft) -> None:
    """D8(a): `apply_exact_layout` used to accept the same field named twice, leaving
    one Column in two Rows' `Row::Column` while its own `Row` back-ref names only
    one. The geometry rule groups BY that back-ref, so the duplicate appears once
    per group and reads perfectly clean."""
    d = copy.deepcopy(clean_draft)
    rows = [
        v
        for v in d.values()
        if isinstance(v, dict)
        and v.get("Kind") == "Row"
        and (v.get("Row::Column") or [])
    ]
    victim = rows[0]["Row::Column"][0]
    rows[1]["Row::Column"].append(victim)  # a second row now claims it too

    rep = FlowDraft.from_wire(d).problems()
    assert any(victim in p and "two rows claim" in p for p in rep.problems), (
        rep.problems
    )
    assert rep.checked["row_column_claims"] > 0


def test_four_column_row_from_the_real_prod_template_is_not_flagged() -> None:
    """Counter-capture, stated deliberately:
    `shapes/process_template_identity_shell.json` — a de-identified capture of a
    REAL published production template — carries a Row with FOUR field columns at
    (0,2) (2,4) (4,5) (5,6). "At most 3 columns per row" is the consequence of
    FIELD_SPAN=2 — the auto-tiler's default packing — not a platform limit, so the
    doctor refuses to invent a count bound it has a live capture AGAINST (doctrine
    #10). The WRITE guard now agrees rather than contradicting it — see
    test_layout_guard_accepts_the_four_column_row_the_prod_capture_proves."""

    d = (
        FlowDraft.from_wire(
            {
                "Root": "M1",
                "M1": {"Id": "M1", "Kind": "Model", "Name": "P", "FlowType": "Process"},
            }
        )
        .clone_template_shell()
        .to_wire()
    )
    widest = max(
        (
            len(v.get("Row::Column") or [])
            for v in d.values()
            if isinstance(v, dict) and v.get("Kind") == "Row"
        ),
        default=0,
    )
    assert widest >= 4, (
        "fixture drift: the shipped shell no longer has its 4-column row"
    )
    rep = FlowDraft.from_wire(d).problems()
    assert not any(
        "columns per row" in p or "two rows claim" in p for p in rep.problems
    ), rep.problems


def test_doctor_reports_a_malformed_permission_instead_of_raising() -> None:
    """Doctrine 7: doctor REPORTS, it never raises. A Permission missing
    Column/Activity used to escape `forge_doctor` as a bare KeyError across the
    tool boundary — and doctor is the tool SKILL.md tells the builder to run after
    EVERY edit, on flows this engine did not build."""
    from tests.synthetic import synthetic_process_draft

    draft = synthetic_process_draft()
    draft["Permission_bad"] = {
        "Id": "Permission_bad",
        "Kind": "Permission",
        "Permission": "Editable",
    }  # no Column, no Activity

    report = FlowDraft.from_wire(draft).problems()  # must not raise

    assert report.checked["malformed_permissions"] == 1
    assert any(
        "Permission node(s) missing a Column/Activity" in p for p in report.problems
    )
    assert any("Permission_bad" in p for p in report.problems), (
        "must NAME the offending node"
    )


def test_a_clean_draft_reports_no_malformed_permissions() -> None:
    """The control: the guard must not invent a problem on a well-formed graph."""
    from tests.synthetic import synthetic_process_draft

    report = FlowDraft.from_wire(synthetic_process_draft()).problems()
    assert report.checked["malformed_permissions"] == 0
    assert not [
        p for p in report.problems if "malformed" in p or "missing a Column" in p
    ]


def test_doctor_reports_many_malformed_permissions_with_ellipsis(
    clean_draft: Draft,
) -> None:
    d = copy.deepcopy(clean_draft)
    for i in range(8):
        d[f"Permission_bad_{i}"] = {
            "Id": f"Permission_bad_{i}",
            "Kind": "Permission",
            "Permission": "Editable",
        }
    rep = FlowDraft.from_wire(d).problems()
    assert rep.checked["malformed_permissions"] == 8
    assert any("..." in p and "Permission node(s) missing" in p for p in rep.problems)


# ---- additional branch coverage tests ----------------------------------------


def test_goto_jumping_to_missing_activity_flagged(clean_draft: Draft) -> None:
    d = copy.deepcopy(clean_draft)
    (goto,) = _nodes_of(d, NodeType="GotoTask")
    goto["Goto"] = "Activity_DoesNotExist99"
    rep = FlowDraft.from_wire(d).problems()
    assert any("jumps to missing activity" in p for p in rep.problems)


def test_goto_jumping_out_of_own_branch_flagged(clean_draft: Draft) -> None:
    d = copy.deepcopy(clean_draft)
    (goto,) = _nodes_of(d, NodeType="GotoTask")
    target = d[goto["Goto"]]
    target["ProcessDef"] = "ProcessDef_OtherBranch99"
    rep = FlowDraft.from_wire(d).problems()
    assert any("jumps out of its own branch" in p for p in rep.problems)


def test_goto_missing_back_ref_on_target_flagged(clean_draft: Draft) -> None:
    d = copy.deepcopy(clean_draft)
    (goto,) = _nodes_of(d, NodeType="GotoTask")
    target = d[goto["Goto"]]
    target["Goto::Activity"] = []
    rep = FlowDraft.from_wire(d).problems()
    assert any("missing the Goto::Activity back-ref" in p for p in rep.problems)


def test_goto_gate_field_missing_from_draft_flagged(clean_draft: Draft) -> None:
    d = copy.deepcopy(clean_draft)
    (goto,) = _nodes_of(d, NodeType="GotoTask")
    (xid,) = goto["Activity::Expression"]
    (root_nid,) = d[xid]["Expression::Node"]
    for child_nid in d[root_nid]["Node::Node"]:
        if d[child_nid].get("Type") == "Field":
            d[child_nid]["Field"] = "Field_DoesNotExist99"
    rep = FlowDraft.from_wire(d).problems()
    assert any(
        "tests missing field" in p and "Field_DoesNotExist99" in p for p in rep.problems
    )


def test_branch_literal_matching_valid_option_passes(clean_draft: Draft) -> None:
    d = copy.deepcopy(clean_draft)
    root = d["Root"]
    (branch_pd,) = _nodes_of(d, Kind="ProcessDef", Name="Path A")
    branch_pd_id = branch_pd["Id"]

    d["Field_SvcSample01"] = {
        "Id": "Field_SvcSample01",
        "Kind": "Field",
        "Model": root,
        "Type": "Select",
        "ReferredList": "List_Sample01",
        "Name": "Service",
    }
    d["Node_Root01"] = {
        "Id": "Node_Root01",
        "Kind": "Node",
        "Type": "Operator",
        "Node::Node": ["Node_Field01", "Node_Static01"],
    }
    d["Node_Field01"] = {
        "Id": "Node_Field01",
        "Kind": "Node",
        "Type": "Field",
        "Field": "Field_SvcSample01",
    }
    d["Node_Static01"] = {
        "Id": "Node_Static01",
        "Kind": "Node",
        "Type": "Static",
        "Value": "Option A",
    }
    d["Expression_Branch01"] = {
        "Id": "Expression_Branch01",
        "Kind": "Expression",
        "ProcessDef": branch_pd_id,
        "Expression::Node": ["Node_Root01"],
    }
    rep = FlowDraft.from_wire(d).problems(
        list_options={"List_Sample01": ["Option A", "Option B"]}
    )
    assert not any("Path A" in p for p in rep.problems)
    assert rep.checked["branch_literals"] == 1


def test_branch_referencing_missing_field_flagged(clean_draft: Draft) -> None:
    d = copy.deepcopy(clean_draft)
    (branch_pd,) = _nodes_of(d, Kind="ProcessDef", Name="Path A")
    branch_pd_id = branch_pd["Id"]

    d["Node_Root01"] = {
        "Id": "Node_Root01",
        "Kind": "Node",
        "Type": "Operator",
        "Node::Node": ["Node_Field01"],
    }
    d["Node_Field01"] = {
        "Id": "Node_Field01",
        "Kind": "Node",
        "Type": "Field",
        "Field": "Field_Missing99",
    }
    d["Expression_Branch01"] = {
        "Id": "Expression_Branch01",
        "Kind": "Expression",
        "ProcessDef": branch_pd_id,
        "Expression::Node": ["Node_Root01"],
    }
    rep = FlowDraft.from_wire(d).problems()
    assert any(
        "branch 'Path A' references missing field Field_Missing99" in p
        for p in rep.problems
    )


def test_branch_comparing_against_non_select_field_is_unvalidated(
    clean_draft: Draft,
) -> None:
    d = copy.deepcopy(clean_draft)
    root = d["Root"]
    (branch_pd,) = _nodes_of(d, Kind="ProcessDef", Name="Path A")
    branch_pd_id = branch_pd["Id"]

    d["Field_Text01"] = {
        "Id": "Field_Text01",
        "Kind": "Field",
        "Model": root,
        "Type": "Text",
        "Name": "Notes",
    }
    d["Node_Root01"] = {
        "Id": "Node_Root01",
        "Kind": "Node",
        "Type": "Operator",
        "Node::Node": ["Node_Field01", "Node_Static01"],
    }
    d["Node_Field01"] = {
        "Id": "Node_Field01",
        "Kind": "Node",
        "Type": "Field",
        "Field": "Field_Text01",
    }
    d["Node_Static01"] = {
        "Id": "Node_Static01",
        "Kind": "Node",
        "Type": "Static",
        "Value": "SomeValue",
    }
    d["Expression_Branch01"] = {
        "Id": "Expression_Branch01",
        "Kind": "Expression",
        "ProcessDef": branch_pd_id,
        "Expression::Node": ["Node_Root01"],
    }
    rep = FlowDraft.from_wire(d).problems(list_options={"List_Sample01": ["Option A"]})
    assert any(
        "not validated (no list options given for its field)" in u
        for u in rep.unvalidated
    )


def test_event_attached_to_missing_field_flagged(clean_draft: Draft) -> None:
    d = copy.deepcopy(clean_draft)
    (event,) = _nodes_of(d, Kind="Event")
    event["Field"] = "Field_DoesNotExist99"
    rep = FlowDraft.from_wire(d).problems()
    assert any("is attached to a missing field" in p for p in rep.problems)


def test_section_without_columns_is_not_flagged_as_never_editable(
    clean_draft: Draft,
) -> None:
    d = copy.deepcopy(clean_draft)
    d["Section_Banner"] = {
        "Id": "Section_Banner",
        "Kind": "Column",
        "Type": "Section",
        "Name": "Info Banner",
        "Column::Row": [],
    }
    rep = FlowDraft.from_wire(d).problems()
    assert not any("Info Banner" in p for p in rep.problems)


def test_owning_table_name_resolution_and_fallbacks() -> None:
    from app.domain.entities._flow_rules import _owning_table_name

    # 1. Normal table with name on Model
    nodes1 = {
        "Model_T": {
            "Id": "Model_T",
            "Kind": "Model",
            "Name": "LineItems",
            "Column": "Col_T",
        },
        "Col_T": {
            "Id": "Col_T",
            "Kind": "Column",
            "Type": "Model",
            "Name": "LineItems",
        },
    }
    assert _owning_table_name(nodes1, {"Model": "Model_T"}) == "LineItems"

    # 2. Table with empty Name on Model, falling back to host Column Name
    nodes2 = {
        "Model_T": {"Id": "Model_T", "Kind": "Model", "Name": "", "Column": "Col_T"},
        "Col_T": {
            "Id": "Col_T",
            "Kind": "Column",
            "Type": "Model",
            "Name": "FallbackHostName",
        },
    }
    assert _owning_table_name(nodes2, {"Model": "Model_T"}) == "FallbackHostName"

    # 3. Model not found or not a Model
    assert _owning_table_name({}, {"Model": "Model_Missing"}) is None
    assert _owning_table_name({"M": {"Kind": "Field"}}, {"Model": "M"}) is None

    # 4. Root model with no host Column
    nodes4 = {"Model_Root": {"Id": "Model_Root", "Kind": "Model", "Name": "RootModel"}}
    assert _owning_table_name(nodes4, {"Model": "Model_Root"}) is None

    # 5. Model with no name on either Model or Column
    nodes5 = {
        "Model_T": {"Id": "Model_T", "Kind": "Model", "Name": "", "Column": "Col_T"},
        "Col_T": {"Id": "Col_T", "Kind": "Column", "Type": "Model", "Name": ""},
    }
    assert _owning_table_name(nodes5, {"Model": "Model_T"}) is None


def test_dangling_list_refs_with_non_string_elements(clean_draft: Draft) -> None:
    d = copy.deepcopy(clean_draft)
    d["Row_Test"] = {
        "Id": "Row_Test",
        "Kind": "Row",
        "Row::Column": [123, None, "Column_DoesNotExist99"],
    }
    rep = FlowDraft.from_wire(d).problems()
    assert any(
        "Row_Test.Row::Column -> missing Column_DoesNotExist99" in p
        for p in rep.problems
    )


def test_branch_condition_with_no_field_sibling_is_unvalidated(
    clean_draft: Draft,
) -> None:
    d = copy.deepcopy(clean_draft)
    (branch_pd,) = _nodes_of(d, Kind="ProcessDef", Name="Path A")
    branch_pd_id = branch_pd["Id"]

    d["Node_Root01"] = {
        "Id": "Node_Root01",
        "Kind": "Node",
        "Type": "Operator",
        "Node::Node": ["Node_Static01"],
    }
    d["Node_Static01"] = {
        "Id": "Node_Static01",
        "Kind": "Node",
        "Type": "Static",
        "Value": "StandaloneStatic",
    }
    d["Expression_Branch01"] = {
        "Id": "Expression_Branch01",
        "Kind": "Expression",
        "ProcessDef": branch_pd_id,
        "Expression::Node": ["Node_Root01"],
    }
    rep = FlowDraft.from_wire(d).problems()
    assert any("literal 'StandaloneStatic' not validated" in u for u in rep.unvalidated)


def test_permission_for_model_column_credits_model_name(clean_draft: Draft) -> None:
    """A Permission on a Model-type column (a nested table) must credit the model's
    OWN name as editable, not just the Section that physically contains it — nest
    it under a differently named Section ("Banner") so `owner_section` alone would
    credit only "Banner"; without `_process_permission_node`'s Model-name credit,
    "TableSection" itself would wrongly show up in `doctor`'s per-Model coverage
    sweep as never editable."""
    d = copy.deepcopy(clean_draft)
    d["Row_Banner_Test"] = {
        "Id": "Row_Banner_Test",
        "Kind": "Row",
        "Column": "Sec_Banner_Test",
        "Row::Column": ["Col_Model_Test"],
    }
    d["Sec_Banner_Test"] = {
        "Id": "Sec_Banner_Test",
        "Kind": "Column",
        "Type": "Section",
        "Name": "Banner",
        "Column::Row": ["Row_Banner_Test"],
    }
    d["Col_Model_Test"] = {
        "Id": "Col_Model_Test",
        "Kind": "Column",
        "Type": "Model",
        "Name": "TableSection",
        "Row": "Row_Banner_Test",
    }
    act = _nodes_of(d, Kind="Activity", NodeType="UserTask")[0]
    d["Permission_Model_Test"] = {
        "Id": "Permission_Model_Test",
        "Kind": "Permission",
        "Permission": "Editable",
        "Activity": act["Id"],
        "Column": "Col_Model_Test",
    }
    rep = FlowDraft.from_wire(d).problems()
    assert not any("TableSection" in p for p in rep.problems), rep.problems


def test_permission_for_suspended_activity_is_ignored_for_editability(
    clean_draft: Draft,
) -> None:
    """A Permission attached to a suspended Activity must not count toward a
    section's editability. "Assessment" in `clean_draft` is owned only by 'Assess
    unit' — suspending that step must surface the section as never editable, not
    silently leave it credited."""
    d = copy.deepcopy(clean_draft)
    (assess,) = _nodes_of(d, Kind="Activity", NodeType="UserTask", Name="Assess unit")
    assess["IsSuspended"] = True
    rep = FlowDraft.from_wire(d).problems()
    assert any("Assessment" in p and "never editable" in p for p in rep.problems), (
        rep.problems
    )


# =====================================================================================
# expr.py -> FlowDraft (moved from test_expr.py; expression_owner moved to
# tests/unit/domain/value_objects/test_expression.py)
# =====================================================================================


Draft = dict[str, Any]


def _nodes_of(draft: Draft, **criteria: Any) -> list[dict[str, Any]]:
    """Every node dict matching all the given key=value criteria."""
    return [
        v
        for v in draft.values()
        if isinstance(v, dict) and all(v.get(k) == val for k, val in criteria.items())
    ]


def _one(draft: Draft, **criteria: Any) -> dict[str, Any]:
    hits = _nodes_of(draft, **criteria)
    assert len(hits) == 1, (
        f"fixture drift: expected exactly one match for {criteria}, got {len(hits)}"
    )
    return hits[0]


# ---- fixtures
# -------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def permissioned_draft() -> Draft:
    """A fully-formed, fully-permissioned process draft — same recipe as
    test_verify.py's permissioned_draft, so `verify.doctor` genuinely has nothing
    to complain about before any of this module's own mutations land on top of it."""
    draft = synthetic_process_draft()
    owners = {**OWNERS, "Other": ["Wrap-up report"]}
    matrix = progressive_matrix(FlowDraft.from_wire(draft), owners)
    return FlowDraft.from_wire(draft).set_step_permissions(matrix).to_wire()


@pytest.fixture()
def branch_pd_id(permissioned_draft: Draft) -> str:
    return _one(permissioned_draft, Kind="ProcessDef", Name="Path A")["Id"]


@pytest.fixture()
def select_field_id(permissioned_draft: Draft) -> str:
    return _one(permissioned_draft, Kind="Field", Name="Route Choice")["Id"]


@pytest.fixture()
def urgency_field_id(permissioned_draft: Draft) -> str:
    return _one(permissioned_draft, Kind="Field", Name="Urgency")["Id"]


@pytest.fixture()
def text_field_id(permissioned_draft: Draft) -> str:
    return _one(permissioned_draft, Kind="Field", Name="Ticket No")["Id"]


@pytest.fixture()
def boolean_field_id(permissioned_draft: Draft) -> str:
    return _one(permissioned_draft, Kind="Field", Name="Bench Done")["Id"]


@pytest.fixture()
def deep_done_field_id(permissioned_draft: Draft) -> str:
    return _one(permissioned_draft, Kind="Field", Name="Deep Done")["Id"]


@pytest.fixture()
def draft_with_bare_goto(permissioned_draft: Draft) -> tuple[Draft, str]:
    """Layer ONE bare (conditionless) GotoTask onto a copy of the clean draft via raw
    dict surgery, so build_goto_gate has a real, otherwise-untouched Activity to
    attach a condition to. Kept separate from tests/synthetic.py's own
    with_goto_and_event (which already carries a condition) so this module's
    assertions are about ITS OWN mutation, not a pre-existing one. Shape matches
    synthetic.py's with_goto_and_event exactly (same GotoTask wiring), minus the
    condition — that absence is expected to make `doctor` flag "loops forever" until
    build_goto_gate is applied, which is exactly the case each test below exercises.
    """
    new = copy.deepcopy(permissioned_draft)
    root = new["Root"]
    pd_id = new[root]["RootProcessDef"]
    pd = new[pd_id]
    chain = list(pd["ProcessDef::Activity"])
    target_id = chain[1]  # first real step after Start

    goto_id = "Activity_SampleBareGoto01"
    new[goto_id] = {
        "Id": goto_id,
        "Kind": "Activity",
        "NodeType": "GotoTask",
        "Name": "Goto-Sample Bare",
        "ProcessDef": pd_id,
        "CreatedAt": "2026-01-01T00:00:00.000Z",
        "Goto": target_id,
    }
    new[target_id].setdefault("Goto::Activity", []).append(goto_id)
    pd["ProcessDef::Activity"] = [*chain, goto_id]
    return new, goto_id


@pytest.fixture()
def draft_with_branch_condition(
    permissioned_draft: Draft,
    branch_pd_id: str,
    select_field_id: str,
) -> tuple[Draft, str]:
    got = (
        FlowDraft.from_wire(permissioned_draft)
        .build_branch_condition(
            process_def_id=branch_pd_id,
            field_id=select_field_id,
            literal="Option A",
            options=None,
        )
        .to_wire()
    )
    expr = _one(got, Kind="Expression", ProcessDef=branch_pd_id)
    return got, expr["Id"]


@pytest.fixture()
def draft_with_goto_condition(
    draft_with_bare_goto: tuple[Draft, str],
    boolean_field_id: str,
) -> tuple[Draft, str, str]:
    draft, goto_id = draft_with_bare_goto
    got = (
        FlowDraft.from_wire(draft)
        .build_goto_gate(goto_activity_id=goto_id, field_id=boolean_field_id)
        .to_wire()
    )
    expr = _one(got, Kind="Expression", Activity=goto_id)
    return got, expr["Id"], goto_id


@pytest.fixture()
def draft_with_legacy_select_goto_condition(
    draft_with_bare_goto: tuple[Draft, str],
    select_field_id: str,
) -> tuple[Draft, str, str]:
    """A goto condition shaped like the ORIGINAL captured branch gate before its
    historical rewire (research/goto_condition_shape.json, cross-checked against
    shapes/expression_goto_ condition.json's notes): Activity-owned, comparing a
    Select field against a Static literal. `build_goto_gate` itself can never produce
    this shape — it only ever writes Boolean+false() — so this is hand-built via raw
    dict surgery, exactly the "offline ... + raw dict surgery" testing convention
    this module already uses elsewhere. This is the real legacy shape
    `rewire_condition` must still accept AS INPUT and correctly convert.
    """
    new, goto_id = draft_with_bare_goto

    expr_id = "Expression_SLegacySelectGoto01"
    root_id = "Node_SLegacyRoot01"
    lhs_id = "Node_SLegacyLhs01"
    rhs_id = "Node_SLegacyRhs01"

    new[lhs_id] = {
        "Id": lhs_id,
        "Kind": "Node",
        "Type": "Field",
        "Field": select_field_id,
        "DataType": "String",
        "Node": root_id,
    }
    new[rhs_id] = {
        "Id": rhs_id,
        "Kind": "Node",
        "Type": "Static",
        "Value": "Option A",
        "DataType": "String",
        "Node": root_id,
    }
    new[root_id] = {
        "Id": root_id,
        "Kind": "Node",
        "Type": "Function",
        "Value": "=",
        "Syntax": "Infix",
        "Expression": expr_id,
        "FieldRefCount": 1,
        "Node::Node": [lhs_id, rhs_id],
        "DataType": "Boolean",
        "Category": "String",
    }
    new[expr_id] = {
        "Id": expr_id,
        "Kind": "Expression",
        "ExpressionStr": f'{select_field_id} = "Option A"',
        "Activity": goto_id,
        "Expression::Node": [root_id],
    }
    new[goto_id]["Activity::Expression"] = [expr_id]
    new[select_field_id].setdefault("Field::Node", []).append(lhs_id)

    return new, expr_id, goto_id


# ---- baseline sanity
# --------------------------------------------------------------------------


def test_clean_draft_fixture_is_actually_clean(permissioned_draft: Draft) -> None:
    assert FlowDraft.from_wire(permissioned_draft).problems().ok(), (
        "fixture drift: permissioned_draft must be clean before any mutation"
    )


# ---- build_branch_condition
# -----------------------------------------------------------------


def test_build_branch_condition_full_node_set(
    permissioned_draft: Draft,
    branch_pd_id: str,
    select_field_id: str,
) -> None:
    got = (
        FlowDraft.from_wire(permissioned_draft)
        .build_branch_condition(
            process_def_id=branch_pd_id,
            field_id=select_field_id,
            literal="Option A",
            options=None,
        )
        .to_wire()
    )

    expr = _one(got, Kind="Expression", ProcessDef=branch_pd_id)
    assert expr["ExpressionStr"] == f'{select_field_id} = "Option A"'
    assert len(expr["Expression::Node"]) == 1
    root_id = expr["Expression::Node"][0]
    root = got[root_id]

    assert root["Type"] == "Function" and root["Value"] == "="
    assert root["Syntax"] == "Infix"
    assert root["DataType"] == "Boolean"
    assert root["Category"] == "String"  # operand class for a Select comparison
    assert root["FieldRefCount"] == 1
    assert root["Expression"] == expr["Id"]  # bidirectional owner back-ref on the root

    lhs_id, rhs_id = root["Node::Node"]
    lhs, rhs = got[lhs_id], got[rhs_id]

    assert lhs["Type"] == "Field" and lhs["Field"] == select_field_id
    assert lhs["DataType"] == "String" and lhs["Node"] == root_id
    assert "Category" not in lhs

    assert rhs["Type"] == "Static" and rhs["Value"] == "Option A"
    assert rhs["DataType"] == "String" and rhs["Node"] == root_id
    assert "Category" not in rhs

    assert lhs_id in got[select_field_id]["Field::Node"]
    assert expr["Id"] in got[branch_pd_id]["ProcessDef::Expression"]
    assert expression_owner(expr) == "branch"
    assert FlowDraft.from_wire(got).problems().ok()


def test_build_branch_condition_accepts_text_field(
    permissioned_draft: Draft,
    branch_pd_id: str,
    text_field_id: str,
) -> None:
    """Text is the same string-on-the-wire representation as Select — see the
    _BRANCH_FIELD_DATA_TYPE comment in entities/_flow_ops.py for why it, and
    only it besides Select, is included."""
    got = (
        FlowDraft.from_wire(permissioned_draft)
        .build_branch_condition(
            process_def_id=branch_pd_id,
            field_id=text_field_id,
            literal="Option A",
            options=None,
        )
        .to_wire()
    )
    expr = _one(got, Kind="Expression", ProcessDef=branch_pd_id)
    root_id = expr["Expression::Node"][0]
    assert got[root_id]["Category"] == "String"
    assert FlowDraft.from_wire(got).problems().ok()


def test_build_branch_condition_input_not_mutated(
    permissioned_draft: Draft,
    branch_pd_id: str,
    select_field_id: str,
) -> None:
    before = copy.deepcopy(permissioned_draft)
    _ = (
        FlowDraft.from_wire(permissioned_draft)
        .build_branch_condition(
            process_def_id=branch_pd_id,
            field_id=select_field_id,
            literal="Option A",
            options=None,
        )
        .to_wire()
    )
    assert permissioned_draft == before


def test_build_branch_condition_literal_outside_options_rejected_before_mutation(
    permissioned_draft: Draft,
    branch_pd_id: str,
    select_field_id: str,
) -> None:
    before = copy.deepcopy(permissioned_draft)
    with pytest.raises(ValueError):
        FlowDraft.from_wire(permissioned_draft).build_branch_condition(
            process_def_id=branch_pd_id,
            field_id=select_field_id,
            literal="Not A Real Option",
            options=["Option A", "Option B"],
        ).to_wire()
    assert permissioned_draft == before, (
        "a literal that cannot match must never be written, not even partially"
    )


def test_build_branch_condition_literal_inside_options_accepted(
    permissioned_draft: Draft,
    branch_pd_id: str,
    select_field_id: str,
) -> None:
    got = (
        FlowDraft.from_wire(permissioned_draft)
        .build_branch_condition(
            process_def_id=branch_pd_id,
            field_id=select_field_id,
            literal="Option A",
            options=["Option A", "Option B"],
        )
        .to_wire()
    )
    assert FlowDraft.from_wire(got).problems().ok()


def test_build_branch_condition_options_none_is_allowed(
    permissioned_draft: Draft,
    branch_pd_id: str,
    select_field_id: str,
) -> None:
    """options=None skips validation entirely — the caller owns the risk (CLAUDE.md:
    "never guess a literal", but an explicit None is not a guess, it is the
    caller's own informed choice)."""
    got = (
        FlowDraft.from_wire(permissioned_draft)
        .build_branch_condition(
            process_def_id=branch_pd_id,
            field_id=select_field_id,
            literal="Whatever The Caller Wants",
            options=None,
        )
        .to_wire()
    )
    expr = _one(got, Kind="Expression", ProcessDef=branch_pd_id)
    assert expr["ExpressionStr"] == f'{select_field_id} = "Whatever The Caller Wants"'


def test_build_branch_condition_unknown_process_def_rejected(
    permissioned_draft: Draft,
    select_field_id: str,
) -> None:
    before = copy.deepcopy(permissioned_draft)
    with pytest.raises(ValueError):
        FlowDraft.from_wire(permissioned_draft).build_branch_condition(
            process_def_id="ProcessDef_DoesNotExist99",
            field_id=select_field_id,
            literal="Option A",
            options=None,
        ).to_wire()
    assert permissioned_draft == before


def test_build_branch_condition_unknown_field_rejected(
    permissioned_draft: Draft, branch_pd_id: str
) -> None:
    before = copy.deepcopy(permissioned_draft)
    with pytest.raises(ValueError):
        FlowDraft.from_wire(permissioned_draft).build_branch_condition(
            process_def_id=branch_pd_id,
            field_id="Field_DoesNotExist99",
            literal="Option A",
            options=None,
        ).to_wire()
    assert permissioned_draft == before


def test_build_branch_condition_rejects_uncaptured_field_type(
    permissioned_draft: Draft,
    branch_pd_id: str,
    boolean_field_id: str,
) -> None:
    """A Boolean field compared via a Static literal is an uncaptured wire shape —
    build_goto_gate owns the Boolean/false() combination, never a Static
    (CLAUDE.md Expressions)."""
    before = copy.deepcopy(permissioned_draft)
    with pytest.raises(ValueError):
        FlowDraft.from_wire(permissioned_draft).build_branch_condition(
            process_def_id=branch_pd_id,
            field_id=boolean_field_id,
            literal="Option A",
            options=None,
        ).to_wire()
    assert permissioned_draft == before


def test_build_branch_condition_twice_with_identical_args_does_not_duplicate_backrefs(
    permissioned_draft: Draft,
    branch_pd_id: str,
    select_field_id: str,
) -> None:
    """Ids are deterministic (hash of process_def_id/field_id/literal), so a repeat
    call with identical args overwrites the same Expression/Node dicts
    idempotently — but the LIST-shaped back-refs (ProcessDef::Expression,
    Field::Node) must not gain a second entry for the same node id. No UI-built
    flow ever produced a back-ref list with a repeated id."""
    once = (
        FlowDraft.from_wire(permissioned_draft)
        .build_branch_condition(
            process_def_id=branch_pd_id,
            field_id=select_field_id,
            literal="Option A",
            options=None,
        )
        .to_wire()
    )
    twice = (
        FlowDraft.from_wire(once)
        .build_branch_condition(
            process_def_id=branch_pd_id,
            field_id=select_field_id,
            literal="Option A",
            options=None,
        )
        .to_wire()
    )

    pd_expr_ids = twice[branch_pd_id]["ProcessDef::Expression"]
    assert len(pd_expr_ids) == len(set(pd_expr_ids)), (
        "ProcessDef::Expression must not repeat an id"
    )

    field_node_ids = twice[select_field_id]["Field::Node"]
    assert len(field_node_ids) == len(set(field_node_ids)), (
        "Field::Node must not repeat an id"
    )

    assert FlowDraft.from_wire(twice).problems().ok()


# ---- build_goto_gate
# --------------------------------------------------------------------------


def test_build_goto_gate_zero_arg_false_literal_shape(
    draft_with_bare_goto: tuple[Draft, str],
    boolean_field_id: str,
) -> None:
    draft, goto_id = draft_with_bare_goto
    got = (
        FlowDraft.from_wire(draft)
        .build_goto_gate(goto_activity_id=goto_id, field_id=boolean_field_id)
        .to_wire()
    )

    expr = _one(got, Kind="Expression", Activity=goto_id)
    assert expr["ExpressionStr"] == f"{boolean_field_id} = false()"
    assert len(expr["Expression::Node"]) == 1
    root_id = expr["Expression::Node"][0]
    root = got[root_id]

    assert root["DataType"] == "Boolean" and root["Category"] == "Boolean"
    assert root["Syntax"] == "Infix" and root["FieldRefCount"] == 1
    assert root["Expression"] == expr["Id"]

    lhs_id, rhs_id = root["Node::Node"]
    lhs, rhs = got[lhs_id], got[rhs_id]

    assert lhs["Type"] == "Field" and lhs["Field"] == boolean_field_id
    assert lhs["DataType"] == "Boolean"
    assert "Category" not in lhs

    # the zero-arg false() literal: a Function, never a Static — and unlike the infix
    # root, no Syntax and no Node::Node (CLAUDE.md: "No Node::Node, no Syntax key")
    assert rhs["Type"] == "Function" and rhs["Value"] == "false"
    assert rhs["DataType"] == "Boolean" and rhs["Category"] == "Boolean"
    assert "Syntax" not in rhs
    assert "Node::Node" not in rhs

    assert lhs_id in got[boolean_field_id]["Field::Node"]
    assert expr["Id"] in got[goto_id]["Activity::Expression"]
    assert expression_owner(expr) == "goto"
    assert FlowDraft.from_wire(got).problems().ok()


def test_build_goto_gate_input_not_mutated(
    draft_with_bare_goto: tuple[Draft, str],
    boolean_field_id: str,
) -> None:
    draft, goto_id = draft_with_bare_goto
    before = copy.deepcopy(draft)
    _ = (
        FlowDraft.from_wire(draft)
        .build_goto_gate(goto_activity_id=goto_id, field_id=boolean_field_id)
        .to_wire()
    )
    assert draft == before


def test_build_goto_gate_rejects_non_boolean_field(
    draft_with_bare_goto: tuple[Draft, str],
    select_field_id: str,
) -> None:
    """Gate polarity: an optional Select fails OPEN (silently escapes the loop) —
    never allowed to gate a GotoTask (CLAUDE.md Gate polarity)."""
    draft, goto_id = draft_with_bare_goto
    before = copy.deepcopy(draft)
    with pytest.raises(ValueError):
        FlowDraft.from_wire(draft).build_goto_gate(
            goto_activity_id=goto_id, field_id=select_field_id
        ).to_wire()
    assert draft == before


def test_build_goto_gate_unknown_activity_rejected(
    permissioned_draft: Draft, boolean_field_id: str
) -> None:
    before = copy.deepcopy(permissioned_draft)
    with pytest.raises(ValueError):
        FlowDraft.from_wire(permissioned_draft).build_goto_gate(
            goto_activity_id="Activity_DoesNotExist99",
            field_id=boolean_field_id,
        ).to_wire()
    assert permissioned_draft == before


def test_build_goto_gate_unknown_field_rejected(
    draft_with_bare_goto: tuple[Draft, str],
) -> None:
    draft, goto_id = draft_with_bare_goto
    before = copy.deepcopy(draft)
    with pytest.raises(ValueError):
        FlowDraft.from_wire(draft).build_goto_gate(
            goto_activity_id=goto_id, field_id="Field_DoesNotExist99"
        ).to_wire()
    assert draft == before


# ---- remove_condition
# ------------------------------------------------------------------------- The
# SET-semantics counterpart to build_branch_condition/build_goto_gate: a caller that
# wants "this branch/goto's condition is now X" needs the OLD one gone first, or a
# re-run with a changed field/literal mints a second Expression alongside the stale one
# (different id, since the id is a hash of the args) rather than replacing it.


def test_remove_branch_condition_deletes_expression_and_node_subtree(
    draft_with_branch_condition: tuple[Draft, str],
    branch_pd_id: str,
    select_field_id: str,
) -> None:
    draft, expr_id = draft_with_branch_condition
    root_id = draft[expr_id]["Expression::Node"][0]
    lhs_id, rhs_id = draft[root_id]["Node::Node"]

    got = FlowDraft.from_wire(draft).remove_condition(expression_id=expr_id).to_wire()

    assert (
        expr_id not in got
        and root_id not in got
        and lhs_id not in got
        and rhs_id not in got
    )
    assert expr_id not in (got[branch_pd_id].get("ProcessDef::Expression") or [])
    assert lhs_id not in (got[select_field_id].get("Field::Node") or [])
    assert FlowDraft.from_wire(got).problems().ok()


def test_remove_goto_condition_deletes_expression_and_node_subtree(
    draft_with_goto_condition: tuple[Draft, str, str],
    boolean_field_id: str,
) -> None:
    draft, expr_id, goto_id = draft_with_goto_condition
    root_id = draft[expr_id]["Expression::Node"][0]
    lhs_id, rhs_id = draft[root_id]["Node::Node"]

    got = FlowDraft.from_wire(draft).remove_condition(expression_id=expr_id).to_wire()

    assert (
        expr_id not in got
        and root_id not in got
        and lhs_id not in got
        and rhs_id not in got
    )
    assert expr_id not in (got[goto_id].get("Activity::Expression") or [])
    assert lhs_id not in (got[boolean_field_id].get("Field::Node") or [])
    # doctor still complains the goto has NO condition -- correct, we just removed it on
    # purpose
    assert any(
        "NO condition" in p for p in FlowDraft.from_wire(got).problems().problems
    )


def test_remove_condition_input_not_mutated(
    draft_with_branch_condition: tuple[Draft, str],
) -> None:
    draft, expr_id = draft_with_branch_condition
    before = copy.deepcopy(draft)
    _ = FlowDraft.from_wire(draft).remove_condition(expression_id=expr_id).to_wire()
    assert draft == before


def test_remove_condition_unknown_expression_rejected(
    permissioned_draft: Draft,
) -> None:
    before = copy.deepcopy(permissioned_draft)
    with pytest.raises(ValueError):
        FlowDraft.from_wire(permissioned_draft).remove_condition(
            expression_id="Expression_DoesNotExist99"
        ).to_wire()
    assert permissioned_draft == before


def test_remove_condition_rejects_property_owned_expression(
    permissioned_draft: Draft,
) -> None:
    draft = copy.deepcopy(permissioned_draft)
    draft["Property_SamplePrefix01"] = {
        "Id": "Property_SamplePrefix01",
        "Kind": "Property",
        "Name": "PrefixExpression",
        "ValueType": "Expression",
    }
    draft["Expression_SamplePrefix01"] = {
        "Id": "Expression_SamplePrefix01",
        "Kind": "Expression",
        "ExpressionStr": 'concatenate("SAMPLE")',
        "Property": "Property_SamplePrefix01",
    }
    before = copy.deepcopy(draft)
    with pytest.raises(ValueError):
        FlowDraft.from_wire(draft).remove_condition(
            expression_id="Expression_SamplePrefix01"
        ).to_wire()
    assert draft == before


def test_remove_then_build_branch_condition_replaces_not_accumulates(
    permissioned_draft: Draft,
    branch_pd_id: str,
    select_field_id: str,
) -> None:
    """The actual SET workflow: build with one literal, remove, build again with a
    DIFFERENT literal on the SAME branch -> exactly one Expression on that
    ProcessDef, holding the NEW value, never two."""
    first = (
        FlowDraft.from_wire(permissioned_draft)
        .build_branch_condition(
            process_def_id=branch_pd_id,
            field_id=select_field_id,
            literal="Option A",
            options=None,
        )
        .to_wire()
    )
    first_expr_id = _one(first, Kind="Expression", ProcessDef=branch_pd_id)["Id"]

    cleared = (
        FlowDraft.from_wire(first)
        .remove_condition(expression_id=first_expr_id)
        .to_wire()
    )
    second = (
        FlowDraft.from_wire(cleared)
        .build_branch_condition(
            process_def_id=branch_pd_id,
            field_id=select_field_id,
            literal="Option B",
            options=None,
        )
        .to_wire()
    )

    exprs = _nodes_of(second, Kind="Expression", ProcessDef=branch_pd_id)
    assert len(exprs) == 1, (
        f"expected exactly one condition on the branch, got {len(exprs)}"
    )
    assert exprs[0]["ExpressionStr"] == f'{select_field_id} = "Option B"'
    assert FlowDraft.from_wire(second).problems().ok()


def test_process_def_expression_ids_tracks_build_and_remove(
    permissioned_draft: Draft,
    branch_pd_id: str,
    select_field_id: str,
) -> None:
    """G9 review: this is the read-only accessor `client.py`'s
    apply_branch_conditions uses instead of reaching into `FlowDraft.nodes`
    itself to list a ProcessDef's existing conditions before rebuilding."""
    empty = FlowDraft.from_wire(permissioned_draft)
    assert empty.process_def_expression_ids(branch_pd_id) == ()

    built = FlowDraft.from_wire(permissioned_draft).build_branch_condition(
        process_def_id=branch_pd_id,
        field_id=select_field_id,
        literal="Option A",
        options=None,
    )
    expr_id = _one(built.to_wire(), Kind="Expression", ProcessDef=branch_pd_id)["Id"]
    assert built.process_def_expression_ids(branch_pd_id) == (expr_id,)

    cleared = built.remove_condition(expression_id=expr_id)
    assert cleared.process_def_expression_ids(branch_pd_id) == ()


def test_process_def_expression_ids_unknown_id_reads_as_empty(
    permissioned_draft: Draft,
) -> None:
    assert (
        FlowDraft.from_wire(permissioned_draft).process_def_expression_ids(
            "ProcessDef_nope"
        )
        == ()
    )


def test_remove_condition_recurses_into_a_nested_compound_condition(
    permissioned_draft: Draft,
    branch_pd_id: str,
    select_field_id: str,
    urgency_field_id: str,
) -> None:
    """No `build_*` function in this module ever writes deeper than root+2-leaves — but
    `apply_branch_conditions` calls `remove_condition` on ANY pre-existing ProcessDef
    Expression, including one a human built in the UI, and a compound AND/OR of two
    comparisons is a plausible deeper shape (uncaptured — this is a synthetic
    stand-in via raw dict surgery, the same convention
    `draft_with_legacy_select_goto_condition` already uses for an uncaptured shape,
    NOT a claim that "and" is the real captured operator string). A shallow (root,
    then direct children only) walk would delete the AND root and its two comparison
    sub-roots but strand THEIR leaf nodes — this pins that the walk goes all the way
    down instead.
    """
    draft = copy.deepcopy(permissioned_draft)
    expr_id = "Expression_SCompound01"
    and_root_id = "Node_SAndRoot01"
    cmp1_root_id, cmp1_lhs_id, cmp1_rhs_id = (
        "Node_SCmp1Root01",
        "Node_SCmp1Lhs01",
        "Node_SCmp1Rhs01",
    )
    cmp2_root_id, cmp2_lhs_id, cmp2_rhs_id = (
        "Node_SCmp2Root01",
        "Node_SCmp2Lhs01",
        "Node_SCmp2Rhs01",
    )

    draft[cmp1_lhs_id] = {
        "Id": cmp1_lhs_id,
        "Kind": "Node",
        "Type": "Field",
        "Field": select_field_id,
        "DataType": "String",
        "Node": cmp1_root_id,
    }
    draft[cmp1_rhs_id] = {
        "Id": cmp1_rhs_id,
        "Kind": "Node",
        "Type": "Static",
        "Value": "Option A",
        "DataType": "String",
        "Node": cmp1_root_id,
    }
    draft[cmp1_root_id] = {
        "Id": cmp1_root_id,
        "Kind": "Node",
        "Type": "Function",
        "Value": "=",
        "Syntax": "Infix",
        "DataType": "Boolean",
        "Category": "String",
        "Node::Node": [cmp1_lhs_id, cmp1_rhs_id],
        "Node": and_root_id,
    }
    draft[cmp2_lhs_id] = {
        "Id": cmp2_lhs_id,
        "Kind": "Node",
        "Type": "Field",
        "Field": urgency_field_id,
        "DataType": "String",
        "Node": cmp2_root_id,
    }
    draft[cmp2_rhs_id] = {
        "Id": cmp2_rhs_id,
        "Kind": "Node",
        "Type": "Static",
        "Value": "High",
        "DataType": "String",
        "Node": cmp2_root_id,
    }
    draft[cmp2_root_id] = {
        "Id": cmp2_root_id,
        "Kind": "Node",
        "Type": "Function",
        "Value": "=",
        "Syntax": "Infix",
        "DataType": "Boolean",
        "Category": "String",
        "Node::Node": [cmp2_lhs_id, cmp2_rhs_id],
        "Node": and_root_id,
    }
    draft[and_root_id] = {
        "Id": and_root_id,
        "Kind": "Node",
        "Type": "Function",
        "Value": "and",
        "Syntax": "Infix",
        "DataType": "Boolean",
        "Expression": expr_id,
        "Node::Node": [cmp1_root_id, cmp2_root_id],
    }
    draft[expr_id] = {
        "Id": expr_id,
        "Kind": "Expression",
        "ExpressionStr": (
            f'{select_field_id} = "Option A" and {urgency_field_id} = "High"'
        ),
        "ProcessDef": branch_pd_id,
        "Expression::Node": [and_root_id],
    }
    draft[branch_pd_id].setdefault("ProcessDef::Expression", []).append(expr_id)
    draft[select_field_id].setdefault("Field::Node", []).append(cmp1_lhs_id)
    draft[urgency_field_id].setdefault("Field::Node", []).append(cmp2_lhs_id)

    got = FlowDraft.from_wire(draft).remove_condition(expression_id=expr_id).to_wire()

    for nid in (
        expr_id,
        and_root_id,
        cmp1_root_id,
        cmp1_lhs_id,
        cmp1_rhs_id,
        cmp2_root_id,
        cmp2_lhs_id,
        cmp2_rhs_id,
    ):
        assert nid not in got, f"{nid} must be gone -- a shallow walk would strand it"
    assert expr_id not in (got[branch_pd_id].get("ProcessDef::Expression") or [])
    assert cmp1_lhs_id not in (got[select_field_id].get("Field::Node") or [])
    assert cmp2_lhs_id not in (got[urgency_field_id].get("Field::Node") or [])
    assert FlowDraft.from_wire(got).problems().ok()


# ---- rewire_condition — branch (ProcessDef-owned)
# -------------------------------------------


def test_rewire_branch_condition_all_six_edits(
    draft_with_branch_condition: tuple[Draft, str],
    select_field_id: str,
    urgency_field_id: str,
) -> None:
    draft, expr_id = draft_with_branch_condition
    old_field_node_id = draft[select_field_id]["Field::Node"][0]

    got = (
        FlowDraft.from_wire(draft)
        .rewire_condition(
            expression_id=expr_id,
            new_field_id=urgency_field_id,
            options=["Option A", "Option B"],
            new_literal="Option B",
        )
        .to_wire()
    )

    expr = got[expr_id]
    root_id = expr["Expression::Node"][0]
    root = got[root_id]
    lhs_id, rhs_id = root["Node::Node"]
    lhs, rhs = got[lhs_id], got[rhs_id]

    # 1 + 2: the Field node's own reference and DataType
    assert lhs["Field"] == urgency_field_id
    assert lhs["DataType"] == "String"
    # 3: the literal node value
    assert rhs["Type"] == "Static" and rhs["Value"] == "Option B"
    # 4: the root's Category, recomputed from the new operands
    assert root["Category"] == "String"
    # 5: the ExpressionStr mirror
    assert expr["ExpressionStr"] == f'{urgency_field_id} = "Option B"'
    # 6: the Field::Node back-ref moved off the old field onto the new one
    assert old_field_node_id not in (got[select_field_id].get("Field::Node") or [])
    assert lhs_id in got[urgency_field_id]["Field::Node"]

    assert FlowDraft.from_wire(got).problems().ok()


def test_rewire_branch_condition_input_not_mutated(
    draft_with_branch_condition: tuple[Draft, str],
    urgency_field_id: str,
) -> None:
    draft, expr_id = draft_with_branch_condition
    before = copy.deepcopy(draft)
    _ = (
        FlowDraft.from_wire(draft)
        .rewire_condition(
            expression_id=expr_id,
            new_field_id=urgency_field_id,
            options=["Option A", "Option B"],
            new_literal="Option B",
        )
        .to_wire()
    )
    assert draft == before


def test_rewire_branch_condition_keeps_old_literal_when_new_literal_omitted(
    draft_with_branch_condition: tuple[Draft, str],
    urgency_field_id: str,
) -> None:
    draft, expr_id = draft_with_branch_condition
    got = (
        FlowDraft.from_wire(draft)
        .rewire_condition(expression_id=expr_id, new_field_id=urgency_field_id)
        .to_wire()
    )
    root_id = got[expr_id]["Expression::Node"][0]
    _, rhs_id = got[root_id]["Node::Node"]
    assert got[rhs_id]["Value"] == "Option A"  # carried over from before the rewire
    assert FlowDraft.from_wire(got).problems().ok()


def test_rewire_branch_condition_literal_outside_options_rejected(
    draft_with_branch_condition: tuple[Draft, str],
    urgency_field_id: str,
) -> None:
    draft, expr_id = draft_with_branch_condition
    before = copy.deepcopy(draft)
    with pytest.raises(ValueError):
        FlowDraft.from_wire(draft).rewire_condition(
            expression_id=expr_id,
            new_field_id=urgency_field_id,
            options=["Option A", "Option B"],
            new_literal="Not Real",
        ).to_wire()
    assert draft == before


def test_rewire_branch_condition_rejects_uncaptured_field_type(
    draft_with_branch_condition: tuple[Draft, str],
    boolean_field_id: str,
) -> None:
    draft, expr_id = draft_with_branch_condition
    before = copy.deepcopy(draft)
    with pytest.raises(ValueError):
        FlowDraft.from_wire(draft).rewire_condition(
            expression_id=expr_id, new_field_id=boolean_field_id
        ).to_wire()
    assert draft == before


def test_rewire_unknown_new_field_leaves_draft_untouched(
    draft_with_branch_condition: tuple[Draft, str],
) -> None:
    draft, expr_id = draft_with_branch_condition
    before = copy.deepcopy(draft)
    with pytest.raises(ValueError):
        FlowDraft.from_wire(draft).rewire_condition(
            expression_id=expr_id, new_field_id="Field_DoesNotExist99"
        ).to_wire()
    assert draft == before


def test_rewire_unknown_expression_leaves_draft_untouched(
    draft_with_branch_condition: tuple[Draft, str],
    urgency_field_id: str,
) -> None:
    draft, _expr_id = draft_with_branch_condition
    before = copy.deepcopy(draft)
    with pytest.raises(ValueError):
        FlowDraft.from_wire(draft).rewire_condition(
            expression_id="Expression_DoesNotExist99",
            new_field_id=urgency_field_id,
        ).to_wire()
    assert draft == before


def test_rewire_rejects_property_owned_expression(
    permissioned_draft: Draft, urgency_field_id: str
) -> None:
    """A SequenceNumber prefix Expression is Property-owned, not a condition — never
    rewired (CLAUDE.md: three owner keys mean three different things; Property is
    not routing)."""
    draft = copy.deepcopy(permissioned_draft)
    draft["Property_SamplePrefix01"] = {
        "Id": "Property_SamplePrefix01",
        "Kind": "Property",
        "Name": "PrefixExpression",
        "ValueType": "Expression",
    }
    draft["Expression_SamplePrefix01"] = {
        "Id": "Expression_SamplePrefix01",
        "Kind": "Expression",
        "ExpressionStr": 'concatenate("SAMPLE")',
        "Property": "Property_SamplePrefix01",
    }
    before = copy.deepcopy(draft)
    with pytest.raises(ValueError):
        FlowDraft.from_wire(draft).rewire_condition(
            expression_id="Expression_SamplePrefix01",
            new_field_id=urgency_field_id,
        ).to_wire()
    assert draft == before


def test_rewire_condition_rejects_when_literal_child_is_not_static_or_function(
    permissioned_draft: Draft,
    branch_pd_id: str,
    select_field_id: str,
    urgency_field_id: str,
) -> None:
    """Two Field-type children (a field-vs-field comparison) is a
    malformed/uncaptured AST that no build_* function here ever writes. Silently
    treating the second Field as "the literal" would overwrite a real field
    reference instead of refusing — this pins the explicit refusal."""
    draft = copy.deepcopy(permissioned_draft)
    expr_id = "Expression_SMalformed01"
    root_id = "Node_SMalformedRoot01"
    lhs_id = "Node_SMalformedLhs01"
    rhs_id = "Node_SMalformedRhs01"  # also Type Field — malformed, not Static/Function

    draft[lhs_id] = {
        "Id": lhs_id,
        "Kind": "Node",
        "Type": "Field",
        "Field": select_field_id,
        "DataType": "String",
        "Node": root_id,
    }
    draft[rhs_id] = {
        "Id": rhs_id,
        "Kind": "Node",
        "Type": "Field",
        "Field": urgency_field_id,
        "DataType": "String",
        "Node": root_id,
    }
    draft[root_id] = {
        "Id": root_id,
        "Kind": "Node",
        "Type": "Function",
        "Value": "=",
        "Syntax": "Infix",
        "Expression": expr_id,
        "FieldRefCount": 2,
        "Node::Node": [lhs_id, rhs_id],
        "DataType": "Boolean",
        "Category": "String",
    }
    draft[expr_id] = {
        "Id": expr_id,
        "Kind": "Expression",
        "ExpressionStr": f"{select_field_id} = {urgency_field_id}",
        "ProcessDef": branch_pd_id,
        "Expression::Node": [root_id],
    }
    draft[branch_pd_id].setdefault("ProcessDef::Expression", []).append(expr_id)
    draft[select_field_id].setdefault("Field::Node", []).append(lhs_id)
    draft[urgency_field_id].setdefault("Field::Node", []).append(rhs_id)

    before = copy.deepcopy(draft)
    with pytest.raises(ValueError):
        FlowDraft.from_wire(draft).rewire_condition(
            expression_id=expr_id, new_field_id=urgency_field_id
        ).to_wire()
    assert draft == before


# ---- rewire_condition — goto (Activity-owned)
# -------------------------------------------------


def test_rewire_goto_condition_all_six_edits(
    draft_with_goto_condition: tuple[Draft, str, str],
    boolean_field_id: str,
    deep_done_field_id: str,
) -> None:
    draft, expr_id, _goto_id = draft_with_goto_condition
    old_field_node_id = draft[boolean_field_id]["Field::Node"][0]

    got = (
        FlowDraft.from_wire(draft)
        .rewire_condition(expression_id=expr_id, new_field_id=deep_done_field_id)
        .to_wire()
    )

    expr = got[expr_id]
    root_id = expr["Expression::Node"][0]
    root = got[root_id]
    lhs_id, rhs_id = root["Node::Node"]
    lhs, rhs = got[lhs_id], got[rhs_id]

    assert lhs["Field"] == deep_done_field_id
    assert lhs["DataType"] == "Boolean"
    assert rhs["Type"] == "Function" and rhs["Value"] == "false"
    assert root["Category"] == "Boolean"
    assert expr["ExpressionStr"] == f"{deep_done_field_id} = false()"
    assert old_field_node_id not in (got[boolean_field_id].get("Field::Node") or [])
    assert lhs_id in got[deep_done_field_id]["Field::Node"]
    assert expression_owner(expr) == "goto"
    assert FlowDraft.from_wire(got).problems().ok()


def test_rewire_goto_condition_input_not_mutated(
    draft_with_goto_condition: tuple[Draft, str, str],
    deep_done_field_id: str,
) -> None:
    draft, expr_id, _goto_id = draft_with_goto_condition
    before = copy.deepcopy(draft)
    _ = (
        FlowDraft.from_wire(draft)
        .rewire_condition(expression_id=expr_id, new_field_id=deep_done_field_id)
        .to_wire()
    )
    assert draft == before


def test_rewire_goto_condition_rejects_non_boolean_new_field(
    draft_with_goto_condition: tuple[Draft, str, str],
    select_field_id: str,
) -> None:
    draft, expr_id, _goto_id = draft_with_goto_condition
    before = copy.deepcopy(draft)
    with pytest.raises(ValueError):
        FlowDraft.from_wire(draft).rewire_condition(
            expression_id=expr_id, new_field_id=select_field_id
        ).to_wire()
    assert draft == before


def test_rewire_goto_condition_rejects_new_literal(
    draft_with_goto_condition: tuple[Draft, str, str],
    deep_done_field_id: str,
) -> None:
    """A goto gate is always tested against false() — there is no other captured
    shape, so a caller-supplied literal is refused rather than silently ignored."""
    draft, expr_id, _goto_id = draft_with_goto_condition
    before = copy.deepcopy(draft)
    with pytest.raises(ValueError):
        FlowDraft.from_wire(draft).rewire_condition(
            expression_id=expr_id,
            new_field_id=deep_done_field_id,
            new_literal="true",
        ).to_wire()
    assert draft == before


def test_rewire_goto_condition_from_legacy_select_static_to_boolean_false(
    draft_with_legacy_select_goto_condition: tuple[Draft, str, str],
    select_field_id: str,
    deep_done_field_id: str,
) -> None:
    """Pins the production op the reviewer hand-ran: a goto gated on a Select field with
    a Static literal (the real shape a UI-built flow can carry —
    research/goto_condition_shape.json's original branch-gate capture, before its
    historical rewire) taken through rewire_condition onto a Boolean field. Must land
    on exactly the shape build_goto_gate itself writes: the zero-arg false()
    Function, with no Syntax and no Node::Node on that leaf.
    """
    draft, expr_id, _goto_id = draft_with_legacy_select_goto_condition
    old_field_node_id = draft[select_field_id]["Field::Node"][-1]

    got = (
        FlowDraft.from_wire(draft)
        .rewire_condition(expression_id=expr_id, new_field_id=deep_done_field_id)
        .to_wire()
    )

    expr = got[expr_id]
    root_id = expr["Expression::Node"][0]
    root = got[root_id]
    lhs_id, rhs_id = root["Node::Node"]
    lhs, rhs = got[lhs_id], got[rhs_id]

    # lhs DataType -> Boolean
    assert lhs["Field"] == deep_done_field_id
    assert lhs["DataType"] == "Boolean"

    # literal node becomes the zero-arg false() Function — no Syntax, no Node::Node
    assert rhs["Type"] == "Function" and rhs["Value"] == "false"
    assert rhs["DataType"] == "Boolean" and rhs["Category"] == "Boolean"
    assert "Syntax" not in rhs
    assert "Node::Node" not in rhs

    # root Category -> Boolean
    assert root["Category"] == "Boolean"
    # ExpressionStr mirrored
    assert expr["ExpressionStr"] == f"{deep_done_field_id} = false()"
    # old Select field's Field::Node no longer lists the node
    assert old_field_node_id not in (got[select_field_id].get("Field::Node") or [])
    assert lhs_id in got[deep_done_field_id]["Field::Node"]

    assert expression_owner(expr) == "goto"
    assert FlowDraft.from_wire(got).problems().ok()


def test_same_named_sections_are_all_covered_by_one_visibility_owner() -> None:
    """The production template has two Sections named "Request Info". An owner keyed by
    that name must permission the fields of BOTH; before, the second one's fields were
    "outside every matrix section" and set_visibility refused the whole write."""
    from app.domain.entities.flow_draft import FlowDraft, progressive_matrix

    bare = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "X", "FlowType": "Process"},
    }
    flow = FlowDraft.from_wire(bare).transplant_template(app_role=("Ro1", "R"))
    wire = flow.to_wire()
    sections = sorted(
        {
            v["Name"]
            for v in wire.values()
            if isinstance(v, dict)
            and v.get("Kind") == "Column"
            and v.get("Type") == "Section"
        }
    )
    twins = [
        v
        for v in wire.values()
        if isinstance(v, dict)
        and v.get("Kind") == "Column"
        and v.get("Name") == "Request Info"
    ]
    assert len(twins) == 2
    steps = [
        v["Name"]
        for v in wire.values()
        if isinstance(v, dict)
        and v.get("Kind") == "Activity"
        and v.get("Name") == "Start"
    ]
    out = flow.set_step_permissions(
        progressive_matrix(flow, {s: steps for s in sections})
    )
    permitted = {
        v["Column"]
        for v in out.to_wire().values()
        if isinstance(v, dict) and v.get("Kind") == "Permission"
    }
    for twin in twins:
        cols = {
            c
            for rid in twin.get("Column::Row", [])
            for c in wire[rid].get("Row::Column", [])
        }
        field_cols = {
            c
            for c in cols
            if wire[c].get("Type") == "Field" and not wire[c].get("IsHidden")
        }
        assert field_cols and field_cols <= permitted


def _template_flow() -> FlowDraft:
    from app.domain.entities.flow_draft import FlowDraft

    bare = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "X", "FlowType": "Process"},
    }
    return FlowDraft.from_wire(bare).transplant_template(app_role=("Ro1", "R"))


def _sections(wire: dict) -> dict[str, dict]:
    return {
        k: v
        for k, v in wire.items()
        if isinstance(v, dict)
        and v.get("Kind") == "Column"
        and v.get("Type") == "Section"
    }


def test_place_in_sections_keeps_every_untouched_section_verbatim() -> None:
    """Adding fields to a new section on the production template leaves the other
    sections' whole subtrees alone: Grids, help text, IsHidden, ids."""
    from app.domain.entities._flow_ops import _section_layout
    from app.domain.value_objects.field_spec import FieldSpec
    from app.domain.value_objects.field_type import FieldType

    before = _template_flow()
    after = (
        before.apply_changes([FieldSpec(name="Approval Note", type=FieldType.TEXTAREA)])
        .place_in_sections([("Request Details", ["Approval Note"])])
        .to_wire()
    )
    w0 = before.to_wire()

    for sid, sec in _sections(w0).items():
        assert after[sid]["Name"] == sec["Name"]
        assert after[sid].get("Description") == sec.get("Description")
        assert after[sid].get("IsHidden") == sec.get("IsHidden")

    def grids(w: dict) -> int:
        return sum(
            1 for v in w.values() if isinstance(v, dict) and v.get("Type") == "Grid"
        )

    assert grids(after) == grids(w0) == 5
    # both copies of each duplicate-named field are still inside a section
    layout = _section_layout(after)
    covered = {
        c for s in layout.section_id_of_name.values() for c in layout.members.get(s, ())
    }
    for name in ("Email ผู้เปิดงาน", "รหัสพนักงานผู้เปิดงาน"):
        cols = [
            v["Column"]
            for v in after.values()
            if isinstance(v, dict)
            and v.get("Kind") == "Field"
            and v.get("Name") == name
        ]
        assert len(cols) == 2 and set(cols) <= covered
    new = [s for s in _sections(after).values() if s["Name"] == "Request Details"]
    assert len(new) == 1


def test_place_in_sections_is_a_no_op_when_fields_are_already_placed() -> None:
    flow = _template_flow()
    groups = [("Request Info", ["Description"])]
    once = flow.place_in_sections(groups).to_wire()
    twice = flow.place_in_sections(groups).place_in_sections(groups).to_wire()
    assert once == twice == flow.to_wire()


def test_place_in_sections_moves_a_field_and_drops_the_row_it_emptied() -> None:
    from app.domain.entities.flow_draft import FlowDraft
    from app.domain.value_objects.field_spec import FieldSpec
    from app.domain.value_objects.field_type import FieldType

    bare = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "X", "FlowType": "Process"},
    }
    flow = (
        FlowDraft.from_wire(bare)
        .apply_changes([FieldSpec(name="A", type=FieldType.TEXT)])
        .place_in_sections([("First", ["A"])])
    )
    w1 = flow.to_wire()
    col = next(
        v["Column"]
        for v in w1.values()
        if isinstance(v, dict) and v.get("Kind") == "Field" and v.get("Name") == "A"
    )
    old_row = w1[col]["Row"]
    w2 = flow.place_in_sections([("Second", ["A"])]).to_wire()
    second = next(k for k, v in _sections(w2).items() if v["Name"] == "Second")
    assert w2[w2[col]["Row"]]["Column"] == second
    assert old_row not in w2


def test_place_in_sections_never_reuses_a_live_row_id() -> None:
    """Live regression (2026-09-24): re-adding a field to a section in a later call
    minted the SAME row id as the section's existing row, overwrote it, and orphaned
    the two sibling fields it held."""
    from app.domain.entities._flow_ops import _section_layout
    from app.domain.entities.flow_draft import FlowDraft
    from app.domain.value_objects.field_spec import FieldSpec
    from app.domain.value_objects.field_type import FieldType

    bare = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "X", "FlowType": "Process"},
    }
    specs = [FieldSpec(name=n, type=FieldType.TEXT) for n in ("A", "B", "C")]
    flow = (
        FlowDraft.from_wire(bare)
        .apply_changes(specs)
        .place_in_sections([("Request", ["A", "B", "C"])])
    )
    flow = flow.apply_changes([FieldSpec(name="D", type=FieldType.TEXT)])
    wire = flow.place_in_sections([("Request", ["D"])]).to_wire()
    sec = next(
        k
        for k, v in wire.items()
        if isinstance(v, dict)
        and v.get("Type") == "Section"
        and v.get("Name") == "Request"
    )
    rows = wire[sec]["Column::Row"]
    assert len(rows) == len(set(rows)) == 2
    covered = set(_section_layout(wire).members[sec])
    for name in "ABCD":
        col = next(
            v["Column"]
            for v in wire.values()
            if isinstance(v, dict)
            and v.get("Kind") == "Field"
            and v.get("Name") == name
        )
        assert col in covered, name


def test_apply_changes_never_reuses_a_row_id_from_an_earlier_call() -> None:
    from app.domain.entities.flow_draft import FlowDraft
    from app.domain.value_objects.field_spec import FieldSpec
    from app.domain.value_objects.field_type import FieldType

    bare = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "X", "FlowType": "Process"},
    }
    flow = FlowDraft.from_wire(bare).apply_changes(
        [FieldSpec(name=n, type=FieldType.TEXT) for n in ("A", "B", "C")]
    )
    wire = flow.apply_changes([FieldSpec(name="D", type=FieldType.TEXT)]).to_wire()
    rows = [
        v
        for v in wire.values()
        if isinstance(v, dict) and v.get("Kind") == "Row" and v.get("Column")
    ]
    placed = [c for r in rows for c in r.get("Row::Column", [])]
    cols = [
        v["Column"]
        for v in wire.values()
        if isinstance(v, dict) and v.get("Kind") == "Field"
    ]
    assert sorted(placed) == sorted(cols)
