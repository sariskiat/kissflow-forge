"""Spec for app.application.models.requests.intake.app_spec — the Pydantic AppSpec tree.

Round-trip invariant (G10, see app_spec.py's own module docstring): for every spec dict
`d` the old dataclass-based `app.application.intake.schema`/`serde` pair accepted,
`AppSpec.model_validate(d).model_dump(mode="json")` equals what that old pair produced.
The golden files under `tests/fixtures/app_spec_golden/` were captured by running the
OLD code once, before `schema.py`/`serde.py` were deleted (see the goal's own report for
how); each golden file's content is already `spec_to_dict(spec_from_dict(original))`, so
the invariant collapses to: this module reproduces the golden file exactly, both ways.

The rest of this file replaces `tests/test_serde.py`'s round-trip and validation cases
(now moot or answered differently): a malformed spec now raises
`pydantic.ValidationError` (itself a `ValueError`) rather than a hand-written
path-naming `ValueError` — Pydantic's own error already names the offending field.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.application.models.requests.intake.app_spec import (
    AppSpec,
    ClickActionKind,
    DataModel,
    DesignNode,
    FieldReq,
    MasterData,
    OnClickAction,
    PageIntent,
    PersonaView,
    PopupIntent,
    ProblemGoal,
    ReworkLoops,
    Routing,
    WidgetIntent,
    blank_spec,
)
from app.domain.value_objects.field_type import FieldType, Visibility

GOLDEN_DIR = Path(__file__).resolve().parents[5] / "fixtures" / "app_spec_golden"
GOLDEN_FILES = sorted(GOLDEN_DIR.glob("*.json"))


def _load(name: str) -> dict:
    return json.loads((GOLDEN_DIR / f"{name}.json").read_text(encoding="utf-8"))


def _dims(gaps: tuple[str, ...]) -> list[int]:
    """Dimension numbers named by a `gaps()` result, in order (each sentence is
    `"N. name: ..."`)."""
    return [int(s.split(".", 1)[0]) for s in gaps]


# ---- the load-bearing invariant, over every captured golden shape --------------------


@pytest.mark.parametrize("path", GOLDEN_FILES, ids=lambda p: p.stem)
def test_model_validate_then_model_dump_reproduces_the_golden_file(path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    got = AppSpec.model_validate(data).model_dump(mode="json")
    assert got == data


def test_at_least_the_documented_golden_shapes_are_present() -> None:
    """Pins the golden set itself, so a golden file silently going missing fails loudly
    here rather than just shrinking the parametrize list above unnoticed.
    """
    names = {p.stem for p in GOLDEN_FILES}
    assert names == {
        "blank",
        "full",
        "linear",
        "multi_stage_route",
        "explicit_trigger",
        "popup_on_click",
        "page_design_tree",
        "visibility_role_claim",
    }


# ---- gaps() / blocking_gaps(): the output-invariant audit over 11 dimensions ---------


def test_blank_spec_gaps_lists_all_eleven_dimensions_in_order() -> None:
    gaps = blank_spec().gaps()
    assert len(gaps) == 11
    for n, sentence in enumerate(gaps, start=1):
        assert sentence.startswith(f"{n}. ")


def test_blank_spec_blocking_gaps_excludes_the_advisory_timing_dimension() -> None:
    blocking = blank_spec().blocking_gaps()
    assert len(blocking) == 10
    assert not any(s.startswith("9. ") for s in blocking)


def test_full_spec_has_no_gaps_at_all() -> None:
    spec = AppSpec.model_validate(_load("full"))
    assert spec.gaps() == ()
    assert spec.blocking_gaps() == ()


def test_linear_spec_has_no_blocking_gaps_but_flags_timing() -> None:
    """`linear` deliberately leaves Timing blank (advisory, never blocking) while using
    `confirmed_none` for routing/rework/master-data instead of inventing fake content.
    """
    spec = AppSpec.model_validate(_load("linear"))
    assert spec.blocking_gaps() == ()
    assert any(s.startswith("9. ") for s in spec.gaps())


def test_partially_filled_spec_has_exactly_the_missing_dimensions() -> None:
    # fill in ONLY 1 (problem/goal), 2 (roles), 3 (stages) -- dimensions 4..11 stay
    # empty/unconfirmed
    full = AppSpec.model_validate(_load("full"))
    partial = blank_spec().model_copy(
        update={
            "problem_goal": full.problem_goal,
            "roles": full.roles,
            "stages": full.stages,
        }
    )
    assert _dims(partial.gaps()) == [4, 5, 6, 7, 8, 9, 10, 11]


def test_confirmed_none_defaults_to_false_so_a_blank_dimension_still_gaps() -> None:
    """Without the explicit flag, an empty Routing/ReworkLoops/MasterData is STILL a
    gap -- the `confirmed_none` escape hatch is opt-in, never silently assumed."""
    spec = AppSpec.model_validate(_load("full")).model_copy(
        update={
            "routing": Routing(points=()),
            "rework_loops": ReworkLoops(loops=()),
            "master_data": MasterData(lists=()),
        }
    )
    assert _dims(spec.gaps()) == [4, 5, 7]


def test_parallel_branches_documented_as_out_of_scope() -> None:
    import app.application.models.requests.intake.app_spec as app_spec_module

    doc = (app_spec_module.__doc__ or "").lower()
    assert "parallel" in doc
    assert "out of scope" in doc


# ---- round trip: the load-bearing proof, restated directly (not just via goldens) ----


def test_full_spec_round_trips_exactly() -> None:
    spec = AppSpec.model_validate(_load("full"))
    got = AppSpec.model_validate(spec.model_dump(mode="json"))
    assert got == spec


def test_round_trip_preserves_tuple_types_not_just_equal_values() -> None:
    got = AppSpec.model_validate(_load("full"))
    assert isinstance(got.roles.roles, tuple)
    assert isinstance(got.routing.points[0].route_per_option, tuple)
    assert isinstance(got.routing.points[0].route_per_option[0], tuple)
    assert isinstance(got.routing.points[0].route_per_option[0][1], tuple)
    assert isinstance(got.test_cases.cases[0].fills[0].values, tuple)


def test_a_route_option_carrying_a_multi_stage_sequence_round_trips() -> None:
    """P1 (#30): a DecisionPoint option routes to an ORDERED SEQUENCE of stages, not a
    single stage. The golden `multi_stage_route` fixture pins a two-stage branch and
    a one-stage branch side by side.
    """
    got = AppSpec.model_validate(_load("multi_stage_route"))
    assert got.routing.points[0].route_per_option[0][1] == ("Repair", "Quality Check")
    assert got.routing.points[0].route_per_option[1][1] == ("Return to Customer",)


# ---- enums: survive by .value, come back as the real enum member ---------------------


def test_enums_come_back_as_real_enum_members() -> None:
    got = AppSpec.model_validate(_load("full"))
    urgency = next(f for f in got.data_model.fields if f.name == "Urgency")
    assert urgency.type is FieldType.SELECT
    quality_passed = next(
        f for f in got.data_model.fields if f.name == "Quality Passed"
    )
    assert quality_passed.type is FieldType.BOOLEAN
    vis_entry = got.visibility.entries[0]
    assert isinstance(vis_entry.permission, Visibility)


def test_explicit_computed_trigger_round_trips_as_the_real_enum_member() -> None:
    from app.domain.value_objects.field_type import EventTrigger

    got = AppSpec.model_validate(_load("explicit_trigger"))
    assert got.data_model.computed[0].trigger is EventTrigger.ON_SELECT


def test_enum_wire_value_is_the_plain_string_not_an_enum_repr() -> None:
    wire = _load("full")
    urgency = next(f for f in wire["data_model"]["fields"] if f["name"] == "Urgency")
    assert urgency["type"] == "Select"
    assert type(urgency["type"]) is str
    vis_entry = wire["visibility"]["entries"][0]
    assert type(vis_entry["permission"]) is str


# ---- tuple-of-pairs: a list of two-element lists on the wire -------------------------


def test_tuple_of_pairs_is_a_list_of_two_element_lists_on_the_wire() -> None:
    wire = AppSpec.model_validate(_load("full")).model_dump(mode="json")
    route = wire["routing"]["points"][0]["route_per_option"]
    for pair in route:
        assert isinstance(pair, list)
        assert len(pair) == 2
        assert isinstance(pair[1], list)  # the target is a stage SEQUENCE (P1)


def test_wire_dict_holds_no_tuples_anywhere() -> None:
    def _walk(node: object) -> None:
        assert not isinstance(node, tuple), f"found a bare tuple on the wire: {node!r}"
        if isinstance(node, dict):
            for v in node.values():
                _walk(v)
        elif isinstance(node, list):
            for v in node:
                _walk(v)

    _walk(AppSpec.model_validate(_load("full")).model_dump(mode="json"))


# ---- None stays None -----------------------------------------------------------------


def test_none_stays_none_through_the_round_trip() -> None:
    wire = _load("full")
    field = next(f for f in wire["data_model"]["fields"] if f["list_name"] is None)
    got = AppSpec.model_validate(wire)
    assert (
        next(f for f in got.data_model.fields if f.name == field["name"]).list_name
        is None
    )


# ---- JSON-dumps-able, and survives an ACTUAL text round trip, not just a dict one ----


def test_wire_dict_is_json_dumps_able_and_round_trips_through_real_json_text() -> None:
    wire = _load("full")
    text = json.dumps(wire)
    reloaded = AppSpec.model_validate(json.loads(text))
    assert reloaded.model_dump(mode="json") == wire


# ---- malformed input: pydantic.ValidationError, which is a ValueError ----------------


def test_missing_top_level_key_raises() -> None:
    wire = _load("full")
    del wire["problem_goal"]
    with pytest.raises(ValidationError, match="problem_goal"):
        AppSpec.model_validate(wire)


def test_missing_nested_key_raises() -> None:
    wire = _load("full")
    del wire["problem_goal"]["pain"]
    with pytest.raises(ValidationError, match="pain"):
        AppSpec.model_validate(wire)


def test_missing_key_inside_a_tuple_element_raises() -> None:
    wire = _load("full")
    del wire["data_model"]["fields"][0]["name"]
    with pytest.raises(ValidationError, match="name"):
        AppSpec.model_validate(wire)


def test_bad_enum_value_raises_naming_the_bad_value() -> None:
    wire = _load("full")
    wire["data_model"]["fields"][0]["type"] = "NotARealFieldType"
    with pytest.raises(ValidationError, match="NotARealFieldType"):
        AppSpec.model_validate(wire)


def test_unknown_top_level_key_raises_naming_it() -> None:
    """`extra="forbid"` on every model matches the old serde.py's strictness: a stray
    key (e.g. a caller's typo, or a leftover dimension from an older spec shape) is
    refused, not silently dropped -- `forge_update_spec`'s own merge-then-validate step
    depends on this.
    """
    wire = _load("full")
    wire["not_a_real_dimension"] = "surprise"
    with pytest.raises(ValidationError, match="not_a_real_dimension"):
        AppSpec.model_validate(wire)


def test_unknown_nested_key_raises_naming_it() -> None:
    wire = _load("full")
    wire["problem_goal"]["extra_field_nobody_asked_for"] = "x"
    with pytest.raises(ValidationError, match="extra_field_nobody_asked_for"):
        AppSpec.model_validate(wire)


def test_wrong_shape_for_a_model_field_raises() -> None:
    wire = _load("full")
    wire["problem_goal"] = "not an object"
    with pytest.raises(ValidationError):
        AppSpec.model_validate(wire)


def test_wrong_shape_for_a_tuple_field_raises() -> None:
    wire = _load("full")
    wire["roles"]["roles"] = "not a list"
    with pytest.raises(ValidationError):
        AppSpec.model_validate(wire)


def test_top_level_input_must_be_an_object() -> None:
    with pytest.raises(ValidationError):
        AppSpec.model_validate(["not", "a", "dict"])


def test_bad_pain_type_raises_a_value_error() -> None:
    """A `ValidationError` IS a `ValueError` (the boundary the old `except ValueError`
    sites at the MCP tool edge depend on).
    """
    wire = _load("full")
    wire["problem_goal"]["pain"] = 5
    with pytest.raises(ValueError):
        AppSpec.model_validate(wire)


# ---- minimal spec (every default taken) still round-trips ----------------------------


def test_blank_spec_round_trips() -> None:
    spec = blank_spec()
    got = AppSpec.model_validate(spec.model_dump(mode="json"))
    assert got == spec
    assert spec.approved is False
    assert spec.routing.confirmed_none is False


def test_blank_spec_matches_its_golden_file() -> None:
    assert blank_spec().model_dump(mode="json") == _load("blank")


# ---- frozen: a spec is never mutated in place ----------------------------------------


def test_app_spec_is_frozen() -> None:
    spec = blank_spec()
    with pytest.raises(ValidationError):
        spec.app_name = "changed"  # type: ignore[misc]  # ty: ignore[invalid-assignment]


def test_model_copy_returns_a_new_instance_with_the_field_changed() -> None:
    spec = blank_spec()
    revised = spec.model_copy(update={"app_name": "Renamed"})
    assert revised.app_name == "Renamed"
    assert spec.app_name == ""  # the original is untouched


# ---- page behavior: popups + on-click, and the page.design.md tree -------------------


def test_page_behavior_popup_and_open_popup_action_round_trips() -> None:
    got = AppSpec.model_validate(_load("popup_on_click"))
    page = got.personas.views[0].pages[0]
    assert page.popups[0].name == "Detail"
    assert page.on_click[0].kind is ClickActionKind.OPEN_POPUP
    assert page.on_click[0].target_popup == "Detail" and page.on_click[0].script is None
    assert page.on_click[1].kind is ClickActionKind.JS_ACTION
    assert page.on_click[1].script and page.on_click[1].target_popup is None


def test_page_design_tree_round_trips() -> None:
    got = AppSpec.model_validate(_load("page_design_tree"))
    page = got.personas.views[0].pages[0]
    design = page.design
    assert design is not None
    assert design.children[0].children[0].style[0] == (
        "Label.Color",
        "token:Color.White",
    )
    widget = design.children[1].children[0].widget
    assert widget is not None
    assert widget.slug == "view/form"


def test_a_page_carrying_no_design_stays_none() -> None:
    got = AppSpec.model_validate(_load("full"))
    assert got.personas.views[0].pages[0].design is None


def test_visibility_entry_role_claim_round_trips() -> None:
    got = AppSpec.model_validate(_load("visibility_role_claim"))
    assert got.visibility.entries[0].role == "Finance"


# ---- constructing the tree directly (not just from a golden dict) also validates -----


def test_constructing_the_tree_directly_validates_and_coerces() -> None:
    spec = AppSpec.model_validate(
        {
            **blank_spec().model_dump(mode="json"),
            "app_name": "Direct",
            "problem_goal": ProblemGoal(
                pain="p",
                goal="g",
                done_definition="d",
                terminal_states=("Done",),
                result_values=("Ok",),
            ).model_dump(mode="json"),
            "data_model": DataModel(
                fields=(
                    FieldReq(name="F", type=FieldType.TEXT, required=True, stage="S"),
                ),
                tables=(),
                computed=(),
            ).model_dump(mode="json"),
        }
    )
    assert spec.app_name == "Direct"
    assert spec.data_model.fields[0].type is FieldType.TEXT


def test_design_node_self_reference_and_widget_intent_construct_directly() -> None:
    """DesignNode is self-referential (`children: tuple[DesignNode, ...]`) --
    constructing one outside a round trip exercises Pydantic's own forward-reference
    resolution directly.
    """
    node = DesignNode(
        kind="container",
        children=(
            DesignNode(kind="widget", widget=WidgetIntent(slug="general/label")),
        ),
    )
    assert node.children[0].widget is not None
    assert node.children[0].widget.slug == "general/label"


def test_page_intent_and_persona_view_construct_directly() -> None:
    page = PageIntent(name="Board", widgets=(WidgetIntent(slug="general/label"),))
    view = PersonaView(role="Manager", pages=(page,), kpis=(), actions=())
    assert view.pages[0].name == "Board"


def test_popup_and_on_click_construct_directly() -> None:
    popup = PopupIntent(name="Detail", widgets=())
    action = OnClickAction(
        action="Show", kind=ClickActionKind.OPEN_POPUP, target_popup="Detail"
    )
    assert popup.name == "Detail"
    assert action.kind is ClickActionKind.OPEN_POPUP
