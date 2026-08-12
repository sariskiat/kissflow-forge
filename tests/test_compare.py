"""kfforge.compare (#16): the fidelity comparator judges the BUILT graph against the INPUT
spec. Offline: drafts are built with the engine's own builders (never hand-guessed shapes),
then broken in the specific way each check exists to catch — every test's break is a real bug
class from eval case 1 (#16 'each of which caught a real bug')."""
from __future__ import annotations

from typing import Any

from test_intake import _full_spec

from kfforge.compare import CompareReport, compare_built_to_spec
from kfforge.graph import apply_changes, build_workflow, regroup_into_sections
from kfforge.types import FieldSpec, FieldType


def _built_fields(spec: Any) -> dict[str, Any]:
    """A draft carrying every field/table-column the spec asks for, engine-built."""
    bare = {"Root": "M1", "M1": {"Id": "M1", "Kind": "Model", "Name": "P", "FlowType": "Process"}}
    specs = [FieldSpec(name=f.name, type=f.type,
                       referred_list=("L1" if getattr(f, "list_name", None) else None))
             for f in spec.data_model.fields]
    for t in spec.data_model.tables:
        specs += [FieldSpec(name=c.name, type=c.type) for c in t.columns]
    return apply_changes(bare, specs)


def _msgs(rep: CompareReport) -> str:
    return "\n".join(rep.mismatches)


def test_wrong_field_type_and_missing_field_flagged() -> None:
    spec = _full_spec()
    draft = _built_fields(spec)
    # break: retype Urgency (Select -> Text) and delete Quantity outright
    urgency = next(v for v in draft.values()
                   if isinstance(v, dict) and v.get("Name") == "Urgency")
    urgency["Type"] = "Text"
    qty = next(k for k, v in draft.items()
               if isinstance(v, dict) and v.get("Name") == "Quantity")
    del draft[qty]
    rep = compare_built_to_spec(draft, spec)
    assert "built as 'Text', input asked 'Select'" in _msgs(rep)
    assert "field 'Quantity' (Number) asked for by the input is absent" in _msgs(rep)


def test_select_without_referredlist_flagged() -> None:
    spec = _full_spec()
    draft = _built_fields(spec)
    urgency = next(v for v in draft.values()
                   if isinstance(v, dict) and v.get("Name") == "Urgency")
    urgency.pop("ReferredList", None)
    rep = compare_built_to_spec(draft, spec)
    assert "no ReferredList" in _msgs(rep)


def test_unrequested_extra_field_flagged() -> None:
    spec = _full_spec()
    draft = _built_fields(spec)
    draft2 = apply_changes(draft, [FieldSpec(name="Phantom", type=FieldType.TEXT)])
    rep = compare_built_to_spec(draft2, spec)
    assert "'Phantom'" in _msgs(rep) and "never asked for it" in _msgs(rep)


def test_stranded_empty_banner_flagged() -> None:
    spec = _full_spec()
    draft = _built_fields(spec)
    draft = regroup_into_sections(
        draft, [("Intake Basics", ["Unit Name"]), ("Banner", []), ("Tail", ["Customer Name"])])
    rep = compare_built_to_spec(draft, spec)
    assert "stranded banner breaks the WHOLE form's render" in _msgs(rep)


def test_spurious_permission_on_hidden_column_flagged() -> None:
    spec = _full_spec()
    draft = _built_fields(spec)
    draft["Column_Hidden1"] = {"Id": "Column_Hidden1", "Kind": "Column", "IsHidden": True}
    draft["Permission_Bad1"] = {"Id": "Permission_Bad1", "Kind": "Permission",
                                "Column": "Column_Hidden1", "Permission": "Editable"}
    rep = compare_built_to_spec(draft, spec)
    assert "SequenceNumber/IsHidden columns" in _msgs(rep)


def test_missing_event_on_computed_source_flagged() -> None:
    spec = _full_spec()
    rep = compare_built_to_spec(_built_fields(spec), spec)
    assert "carries NO event" in _msgs(rep)


def test_unconditional_branch_and_ungated_loop_flagged() -> None:
    spec = _full_spec()
    draft = _built_fields(spec)
    draft = build_workflow(
        draft, [(s.name, None) for s in spec.stages.stages],
        parallel=("Route", [("A", [("A1", None)]), ("B", [("B1", None)])]), parallel_after=0)
    rep = compare_built_to_spec(draft, spec)
    assert "NO condition" in _msgs(rep) and "fail-open" in _msgs(rep)
    assert "no GotoTask targeting" in _msgs(rep)          # the spec's loop was never built


def test_incomplete_style_chain_flagged() -> None:
    spec = _full_spec()
    draft = _built_fields(spec)
    draft["Appearance_Bad1"] = {"Id": "Appearance_Bad1", "Kind": "Appearance",
                                "Appearance::Style": []}
    rep = compare_built_to_spec(draft, spec)
    assert "must be exactly 1" in _msgs(rep)


def test_benign_platform_nodes_are_declared_ignored_not_flagged() -> None:
    spec = _full_spec()
    draft = _built_fields(spec)
    draft["User_Pub1"] = {"Id": "User_Pub1", "Kind": "User", "Name": "PublishedBy"}
    rep = compare_built_to_spec(draft, spec)
    assert any("platform publish side-effect" in i for i in rep.ignored)
    assert "User_Pub1" not in _msgs(rep)
