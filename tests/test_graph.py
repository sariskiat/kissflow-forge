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


def test_user_field_gets_a_querydefinition_sibling():
    """A bare Field{Type:"User"} blocks publish (KISSFLOW_ERROR_04211, #59). apply_changes must
    mint the sibling QueryDefinition and cross-link it, so the batch publishes."""
    new = apply_changes(_load(), [FieldSpec(name="Assigned To", type=FieldType.USER)])
    fid = next(k for k, v in new.items()
               if isinstance(v, dict) and v.get("Type") == "User")
    field = new[fid]
    qids = field["Field::QueryDefinition"]
    assert len(qids) == 1
    qd = new[qids[0]]
    assert qd["Kind"] == "QueryDefinition"
    assert qd["FlowType"] == "User" and qd["LHSModel"] == "User"
    assert qd["Field"] == fid          # back-ref points home
    assert "LHSModel" not in field     # LHSModel belongs on the QueryDefinition, not the Field


def test_user_field_lhsmodel_override_lands_on_the_querydefinition():
    new = apply_changes(_load(), [FieldSpec(
        name="Employee", type=FieldType.USER, options={"LHSModel": "_employee"})])
    fid = next(k for k, v in new.items()
               if isinstance(v, dict) and v.get("Type") == "User")
    qd = new[new[fid]["Field::QueryDefinition"][0]]
    assert qd["LHSModel"] == "_employee"
    assert "LHSModel" not in new[fid]


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


# ---- clone_template_shell (issue #59 — process-template identity/initiate shell) -------------

def _bare_process() -> dict:
    return {"Root": "M1", "M1": {"Id": "M1", "Kind": "Model", "Name": "P", "FlowType": "Process"}}


def test_clone_template_shell_grafts_identity_fields_and_manager_approve() -> None:
    from kfforge.graph import clone_template_shell

    got = clone_template_shell(_bare_process())
    m = got["M1"]

    assert m["RootProcessDef"], "clone must scaffold a real ProcessDef, same contract as ensure_process_def"
    field_ids = m.get("Model::Field", [])
    assert len(field_ids) == 28, "the identity/initiate shell carries 28 fields"
    names = {got[fid]["Name"] for fid in field_ids}
    assert "Manager Display Name" in names
    # "Branch" is a BARE name now. It used to ship as "Branch (TODO: was a Reference field ...)" —
    # a developer note published as a user-facing label on every from_template=True process. The
    # reconnect notes live in the shape's own `notes`; verify.doctor rule 7c flags any that come
    # back.
    assert "Branch" in names
    assert not any("TODO:" in n for n in names), sorted(n for n in names if "TODO:" in n)

    pd = got[m["RootProcessDef"]]
    acts = [got[a] for a in pd["ProcessDef::Activity"]]
    assert [a["NodeType"] for a in acts] == ["StartEvent", "UserTask", "EndEvent"]
    assert acts[1]["Name"] == "Manager Approve"


def test_clone_template_shell_has_a_complete_style_chain() -> None:
    from kfforge.graph import clone_template_shell

    got = clone_template_shell(_bare_process())
    m = got["M1"]
    app_ids = m["Model::Appearance"]
    assert len(app_ids) == 1
    appearance = got[app_ids[0]]
    assert appearance["Kind"] == "Appearance" and appearance["Model"] == "M1"
    style_ids = appearance["Appearance::Style"]
    assert len(style_ids) == 1, "an EMPTY Appearance::Style breaks render just as badly as a missing chain"
    style = got[style_ids[0]]
    assert style["Kind"] == "Style" and style["Appearance"] == app_ids[0]
    assert m["Button::Row"], "the builder UI needs Button::Row too"


def test_clone_template_shell_is_idempotent() -> None:
    from kfforge.graph import clone_template_shell

    once = clone_template_shell(_bare_process())
    twice = clone_template_shell(once)
    assert twice == once, "re-cloning onto an already-scaffolded process must change nothing"


def test_clone_template_shell_does_not_mutate_input() -> None:
    from kfforge.graph import clone_template_shell

    bare = _bare_process()
    _ = clone_template_shell(bare)
    assert bare == {"Root": "M1", "M1": {"Id": "M1", "Kind": "Model", "Name": "P", "FlowType": "Process"}}


def test_two_independent_clones_never_collide_ids() -> None:
    from kfforge.graph import clone_template_shell

    a = clone_template_shell(_bare_process())
    b = clone_template_shell(_bare_process())
    overlap = (set(a) & set(b)) - {"Root", "M1"}
    assert not overlap, f"two from_template clones minted colliding ids: {overlap}"


def test_clone_template_shell_missing_template_file_raises() -> None:
    from kfforge.graph import clone_template_shell

    with pytest.raises(ValueError):
        clone_template_shell(_bare_process(), template_path="/no/such/file.json")


def test_clone_template_shell_env_var_override(monkeypatch, tmp_path) -> None:
    from kfforge.graph import clone_template_shell

    custom = tmp_path / "tiny_template.json"
    custom.write_text(json.dumps({
        "kind": "Model", "description": "d", "source_capture": "x.json", "notes": [],
        "template": {
            "Model_Sample01": {"Id": "Model_Sample01", "Kind": "Model", "Model::Row": [],
                               "Model::Field": ["Field_Sample01"], "Model::ProcessDef": ["ProcessDef_Sample01"],
                               "RootProcessDef": "ProcessDef_Sample01", "Button::Row": []},
            "Field_Sample01": {"Id": "Field_Sample01", "Kind": "Field", "Type": "Text",
                               "Model": "Model_Sample01", "Name": "Tiny Field"},
            "ProcessDef_Sample01": {"Id": "ProcessDef_Sample01", "Kind": "ProcessDef",
                                    "WorkflowType": "Sequence", "Model": "Model_Sample01",
                                    "ProcessDef::Activity": ["Activity_Sample01"]},
            "Activity_Sample01": {"Id": "Activity_Sample01", "Kind": "Activity", "NodeType": "StartEvent",
                                  "Name": "Start", "ProcessDef": "ProcessDef_Sample01"},
        },
    }))
    monkeypatch.setenv("KF_PROCESS_TEMPLATE", str(custom))
    got = clone_template_shell(_bare_process())
    m = got["M1"]
    assert len(m["Model::Field"]) == 1
    assert got[m["Model::Field"][0]]["Name"] == "Tiny Field"


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


def test_apply_exact_layout_detaches_a_field_pulled_from_an_unnamed_section() -> None:
    """A field whose current section is NOT named in the layout must leave its old row behind:
    keeping the column listed in both the old section's row and the new one is the
    one-column-two-rows corruption doctor rule 8b exists to flag."""
    from kfforge.graph import apply_exact_layout, regroup_into_sections

    base = regroup_into_sections(_draft_with_fields("a", "b"), [("A", ["a"]), ("B", ["b"])])
    got = apply_exact_layout(base, {"B": [[("a", 0, 3), ("b", 3, 6)]]})

    owners: dict[str, list[str]] = {}
    for rid, node in got.items():
        if isinstance(node, dict) and node.get("Kind") == "Row":
            for cid in node.get("Row::Column") or []:
                owners.setdefault(cid, []).append(rid)
    assert all(len(rows) == 1 for rows in owners.values()), (
        f"a column is listed by more than one row: {owners}"
    )
    sec_a = next(v for v in got.values()
                 if isinstance(v, dict) and v.get("Type") == "Section" and v.get("Name") == "A")
    for rid in sec_a.get("Column::Row") or []:
        assert rid in got, f"section A lists a row that no longer exists: {rid}"
        assert got[rid].get("Row::Column"), f"section A keeps an emptied row: {rid}"


def _section_rows(draft: dict, section_name: str = "S") -> list[list[tuple[str, int, int]]]:
    """One inner list per Row of the named section: `(field name, Start, End)` in row order.

    Reads the ROW nodes' own `Row::Column` lists, never the draft's dict insertion order — the
    latter is stable regardless and hides an unordered leftover pack completely.
    """
    sec = next(v for v in draft.values() if isinstance(v, dict)
               and v.get("Type") == "Section" and v.get("Name") == section_name)
    col_name = {f["Column"]: f["Name"] for f in draft.values()
                if isinstance(f, dict) and f.get("Kind") == "Field"}
    return [[(col_name[c], draft[c]["Start"], draft[c]["End"])
             for c in draft[rid]["Row::Column"]]
            for rid in sec["Column::Row"]]


def test_apply_exact_layout_keeps_unlisted_fields_in_a_trailing_row() -> None:
    """A partial layout spec never drops a field off the form — leftovers go in a trailing row,
    in the section's pre-existing order, tiled on the grid (not merely 'present in some order')."""
    from kfforge.graph import apply_exact_layout, regroup_into_sections

    base = regroup_into_sections(_draft_with_fields("a", "b", "c"), [("S", ["a", "b", "c"])])
    got = apply_exact_layout(base, {"S": [[("a", 0, 6)]]})  # b and c not named
    assert _section_rows(got) == [
        [("a", 0, 6)],
        [("b", 0, 2), ("c", 2, 4)],             # the trailing leftover row, in the order they sat
    ]


def test_apply_exact_layout_leftovers_never_run_off_the_grid() -> None:
    """#F1: a partial layout is the DOCUMENTED usage, and 5 leftovers used to run off the end.

    The old packer added FIELD_SPAN per leftover with no cap, emitting a column at (6,8) — one
    past the 6-unit row — and then one at (8,6) with End < Start. Either breaks rendering for the
    WHOLE flow (CLAUDE.md > Node-graph invariants), from the normal path, on 6 ordinary fields.
    """
    from kfforge.graph import ROW_UNITS, apply_exact_layout, regroup_into_sections

    names = ["Ticket No", "Contact Date", "Problem", "Unit Serial", "Urgency", "Outcome"]
    base = regroup_into_sections(_draft_with_fields(*names), [("Big", names)])
    got = apply_exact_layout(base, {"Big": [[("Ticket No", 0, ROW_UNITS)]]})

    rows = _section_rows(got, "Big")
    assert rows == [
        [("Ticket No", 0, 6)],
        [("Contact Date", 0, 2), ("Problem", 2, 4), ("Unit Serial", 4, 6)],
        [("Urgency", 0, 2), ("Outcome", 2, 4)],
    ]
    for row in rows:                             # the invariant itself, stated independently
        assert len(row) <= 3
        for name, start, end in row:
            assert 0 <= start < end <= ROW_UNITS, (name, start, end)


def test_apply_exact_layout_leftover_order_is_deterministic() -> None:
    """The leftovers used to be read out of a `set[str]`, and Python randomizes string hashing per
    process — the SAME input produced a different field order on every run. The order must be the
    section's own pre-existing row/column order: the order the user already sees on the form."""
    from kfforge.graph import apply_exact_layout, regroup_into_sections

    names = ["Ticket No", "Contact Date", "Problem", "Unit Serial", "Urgency", "Outcome"]
    base = regroup_into_sections(_draft_with_fields(*names), [("Big", names)])
    spec = {"Big": [[("Ticket No", 0, 6)]]}

    runs = [_section_rows(apply_exact_layout(base, spec), "Big") for _ in range(8)]
    assert all(r == runs[0] for r in runs), runs

    leftover_order = [n for row in runs[0][1:] for n, _, _ in row]
    assert leftover_order == names[1:], "leftovers must keep the section's existing field order"


def test_apply_exact_layout_leftover_order_survives_a_different_hash_seed() -> None:
    """The set-iteration bug is invisible within one process — hashing is randomized per PROCESS.
    Run the same input under two different PYTHONHASHSEEDs and demand the same field order."""
    import os
    import subprocess
    import sys

    src = (
        "import json,sys;"
        "sys.path.insert(0, %r);"
        "from kfforge.graph import apply_changes, apply_exact_layout, regroup_into_sections;"
        "from kfforge.types import FieldSpec, FieldType;"
        "names=['Ticket No','Contact Date','Problem','Unit Serial','Urgency','Outcome'];"
        "d={'Root':'M1','M1':{'Id':'M1','Kind':'Model','Name':'F','FlowType':'Form'}};"
        "d=apply_changes(d,[FieldSpec(name=n,type=FieldType.TEXT) for n in names]);"
        "d=regroup_into_sections(d,[('Big',names)]);"
        "g=apply_exact_layout(d,{'Big':[[('Ticket No',0,6)]]});"
        "sec=next(v for v in g.values() if isinstance(v,dict) and v.get('Type')=='Section');"
        "cn={f['Column']:f['Name'] for f in g.values() "
        "    if isinstance(f,dict) and f.get('Kind')=='Field'};"
        "print(json.dumps([[cn[c] for c in g[r]['Row::Column']] for r in sec['Column::Row']]))"
    ) % str(pathlib.Path(__file__).resolve().parent.parent)

    outs = []
    for seed in ("1", "424242"):
        env = {**os.environ, "PYTHONHASHSEED": seed}
        outs.append(subprocess.run([sys.executable, "-c", src], check=True, env=env,
                                   capture_output=True, text=True).stdout.strip())
    assert outs[0] == outs[1], outs
    assert json.loads(outs[0]) == [
        ["Ticket No"], ["Contact Date", "Problem", "Unit Serial"], ["Urgency", "Outcome"]]


def test_apply_exact_layout_rejects_a_span_off_the_end_of_the_grid() -> None:
    """A Row is a 6-unit grid; End past it breaks rendering for the whole flow. Refuse it."""
    import pytest
    from kfforge.graph import apply_exact_layout, regroup_into_sections

    base = regroup_into_sections(_draft_with_fields("a", "b"), [("S", ["a", "b"])])
    with pytest.raises(ValueError, match=r"'a'.*Start=0, End=99.*6-unit"):
        apply_exact_layout(base, {"S": [[("a", 0, 99)]]})


def test_apply_exact_layout_rejects_a_negative_start() -> None:
    import pytest
    from kfforge.graph import apply_exact_layout, regroup_into_sections

    base = regroup_into_sections(_draft_with_fields("a"), [("S", ["a"])])
    with pytest.raises(ValueError, match=r"'a'.*Start=-1"):
        apply_exact_layout(base, {"S": [[("a", -1, 2)]]})


def test_apply_exact_layout_rejects_an_inverted_span() -> None:
    """End <= Start is the shape the old leftover packer emitted itself, e.g. (8, 6)."""
    import pytest
    from kfforge.graph import apply_exact_layout, regroup_into_sections

    base = regroup_into_sections(_draft_with_fields("a"), [("S", ["a"])])
    with pytest.raises(ValueError, match=r"'a'.*Start=4, End=2"):
        apply_exact_layout(base, {"S": [[("a", 4, 2)]]})

    with pytest.raises(ValueError, match=r"'a'.*Start=2, End=2"):   # zero-width is equally illegal
        apply_exact_layout(base, {"S": [[("a", 2, 2)]]})


def test_apply_exact_layout_rejects_two_overlapping_spans_in_one_row() -> None:
    """Two columns cannot share a unit — the same overflow class, stated per-row."""
    import pytest
    from kfforge.graph import apply_exact_layout, regroup_into_sections

    base = regroup_into_sections(_draft_with_fields("a", "b"), [("S", ["a", "b"])])
    with pytest.raises(ValueError, match=r"overlaps 'b'.*with 'a'"):
        apply_exact_layout(base, {"S": [[("a", 0, 4), ("b", 2, 6)]]})

    # the SAME two spans on two different rows are perfectly legal
    ok = apply_exact_layout(base, {"S": [[("a", 0, 4)], [("b", 2, 6)]]})
    assert _section_rows(ok) == [[("a", 0, 4)], [("b", 2, 6)]]


def test_apply_exact_layout_rejects_the_same_field_placed_twice() -> None:
    """D8(a): a Column belongs to exactly ONE Row. Naming a field twice used to be accepted, and
    the draft it produced had one Column in two Rows' `Row::Column` while the Column's own `Row`
    back-ref named only the last — a corruption the doctor's geometry rule cannot see, because it
    groups BY that back-ref and the duplicate shows up once per group."""
    import pytest
    from kfforge.graph import apply_exact_layout, regroup_into_sections

    base = regroup_into_sections(_draft_with_fields("a", "b"), [("S", ["a", "b"])])
    with pytest.raises(ValueError, match=r"'a'.*twice"):
        apply_exact_layout(base, {"S": [[("a", 0, 6)], [("a", 0, 6)]]})


def test_apply_exact_layout_rejects_the_same_field_placed_in_two_sections() -> None:
    """The duplicate is illegal across the WHOLE spec, not just within one row: a field has one
    Column, so two sections claiming it is the same one-column-two-rows corruption."""
    import pytest
    from kfforge.graph import apply_exact_layout, regroup_into_sections

    base = regroup_into_sections(_draft_with_fields("a", "b"), [("S1", ["a"]), ("S2", ["b"])])
    with pytest.raises(ValueError, match=r"'a'.*twice"):
        apply_exact_layout(base, {"S1": [[("a", 0, 6)]], "S2": [[("a", 0, 6)]]})


def _prod_capture_widest_row() -> list[tuple[int, int]]:
    """The (Start, End) spans of the WIDEST row in shapes/process_template_identity_shell.json —
    read out of the shape file itself so this test can never drift from the capture it cites."""
    import json as _json
    import pathlib as _pathlib

    shape = _json.loads(
        (_pathlib.Path(__file__).parent.parent / "shapes"
         / "process_template_identity_shell.json").read_text(encoding="utf-8"))["template"]
    rows = [[(shape[c]["Start"], shape[c]["End"]) for c in v.get("Row::Column") or []
             if shape.get(c, {}).get("Type") == "Field"]
            for v in shape.values() if isinstance(v, dict) and v.get("Kind") == "Row"]
    return max(rows, key=len)


def test_layout_guard_accepts_the_four_column_row_the_prod_capture_proves() -> None:
    """G3, replacing a refusal the repo has a capture AGAINST (doctrine #10). The write guard used
    to cap a caller-stated row at 3 columns, calling a 4th "render-breaking" — but
    shapes/process_template_identity_shell.json, de-identified off a REAL PUBLISHED production
    template, carries exactly that geometry ((0,2) (2,4) (4,5) (5,6)) and renders. `verify.doctor`
    already refused to assert a count bound for that reason; the WRITE guard asserting the
    opposite was the same repo contradicting itself. What stays enforced is what the capture
    actually backs: in-grid, disjoint, one column to one Row."""
    from kfforge.graph import apply_exact_layout, regroup_into_sections, validate_layout_spans

    spans = _prod_capture_widest_row()
    assert len(spans) >= 4, "fixture drift: the shipped shell no longer has its 4-column row"

    names = [f"f{i}" for i in range(len(spans))]
    row = [(n, s, e) for n, (s, e) in zip(names, spans, strict=True)]
    validate_layout_spans({"S": [row]})                       # pure guard: must not raise

    base = regroup_into_sections(_draft_with_fields(*names), [("S", names)])
    got = apply_exact_layout(base, {"S": [row]})
    assert _section_rows(got)[0] == row, "the production geometry must land verbatim"


def test_layout_guard_still_refuses_what_the_capture_does_back() -> None:
    """The count bound is gone; the capture-backed invariants are NOT. Six 1-unit columns are fine
    (in-grid, disjoint, that is the whole rule), an overlap is refused, and off-grid is refused."""
    import pytest
    from kfforge.graph import validate_layout_spans

    names = [f"f{i}" for i in range(6)]
    validate_layout_spans({"S": [[(n, i, i + 1) for i, n in enumerate(names)]]})

    with pytest.raises(ValueError, match="disjoint"):
        validate_layout_spans({"S": [[("a", 0, 4), ("b", 2, 6)]]})
    with pytest.raises(ValueError, match=r"0 <= Start < End <= 6"):
        validate_layout_spans({"S": [[("a", 0, 7)]]})


def test_apply_exact_layout_rejects_a_bad_span_before_touching_the_draft() -> None:
    """Pure-function discipline: a rejected spec leaves the draft byte-identical — the validation
    runs before the deepcopy, so a later section's bad row cannot half-apply an earlier one."""
    import copy as _copy

    import pytest
    from kfforge.graph import apply_exact_layout, regroup_into_sections

    base = regroup_into_sections(_draft_with_fields("a", "b"), [("S1", ["a"]), ("S2", ["b"])])
    snapshot = _copy.deepcopy(base)
    with pytest.raises(ValueError, match="S2"):
        apply_exact_layout(base, {"S1": [[("a", 0, 6)]], "S2": [[("b", 0, 7)]]})
    assert base == snapshot


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


def test_add_goto_task_branch_process_def_id_matches_default_when_target_already_in_branch(
    monkeypatch,
) -> None:
    """Passing the target's OWN branch explicitly must be byte-identical to omitting the param —
    the validation is a no-op when the caller's assumption was already correct."""
    from kfforge import graph as graph_mod
    from kfforge.graph import add_goto_task

    # Freeze _now: the two add_goto_task calls below each stamp CreatedAt from a LIVE millisecond
    # clock, so straddling a ms boundary would make them differ on that one incidental key (~3%
    # of runs) — nothing to do with the branch-resolution logic this test actually asserts.
    monkeypatch.setattr(graph_mod, "_now", lambda: "2026-08-12T00:00:00.000Z")

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
    # A real step needs an assignee or doctor (correctly) flags it as a submit-500 — wire one so
    # this assertion tests the goto/gate loop, not the separately-covered assignee rule.
    draft["Resource_ReviewAssignee"] = {
        "Id": "Resource_ReviewAssignee", "Kind": "Resource", "ValueType": "AppRole",
        "Value": "Role_Test", "Activity": review_id}
    draft[review_id]["Activity::Resource"] = ["Resource_ReviewAssignee"]
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


# ---- add_table: the SECOND door onto the bare-Select publish-500 -------------------------------

def test_add_table_refuses_a_select_child_with_no_referred_list() -> None:
    """G1. `apply_changes` refuses a bare Select (the 2026-08-19 publish-500 diagnosis), and
    `add_table` minted the byte-identical `Field{Type:"Select"}` with no `ReferredList` and no
    complaint — the same deterministic publish-500 through a second door, on a flow
    `forge_add_table` had just built and `verify.doctor` would then flag. ONE rule, both doors:
    the refusal reuses apply_changes' own predicate rather than a second copy that can drift."""
    import pytest
    from kfforge.graph import add_table

    bare = {"Root": "M1", "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Form"}}
    with pytest.raises(ValueError) as exc:
        add_table(bare, "Items", [("Item", "Text", None), ("Grade", "Select", None)])

    msg = str(exc.value)
    assert "'Grade'" in msg, msg                      # NAME the offending child column
    assert "ReferredList" in msg, msg
    # and show the escape hatch that already exists but was named nowhere
    assert "'Grade', 'Select', {'ReferredList':" in msg, msg


def test_add_table_writes_a_select_child_that_names_its_list() -> None:
    """The escape hatch the refusal points at: the child-spec `options` dict already passes
    `ReferredList` through verbatim — a wired table-child Select is legal and unchanged."""
    from kfforge.graph import add_table

    bare = {"Root": "M1", "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Form"}}
    got = add_table(bare, "Items", [("Item", "Text", None),
                                    ("Grade", "Select", {"ReferredList": "List_G1"})])
    (grade,) = [n for n in got.values()
                if isinstance(n, dict) and n.get("Kind") == "Field" and n.get("Name") == "Grade"]
    assert grade["Type"] == "Select" and grade["ReferredList"] == "List_G1"


def test_add_table_refuses_the_bad_child_before_writing_any_node() -> None:
    """Validation-first, exactly like apply_changes: a table whose LAST column is a bare Select
    must leave the caller's draft byte-identical — a refused spec writes nothing at all."""
    import copy as _copy

    import pytest
    from kfforge.graph import add_table

    draft = {"Root": "M1", "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Form"}}
    snapshot = _copy.deepcopy(draft)
    with pytest.raises(ValueError, match="'Grade'"):
        add_table(draft, "Items", [("Item", "Text", None), ("Grade", "Select", None)])
    assert draft == snapshot


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


def test_add_field_validation_writes_error_message_when_given() -> None:
    """#48/#55: ErrorMessage is a real per-Condition key the platform writes — closes the gap
    docs/capabilities/config.validation.md flags on the engine's own docstring."""
    from kfforge.graph import add_field_validation, apply_changes
    from kfforge.types import FieldSpec, FieldType

    bare = {"Root": "M1", "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Form"}}
    d = apply_changes(bare, [FieldSpec(name="Notes", type=FieldType.TEXT)])
    got = add_field_validation(d, "Notes", "MAX_LENGTH", "10",
                               error_message="Maximum length is 10 characters")
    fld = next(n for n in got.values()
              if isinstance(n, dict) and n.get("Kind") == "Field" and n.get("Name") == "Notes")
    crit = got[fld["FieldValidation::Criteria"][0]]
    cond = got[crit["Criteria::Condition"][0]]
    assert cond["ErrorMessage"] == "Maximum length is 10 characters"

    # omitted -> the key is simply absent, never written as None
    without = add_field_validation(d, "Notes", "CONTAINS", "x")
    fld2 = next(n for n in without.values()
               if isinstance(n, dict) and n.get("Kind") == "Field" and n.get("Name") == "Notes")
    crit2 = without[fld2["FieldValidation::Criteria"][0]]
    cond2 = next(without[cid] for cid in crit2["Criteria::Condition"]
                if without[cid]["Operator"] == "CONTAINS")
    assert "ErrorMessage" not in cond2


def test_set_field_computed_builds_function_ast_with_field_and_static_args() -> None:
    """#48/#55: the FOURTH Expression owner — Field itself — for a computed formula. Root
    Function node carries NO Syntax key (a prefix call, unlike a branch/goto '=' infix root)."""
    from kfforge.graph import apply_changes, set_field_computed
    from kfforge.types import FieldSpec, FieldType

    bare = {"Root": "M1", "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Process"}}
    d = apply_changes(bare, [FieldSpec(name="Computed Sample", type=FieldType.TEXT),
                             FieldSpec(name="Source Number", type=FieldType.NUMBER)])
    formula = {"fn": "concatenate", "args": [{"static": "BR-"}, {"field": "Source Number"}]}
    got = set_field_computed(d, "Computed Sample", formula)

    fld = next(n for n in got.values()
              if isinstance(n, dict) and n.get("Kind") == "Field" and n.get("Name") == "Computed Sample")
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

    src = next(n for n in got.values()
              if isinstance(n, dict) and n.get("Kind") == "Field" and n.get("Name") == "Source Number")
    field_node = next(got[c] for c in root["Node::Node"] if got[c]["Type"] == "Field")
    assert field_node["Field"] == src["Id"]
    assert field_node["Id"] in src.get("Field::Node", [])

    # idempotent-ish: a second call REPLACES the expression, never accumulates a second one
    again = set_field_computed(got, "Computed Sample", formula)
    fld2 = next(n for n in again.values()
               if isinstance(n, dict) and n.get("Kind") == "Field" and n.get("Name") == "Computed Sample")
    assert len(fld2["Field::Expression"]) == 1


def test_set_field_computed_raises_on_missing_field_refs() -> None:
    from kfforge.graph import apply_changes, set_field_computed
    from kfforge.types import FieldSpec, FieldType
    import pytest

    bare = {"Root": "M1", "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Process"}}
    d = apply_changes(bare, [FieldSpec(name="Computed Sample", type=FieldType.TEXT)])
    with pytest.raises(ValueError, match="no field named"):
        set_field_computed(d, "Computed Sample",
                           {"fn": "concatenate", "args": [{"field": "Nope"}]})
    with pytest.raises(ValueError, match="set_field_computed: field not found"):
        set_field_computed(d, "Nope", {"fn": "concatenate", "args": [{"static": "x"}]})


def test_set_conditional_visibility_builds_columnvisibility_criteria() -> None:
    """#48/#55: the THIRD Criteria owner family — ColumnVisibility. Target hidden by default;
    the trigger Column gets the bidirectional LHSOwnField::Condition back-ref."""
    from kfforge.graph import apply_changes, set_conditional_visibility
    from kfforge.types import FieldSpec, FieldType

    bare = {"Root": "M1", "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Form"}}
    d = apply_changes(bare, [FieldSpec(name="Show Details", type=FieldType.BOOLEAN),
                             FieldSpec(name="Details", type=FieldType.TEXT)])
    got = set_conditional_visibility(d, "Details", "Show Details", "EQUAL_TO", "true")

    details = next(n for n in got.values()
                   if isinstance(n, dict) and n.get("Kind") == "Field" and n.get("Name") == "Details")
    target_col = got[details["Column"]]
    assert target_col["IsHidden"] is True
    crit_id = target_col["ColumnVisibility::Criteria"][0]
    crit = got[crit_id]
    assert crit["IsOR"] is False
    cond = got[crit["Criteria::Condition"][0]]
    assert cond["Operator"] == "EQUAL_TO"
    assert cond["HasArguments"] is False
    assert cond["RHSValue"] == "true"

    trigger = next(n for n in got.values()
                  if isinstance(n, dict) and n.get("Kind") == "Field" and n.get("Name") == "Show Details")
    trigger_col = got[trigger["Column"]]
    assert cond["LHSOwnField"] == trigger_col["Id"]
    assert cond["Id"] in trigger_col.get("LHSOwnField::Condition", [])

    # idempotent-ish: a second call REPLACES the rule, never duplicates it
    again = set_conditional_visibility(got, "Details", "Show Details", "EQUAL_TO", "false")
    details2 = next(n for n in again.values()
                    if isinstance(n, dict) and n.get("Kind") == "Field" and n.get("Name") == "Details")
    col2 = again[details2["Column"]]
    assert len(col2["ColumnVisibility::Criteria"]) == 1
    cond2 = again[again[col2["ColumnVisibility::Criteria"][0]]["Criteria::Condition"][0]]
    assert cond2["RHSValue"] == "false"


def test_set_conditional_visibility_raises_on_missing_fields() -> None:
    from kfforge.graph import apply_changes, set_conditional_visibility
    from kfforge.types import FieldSpec, FieldType
    import pytest

    bare = {"Root": "M1", "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Form"}}
    d = apply_changes(bare, [FieldSpec(name="Details", type=FieldType.TEXT)])
    with pytest.raises(ValueError, match="trigger field not found"):
        set_conditional_visibility(d, "Details", "Nope", "EQUAL_TO", "true")
    with pytest.raises(ValueError, match="set_conditional_visibility: field not found"):
        set_conditional_visibility(d, "Nope", "Details", "EQUAL_TO", "true")


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


# ---- regroup_into_sections must not corrupt a template-cloned (nested Grid) form -------------
#
# The template shell's sections nest fields under Grid-type Columns (Section -> Row -> Grid
# Column -> Row -> Field Column), unlike a plain engine-built form (Section -> Row -> Field
# Column directly). Adding ONE field to an EXISTING template section via regroup_into_sections
# used to (a) leave the old Grid columns behind, still pointing at deleted Rows -> dangling refs
# 137 -> 286 live, and (b) dump every OTHER field in that section into a trailing "Other" section
# since `groups` was treated as the complete layout. See CLAUDE.md's own repro write-up.

def _dangling_refs(draft: dict) -> list[str]:
    """Mirror verify.doctor's own dangling-ref rule exactly: every list value under a key
    containing '::' must point at a node that still exists in the draft."""
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


def test_regroup_on_template_shell_adds_one_field_with_no_dangling_refs_or_orphaned_grid() -> None:
    """The most natural first build action on a template-cloned process: add ONE field to an
    EXISTING template section, through the same two-step path forge_apply_fields uses
    (apply the field, then regroup with a partial section map merged against current
    membership)."""
    from kfforge.graph import apply_changes, clone_template_shell, merge_groups, regroup_into_sections
    from kfforge.types import FieldSpec, FieldType

    draft = clone_template_shell(_bare_process())
    new = apply_changes(draft, [FieldSpec(name="New Field", type=FieldType.TEXT)])
    merged = merge_groups(new, [("Request Info", ["New Field"])])
    got = regroup_into_sections(new, merged)

    assert _dangling_refs(got) == [], "no reference may point at a node the rebuild deleted"

    grid_columns = [k for k, v in got.items()
                    if isinstance(v, dict) and v.get("Kind") == "Column" and v.get("Type") == "Grid"]
    assert grid_columns == [], "the old nested Grid wrapper columns must not survive a regroup"

    # every pre-existing Required field must still live in a REAL named section, never "Other"
    required = {v["Name"] for v in draft.values()
               if isinstance(v, dict) and v.get("Kind") == "Field" and v.get("Required")}
    assert required, "sanity: the template ships Required fields"

    section_of: dict[str, str] = {}
    for sid, sec in got.items():
        if isinstance(sec, dict) and sec.get("Kind") == "Column" and sec.get("Type") == "Section":
            for rid in sec.get("Column::Row") or []:
                for cid in got[rid]["Row::Column"]:
                    for fid in got[cid].get("Column::Field") or []:
                        section_of[got[fid]["Name"]] = sec.get("Name")

    for name in required:
        assert section_of.get(name) not in (None, "Other"), \
            f"required field {name!r} must stay in a real section, not fall to Other"

    # the new field landed exactly where the caller asked
    assert section_of.get("New Field") == "Request Info"


def test_regroup_on_a_plain_engine_built_form_is_unchanged() -> None:
    """Regression guard: a non-nested engine-built form (no Grid wrapper columns) must regroup
    exactly as it did before the template-shell fix."""
    from kfforge.graph import regroup_into_sections

    got = regroup_into_sections(_draft_with_fields("a", "b", "c", "d"),
                                [("Step 1", ["a", "b"]), ("Step 2", ["c", "d"])])

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
    """A table host lives in its own root-level Row, outside every Section (CLAUDE.md > Tables).
    regroup_into_sections rebuilds field-layout Rows/Sections; it must never delete the table's
    own host Row or its nested schema Row, and the table host Column must survive untouched."""
    from kfforge.graph import add_table, regroup_into_sections
    from kfforge.types import FieldType

    draft = regroup_into_sections(_draft_with_fields("A", "B"),
                                  [("Head", ["A"]), ("Log Banner", []), ("Tail", ["B"])])
    draft = add_table(draft, "Log", [("Round", FieldType.NUMBER)], after_section="Log Banner")

    # add one more field to an existing section on the table-bearing draft, same call shape as
    # the template-shell scenario above
    from kfforge.graph import apply_changes, merge_groups
    from kfforge.types import FieldSpec

    new = apply_changes(draft, [FieldSpec(name="C", type=FieldType.TEXT)])
    merged = merge_groups(new, [("Head", ["C"])])
    got = regroup_into_sections(new, merged)

    assert _dangling_refs(got) == []

    table_hosts = [v for v in got.values()
                  if isinstance(v, dict) and v.get("Kind") == "Column" and v.get("Type") == "Model"]
    assert len(table_hosts) == 1, "the table host column must survive a regroup untouched"
    host = table_hosts[0]
    assert got.get(host["Row"]) is not None, "the table host's own root Row must survive"
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
# `delete_nodes` had ZERO callers before the client wrappers landed, so its sweep had never been
# exercised against a field carrying any of the CONFIGURATION nodes the engine can now attach
# (query definition, computed formula, validation, conditional visibility, sequence properties).
# Every one of those hangs off the field by a SCALAR back-reference, which `_sweep_dangling` is
# deliberately blind to and which is the deterministic publish-500 (#18).
# =====================================================================================

def _scalar_dangling_refs(draft: dict) -> list[str]:
    """Every SCALAR (non-list) value that LOOKS like a node id and points at a node that is not
    in the draft. The exact blind spot `_dangling_refs`/`_sweep_dangling` (list-only, by design)
    cannot see — and the one that publishes 500 with zero diagnostics."""
    prefixes = ("Field_", "Column_", "Row_", "Permission_", "Event_", "Expression_", "Node_",
                "Criteria_", "Condition_", "QueryDefinition_", "Property_", "Activity_",
                "ProcessDef_", "Resource_", "Model_")
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
    from kfforge.graph import apply_changes
    d = {"Root": "M1", "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Form"}}
    return apply_changes(d, list(specs))


def test_delete_nodes_sweeps_a_user_fields_query_definition() -> None:
    """A `User` field's sibling QueryDefinition holds a SCALAR `Field` back-ref. Left behind it is
    an orphan pointing at a dead id — and refusing the delete instead would make every User field
    permanently undeletable, since nothing on the tool surface can remove a QueryDefinition."""
    from kfforge.graph import delete_closure, delete_nodes

    draft = _form_with(FieldSpec(name="Owner", type=FieldType.USER))
    qids = [k for k, v in draft.items() if isinstance(v, dict) and v.get("Kind") == "QueryDefinition"]
    assert len(qids) == 1, "fixture must actually carry the User field's QueryDefinition"

    assert qids[0] in delete_closure(draft, ("Owner",))
    got = delete_nodes(draft, ("Owner",))
    assert qids[0] not in got
    assert _scalar_dangling_refs(got) == []


def test_delete_nodes_sweeps_the_fields_own_computed_expression_tree() -> None:
    from kfforge.graph import delete_nodes, set_field_computed

    draft = _form_with(FieldSpec(name="Total", type=FieldType.NUMBER),
                       FieldSpec(name="Qty", type=FieldType.NUMBER))
    draft = set_field_computed(draft, "Total", {"fn": "concatenate",
                                                "args": [{"static": "n="}, {"field": "Qty"}]})
    assert any(v.get("Kind") == "Expression" for v in draft.values() if isinstance(v, dict))

    got = delete_nodes(draft, ("Total",))
    assert not [v for v in got.values() if isinstance(v, dict) and v.get("Kind") == "Expression"]
    assert not [v for v in got.values() if isinstance(v, dict) and v.get("Kind") == "Node"]
    assert _scalar_dangling_refs(got) == []
    assert "Qty" in {v.get("Name") for v in got.values()
                     if isinstance(v, dict) and v.get("Kind") == "Field"}


def test_delete_nodes_sweeps_the_fields_own_validation_criteria_and_conditions() -> None:
    from kfforge.graph import add_field_validation, delete_nodes

    draft = _form_with(FieldSpec(name="Code", type=FieldType.TEXT))
    draft = add_field_validation(draft, "Code", "MAX_LENGTH", "10")
    assert any(v.get("Kind") == "Condition" for v in draft.values() if isinstance(v, dict))

    got = delete_nodes(draft, ("Code",))
    assert not [v for v in got.values() if isinstance(v, dict)
                and v.get("Kind") in ("Criteria", "Condition")]
    assert _scalar_dangling_refs(got) == []


def test_delete_nodes_sweeps_the_fields_own_conditional_visibility_rule() -> None:
    """Deleting the TARGET of a conditional-visibility rule takes the rule with it — and the
    trigger column's `LHSOwnField::Condition` back-ref is a LIST, so the existing sweep clears it."""
    from kfforge.graph import delete_nodes, set_conditional_visibility

    draft = _form_with(FieldSpec(name="Reason", type=FieldType.TEXT),
                       FieldSpec(name="Flag", type=FieldType.BOOLEAN))
    draft = set_conditional_visibility(draft, "Reason", "Flag", "EQUAL_TO", "true")

    got = delete_nodes(draft, ("Reason",))
    assert not [v for v in got.values() if isinstance(v, dict)
                and v.get("Kind") in ("Criteria", "Condition")]
    assert _scalar_dangling_refs(got) == []
    assert _dangling_refs(got) == []


def test_delete_nodes_still_sweeps_the_column_and_its_permissions() -> None:
    """Regression net for the ORIGINAL sweep, now that delete_nodes routes through
    delete_closure: the field, its Column and every Permission on that Column still go."""
    from kfforge.graph import delete_nodes

    draft = _form_with(FieldSpec(name="a", type=FieldType.TEXT),
                       FieldSpec(name="b", type=FieldType.TEXT))
    fid = next(k for k, v in draft.items()
               if isinstance(v, dict) and v.get("Kind") == "Field" and v.get("Name") == "a")
    col = draft[fid]["Column"]
    draft["Permission_x"] = {"Id": "Permission_x", "Kind": "Permission", "Column": col,
                             "Activity": "Activity_1", "Permission": "Editable"}
    draft[col].setdefault("Column::Permission", []).append("Permission_x")

    got = delete_nodes(draft, ("a",))
    assert fid not in got and col not in got and "Permission_x" not in got
    assert "b" in {v.get("Name") for v in got.values()
                   if isinstance(v, dict) and v.get("Kind") == "Field"}


def test_delete_nodes_unknown_name_raises_before_any_copy() -> None:
    from kfforge.graph import delete_nodes

    draft = _form_with(FieldSpec(name="a", type=FieldType.TEXT))
    snapshot = copy.deepcopy(draft)
    with pytest.raises(ValueError, match="no field named 'nope'"):
        delete_nodes(draft, ("a", "nope"))
    assert draft == snapshot, "a rejected delete must leave the input byte-identical"


def test_field_delete_blockers_is_empty_for_a_plain_field() -> None:
    from kfforge.graph import field_delete_blockers

    draft = _form_with(FieldSpec(name="a", type=FieldType.TEXT),
                       FieldSpec(name="b", type=FieldType.TEXT))
    assert field_delete_blockers(draft, ("a",)) == ()


def test_field_delete_blockers_names_a_surviving_formula_that_reads_the_field() -> None:
    """`Total`'s formula reads `Qty` by id through a `Node{Type:"Field"}`. Deleting `Qty` leaves
    that Node holding a dead scalar — and sweeping it would silently rewrite Total's formula, a
    change the caller never asked for. So: refuse, and name the remedy."""
    from kfforge.graph import field_delete_blockers, set_field_computed

    draft = _form_with(FieldSpec(name="Total", type=FieldType.NUMBER),
                       FieldSpec(name="Qty", type=FieldType.NUMBER))
    draft = set_field_computed(draft, "Total", {"fn": "concatenate", "args": [{"field": "Qty"}]})

    blockers = field_delete_blockers(draft, ("Qty",))
    assert len(blockers) == 1
    assert "'Qty'" in blockers[0] and "Expression" in blockers[0]
    assert field_delete_blockers(draft, ("Total",)) == (), "the OWNER of the formula deletes clean"


def test_field_delete_blockers_names_a_conditional_visibility_trigger() -> None:
    from kfforge.graph import field_delete_blockers, set_conditional_visibility

    draft = _form_with(FieldSpec(name="Reason", type=FieldType.TEXT),
                       FieldSpec(name="Flag", type=FieldType.BOOLEAN))
    draft = set_conditional_visibility(draft, "Reason", "Flag", "EQUAL_TO", "true")

    blockers = field_delete_blockers(draft, ("Flag",))
    assert len(blockers) == 1 and "TRIGGER" in blockers[0] and "'Flag'" in blockers[0]
    assert field_delete_blockers(draft, ("Reason",)) == ()


def test_field_delete_blockers_names_a_surviving_event_script_that_uses_the_id() -> None:
    """`set_field_events` already refuses a script naming a MISSING field ("breaks the WHOLE form
    at load"). The delete side of the same rule: never create that condition either."""
    from kfforge.graph import field_delete_blockers, set_field_events

    draft = _form_with(FieldSpec(name="Source", type=FieldType.TEXT),
                       FieldSpec(name="Target", type=FieldType.TEXT))
    tgt = next(k for k, v in draft.items()
               if isinstance(v, dict) and v.get("Kind") == "Field" and v.get("Name") == "Target")
    draft = set_field_events(draft, {"Source": [("onChange", f"kf.x('{tgt}');")]})

    blockers = field_delete_blockers(draft, ("Target",))
    assert len(blockers) == 1 and "Script" in blockers[0] and "'Target'" in blockers[0]
    assert field_delete_blockers(draft, ("Source",)) == (), "the event's OWN field deletes clean"


def test_delete_closure_sweeps_table_and_its_cluster() -> None:
    from kfforge.graph import add_table, delete_closure, delete_nodes

    draft = _form_with(FieldSpec(name="Notes", type=FieldType.TEXT))
    draft = add_table(draft, "Items", [("Qty", FieldType.NUMBER), ("Desc", FieldType.TEXT)])

    host_col = next(k for k, v in draft.items()
                    if isinstance(v, dict) and v.get("Kind") == "Column"
                    and v.get("Type") == "Model" and v.get("Name") == "Items")
    nested_model = draft[host_col]["Column::Model"][0]

    doomed = delete_closure(draft, tables=("Items",))
    assert host_col in doomed
    assert nested_model in doomed
    assert draft[host_col].get("Row") in doomed
    for r in draft[nested_model].get("Model::Row", []):
        assert r in doomed
    for f in draft[nested_model].get("Model::Field", []):
        assert f in doomed
        assert draft[f]["Column"] in doomed

    got = delete_nodes(draft, tables=("Items",))
    assert host_col not in got
    assert nested_model not in got
    assert "Notes" in {v.get("Name") for v in got.values() if isinstance(v, dict) and v.get("Kind") == "Field"}
    assert _scalar_dangling_refs(got) == []


def test_delete_closure_unknown_table_raises() -> None:
    from kfforge.graph import delete_closure

    draft = _form_with(FieldSpec(name="Notes", type=FieldType.TEXT))
    with pytest.raises(ValueError, match="no table named 'Missing'"):
        delete_closure(draft, tables=("Missing",))


def test_delete_closure_sweeps_sequence_number_property_chain() -> None:
    from kfforge.graph import (
        add_sequence_number,
        apply_changes,
        build_workflow,
        delete_closure,
        delete_nodes,
        regroup_into_sections,
    )

    bare = {"Root": "M1", "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Process"}}
    d = apply_changes(bare, [FieldSpec(name="a", type=FieldType.TEXT)])
    d = regroup_into_sections(d, [("S", ["a"])])
    d = build_workflow(d, [("Log it", None)])
    draft = add_sequence_number(d, "running number", "S", "PRE-", "0001", "Start", 0, 2)

    prop_ids = [k for k, v in draft.items() if isinstance(v, dict) and v.get("Kind") == "Property"]
    assert len(prop_ids) == 3, "SequenceNumber creates 3 Property nodes"

    doomed = delete_closure(draft, fields=("running number",))
    for pid in prop_ids:
        assert pid in doomed

    got = delete_nodes(draft, fields=("running number",))
    assert not any(isinstance(v, dict) and v.get("Kind") == "Property" for v in got.values())
    assert _scalar_dangling_refs(got) == []


def test_delete_closure_resolves_field_by_raw_node_id_and_handles_missing_column() -> None:
    from kfforge.graph import delete_closure

    draft = _form_with(FieldSpec(name="A", type=FieldType.TEXT))
    fid = next(k for k, v in draft.items() if isinstance(v, dict) and v.get("Kind") == "Field" and v.get("Name") == "A")

    # Resolve by raw id
    assert fid in delete_closure(draft, fields=(fid,))

    # Field without a Column
    draft["Field_no_col"] = {"Id": "Field_no_col", "Kind": "Field", "Name": "NoCol", "Column": None}
    assert "Field_no_col" in delete_closure(draft, fields=("NoCol",))


def test_delete_closure_sweeps_events_and_criteria_with_column_visibility() -> None:
    from kfforge.graph import delete_closure

    draft = _form_with(FieldSpec(name="Flag", type=FieldType.BOOLEAN))
    fid = next(k for k, v in draft.items() if isinstance(v, dict) and v.get("Kind") == "Field" and v.get("Name") == "Flag")
    col = draft[fid]["Column"]

    draft["Event_1"] = {"Id": "Event_1", "Kind": "Event", "Field": fid, "Type": "onChange"}
    draft["Criteria_1"] = {"Id": "Criteria_1", "Kind": "Criteria", "ColumnVisibility": col, "Criteria::Condition": ["Condition_1"]}
    draft["Condition_1"] = {"Id": "Condition_1", "Kind": "Condition", "Criteria": "Criteria_1"}

    # Surviving criteria and property
    draft["Field_surv"] = {"Id": "Field_surv", "Kind": "Field", "Name": "Surv", "Column": "Col_surv"}
    draft["Property_surv"] = {"Id": "Property_surv", "Kind": "Property", "Field": "Field_surv"}
    draft["Criteria_surv"] = {"Id": "Criteria_surv", "Kind": "Criteria", "FieldValidation": "Field_surv"}

    doomed = delete_closure(draft, fields=("Flag",))
    assert "Event_1" in doomed
    assert "Criteria_1" in doomed
    assert "Condition_1" in doomed
    assert "Property_surv" not in doomed
    assert "Criteria_surv" not in doomed


def test_delete_closure_table_and_node_tree_edge_cases() -> None:
    from kfforge.graph import _node_tree, delete_closure

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
        "Col_tbl": {"Id": "Col_tbl", "Kind": "Column", "Type": "Model", "Name": "Tbl", "Row": None, "Column::Model": ["Model_tbl"]},
        "Model_tbl": {"Id": "Model_tbl", "Kind": "Model", "Model::Field": ["Field_child"]},
        "Field_child": {"Id": "Field_child", "Kind": "Field", "Column": None},
    }
    doomed = delete_closure(table_draft, tables=("Tbl",))
    assert doomed == {"Col_tbl", "Model_tbl", "Field_child"}


# ---- apply_changes: a Select must name the list its options live in --------------------------

def test_apply_changes_refuses_a_select_with_no_referred_list() -> None:
    """Rule A′ (2026-08-19 publish-500 diagnosis). A Select's OPTIONS live in a separate list
    flow; minting one with no `ReferredList` is a dropdown bound to nothing, which PUTs 200 and
    dies on publish with a bare MetadataError. The `FieldType.USER` branch twenty lines below
    already refuses/repairs its own version of exactly this defect — refuse at compile (ADR-0004),
    naming the fix, rather than writing a field that cannot publish."""
    import pytest
    from kfforge.graph import apply_changes
    from kfforge.types import FieldSpec, FieldType

    with pytest.raises(ValueError, match=r"'Urgency'.*referred_list"):
        apply_changes(_load(), [FieldSpec(name="Urgency", type=FieldType.SELECT)])


def test_apply_changes_refuses_the_select_before_touching_the_graph() -> None:
    """Validation-first, like every other refusal in apply_changes: a batch whose LAST spec is a
    bare Select must not have written the earlier ones."""
    import copy as _copy

    import pytest
    from kfforge.graph import apply_changes
    from kfforge.types import FieldSpec, FieldType

    draft = _load()
    snapshot = _copy.deepcopy(draft)
    with pytest.raises(ValueError, match="referred_list"):
        apply_changes(draft, [FieldSpec(name="Notes", type=FieldType.TEXT),
                              FieldSpec(name="Urgency", type=FieldType.SELECT)])
    assert draft == snapshot


def test_apply_changes_writes_a_wired_select() -> None:
    from kfforge.graph import apply_changes
    from kfforge.types import FieldSpec, FieldType

    got = apply_changes(_load(), [FieldSpec(name="Urgency", type=FieldType.SELECT,
                                            referred_list="List_Sample01")])
    (fld,) = [v for v in got.values() if isinstance(v, dict) and v.get("Name") == "Urgency"]
    assert fld["Type"] == "Select" and fld["ReferredList"] == "List_Sample01"


# ---- S2(a) / D10: progressive_matrix DROPPED an unknown name instead of refusing it -----------
# Two tool descriptions (kf_plan_step_visibility, kf_set_step_visibility) already claimed "a
# section or step name that is not in `draft` is refused as DATA here". It was not: an unknown
# section key matched no Section and simply never appeared, and an unknown step name matched no
# Activity, which read as "nobody owns this section" and quietly emitted ReadOnly everywhere —
# on a DESTRUCTIVE rebuild that deletes every Permission first. The name the caller supplied
# landed in no bucket at all (doctrine 2).


def _visibility_draft() -> dict:
    from synthetic import synthetic_process_draft

    return synthetic_process_draft()


def test_progressive_matrix_refuses_a_section_name_that_is_not_on_the_form() -> None:
    from kfforge.graph import progressive_matrix

    with pytest.raises(ValueError, match=r"section\(s\) not on this form.*NoSuchSection"):
        progressive_matrix(_visibility_draft(), {"NoSuchSection": ["Assess unit"]})


def test_progressive_matrix_refuses_a_step_name_that_is_not_on_the_workflow() -> None:
    from kfforge.graph import progressive_matrix

    with pytest.raises(ValueError, match=r"step\(s\) not on this workflow.*Assess Unit"):
        progressive_matrix(_visibility_draft(), {"Assessment": ["Assess Unit"]})   # wrong case


def test_the_refusal_names_what_is_actually_available() -> None:
    """A refusal a caller cannot act on is a dead end — both messages list the real set."""
    from kfforge.graph import progressive_matrix

    with pytest.raises(ValueError) as sec:
        progressive_matrix(_visibility_draft(), {"Intak": ["Start"]})
    assert "Intake" in str(sec.value)

    with pytest.raises(ValueError) as step:
        progressive_matrix(_visibility_draft(), {"Intake": ["Strt"]})
    assert "Start" in str(step.value)


def test_a_section_the_owners_map_deliberately_omits_is_still_legal() -> None:
    """The control, and it must pass BOTH before and after the guard: leaving a section out of
    `owners` is the documented unowned case (ReadOnly everywhere), NOT an unresolved name. A guard
    that could not tell the two apart would break every real call — the synthetic draft's own
    "Other" section is deliberately unowned."""
    from synthetic import OWNERS

    from kfforge.graph import progressive_matrix
    from kfforge.types import Visibility

    matrix = progressive_matrix(_visibility_draft(), OWNERS)
    assert "Other" not in OWNERS and "Other" in matrix
    assert set(matrix["Other"].values()) == {Visibility.READONLY}


def test_an_empty_owner_list_is_still_legal() -> None:
    """The other half of the control: `{"Other": []}` names a REAL section with no owner. It must
    stay legal — only an unresolvable NAME is refused, never an empty list."""
    from kfforge.graph import progressive_matrix
    from kfforge.types import Visibility

    matrix = progressive_matrix(_visibility_draft(), {"Other": []})
    assert set(matrix["Other"].values()) == {Visibility.READONLY}


def test_repack_layout_pure_does_not_mutate_input() -> None:
    from synthetic import synthetic_process_draft
    from kfforge.graph import repack_layout

    draft = synthetic_process_draft()
    before = copy.deepcopy(draft)
    out = repack_layout(draft)
    assert draft == before
    assert out is not draft


def test_repack_layout_default_widths_and_column_stretching() -> None:
    from synthetic import synthetic_process_draft
    from kfforge.graph import repack_layout

    draft = synthetic_process_draft()
    repacked = repack_layout(draft)

    # In synthetic draft:
    # "Intake" has Ticket No (Text, 3), Contact Date (Date, 3), Unit Serial (Text, 3), Problem (Textarea, 6)
    # Row 0: Ticket No (0, 3), Contact Date (3, 6)
    # Row 1: Unit Serial (0, 6) -> stretched to 6
    # Row 2: Problem (0, 6)
    intake_sec = next(v for v in repacked.values() if isinstance(v, dict) and v.get("Type") == "Section" and v.get("Name") == "Intake")
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
    from kfforge.graph import repack_layout

    draft = synthetic_process_draft()
    repacked = repack_layout(draft, widths={"Text": 6, "Select": 2, "Uncapped": 10})

    # "Wrap-up" has Wrap Summary (Textarea, 6), Outcome (Select, 2), Handoff Owner (Text, 6)
    # Row 0: Wrap Summary (0, 6)
    # Row 1: Outcome (0, 6) -> stretched from 2 to 6
    # Row 2: Handoff Owner (0, 6)
    wrap_sec = next(v for v in repacked.values() if isinstance(v, dict) and v.get("Type") == "Section" and v.get("Name") == "Wrap-up")
    row_ids = wrap_sec["Column::Row"]
    assert len(row_ids) == 3


def test_repack_layout_section_and_step_descriptions() -> None:
    from synthetic import synthetic_process_draft
    from kfforge.graph import repack_layout

    draft = synthetic_process_draft()
    sec_desc = {"Intake": "Intake Subtitle", "UnmatchedSec": "No-op"}
    step_desc = {"Ticket arrives": "Step 1 Subtitle", "UnmatchedStep": "No-op"}

    repacked = repack_layout(draft, section_descriptions=sec_desc, step_descriptions=step_desc)

    intake_sec = next(v for v in repacked.values() if isinstance(v, dict) and v.get("Type") == "Section" and v.get("Name") == "Intake")
    assert intake_sec.get("Description") == "Intake Subtitle"

    step_node = next(v for v in repacked.values() if isinstance(v, dict) and v.get("Kind") == "Activity" and v.get("Name") == "Ticket arrives")
    assert step_node.get("Description") == "Step 1 Subtitle"

    other_sec = next(v for v in repacked.values() if isinstance(v, dict) and v.get("Type") == "Section" and v.get("Name") == "Other")
    assert "Description" not in other_sec


def test_repack_layout_edge_cases_and_unknown_types() -> None:
    from kfforge.graph import repack_layout

    # Edge cases:
    # 1. Section with empty Column::Row or None Column::Row
    # 2. Section with Row having empty Row::Column or dangling row id
    # 3. Field without Column reference
    # 4. Column of non-Section type (e.g. Model or Field)
    # 5. Column with unknown field type (falls back to DEFAULT_WIDTH)
    synthetic_draft = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "FlowType": "Process"},
        "Sec_Empty": {"Id": "Sec_Empty", "Kind": "Column", "Type": "Section", "Name": "EmptySec", "Column::Row": []},
        "Sec_NoneRows": {"Id": "Sec_NoneRows", "Kind": "Column", "Type": "Section", "Name": "NoneRowsSec", "Column::Row": None},
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
        "Field_Unknown": {"Id": "Field_Unknown", "Kind": "Field", "Type": "CustomUnknownType", "Column": "Col_Unknown"},
        "Col_NoField": {"Id": "Col_NoField", "Kind": "Column", "Type": "Field"},
        "Field_NoCol": {"Id": "Field_NoCol", "Kind": "Field", "Type": "Text"},
        "Col_Model": {"Id": "Col_Model", "Kind": "Column", "Type": "Model"},
    }

    repacked = repack_layout(synthetic_draft, widths={})
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


def test_repack_layout_passes_doctor_audit() -> None:
    from synthetic import synthetic_process_draft
    from kfforge.graph import repack_layout
    from kfforge.verify import doctor

    draft = synthetic_process_draft()
    repacked = repack_layout(draft)
    report = doctor(repacked)
    assert report.ok, report.violations

