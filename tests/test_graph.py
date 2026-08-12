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

    # Number carries the builder's own defaults; the oracle has them too.
    assert by_name["amount"]["DefaultValue"] == "0" and by_name["amount"]["Decimalpoint"] == "2"
    # Textarea AllowFormatting and Attachment CaptureOnly are OPT-IN now: the UI-built oracle
    # carries neither key on a fresh field, so a default of False was an extra key it did not have.
    assert "AllowFormatting" not in by_name["notes"]
    assert "CaptureOnly" not in by_name["file"]
    # a plain Text field gets no type-specific extras
    assert not {"AllowFormatting", "Decimalpoint", "CaptureOnly"} & set(by_name["plain"])


def test_field_options_pass_through_verbatim_to_the_node() -> None:
    """Opt-in per-type keys (AllowFormatting/CaptureOnly) land on the Field node as given.

    The oracle has TWO Textarea populations: plain ones OMIT AllowFormatting, canvas ones carry
    `AllowFormatting=False`. Default-omit handles the first; opt-in options handle the second.
    """
    from kfforge.graph import apply_changes
    from kfforge.types import FieldSpec, FieldType

    bare = {"Root": "M1", "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Form"}}
    got = apply_changes(bare, [
        FieldSpec(name="canvas", type=FieldType.TEXTAREA, options={"AllowFormatting": False}),
        FieldSpec(name="plain", type=FieldType.TEXTAREA),
        FieldSpec(name="upload", type=FieldType.ATTACHMENT, options={"CaptureOnly": False}),
    ])
    by_name = {n["Name"]: n for n in got.values()
               if isinstance(n, dict) and n.get("Kind") == "Field"}
    assert by_name["canvas"]["AllowFormatting"] is False
    assert "AllowFormatting" not in by_name["plain"]        # default stays omit
    assert by_name["upload"]["CaptureOnly"] is False


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


def test_regroup_creates_an_empty_banner_section_in_place() -> None:
    """An empty `names` group is a banner section (header + description, no fields). It must be
    created (not skipped) and keep its position in `plan`, so a banner placed between two field
    sections lands between them in Model::Row — learned from the golden FDE-Log banner."""
    from kfforge.graph import regroup_into_sections

    got = regroup_into_sections(_draft_with_fields("a", "b"),
                                [("Before", ["a"]), ("Banner", []), ("After", ["b"])])
    sections = [got[got[t]["Row::Column"][0]]["Name"] for t in got["M1"]["Model::Row"]]
    assert sections == ["Before", "Banner", "After"], sections
    banner = got[got[got["M1"]["Model::Row"][1]]["Row::Column"][0]]
    assert banner["Type"] == "Section" and banner["Name"] == "Banner"
    assert banner["Column::Row"] == [], "a banner section has no field rows"


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


def test_apply_exact_layout_places_fields_at_stated_coordinates() -> None:
    """The 'I know where every field goes' API: caller states (Start, End) per field, engine obeys
    exactly — full-width, half, and a lone right-aligned field (the case auto-tile gets wrong)."""
    from kfforge.graph import apply_exact_layout, regroup_into_sections

    base = regroup_into_sections(_draft_with_fields("a", "b", "c", "d"), [("S", ["a", "b", "c", "d"])])
    layout = {"S": [
        [("a", 0, 3), ("b", 3, 6)],   # 2-per-row
        [("c", 0, 6)],                # full-width
        [("d", 3, 6)],                 # lone, right-aligned
    ]}
    got = apply_exact_layout(base, layout)
    sec = next(v for v in got.values() if isinstance(v, dict) and v.get("Type") == "Section")
    col_name = {f["Column"]: f["Name"] for f in got.values()
                if isinstance(f, dict) and f.get("Kind") == "Field"}
    rows = [got[r] for r in sec["Column::Row"]]
    assert len(rows) == 3
    coords = {col_name[c]: (got[c]["Start"], got[c]["End"])
              for r in rows for c in r["Row::Column"]}
    assert coords == {"a": (0, 3), "b": (3, 6), "c": (0, 6), "d": (3, 6)}


def test_apply_exact_layout_preserves_field_and_column_ids() -> None:
    """Like regroup, an exact re-layout must not re-mint ids — Permissions/Events reference them."""
    from kfforge.graph import apply_exact_layout, regroup_into_sections

    before = regroup_into_sections(_draft_with_fields("a", "b"), [("S", ["a", "b"])])
    ids = {n["Name"]: (n["Id"], n["Column"]) for n in before.values()
           if isinstance(n, dict) and n.get("Kind") == "Field"}
    after = apply_exact_layout(before, {"S": [[("a", 0, 3), ("b", 3, 6)]]})
    ids2 = {n["Name"]: (n["Id"], n["Column"]) for n in after.values()
            if isinstance(n, dict) and n.get("Kind") == "Field"}
    assert ids == ids2


def test_apply_exact_layout_keeps_unlisted_fields_in_a_trailing_row() -> None:
    """A partial layout spec never drops a field off the form — leftovers go in a trailing row."""
    from kfforge.graph import apply_exact_layout, regroup_into_sections

    base = regroup_into_sections(_draft_with_fields("a", "b", "c"), [("S", ["a", "b", "c"])])
    got = apply_exact_layout(base, {"S": [[("a", 0, 6)]]})  # b and c not named
    sec = next(v for v in got.values() if isinstance(v, dict) and v.get("Type") == "Section")
    col_name = {f["Column"]: f["Name"] for f in got.values()
                if isinstance(f, dict) and f.get("Kind") == "Field"}
    rows = [got[r] for r in sec["Column::Row"]]
    assert len(rows) == 2                       # the named row + the trailing leftover row
    leftover_names = [col_name[c] for c in rows[1]["Row::Column"]]
    assert sorted(leftover_names) == ["b", "c"]


def test_apply_exact_layout_raises_on_a_field_not_in_the_draft() -> None:
    """Fail loud: a stale layout naming a deleted field must not silently drop it."""
    import pytest
    from kfforge.graph import apply_exact_layout, regroup_into_sections

    base = regroup_into_sections(_draft_with_fields("a"), [("S", ["a"])])
    with pytest.raises(ValueError, match="ghost"):
        apply_exact_layout(base, {"S": [[("ghost", 0, 6)]]})


def test_apply_exact_layout_sets_section_descriptions() -> None:
    """`descriptions` lands a plain string OR a serialized rich-text doc on the section, same write
    as the row rebuild (the builder writes the latter for formatted text; both coexist live)."""
    from kfforge.graph import apply_exact_layout, regroup_into_sections

    base = regroup_into_sections(_draft_with_fields("a"), [("S", ["a"])])
    rich = '[{"type":"paragraph","nodes":[{"type":"bold"}]}]'
    got = apply_exact_layout(base, {"S": [[("a", 0, 6)]]},
                             descriptions={"S": rich})
    sec = next(v for v in got.values() if isinstance(v, dict) and v.get("Type") == "Section")
    assert sec["Description"] == rich


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


# ---- add_goto_task — branch_process_def_id (Node M, conditional routing) ---------------------
# The oracle app's own two GotoTasks each sit LAST within their own branch ProcessDef, targeting an
# early step of that SAME branch (CLAUDE.md Workflow). Before this parameter, the chain that hosts
# a new GotoTask was always DERIVED from the target's own ProcessDef, with no way for a caller to
# say which chain they actually meant — reproduced live 2026-08-07 (node M): a target 2 root steps
# before a 2-branch Parallel landed the GotoTask after the LAST root-chain activity, not scoped to
# either branch. `branch_process_def_id` closes that by PINNING and VALIDATING the intended chain.

def _process_with_parallel_branches() -> tuple[dict, str, str, str]:
    """2 root steps -> a 2-branch Parallel (2 steps each) -> End. Returns (draft, root_pd_id,
    branch_a_pd_id, branch_b_pd_id)."""
    from kfforge.graph import build_workflow

    bare = {"Root": "M1", "M1": {"Id": "M1", "Kind": "Model", "Name": "P", "FlowType": "Process"}}
    draft = build_workflow(
        bare,
        [("Root Step 1", None), ("Root Step 2", None)],
        parallel=("Fork", [
            ("Branch A", [("A1", None), ("A2", None)]),
            ("Branch B", [("B1", None), ("B2", None)]),
        ]),
        parallel_after=1,
    )
    root_pd_id = draft["M1"]["RootProcessDef"]
    branch_a_pd_id = next(v["Id"] for v in draft.values()
                          if isinstance(v, dict) and v.get("Kind") == "ProcessDef"
                          and v.get("Name") == "Branch A")
    branch_b_pd_id = next(v["Id"] for v in draft.values()
                          if isinstance(v, dict) and v.get("Kind") == "ProcessDef"
                          and v.get("Name") == "Branch B")
    return draft, root_pd_id, branch_a_pd_id, branch_b_pd_id


def test_add_goto_task_branch_process_def_id_lands_inside_that_branch_not_root() -> None:
    from kfforge.graph import add_goto_task

    draft, root_pd_id, branch_a_pd_id, _branch_b_pd_id = _process_with_parallel_branches()
    a1_id = next(a for a in draft[branch_a_pd_id]["ProcessDef::Activity"] if draft[a]["Name"] == "A1")

    got, goto_id = add_goto_task(draft, target_activity_id=a1_id, branch_process_def_id=branch_a_pd_id)

    assert got[goto_id]["ProcessDef"] == branch_a_pd_id
    branch_a_chain = got[branch_a_pd_id]["ProcessDef::Activity"]
    assert branch_a_chain[-1] == goto_id, "GotoTask must sit LAST within its own branch"
    assert [got[a]["Name"] for a in branch_a_chain] == ["A1", "A2", "Goto-A1"]
    # the root chain and the sibling branch must be completely untouched
    root_chain_names = [got[a]["Name"] for a in got[root_pd_id]["ProcessDef::Activity"]]
    assert root_chain_names == ["Start", "Root Step 1", "Root Step 2", "Fork", "End"]


def test_add_goto_task_branch_process_def_id_matches_default_when_target_already_in_branch() -> None:
    """Passing the target's OWN branch explicitly must be byte-identical to omitting the param —
    the validation is a no-op when the caller's assumption was already correct."""
    from kfforge.graph import add_goto_task

    draft, _root_pd_id, branch_a_pd_id, _branch_b_pd_id = _process_with_parallel_branches()
    a1_id = next(a for a in draft[branch_a_pd_id]["ProcessDef::Activity"] if draft[a]["Name"] == "A1")

    with_branch, goto_id_1 = add_goto_task(draft, target_activity_id=a1_id,
                                           branch_process_def_id=branch_a_pd_id)
    without_branch, goto_id_2 = add_goto_task(draft, target_activity_id=a1_id)

    assert goto_id_1 == goto_id_2
    assert with_branch == without_branch


def test_add_goto_task_branch_process_def_id_rejects_target_outside_that_branch() -> None:
    """THE reproduced gap: a target OUTSIDE the named branch (here, a shared root-chain step before
    the Parallel) must be a loud, pre-write ValueError — never a silent misplacement into the
    wrong chain (which, for a root-chain target, used to mean landing after the LAST root-chain
    activity, evaluated once for the whole item instead of scoped to one branch)."""
    from kfforge.graph import add_goto_task

    draft, root_pd_id, branch_a_pd_id, _branch_b_pd_id = _process_with_parallel_branches()
    root_step_2_id = next(a for a in draft[root_pd_id]["ProcessDef::Activity"]
                          if draft[a]["Name"] == "Root Step 2")
    before = copy.deepcopy(draft)

    with pytest.raises(ValueError, match="never cross-branch"):
        add_goto_task(draft, target_activity_id=root_step_2_id, branch_process_def_id=branch_a_pd_id)
    assert draft == before


def test_add_goto_task_branch_process_def_id_rejects_target_in_sibling_branch() -> None:
    from kfforge.graph import add_goto_task

    draft, _root_pd_id, branch_a_pd_id, branch_b_pd_id = _process_with_parallel_branches()
    b1_id = next(a for a in draft[branch_b_pd_id]["ProcessDef::Activity"] if draft[a]["Name"] == "B1")
    before = copy.deepcopy(draft)

    with pytest.raises(ValueError):
        add_goto_task(draft, target_activity_id=b1_id, branch_process_def_id=branch_a_pd_id)
    assert draft == before


def test_add_goto_task_branch_process_def_id_rejects_unknown_process_def() -> None:
    from kfforge.graph import add_goto_task

    draft, _root_pd_id, branch_a_pd_id, _branch_b_pd_id = _process_with_parallel_branches()
    a1_id = next(a for a in draft[branch_a_pd_id]["ProcessDef::Activity"] if draft[a]["Name"] == "A1")
    before = copy.deepcopy(draft)

    with pytest.raises(ValueError):
        add_goto_task(draft, target_activity_id=a1_id, branch_process_def_id="ProcessDef_DoesNotExist99")
    assert draft == before


def test_add_goto_task_root_chain_behavior_unchanged_when_a_parallel_also_exists() -> None:
    """A root-chain target with NO branch_process_def_id must still behave exactly like the
    pre-existing (pre-node-M) root-chain tests, even in a draft that ALSO has a Parallel — the new
    parameter must never change default behavior just because branches exist elsewhere."""
    from kfforge.graph import add_goto_task

    draft, root_pd_id, _branch_a_pd_id, _branch_b_pd_id = _process_with_parallel_branches()
    root_step_1_id = next(a for a in draft[root_pd_id]["ProcessDef::Activity"]
                          if draft[a]["Name"] == "Root Step 1")

    got, goto_id = add_goto_task(draft, target_activity_id=root_step_1_id)

    assert got[goto_id]["ProcessDef"] == root_pd_id
    chain = got[root_pd_id]["ProcessDef::Activity"]
    names = [got[a]["Name"] for a in chain]
    # last among the REAL activities, but before the trailing EndEvent — same rule as ever
    assert names == ["Start", "Root Step 1", "Root Step 2", "Fork", "Goto-Root Step 1", "End"]
    assert got[chain[-1]]["NodeType"] == "EndEvent"


# ---- build_workflow — N sequential Parallel gateways (S2, ticket #33) ------------------------
# build_workflow used to support at most one Parallel gateway via `parallel`/`parallel_after`.
# `parallels` generalizes that to a list of `(parallel_spec, after_index)` pairs, and adds an
# explicit branch-name-uniqueness check (a branch id is a hash of (model, kind, index, name), so
# two branches sharing a name would otherwise collide silently).

def test_build_workflow_two_sequential_parallels() -> None:
    from kfforge.graph import build_workflow

    bare = {"Root": "M1", "M1": {"Id": "M1", "Kind": "Model", "Name": "P", "FlowType": "Process"}}
    got = build_workflow(
        bare,
        [("S1", None), ("S2", None)],
        parallels=[
            (("Fork1", [("A", [("A1", None)]), ("B", [("B1", None)])]), 0),
            (("Fork2", [("C", [("C1", None)]), ("D", [("D1", None)])]), 1),
        ],
    )

    root_pd_id = got["M1"]["RootProcessDef"]
    root_chain = got[root_pd_id]["ProcessDef::Activity"]
    root_names = [got[a]["Name"] for a in root_chain]
    assert root_names == ["Start", "S1", "Fork1", "S2", "Fork2", "End"], \
        "Fork1 sits right after S1, Fork2 right after S2 — root chain order preserved"

    parallel_nodes = [n for n in got.values()
                      if isinstance(n, dict) and n.get("Kind") == "Activity"
                      and n.get("NodeType") == "Parallel"]
    assert len(parallel_nodes) == 2, "exactly two Parallel gateway Activities"
    assert [n["Name"] for n in parallel_nodes] == ["Fork1", "Fork2"], \
        "Fork1 before Fork2, matching root ProcessDef::Activity order"

    branch_pds = {n["Name"]: n for n in got.values()
                 if isinstance(n, dict) and n.get("Kind") == "ProcessDef" and n.get("Name") in
                 ("A", "B", "C", "D")}
    assert set(branch_pds) == {"A", "B", "C", "D"}
    assert [got[a]["Name"] for a in branch_pds["A"]["ProcessDef::Activity"]] == ["A1"]
    assert [got[a]["Name"] for a in branch_pds["B"]["ProcessDef::Activity"]] == ["B1"]
    assert [got[a]["Name"] for a in branch_pds["C"]["ProcessDef::Activity"]] == ["C1"]
    assert [got[a]["Name"] for a in branch_pds["D"]["ProcessDef::Activity"]] == ["D1"]

    branch_ids = {n["Id"] for n in branch_pds.values()}
    assert len(branch_ids) == 4, "all four branch ProcessDef ids are distinct"


def test_build_workflow_duplicate_branch_name_across_splits_raises() -> None:
    from kfforge.graph import build_workflow

    bare = {"Root": "M1", "M1": {"Id": "M1", "Kind": "Model", "Name": "P", "FlowType": "Process"}}
    with pytest.raises(ValueError, match="Yes"):
        build_workflow(
            bare,
            [("S1", None), ("S2", None)],
            parallels=[
                (("Fork1", [("Yes", [("A1", None)]), ("No", [("A2", None)])]), 0),
                (("Fork2", [("Yes", [("C1", None)]), ("Maybe", [("D1", None)])]), 1),
            ],
        )


def test_build_workflow_single_parallel_unchanged() -> None:
    """The pre-existing `parallel=`/`parallel_after=` path must produce byte-identical output to
    before — same Parallel count, same branch names/steps, same branch id values (100 + b_i)."""
    draft, root_pd_id, branch_a_pd_id, branch_b_pd_id = _process_with_parallel_branches()

    parallel_nodes = [n for n in draft.values()
                      if isinstance(n, dict) and n.get("Kind") == "Activity"
                      and n.get("NodeType") == "Parallel"]
    assert len(parallel_nodes) == 1
    assert parallel_nodes[0]["Name"] == "Fork"

    root_names = [draft[a]["Name"] for a in draft[root_pd_id]["ProcessDef::Activity"]]
    assert root_names == ["Start", "Root Step 1", "Root Step 2", "Fork", "End"]

    assert [draft[a]["Name"] for a in draft[branch_a_pd_id]["ProcessDef::Activity"]] == \
        ["A1", "A2"]
    assert [draft[a]["Name"] for a in draft[branch_b_pd_id]["ProcessDef::Activity"]] == \
        ["B1", "B2"]
    assert draft[branch_a_pd_id]["Id"] != draft[branch_b_pd_id]["Id"]


def test_build_workflow_parallel_and_parallels_both_given_raises() -> None:
    from kfforge.graph import build_workflow

    bare = {"Root": "M1", "M1": {"Id": "M1", "Kind": "Model", "Name": "P", "FlowType": "Process"}}
    with pytest.raises(ValueError):
        build_workflow(
            bare,
            [("S1", None)],
            parallel=("Fork", [("A", [("A1", None)]), ("B", [("B1", None)])]),
            parallel_after=0,
            parallels=[
                (("Fork2", [("C", [("C1", None)]), ("D", [("D1", None)])]), 0),
            ],
        )


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


def test_field_override_matrix_branch_aware_per_step_rule() -> None:
    """The per-FIELD matrix's branch-aware rule, in one fixture (2 root steps + 2-branch Parallel +
    End). A header field (root-owned, no tail edit) is ReadOnly through the branches; a verdict
    field (root-owned, editable at the tail End) is Hidden through the branch detour; a branch-
    private field is Hidden on the sibling branch and ReadOnly at the tail. This is the load-
    bearing rule a plain editable-list + the section lever gets wrong — the only check left
    behind for this non-trivial logic."""
    from kfforge.graph import apply_changes, field_override_matrix
    from kfforge.types import FieldSpec, FieldType, Visibility

    draft, _root_pd_id, _branch_a_pd_id, _branch_b_pd_id = _process_with_parallel_branches()
    draft = apply_changes(draft, [
        FieldSpec(name="Header", type=FieldType.TEXT),
        FieldSpec(name="Verdict", type=FieldType.TEXT),
        FieldSpec(name="A-only", type=FieldType.TEXT),
    ])

    m = field_override_matrix(draft, {
        "Header": ["Start"],       # root-owned, no tail edit
        "Verdict": ["End"],         # root-owned, editable at tail -> has_tail
        "A-only": ["A1", "A2"],     # branch A only
    })

    def row(fnm: str) -> dict:
        return {draft[a].get("Name"): m[fnm][a] for a in m[fnm]}

    E, R, H = Visibility.EDITABLE, Visibility.READONLY, Visibility.HIDDEN
    # header: Editable at Start, ReadOnly everywhere else, including both branches
    assert row("Header") == {"Start": E, "Root Step 1": R, "Root Step 2": R,
                             "A1": R, "A2": R, "B1": R, "B2": R, "End": R}
    # verdict: Hidden everywhere except Editable at End (a tail edit hides the branch detour)
    assert row("Verdict") == {"Start": H, "Root Step 1": H, "Root Step 2": H,
                              "A1": H, "A2": H, "B1": H, "B2": H, "End": E}
    # A-only: Editable in branch A, Hidden on sibling B and pre-branch root, ReadOnly at the tail
    assert row("A-only") == {"Start": H, "Root Step 1": H, "Root Step 2": H,
                              "A1": E, "A2": E, "B1": H, "B2": H, "End": R}


def test_field_override_matrix_empty_list_is_readonly_everywhere() -> None:
    from kfforge.graph import apply_changes, field_override_matrix
    from kfforge.types import FieldSpec, FieldType, Visibility

    draft, _root, _a, _b = _process_with_parallel_branches()
    draft = apply_changes(draft, [FieldSpec(name="Stamp", type=FieldType.TEXT)])
    m = field_override_matrix(draft, {"Stamp": []})
    assert set(m["Stamp"].values()) == {Visibility.READONLY}


def test_add_table_per_column_options_override_type_defaults() -> None:
    """A table column may carry opt-in options written verbatim (e.g. an integer-only Number
    with Decimalpoint=0, overriding the Number default of "2"). A bare 2-tuple column keeps
    the type default."""
    from kfforge.graph import add_table
    from kfforge.types import FieldType

    bare = {"Root": "M1", "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Form"}}
    got = add_table(bare, "Log", [
        ("Round", FieldType.NUMBER, {"Decimalpoint": 0}),
        ("Hours", FieldType.NUMBER),  # bare 2-tuple -> default Decimalpoint "2"
    ])
    cols = {n["Name"]: n for n in got.values()
            if isinstance(n, dict) and n.get("Kind") == "Field"}
    assert cols["Round"]["Decimalpoint"] == 0       # opt-in overrides the "2" default
    assert cols["Hours"]["Decimalpoint"] == "2"     # default survives untouched


def test_build_workflow_step_meta_writes_suspended_and_description() -> None:
    """step_meta writes IsSuspended+SuspendedAt and Description on the named step; a step not in
    meta gets neither; Start/EndEvent are untouched."""
    from kfforge.graph import build_workflow

    bare = {"Root": "M1", "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Process"}}
    got = build_workflow(
        bare, [("Log it", None), ("Queue", None), ("Decide", None)],
        step_meta={
            "Log it": {"description": "Log the request and who is asking.", "suspended": True},
            "Decide": {"description": "Pick the service level for this case."},
        },
    )
    acts = {n["Name"]: n for n in got.values()
            if isinstance(n, dict) and n.get("Kind") == "Activity" and "Name" in n}
    assert acts["Log it"]["IsSuspended"] is True
    assert "SuspendedAt" in acts["Log it"]
    assert acts["Log it"]["Description"] == "Log the request and who is asking."
    assert acts["Decide"]["Description"] == "Pick the service level for this case."
    assert "IsSuspended" not in acts["Queue"]            # meta absent -> no flag
    assert "Description" not in acts["Queue"]
    assert "IsSuspended" not in acts["Start"]            # Start/End never flagged
    assert "Description" not in acts["End"]


def test_add_sequence_number_builds_field_props_expression_and_hidden_column() -> None:
    """add_sequence_number creates the SequenceNumber Field + hidden Column + own Row + 3
    Property nodes (Padding/Step/PrefixExpression) + Expression + 2 Nodes, stamps the Step at the
    activity resolved by name, and appends the row to the named section. Idempotent."""
    from kfforge.graph import add_sequence_number, apply_changes, build_workflow, regroup_into_sections
    from kfforge.types import FieldSpec, FieldType

    bare = {"Root": "M1", "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Process"}}
    d = apply_changes(bare, [FieldSpec(name="a", type=FieldType.TEXT)])
    d = regroup_into_sections(d, [("S", ["a"])])
    d = build_workflow(d, [("Log it", None)])
    got = add_sequence_number(d, "running number", "S", "PRE-", "0001", "Start", 0, 2)

    start_id = next(n["Id"] for n in got.values()
                   if isinstance(n, dict) and n.get("Kind") == "Activity" and n.get("Name") == "Start")
    fld = next(n for n in got.values()
               if isinstance(n, dict) and n.get("Kind") == "Field" and n.get("Type") == "SequenceNumber")
    assert fld["Name"] == "running number"
    assert fld["Model"] == "M1"
    assert fld["Id"] in got["M1"].get("Model::Field", [])
    assert len(fld["Field::Property"]) == 3

    col = got[fld["Column"]]
    assert col["IsHidden"] is True
    assert (col["Start"], col["End"]) == (0, 2)

    # the section's last row is the sequence-number row, alone
    sec = next(v for v in got.values()
               if isinstance(v, dict) and v.get("Kind") == "Column" and v.get("Type") == "Section"
               and v.get("Name") == "S")
    last_row = got[sec["Column::Row"][-1]]
    assert last_row["Row::Column"] == [col["Id"]]

    props = {got[pid]["Name"]: got[pid] for pid in fld["Field::Property"]}
    assert props["Padding"]["Value"] == "0001"
    assert props["Step"]["Value"] == start_id                       # resolved by NAME
    expr_id = props["PrefixExpression"]["Property::Expression"][0]
    expr = got[expr_id]
    assert expr["ExpressionStr"] == 'concatenate("PRE-")'
    root_node = expr["Expression::Node"][0]
    assert got[root_node]["Value"] == "concatenate"
    lit_node = got[root_node]["Node::Node"][0]
    assert got[lit_node]["Value"] == "PRE-"

    # idempotent: a second add does not duplicate the field
    again = add_sequence_number(got, "running number", "S", "PRE-", "0001", "Start", 0, 2)
    seqs = [n for n in again.values()
            if isinstance(n, dict) and n.get("Type") == "SequenceNumber"]
    assert len(seqs) == 1


def test_add_sequence_number_raises_on_missing_section_and_activity() -> None:
    from kfforge.graph import add_sequence_number, apply_changes, build_workflow, regroup_into_sections
    from kfforge.types import FieldSpec, FieldType
    import pytest

    bare = {"Root": "M1", "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Process"}}
    d = apply_changes(bare, [FieldSpec(name="a", type=FieldType.TEXT)])
    d = regroup_into_sections(d, [("S", ["a"])])
    d = build_workflow(d, [("Log it", None)])
    with pytest.raises(ValueError, match="section"):
        add_sequence_number(d, "rn", "Nope", "P-", "0001", "Start")
    with pytest.raises(ValueError, match="activity"):
        add_sequence_number(d, "rn", "S", "P-", "0001", "Nope")


def test_add_field_validation_builds_criteria_and_condition() -> None:
    """add_field_validation writes Field --FieldValidation::Criteria--> Criteria
    --Criteria::Condition--> Condition{Operator, RHSValue}; idempotent; a second rule appends."""
    from kfforge.graph import add_field_validation, apply_changes
    from kfforge.types import FieldSpec, FieldType

    bare = {"Root": "M1", "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Form"}}
    d = apply_changes(bare, [FieldSpec(name="meeting link", type=FieldType.TEXT)])
    got = add_field_validation(d, "meeting link", "CONTAINS", "microsoft")
    fld = next(n for n in got.values()
               if isinstance(n, dict) and n.get("Kind") == "Field" and n.get("Name") == "meeting link")
    assert len(fld["FieldValidation::Criteria"]) == 1
    crit = got[fld["FieldValidation::Criteria"][0]]
    assert crit["FieldValidation"] == fld["Id"]
    assert len(crit["Criteria::Condition"]) == 1
    cond = got[crit["Criteria::Condition"][0]]
    assert cond["Operator"] == "CONTAINS"
    assert cond["RHSValue"] == "microsoft"
    assert cond["HasArguments"] is True

    # idempotent: same rule twice does not duplicate
    again = add_field_validation(got, "meeting link", "CONTAINS", "microsoft")
    acrit = again[fld["FieldValidation::Criteria"][0]]
    assert len(acrit["Criteria::Condition"]) == 1

    # a second distinct rule appends a Condition to the SAME Criteria
    more = add_field_validation(got, "meeting link", "MAX_LENGTH", "200")
    mcrit = more[fld["FieldValidation::Criteria"][0]]
    assert len(mcrit["Criteria::Condition"]) == 2
    ops = {more[cid]["Operator"] for cid in mcrit["Criteria::Condition"]}
    assert ops == {"CONTAINS", "MAX_LENGTH"}


def test_add_field_validation_raises_on_missing_field() -> None:
    from kfforge.graph import add_field_validation, apply_changes
    from kfforge.types import FieldSpec, FieldType
    import pytest
    bare = {"Root": "M1", "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Form"}}
    d = apply_changes(bare, [FieldSpec(name="a", type=FieldType.TEXT)])
    with pytest.raises(ValueError, match="field not found"):
        add_field_validation(d, "nope", "CONTAINS", "x")


def test_add_table_after_section_places_host_adjacent_to_banner() -> None:
    """#10: a table host must be INSERTABLE right after its banner section's root row in
    Model::Row — appending it last strands the empty banner and the whole form fails to
    render (CLAUDE.md > Tables). after_section names the banner; the host lands at
    index(banner_row) + 1, with later sections after it."""
    from kfforge.graph import add_table, apply_changes, regroup_into_sections
    from kfforge.types import FieldSpec, FieldType

    bare = {"Root": "M1", "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Form"}}
    draft = apply_changes(bare, [FieldSpec(name="A", type=FieldType.TEXT),
                                 FieldSpec(name="B", type=FieldType.TEXT)])
    # banner = empty section between two field sections; table must NOT land after "Tail"
    draft = regroup_into_sections(draft, [("Head", ["A"]), ("Log Banner", []), ("Tail", ["B"])])
    got = add_table(draft, "Log", [("Round", FieldType.NUMBER)], after_section="Log Banner")

    root_rows = got["M1"]["Model::Row"]
    row_label = {}
    for rid in root_rows:
        cols = got[rid].get("Row::Column", [])
        col = got[cols[0]]
        row_label[rid] = (col.get("Type"), col.get("Name"))
    labels = [row_label[r] for r in root_rows]
    assert labels == [("Section", "Head"), ("Section", "Log Banner"),
                      ("Model", "Log"), ("Section", "Tail")]


def test_add_table_after_section_unknown_name_raises() -> None:
    from kfforge.graph import add_table
    from kfforge.types import FieldType
    import pytest

    bare = {"Root": "M1", "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Form"}}
    with pytest.raises(ValueError, match="Nope"):
        add_table(bare, "Log", [("Round", FieldType.NUMBER)], after_section="Nope")


def _three_section_form() -> dict:
    from kfforge.graph import apply_changes, regroup_into_sections
    from kfforge.types import FieldSpec, FieldType

    bare = {"Root": "M1", "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Form"}}
    d = apply_changes(bare, [FieldSpec(name="A", type=FieldType.TEXT),
                             FieldSpec(name="B", type=FieldType.TEXT),
                             FieldSpec(name="C", type=FieldType.TEXT)])
    return regroup_into_sections(d, [("S1", ["A"]), ("S2", ["B"]), ("S3", ["C"])])


def test_set_section_style_full_form_chain_count_is_n_plus_one() -> None:
    """#11: N sections styled + the root Model addressed -> N+1 complete Appearance/Style chains
    (the oracle's 10 = 1 root + 9 sections, expressed here as N, not as 10). Every Appearance owns
    exactly one Style — an empty Appearance::Style breaks the whole form's render (CLAUDE.md)."""
    from kfforge.graph import set_section_style

    got = set_section_style(
        _three_section_form(),
        {name: {"Section.Header.Color": "Color.Secondary.Ten.800"} for name in ("S1", "S2", "S3")},
        root_style={"Form.Field.Color": {"ref": "Color.Primary.500"},
                    "Form.Bg.Color": "Color.Transparent"},
        hint_text_position="Icon",
    )
    apps = {k: v for k, v in got.items() if isinstance(v, dict) and v.get("Kind") == "Appearance"}
    stys = {k: v for k, v in got.items() if isinstance(v, dict) and v.get("Kind") == "Style"}
    assert len(apps) == 4 and len(stys) == 4          # N+1 with N=3
    for a in apps.values():
        assert len(a.get("Appearance::Style") or []) == 1

    root_app_id = (got["M1"].get("Model::Appearance") or [None])[0]
    root_app = got[root_app_id]
    assert root_app["HintTextPosition"] == "Icon"
    root_style = got[root_app["Appearance::Style"][0]]
    # a bare token string wraps as {"ref": ...}; an explicit {"ref"/"value"} dict passes verbatim
    assert root_style["Value"]["Form.Field.Color"] == {"ref": "Color.Primary.500"}
    assert root_style["Value"]["Form.Bg.Color"] == {"ref": "Color.Transparent"}


def test_set_section_style_accepts_explicit_ref_and_value_dicts() -> None:
    """#11: the {"ref": ...} / {"value": ...} shapes pass through verbatim (the old bare-string
    type rejected them at the tool boundary, so styles never landed at all)."""
    from kfforge.graph import set_section_style

    got = set_section_style(_three_section_form(),
                            {"S1": {"Section.Bg.Color": {"value": "#112233"}}})
    sec = next(v for v in got.values()
               if isinstance(v, dict) and v.get("Type") == "Section" and v.get("Name") == "S1")
    style = got[got[sec["Column::Appearance"][0]]["Appearance::Style"][0]]
    assert style["Value"]["Section.Bg.Color"] == {"value": "#112233"}


def test_set_section_style_rejects_unknown_dict_shape() -> None:
    from kfforge.graph import set_section_style
    import pytest

    with pytest.raises(ValueError, match="ref"):
        set_section_style(_three_section_form(), {"S1": {"Section.Bg.Color": {"nope": "x"}}})


def test_build_workflow_repoints_dangling_sequence_step_stamp() -> None:
    """#18: a SequenceNumber's Step Property holds a SCALAR activity id, which the list-only
    dangling sweep never touches — after a workflow rebuild that shifts the stamped step's
    position it pointed at a deleted Activity, and publish 500'd MetadataError deterministically
    (isolated live 2026-08-12 by subsystem bisect + a one-key surgical fix). build_workflow must
    repoint the stamp at the rebuilt activity of the SAME NAME (StartEvent when the name is
    gone), never leave the scalar dangling."""
    from kfforge.graph import add_sequence_number, apply_changes, build_workflow, regroup_into_sections
    from kfforge.types import FieldSpec, FieldType

    bare = {"Root": "M1", "M1": {"Id": "M1", "Kind": "Model", "Name": "P", "FlowType": "Process"}}
    d = apply_changes(bare, [FieldSpec(name="A", type=FieldType.TEXT)])
    d = regroup_into_sections(d, [("Intake", ["A"])])
    d = build_workflow(d, [("Review", None)])
    d = add_sequence_number(d, "Case ID", "Intake", "CASE-", "0001", "Review")
    # rebuild with Review at a NEW position -> new hashed id -> the old stamp target is deleted
    d = build_workflow(d, [("Triage", None), ("Review", None)])

    step = next(v for v in d.values()
                if isinstance(v, dict) and v.get("Kind") == "Property" and v.get("Name") == "Step")
    target = d.get(step.get("Value"))
    assert target is not None, "Step stamp points at a deleted Activity — the publish-500 shape"
    assert target.get("Name") == "Review", "same-name repoint keeps the intended stamp step"

    # name gone entirely -> fall back to the StartEvent, still never dangling
    d2 = build_workflow(d, [("Totally Different", None)])
    step2 = next(v for v in d2.values()
                 if isinstance(v, dict) and v.get("Kind") == "Property" and v.get("Name") == "Step")
    target2 = d2.get(step2.get("Value"))
    assert target2 is not None
    assert target2.get("NodeType") == "StartEvent"
