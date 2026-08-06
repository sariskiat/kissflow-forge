"""Wave-1 unit spec for the offline graph engine. RED until kfforge.graph exists.

Pure + offline: asserts graph.apply_changes builds a valid Kissflow node-graph from a
synthetic fixture. No network, no Kissflow calls, no company data.
"""
import copy
import json
import pathlib

import pytest

# Imports the not-yet-written module -> this is the failing (red) step of TDD.
from kfforge.graph import apply_changes, parse_draft
from kfforge.types import FieldSpec, FieldType

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "form_draft.json"
MODEL_ID = "TestForm_x001"


def _load() -> dict:
    return json.loads(FIXTURE.read_text())


def test_add_field_creates_valid_wired_node():
    draft = _load()
    before = set(draft[MODEL_ID]["Model::Field"])

    new = apply_changes(draft, [FieldSpec(name="Notes", type=FieldType.TEXT, required=False)])

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
    new = apply_changes(_load(), [FieldSpec(name="Notes", type=FieldType.TEXT)])
    fields = parse_draft(new)
    assert any(f.name == "Notes" and f.type == FieldType.TEXT for f in fields)


def test_input_not_mutated():
    draft = _load()
    _ = apply_changes(draft, [FieldSpec(name="Notes", type=FieldType.TEXT)])
    assert draft[MODEL_ID]["Model::Field"] == ["field_fullname_a001"], "apply_changes must not mutate its input"


def test_unknown_type_rejected_before_mutation():
    draft = _load()
    with pytest.raises((ValueError, TypeError, KeyError)):
        bad = FieldSpec(name="Bad", type="Frobnicate")  # invalid type may raise here...
        apply_changes(draft, [bad])                      # ...or here; either way, rejected


def test_bare_process_gets_a_processdef_scaffold() -> None:
    """A bare process draft is unwritable (HTTP 500) until it has a ProcessDef — see FINDINGS.md."""
    from kfforge.graph import ensure_process_def

    bare = {"Root": "M1", "M1": {"Id": "M1", "Kind": "Model", "Name": "P", "FlowType": "Process"}}
    got = ensure_process_def(bare, ("Submit", "Review"))

    pd_id = got["M1"]["RootProcessDef"]
    assert got["M1"]["Model::ProcessDef"] == [pd_id]
    pd = got[pd_id]
    assert pd["Kind"] == "ProcessDef" and pd["WorkflowType"] == "Sequence"

    acts = [got[a] for a in pd["ProcessDef::Activity"]]
    # order IS the workflow: Start, one UserTask per step, Completed
    assert [a["NodeType"] for a in acts] == ["StartEvent", "UserTask", "UserTask", "EndEvent"]
    assert [a["Name"] for a in acts] == ["Start", "Submit", "Review", "Completed"]
    assert all(a["ProcessDef"] == pd_id for a in acts)
    assert "Root" in bare and len(bare) == 2, "input draft must not be mutated"


def test_ensure_process_def_is_idempotent() -> None:
    from kfforge.graph import ensure_process_def

    bare = {"Root": "M1", "M1": {"Id": "M1", "Kind": "Model", "Name": "P", "FlowType": "Process"}}
    once = ensure_process_def(bare, ("Submit",))
    twice = ensure_process_def(once, ("Submit",))
    assert twice == once, "re-scaffolding an existing process must change nothing"


def test_process_needs_at_least_one_step() -> None:
    import pytest

    from kfforge.graph import ensure_process_def

    bare = {"Root": "M1", "M1": {"Id": "M1", "Kind": "Model", "Name": "P", "FlowType": "Process"}}
    with pytest.raises(ValueError):
        ensure_process_def(bare, ())


def test_fields_can_be_added_on_top_of_a_scaffolded_process() -> None:
    from kfforge.graph import apply_changes, ensure_process_def, field_names
    from kfforge.types import FieldSpec, FieldType

    bare = {"Root": "M1", "M1": {"Id": "M1", "Kind": "Model", "Name": "P", "FlowType": "Process"}}
    got = apply_changes(ensure_process_def(bare, ("Submit",)),
                        [FieldSpec(name="Title", type=FieldType.TEXT)])
    assert "Title" in field_names(got)
    assert got["M1"]["RootProcessDef"], "scaffold must survive a field add"


def test_every_flow_gets_an_appearance_node() -> None:
    """Without Model::Appearance the BUILDER renders "There was an error / Reload" (live, 2026-08-03).

    The API accepts and publishes a flow without it, so only the UI catches this — hence the test.
    """
    from kfforge.graph import apply_changes
    from kfforge.types import FieldSpec, FieldType

    bare = {"Root": "M1", "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Form"}}
    got = apply_changes(bare, [FieldSpec(name="A", type=FieldType.TEXT)])

    app_ids = got["M1"]["Model::Appearance"]
    assert len(app_ids) == 1
    appearance = got[app_ids[0]]
    assert appearance["Kind"] == "Appearance" and appearance["Model"] == "M1"
    style = got[appearance["Appearance::Style"][0]]
    assert style["Kind"] == "Style" and style["Appearance"] == app_ids[0]


def test_scaffolded_process_has_appearance_and_button_row() -> None:
    from kfforge.graph import ensure_process_def

    bare = {"Root": "M1", "M1": {"Id": "M1", "Kind": "Model", "Name": "P", "FlowType": "Process"}}
    m = ensure_process_def(bare, ("Submit",))["M1"]
    assert m["Model::Appearance"] and m["Button::Row"], "the builder UI needs both to render"


def test_existing_appearance_is_not_duplicated() -> None:
    from kfforge.graph import apply_changes
    from kfforge.types import FieldSpec, FieldType

    draft = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Form",
               "Model::Appearance": ["Appearance_existing"]},
        "Appearance_existing": {"Id": "Appearance_existing", "Kind": "Appearance", "Model": "M1"},
    }
    got = apply_changes(draft, [FieldSpec(name="A", type=FieldType.TEXT)])
    assert got["M1"]["Model::Appearance"] == ["Appearance_existing"]


def test_columns_tile_the_row_grid_and_never_overflow() -> None:
    """A Row is a 6-unit grid holding 3 field columns. Overflowing it breaks the BUILDER render.

    Regression: 17 columns once landed in ONE Row on a live process, all at Start=0, and the flow
    stopped rendering entirely ("There was an error / Reload").
    """
    from kfforge.graph import FIELD_SPAN, ROW_UNITS, apply_changes
    from kfforge.types import FieldSpec, FieldType

    bare = {"Root": "M1", "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Form"}}
    got = apply_changes(bare, [FieldSpec(name=f"f{i}", type=FieldType.TEXT) for i in range(17)])

    per_row = ROW_UNITS // FIELD_SPAN
    rows = [n for n in got.values() if isinstance(n, dict) and n.get("Kind") == "Row"]
    checked = 0
    for row in rows:
        cols = [got[c] for c in (row.get("Row::Column") or [])]
        if not cols or any(c.get("Type") != "Field" for c in cols):
            continue  # the section's own row carries a single (0,6) Section column
        checked += 1
        assert len(cols) <= per_row, f"row holds {len(cols)} columns, grid fits {per_row}"
        # slots tile the grid edge to edge, no overlaps, no gaps, never past ROW_UNITS
        assert [(c["Start"], c["End"]) for c in cols] == \
               [(i * FIELD_SPAN, (i + 1) * FIELD_SPAN) for i in range(len(cols))]
        assert all(c["End"] <= ROW_UNITS for c in cols)

    field_cols = [n for n in got.values()
                  if isinstance(n, dict) and n.get("Kind") == "Column" and n.get("Type") == "Field"]
    assert len(field_cols) == 17, "every field still gets its own column"
    assert checked >= 6, "17 fields at 3 per row must span at least 6 rows, not pile into one"


def test_field_nodes_carry_the_model_backreference() -> None:
    """Every field Kissflow writes has Model + CreatedAt. Without Model the BUILDER won't render.

    Caught by diffing an API-built process against a UI-built COPY of it (2026-08-03): the API
    accepted and published fields with no Model, so only the builder exposed the defect.
    """
    from kfforge.graph import apply_changes
    from kfforge.types import FieldSpec, FieldType

    bare = {"Root": "M1", "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Form"}}
    got = apply_changes(bare, [FieldSpec(name="A", type=FieldType.TEXT)])
    fields = [n for n in got.values() if isinstance(n, dict) and n.get("Kind") == "Field"]

    assert len(fields) == 1
    assert fields[0]["Model"] == "M1"
    assert fields[0]["CreatedAt"].endswith("Z")
    assert fields[0]["Id"].startswith("Field_"), "Kissflow's own node ids are capitalised"


def test_per_type_defaults_match_what_the_builder_writes() -> None:
    from kfforge.graph import apply_changes
    from kfforge.types import FieldSpec, FieldType

    bare = {"Root": "M1", "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Form"}}
    got = apply_changes(bare, [
        FieldSpec(name="notes", type=FieldType.TEXTAREA),
        FieldSpec(name="amount", type=FieldType.NUMBER),
        FieldSpec(name="file", type=FieldType.ATTACHMENT),
        FieldSpec(name="plain", type=FieldType.TEXT),
    ])
    by_name = {n["Name"]: n for n in got.values()
               if isinstance(n, dict) and n.get("Kind") == "Field"}

    assert by_name["notes"]["AllowFormatting"] is False
    assert by_name["amount"]["DefaultValue"] == "0" and by_name["amount"]["Decimalpoint"] == "2"
    assert by_name["file"]["CaptureOnly"] is False
    # a plain Text field gets no type-specific extras
    assert not {"AllowFormatting", "Decimalpoint", "CaptureOnly"} & set(by_name["plain"])


def _draft_with_fields(*names: str) -> dict:
    d = {"Root": "M1", "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Form"}}
    from kfforge.graph import apply_changes
    from kfforge.types import FieldSpec, FieldType
    return apply_changes(d, [FieldSpec(name=n, type=FieldType.TEXT) for n in names])


def test_regroup_puts_each_field_in_its_named_section() -> None:
    from kfforge.graph import regroup_into_sections

    got = regroup_into_sections(_draft_with_fields("a", "b", "c", "d"),
                                [("Step 1", ["a", "b"]), ("Step 2", ["c", "d"])])

    placed: dict[str, list[str]] = {}
    for top in got["M1"]["Model::Row"]:
        sec = got[got[top]["Row::Column"][0]]
        names = []
        for r in sec["Column::Row"]:
            for c in got[r]["Row::Column"]:
                names += [got[f]["Name"] for f in got[c]["Column::Field"]]
        placed[sec["Name"]] = names

    assert placed == {"Step 1": ["a", "b"], "Step 2": ["c", "d"]}


def test_regroup_never_drops_an_unlisted_field() -> None:
    from kfforge.graph import field_names, regroup_into_sections

    got = regroup_into_sections(_draft_with_fields("a", "b", "orphan"), [("Step 1", ["a", "b"])])
    assert "orphan" in field_names(got)
    sections = [got[got[t]["Row::Column"][0]]["Name"] for t in got["M1"]["Model::Row"]]
    assert "Other" in sections, "unlisted fields must still be laid out somewhere"


def test_regroup_preserves_field_and_column_ids() -> None:
    """Rebuilding layout must not re-mint Field/Column ids — per-step Permissions reference them."""
    from kfforge.graph import regroup_into_sections

    before = _draft_with_fields("a", "b")
    ids = {n["Name"]: (n["Id"], n["Column"]) for n in before.values()
           if isinstance(n, dict) and n.get("Kind") == "Field"}
    after = regroup_into_sections(before, [("S", ["a", "b"])])
    ids2 = {n["Name"]: (n["Id"], n["Column"]) for n in after.values()
            if isinstance(n, dict) and n.get("Kind") == "Field"}
    assert ids == ids2


def test_regroup_still_respects_the_row_grid() -> None:
    from kfforge.graph import FIELD_SPAN, ROW_UNITS, regroup_into_sections

    names = [f"f{i}" for i in range(10)]
    got = regroup_into_sections(_draft_with_fields(*names), [("Big", names)])
    for n in got.values():
        if isinstance(n, dict) and n.get("Kind") == "Row" and n.get("Column"):
            cols = [got[c] for c in n["Row::Column"]]
            assert len(cols) <= ROW_UNITS // FIELD_SPAN
            assert [(c["Start"], c["End"]) for c in cols] == \
                   [(i * FIELD_SPAN, (i + 1) * FIELD_SPAN) for i in range(len(cols))]


def test_build_workflow_sweeps_dangling_permission_backrefs() -> None:
    """Columns hold Column::Permission back-refs. Leaving them dangling breaks PUBLISH.

    Live symptom (a live process, 2026-08-03): draft PUT returned 200, publish returned a bare
    MetadataError, and 6 Columns still referenced deleted Permission nodes.
    """
    from kfforge.graph import build_workflow

    draft = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "P", "FlowType": "Process"},
        "Column_1": {"Id": "Column_1", "Kind": "Column", "Type": "Field",
                     "Column::Field": ["F1"], "Column::Permission": ["Permission_old"]},
        "F1": {"Id": "F1", "Kind": "Field", "Type": "Text", "Name": "a", "Column": "Column_1"},
        "Permission_old": {"Id": "Permission_old", "Kind": "Permission",
                           "Column": "Column_1", "Activity": "Activity_old"},
        "Activity_old": {"Id": "Activity_old", "Kind": "Activity", "NodeType": "UserTask",
                         "Name": "gone", "ProcessDef": "ProcessDef_old"},
        "ProcessDef_old": {"Id": "ProcessDef_old", "Kind": "ProcessDef",
                           "ProcessDef::Activity": ["Activity_old"]},
    }
    got = build_workflow(draft, [("New Step", None)])

    assert "Column::Permission" not in got["Column_1"], "dead back-ref must be swept, not left"
    assert got["F1"]["Column"] == "Column_1", "fields and columns survive a workflow rebuild"

    ids = set(got)
    for node in got.values():
        if not isinstance(node, dict):
            continue
        for key, val in node.items():
            if key == "Id" or not isinstance(val, list):
                continue
            for ref in val:
                if isinstance(ref, str) and ref.split("_")[0] in {"Activity", "ProcessDef",
                                                                  "Resource", "Permission"}:
                    assert ref in ids, f"{node['Id']}.{key} still points at missing {ref}"


def test_sweep_clears_orphans_left_by_an_earlier_partial_write() -> None:
    """Sweeping must key off "target absent", not "I deleted it" — drafts arrive already dirty."""
    from kfforge.graph import build_workflow

    draft = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "P", "FlowType": "Process"},
        # Permission_ghost was deleted by a PREVIOUS run; only the back-ref survived
        "Column_1": {"Id": "Column_1", "Kind": "Column", "Type": "Field",
                     "Column::Field": ["F1"], "Column::Permission": ["Permission_ghost"]},
        "F1": {"Id": "F1", "Kind": "Field", "Type": "Text", "Name": "a", "Column": "Column_1"},
    }
    got = build_workflow(draft, [("Step", None)])
    assert "Column::Permission" not in got["Column_1"]
    assert got["F1"]["Name"] == "a"


# ---- add_goto_task ----------------------------------------------------------------------------
# Node G (P2 server surface) needs a real builder for the GotoTask edge node itself: everything
# else in this module only ever produces a straight-line/parallel chain, and expr.build_goto_gate
# only ATTACHES a condition to an already-existing GotoTask (tests/test_expr.py's own
# draft_with_bare_goto fixture hand-builds one by raw dict surgery for exactly that reason). This
# is that missing builder, shape pinned against shapes/goto_task.json.

def _process_with_review_step() -> tuple[dict, str, str]:
    """A minimal scaffolded process with one real step named "Review". Returns (draft, pd_id,
    review_activity_id)."""
    from kfforge.graph import ensure_process_def

    bare = {"Root": "M1", "M1": {"Id": "M1", "Kind": "Model", "Name": "P", "FlowType": "Process"}}
    draft = ensure_process_def(bare, ("Review",))
    pd_id = draft["M1"]["RootProcessDef"]
    review_id = next(a for a in draft[pd_id]["ProcessDef::Activity"] if draft[a]["Name"] == "Review")
    return draft, pd_id, review_id


def test_add_goto_task_wires_backward_jump_and_backref() -> None:
    from kfforge.graph import add_goto_task

    draft, pd_id, review_id = _process_with_review_step()
    got, goto_id = add_goto_task(draft, target_activity_id=review_id)

    goto = got[goto_id]
    assert goto["Kind"] == "Activity" and goto["NodeType"] == "GotoTask"
    assert goto["Goto"] == review_id
    assert goto["ProcessDef"] == pd_id
    assert goto["Name"] == "Goto-Review", "default name follows the UI convention Goto-<target>"
    assert goto_id in got[review_id]["Goto::Activity"]
    assert goto_id.startswith("Activity_"), "platform-prefixed id, like every node this module mints"
    # carries no Permission-eligible surface of its own (verify.py excludes GotoTask entirely)
    assert "Activity::Permission" not in goto


def test_add_goto_task_sits_before_a_trailing_end_event_not_after() -> None:
    """Live-proven 2026-08-06 (see this function's own docstring correction): a chain ending in
    a real EndEvent must get the GotoTask inserted BEFORE it, not appended strictly last — PUTting
    it strictly last (after the EndEvent too) is REJECTED live with 400 InvalidArguments."""
    from kfforge.graph import add_goto_task

    draft, pd_id, review_id = _process_with_review_step()
    got, goto_id = add_goto_task(draft, target_activity_id=review_id)

    chain = got[pd_id]["ProcessDef::Activity"]
    names = [got[a]["Name"] for a in chain]
    assert names == ["Start", "Review", "Goto-Review", "Completed"], (
        "goto must land last among the REAL activities but BEFORE the terminal EndEvent"
    )
    assert chain[-2] == goto_id, "the SECOND-to-last chain entry must be the goto id itself"
    assert got[chain[-1]]["NodeType"] == "EndEvent", "the EndEvent must stay genuinely last"


def test_add_goto_task_appends_plainly_when_the_chain_has_no_trailing_end_event() -> None:
    """The fallback path — a chain with no EndEvent at all (matches shapes/goto_task.json's own
    minimal 2-activity capture) — still just appends, exactly as originally captured."""
    from kfforge.graph import add_goto_task

    draft = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "P", "FlowType": "Process",
              "RootProcessDef": "PD1", "Model::ProcessDef": ["PD1"]},
        "PD1": {"Id": "PD1", "Kind": "ProcessDef", "WorkflowType": "Sequence",
                "ProcessDef::Activity": ["A1"]},
        "A1": {"Id": "A1", "Kind": "Activity", "NodeType": "UserTask", "Name": "Sample Rework Step",
              "ProcessDef": "PD1"},
    }
    got, goto_id = add_goto_task(draft, target_activity_id="A1")
    assert got["PD1"]["ProcessDef::Activity"] == ["A1", goto_id]


def test_add_goto_task_accepts_an_explicit_name() -> None:
    from kfforge.graph import add_goto_task

    draft, _pd_id, review_id = _process_with_review_step()
    got, goto_id = add_goto_task(draft, target_activity_id=review_id, name="Rework Loop")
    assert got[goto_id]["Name"] == "Rework Loop"


def test_add_goto_task_unknown_activity_rejected() -> None:
    from kfforge.graph import add_goto_task

    draft, _pd_id, _review_id = _process_with_review_step()
    before = copy.deepcopy(draft)
    with pytest.raises(ValueError):
        add_goto_task(draft, target_activity_id="Activity_DoesNotExist99")
    assert draft == before


def test_add_goto_task_input_not_mutated() -> None:
    from kfforge.graph import add_goto_task

    draft, _pd_id, review_id = _process_with_review_step()
    before = copy.deepcopy(draft)
    add_goto_task(draft, target_activity_id=review_id)
    assert draft == before


def test_add_goto_task_is_idempotent_on_rerun() -> None:
    from kfforge.graph import add_goto_task

    draft, pd_id, review_id = _process_with_review_step()
    once, goto_id_1 = add_goto_task(draft, target_activity_id=review_id)
    twice, goto_id_2 = add_goto_task(once, target_activity_id=review_id)

    assert goto_id_1 == goto_id_2, "the id is deterministic on the target, like every id this module mints"
    chain = twice[pd_id]["ProcessDef::Activity"]
    assert chain.count(goto_id_1) == 1, "re-running must not duplicate the GotoTask in the chain"
    assert twice[review_id]["Goto::Activity"].count(goto_id_1) == 1, "back-ref must not duplicate either"


def test_add_goto_task_can_pair_with_build_goto_gate_and_reads_clean() -> None:
    """Integration: add_goto_task + expr.build_goto_gate together produce a loop verify.doctor
    accepts, using a REAL Boolean field and a REAL permission matrix (not raw dict surgery) —
    proving the two builders compose into something the doctor genuinely calls clean. Permissions
    are set BEFORE add_goto_task, matching CLAUDE.md: a loop added to an already-wired flow."""
    from kfforge.expr import build_goto_gate
    from kfforge.graph import (
        add_goto_task,
        apply_changes,
        progressive_matrix,
        set_step_permissions,
    )
    from kfforge.types import FieldSpec, FieldType
    from kfforge.verify import doctor

    draft, _pd_id, review_id = _process_with_review_step()
    draft = apply_changes(draft, [FieldSpec(name="Done Flag", type=FieldType.BOOLEAN)])
    field_id = next(k for k, v in draft.items()
                    if isinstance(v, dict) and v.get("Kind") == "Field" and v.get("Name") == "Done Flag")
    section_name = next(v["Name"] for v in draft.values()
                        if isinstance(v, dict) and v.get("Kind") == "Column" and v.get("Type") == "Section")
    matrix = progressive_matrix(draft, {section_name: ["Start"]})
    draft = set_step_permissions(draft, matrix)

    with_goto, goto_id = add_goto_task(draft, target_activity_id=review_id)
    report_before = doctor(with_goto)
    assert any("NO condition" in p for p in report_before.problems), \
        "a bare goto with no condition must loop forever per verify.doctor's own rule"

    gated = build_goto_gate(with_goto, goto_activity_id=goto_id, field_id=field_id)
    assert doctor(gated).ok(), doctor(gated).problems
