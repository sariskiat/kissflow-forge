"""Spec for kfforge.intake.serde -- the exact dict <-> AppSpec round-trip a stateless MCP tool
surface needs (the server holds no session state, so a spec must survive leaving Python entirely
and coming back as plain JSON on the very next call).

Offline, synthetic AppSpec only -- reuses tests/test_intake.py's own `_full_spec()`/`_linear_spec()`
fixtures (imported directly, the same pattern tests/test_p2_server.py already uses to pull
`FakeClient` out of tests/test_client.py) rather than re-building an 11-dimension fixture a second
time. No real-app vocabulary anywhere in this file (CLAUDE.md BLINDNESS).
"""
from __future__ import annotations

import dataclasses
import json

import pytest
from test_intake import (  # tests/ is on sys.path, see conftest.py
    _full_spec,
    _linear_spec,
)

from kfforge.intake.schema import AppSpec, DataModel, EventTrigger, FieldReq, ProblemGoal
from kfforge.intake.serde import spec_from_dict, spec_to_dict, to_wire
from kfforge.types import FieldType, Visibility

# ---- round trip: the load-bearing proof ---------------------------------------------------


def test_full_spec_round_trips_exactly() -> None:
    spec = _full_spec()
    got = spec_from_dict(spec_to_dict(spec))
    assert got == spec


def test_linear_spec_round_trips_exactly() -> None:
    """The OTHER shape: confirmed_none flags, empty tuples, a blank Timing -- proves the round
    trip is exact for the "nothing here" case too, not just a densely-populated one."""
    spec = _linear_spec()
    got = spec_from_dict(spec_to_dict(spec))
    assert got == spec


def test_round_trip_preserves_dataclass_types_not_just_equal_values() -> None:
    """`==` alone could pass even if a tuple silently became a list somewhere (Python compares
    list == list and tuple == tuple, never mixes truthfully, so a type slip would actually FAIL
    equality too -- but this pins the positive case explicitly: every collection remains a real
    tuple after the round trip, not merely "something equal to one")."""
    spec = _full_spec()
    got = spec_from_dict(spec_to_dict(spec))
    assert isinstance(got, AppSpec)
    assert isinstance(got.roles.roles, tuple)
    assert isinstance(got.routing.points[0].route_per_option, tuple)
    assert isinstance(got.routing.points[0].route_per_option[0], tuple)
    assert isinstance(got.routing.points[0].route_per_option[0][1], tuple)  # the target SEQUENCE
    assert isinstance(got.test_cases.cases[0].fills[0].values, tuple)


def test_a_route_option_carrying_a_multi_stage_sequence_round_trips() -> None:
    """P1 (#30): a DecisionPoint option routes to an ORDERED SEQUENCE of stages, not a single
    stage; a one-element sequence is the old single-stage route. The round trip must preserve the
    sequence, in order, in both directions -- the load-bearing boundary guarantee the reader skill
    and the compile pipeline both lean on."""
    base = _full_spec()
    pt = base.routing.points[0]
    seq_pt = dataclasses.replace(pt, route_per_option=(
        ("Yes", ("Repair", "Quality Check")),  # a two-stage branch
        ("No", ("Return to Customer",)),        # a one-element sequence == the old single-stage route
    ))
    spec = dataclasses.replace(base, routing=dataclasses.replace(base.routing, points=(seq_pt,)))
    got = spec_from_dict(spec_to_dict(spec))
    assert got == spec
    assert got.routing.points[0].route_per_option[0][1] == ("Repair", "Quality Check")
    assert got.routing.points[0].route_per_option[1][1] == ("Return to Customer",)


# ---- enums: survive by .value, come back as the real enum member --------------------------


def test_enums_survive_the_round_trip_as_real_enum_members() -> None:
    spec = _full_spec()
    got = spec_from_dict(spec_to_dict(spec))
    urgency = next(f for f in got.data_model.fields if f.name == "Urgency")
    assert urgency.type is FieldType.SELECT
    quality_passed = next(f for f in got.data_model.fields if f.name == "Quality Passed")
    assert quality_passed.type is FieldType.BOOLEAN
    vis_entry = got.visibility.entries[0]
    assert isinstance(vis_entry.permission, Visibility)
    computed = got.data_model.computed[0]
    assert computed.trigger is None  # the derive-per-source default survives as a real None
    # an EXPLICIT trigger still round-trips as the real enum member (matching the Number
    # sources' own derived onSelect — anything else is refused at compile, #12)
    explicit = dataclasses.replace(
        spec,
        data_model=dataclasses.replace(
            spec.data_model,
            computed=tuple(dataclasses.replace(c, trigger=EventTrigger.ON_SELECT)
                           for c in spec.data_model.computed),
        ),
    )
    got2 = spec_from_dict(spec_to_dict(explicit))
    assert got2.data_model.computed[0].trigger is EventTrigger.ON_SELECT


def test_enum_wire_value_is_the_plain_string_not_an_enum_repr() -> None:
    """Enums serialize by `.value` (the task's own load-bearing detail) -- the WIRE dict must hold
    a plain `str`, never a `FieldType`/`Visibility` instance leaking through (which would still
    happen to `==` a string thanks to StrEnum, but must not be what's actually there)."""
    wire = spec_to_dict(_full_spec())
    urgency = next(f for f in wire["data_model"]["fields"] if f["name"] == "Urgency")
    assert urgency["type"] == "Select"
    assert type(urgency["type"]) is str
    vis_entry = wire["visibility"]["entries"][0]
    assert type(vis_entry["permission"]) is str


# ---- tuple-of-pairs: list of 2-element lists on the wire -----------------------------------


def test_tuple_of_pairs_is_a_list_of_two_element_lists_on_the_wire() -> None:
    wire = spec_to_dict(_full_spec())
    route = wire["routing"]["points"][0]["route_per_option"]
    assert route == [["Yes", ["Repair"]], ["No", ["Return to Customer"]]]
    for pair in route:
        assert isinstance(pair, list) and len(pair) == 2
        assert isinstance(pair[1], list)  # the target is a stage SEQUENCE, a list on the wire (P1)


def test_wire_dict_holds_no_tuples_anywhere() -> None:
    """Every collection on the wire is a `list`, never a `tuple` -- a JSON round trip through
    `json.dumps`/`json.loads` would collapse a stray tuple into a list anyway, so this pins the
    invariant directly rather than relying on JSON's own lossy-ness to hide a bug."""

    def _walk(node: object) -> None:
        assert not isinstance(node, tuple), f"found a bare tuple on the wire: {node!r}"
        if isinstance(node, dict):
            for v in node.values():
                _walk(v)
        elif isinstance(node, list):
            for v in node:
                _walk(v)

    _walk(spec_to_dict(_full_spec()))


# ---- None stays None ------------------------------------------------------------------------


def test_none_stays_none_through_the_round_trip() -> None:
    spec = _full_spec()
    field = next(f for f in spec.data_model.fields if f.list_name is None)
    wire = spec_to_dict(spec)
    wire_field = next(f for f in wire["data_model"]["fields"] if f["name"] == field.name)
    assert wire_field["list_name"] is None
    got = spec_from_dict(wire)
    assert next(f for f in got.data_model.fields if f.name == field.name).list_name is None


# ---- JSON-dumps-able, and survives an ACTUAL text round trip, not just a dict one -----------


def test_wire_dict_is_json_dumps_able_and_round_trips_through_real_json_text() -> None:
    spec = _full_spec()
    text = json.dumps(spec_to_dict(spec))
    reloaded = spec_from_dict(json.loads(text))
    assert reloaded == spec


def test_linear_spec_is_json_dumps_able() -> None:
    text = json.dumps(spec_to_dict(_linear_spec()))
    assert spec_from_dict(json.loads(text)) == _linear_spec()


# ---- malformed input: never silently drops a dimension --------------------------------------


def test_missing_top_level_key_raises_naming_the_path() -> None:
    wire = spec_to_dict(_full_spec())
    del wire["problem_goal"]
    with pytest.raises(ValueError, match=r"AppSpec\.problem_goal: missing required key"):
        spec_from_dict(wire)


def test_missing_nested_key_raises_naming_the_full_dotted_path() -> None:
    wire = spec_to_dict(_full_spec())
    del wire["problem_goal"]["pain"]
    with pytest.raises(ValueError, match=r"AppSpec\.problem_goal\.pain: missing required key"):
        spec_from_dict(wire)


def test_missing_key_inside_a_tuple_element_raises_with_an_indexed_path() -> None:
    wire = spec_to_dict(_full_spec())
    del wire["data_model"]["fields"][0]["name"]
    with pytest.raises(ValueError, match=r"data_model\.fields\[0\]\.name: missing required key"):
        spec_from_dict(wire)


def test_unknown_top_level_key_raises_naming_it() -> None:
    wire = spec_to_dict(_full_spec())
    wire["not_a_real_dimension"] = "surprise"
    with pytest.raises(ValueError, match=r"unknown key.*not_a_real_dimension"):
        spec_from_dict(wire)


def test_unknown_nested_key_raises_naming_it() -> None:
    wire = spec_to_dict(_full_spec())
    wire["problem_goal"]["extra_field_nobody_asked_for"] = "x"
    with pytest.raises(ValueError, match=r"unknown key.*extra_field_nobody_asked_for"):
        spec_from_dict(wire)


def test_bad_enum_value_raises_naming_the_path_and_the_bad_value() -> None:
    wire = spec_to_dict(_full_spec())
    wire["data_model"]["fields"][0]["type"] = "NotARealFieldType"
    with pytest.raises(ValueError, match=r"data_model\.fields\[0\]\.type"):
        spec_from_dict(wire)
    with pytest.raises(ValueError, match="NotARealFieldType"):
        spec_from_dict(wire)


def test_wrong_shape_for_a_dataclass_field_raises() -> None:
    wire = spec_to_dict(_full_spec())
    wire["problem_goal"] = "not an object"
    with pytest.raises(ValueError, match=r"AppSpec\.problem_goal: expected an object"):
        spec_from_dict(wire)


def test_wrong_shape_for_a_tuple_field_raises() -> None:
    wire = spec_to_dict(_full_spec())
    wire["roles"]["roles"] = "not a list"
    with pytest.raises(ValueError, match=r"roles\.roles: expected a list"):
        spec_from_dict(wire)


def test_top_level_input_must_be_an_object() -> None:
    with pytest.raises(ValueError, match="expected an object"):
        spec_from_dict(["not", "a", "dict"])  # type: ignore[arg-type]


# ---- a spec built with a raw string standing in for an enum still serializes cleanly --------
# (compile.py's own cross-checks catch a raw-string enum at COMPILE time -- schema.py's own
# dataclasses never enforce their type hints at construction, see schema.py's module docstring --
# to_wire must not crash on one either, since a caller could hand serde a not-yet-validated spec).


def test_to_wire_handles_a_raw_string_standing_in_for_an_enum() -> None:
    bad_field = FieldReq("Bad", "Text", True, "Stage1")  # type: ignore[arg-type]
    dm = DataModel(fields=(bad_field,), tables=(), computed=())
    wire = to_wire(dm)
    assert wire["fields"][0]["type"] == "Text"  # a plain str stays a plain str, no crash


# ---- to_wire is reused for non-AppSpec dataclasses this package hands back from a tool ------


def test_to_wire_serializes_an_arbitrary_dataclass_generically() -> None:
    """kfforge.server relies on `to_wire` for BuildPlan/Op/ConfirmationRequest/Question too --
    proven here with an ad hoc dataclass so this test does not depend on those modules at all."""

    @dataclasses.dataclass(frozen=True)
    class Leaf:
        name: str
        tags: tuple[str, ...]

    @dataclasses.dataclass(frozen=True)
    class Tree:
        leaves: tuple[Leaf, ...]
        note: str | None

    tree = Tree(leaves=(Leaf("a", ("x", "y")), Leaf("b", ())), note=None)
    assert to_wire(tree) == {
        "leaves": [{"name": "a", "tags": ["x", "y"]}, {"name": "b", "tags": []}],
        "note": None,
    }


def test_to_wire_coerces_dict_keys_to_str_and_recurses_into_dict_values() -> None:
    assert to_wire({"a": (1, 2), "b": {"nested": ("x",)}}) == {
        "a": [1, 2], "b": {"nested": ["x"]},
    }


def test_to_wire_rejects_a_value_it_cannot_serialize() -> None:
    with pytest.raises(ValueError, match="cannot serialize"):
        to_wire(object())


# ---- minimal spec (every default taken) still round-trips -----------------------------------


def test_minimal_spec_with_every_optional_defaulted_round_trips() -> None:
    """Every field that carries a dataclass default (`confirmed_none`, `max_rounds`, `list_name`,
    `section`, `options`, `sections`, `sequence`, `approved`, ...) left at its default -- proves
    the round trip does not depend on a caller always supplying every optional explicitly."""
    from kfforge.intake.schema import (
        DataModel,
        MasterData,
        Personas,
        ReworkLoops,
        Roles,
        Routing,
        Stages,
        TestCases,
        Timing,
        VisibilityMatrix,
    )

    spec = AppSpec(
        app_name="Minimal",
        problem_goal=ProblemGoal(pain="p", goal="g", done_definition="d",
                                 terminal_states=("Done",), result_values=("Ok",)),
        roles=Roles(roles=()),
        stages=Stages(stages=()),
        routing=Routing(points=()),
        rework_loops=ReworkLoops(loops=()),
        data_model=DataModel(fields=(), tables=(), computed=()),
        master_data=MasterData(lists=()),
        visibility=VisibilityMatrix(entries=()),
        timing=Timing(sla_notes="", batch_days=(), reminders=()),
        personas=Personas(views=()),
        test_cases=TestCases(cases=()),
    )
    assert spec_from_dict(spec_to_dict(spec)) == spec
    assert spec.approved is False
    assert spec.routing.confirmed_none is False


def test_field_types_cache_returns_a_read_only_mapping() -> None:
    """The lru_cache hands the SAME object to every caller; a mutable dict would let one decode
    poison every later one. Pinned because a plain-dict regression is otherwise invisible."""
    import types as _types

    from kfforge.intake.schema import AppSpec
    from kfforge.intake.serde import _field_types

    got = _field_types(AppSpec)
    assert isinstance(got, _types.MappingProxyType)
    with pytest.raises(TypeError):
        got["injected"] = str            # type: ignore[index]


def test_page_behavior_popup_and_open_popup_action_round_trips() -> None:
    """#39: a page carrying a PopupIntent + an OpenPopup on-click action survives the wire
    unchanged. Behavior is the schema half of ADR-0005; serde is reflection-driven, so this must
    pass with ZERO serde code change (the two-arm OnClickAction is a discriminant + optional
    payloads, never an `A | B` union serde can't reflect)."""
    from kfforge.intake.schema import (
        ClickActionKind,
        OnClickAction,
        PageIntent,
        PersonaView,
        PopupIntent,
        WidgetIntent,
    )

    base = _full_spec()
    page = PageIntent(
        name="Board",
        widgets=(WidgetIntent("general/label"),),
        popups=(PopupIntent(name="Detail", widgets=(WidgetIntent("general/label"),)),),
        on_click=(
            OnClickAction("Show detail", ClickActionKind.OPEN_POPUP, target_popup="Detail"),
            OnClickAction("Notify", ClickActionKind.JS_ACTION, script="await kf.client.showInfo('x');"),
        ),
    )
    view = PersonaView(role=base.roles.roles[0].name, pages=(page,), kpis=(), actions=("Show detail",))
    spec = dataclasses.replace(
        base, personas=dataclasses.replace(base.personas, views=(view,)))

    got = spec_from_dict(spec_to_dict(spec))
    assert got == spec
    rt_page = got.personas.views[0].pages[0]
    assert rt_page.popups[0].name == "Detail"
    assert rt_page.on_click[0].kind is ClickActionKind.OPEN_POPUP
    assert rt_page.on_click[0].target_popup == "Detail" and rt_page.on_click[0].script is None
    assert rt_page.on_click[1].kind is ClickActionKind.JS_ACTION
    assert rt_page.on_click[1].script and rt_page.on_click[1].target_popup is None


def test_page_design_tree_round_trips() -> None:
    """page.design.md: a page carrying a nested, styled DesignNode tree survives the wire exactly.
    Serde is reflection-driven, so a recursive dataclass (`children: tuple[DesignNode, ...]`) plus a
    `WidgetIntent | None` union round-trips with ZERO serde code change — this proves it, and that
    the `token:`-prefixed style-string convention is preserved byte-for-byte."""
    from kfforge.intake.schema import DesignNode, PageIntent, PersonaView, WidgetIntent

    base = _full_spec()
    design = DesignNode(
        kind="container", name="page shell",
        style=(("Container.Background", "#FCFAF2"), ("Container.Row.Gap", "16px"),
               ("Container.Flex.Direction", "column")),
        children=(
            DesignNode(
                kind="container", name="hero",
                style=(("Container.Background", "#2E6B3B"), ("Container.Padding.Top", "32px")),
                children=(
                    DesignNode(kind="widget", name="hero title",
                               style=(("Label.Color", "token:Color.White"),
                                      ("Label.Font.Weight", "token:Font.Weight.SemiBold")),
                               widget=WidgetIntent("general/label",
                                                   config=(("title", "Submit your case"),))),
                )),
            DesignNode(
                kind="container", name="card",
                style=(("Container.Background", "#FFFFFF"),
                       ("Container.Border.Top.Left.Radius", "14px")),
                children=(
                    DesignNode(kind="widget", name="form",
                               widget=WidgetIntent("view/form",
                                                   config=(("flow_type", "Process"),
                                                           ("flow_id", "RepairJobs")))),
                )),
        ),
    )
    page = PageIntent(name="Submit", widgets=(), design=design)
    view = PersonaView(role=base.roles.roles[0].name, pages=(page,), kpis=(), actions=())
    spec = dataclasses.replace(base, personas=dataclasses.replace(base.personas, views=(view,)))

    got = spec_from_dict(spec_to_dict(spec))
    assert got == spec
    rt_design = got.personas.views[0].pages[0].design
    assert rt_design is not None
    assert rt_design.children[0].children[0].style[0] == ("Label.Color", "token:Color.White")
    assert rt_design.children[1].children[0].widget.slug == "view/form"
    # a design-less page still round-trips with design=None (backward compatibility)
    assert _full_spec().personas.views[0].pages[0].design is None


def test_page_behavior_spec_compiles_and_is_now_governed() -> None:
    """#39 gave the vocabulary; #40 T2 governs it — a spec carrying popups + on-click wiring now
    compiles the behavior INTO the build_page op (no longer ignored), provided the wiring is legal
    (the on-click action is one the owning role declares, its OpenPopup targets a real popup)."""
    from kfforge.intake.compile import compile_spec
    from kfforge.intake.schema import (
        ClickActionKind,
        OnClickAction,
        PopupIntent,
        WidgetIntent,
    )

    base = _full_spec()
    v0 = base.personas.views[0]  # Service Manager — declares "reassign job"
    page = dataclasses.replace(
        v0.pages[0],
        popups=(PopupIntent(name="Detail", widgets=(WidgetIntent("general/label"),)),),
        on_click=(OnClickAction("reassign job", ClickActionKind.OPEN_POPUP, target_popup="Detail"),),
    )
    view = dataclasses.replace(v0, pages=(page,) + v0.pages[1:])
    spec = dataclasses.replace(
        base, personas=dataclasses.replace(base.personas, views=(view,) + base.personas.views[1:]))
    plan = compile_spec(spec)
    build = next(op for op in plan.ops
                 if op.kind == "build_page" and op.args["name"] == page.name)
    assert build.args["popups"] == ({"name": "Detail",
                                     "widgets": ({"slug": "general/label", "config": {},
                                                  "row_fields": ()},)},)
    assert build.args["on_click"] == ({"action": "reassign job", "kind": "OpenPopup",
                                       "target_popup": "Detail", "script": None},)


def test_visibility_entry_role_claim_round_trips() -> None:
    """#6: the `role` claim slot (role-scoped visibility, doctor-refused) survives the wire."""
    full = _full_spec()
    vm = full.visibility
    claimed = dataclasses.replace(vm.entries[0], role="Finance")
    spec = dataclasses.replace(
        full, visibility=dataclasses.replace(vm, entries=(claimed,) + vm.entries[1:]))
    got = spec_from_dict(spec_to_dict(spec))
    assert got == spec
    assert got.visibility.entries[0].role == "Finance"
