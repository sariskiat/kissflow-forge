"""Spec for kfforge.expr — Expression/Node AST builder for branch conditions and GotoTask loop
gates. Offline, synthetic draft from tests/synthetic.py + raw dict surgery — no live Kissflow
calls, no real-app content (CLAUDE.md BLINDNESS discipline: placeholder literals only, e.g.
"Option A", matching the fields tests/synthetic.py already defines).
"""
from __future__ import annotations

import copy
from typing import Any

import pytest
from synthetic import OWNERS, synthetic_process_draft

from kfforge.expr import (
    build_branch_condition,
    build_goto_gate,
    expression_owner,
    remove_condition,
    rewire_condition,
)
from kfforge.graph import progressive_matrix, set_step_permissions
from kfforge.verify import doctor

Draft = dict[str, Any]


def _nodes_of(draft: Draft, **criteria: Any) -> list[dict[str, Any]]:
    """Every node dict matching all the given key=value criteria."""
    return [v for v in draft.values()
            if isinstance(v, dict) and all(v.get(k) == val for k, val in criteria.items())]


def _one(draft: Draft, **criteria: Any) -> dict[str, Any]:
    hits = _nodes_of(draft, **criteria)
    assert len(hits) == 1, f"fixture drift: expected exactly one match for {criteria}, got {len(hits)}"
    return hits[0]


# ---- fixtures -------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def clean_draft() -> Draft:
    """A fully-formed, fully-permissioned process draft — same recipe as test_verify.py's
    clean_draft, so `verify.doctor` genuinely has nothing to complain about before any of this
    module's own mutations land on top of it."""
    draft = synthetic_process_draft()
    owners = {**OWNERS, "Other": ["Wrap-up report"]}
    matrix = progressive_matrix(draft, owners)
    return set_step_permissions(draft, matrix)


@pytest.fixture()
def branch_pd_id(clean_draft: Draft) -> str:
    return _one(clean_draft, Kind="ProcessDef", Name="Path A")["Id"]


@pytest.fixture()
def select_field_id(clean_draft: Draft) -> str:
    return _one(clean_draft, Kind="Field", Name="Route Choice")["Id"]


@pytest.fixture()
def urgency_field_id(clean_draft: Draft) -> str:
    return _one(clean_draft, Kind="Field", Name="Urgency")["Id"]


@pytest.fixture()
def text_field_id(clean_draft: Draft) -> str:
    return _one(clean_draft, Kind="Field", Name="Ticket No")["Id"]


@pytest.fixture()
def boolean_field_id(clean_draft: Draft) -> str:
    return _one(clean_draft, Kind="Field", Name="Bench Done")["Id"]


@pytest.fixture()
def deep_done_field_id(clean_draft: Draft) -> str:
    return _one(clean_draft, Kind="Field", Name="Deep Done")["Id"]


@pytest.fixture()
def draft_with_bare_goto(clean_draft: Draft) -> tuple[Draft, str]:
    """Layer ONE bare (conditionless) GotoTask onto a copy of the clean draft via raw dict
    surgery, so build_goto_gate has a real, otherwise-untouched Activity to attach a condition
    to. Kept separate from tests/synthetic.py's own with_goto_and_event (which already carries a
    condition) so this module's assertions are about ITS OWN mutation, not a pre-existing one.
    Shape matches synthetic.py's with_goto_and_event exactly (same GotoTask wiring), minus the
    condition — that absence is expected to make `doctor` flag "loops forever" until
    build_goto_gate is applied, which is exactly the case each test below exercises.
    """
    new = copy.deepcopy(clean_draft)
    root = new["Root"]
    pd_id = new[root]["RootProcessDef"]
    pd = new[pd_id]
    chain = list(pd["ProcessDef::Activity"])
    target_id = chain[1]                             # first real step after Start

    goto_id = "Activity_SampleBareGoto01"
    new[goto_id] = {"Id": goto_id, "Kind": "Activity", "NodeType": "GotoTask",
                    "Name": "Goto-Sample Bare", "ProcessDef": pd_id,
                    "CreatedAt": "2026-01-01T00:00:00.000Z", "Goto": target_id}
    new[target_id].setdefault("Goto::Activity", []).append(goto_id)
    pd["ProcessDef::Activity"] = [*chain, goto_id]
    return new, goto_id


@pytest.fixture()
def draft_with_branch_condition(
    clean_draft: Draft, branch_pd_id: str, select_field_id: str,
) -> tuple[Draft, str]:
    got = build_branch_condition(clean_draft, process_def_id=branch_pd_id,
                                 field_id=select_field_id, literal="Option A", options=None)
    expr = _one(got, Kind="Expression", ProcessDef=branch_pd_id)
    return got, expr["Id"]


@pytest.fixture()
def draft_with_goto_condition(
    draft_with_bare_goto: tuple[Draft, str], boolean_field_id: str,
) -> tuple[Draft, str, str]:
    draft, goto_id = draft_with_bare_goto
    got = build_goto_gate(draft, goto_activity_id=goto_id, field_id=boolean_field_id)
    expr = _one(got, Kind="Expression", Activity=goto_id)
    return got, expr["Id"], goto_id


@pytest.fixture()
def draft_with_legacy_select_goto_condition(
    draft_with_bare_goto: tuple[Draft, str], select_field_id: str,
) -> tuple[Draft, str, str]:
    """A goto condition shaped like the ORIGINAL captured branch gate before its historical
    rewire (research/goto_condition_shape.json, cross-checked against shapes/expression_goto_
    condition.json's notes): Activity-owned, comparing a Select field against a Static literal.
    `build_goto_gate` itself can never produce this shape — it only ever writes Boolean+false() —
    so this is hand-built via raw dict surgery, exactly the "offline ... + raw dict surgery"
    testing convention this module already uses elsewhere. This is the real legacy shape
    `rewire_condition` must still accept AS INPUT and correctly convert.
    """
    new, goto_id = draft_with_bare_goto

    expr_id = "Expression_SLegacySelectGoto01"
    root_id = "Node_SLegacyRoot01"
    lhs_id = "Node_SLegacyLhs01"
    rhs_id = "Node_SLegacyRhs01"

    new[lhs_id] = {"Id": lhs_id, "Kind": "Node", "Type": "Field", "Field": select_field_id,
                   "DataType": "String", "Node": root_id}
    new[rhs_id] = {"Id": rhs_id, "Kind": "Node", "Type": "Static", "Value": "Option A",
                   "DataType": "String", "Node": root_id}
    new[root_id] = {"Id": root_id, "Kind": "Node", "Type": "Function", "Value": "=",
                    "Syntax": "Infix", "Expression": expr_id, "FieldRefCount": 1,
                    "Node::Node": [lhs_id, rhs_id], "DataType": "Boolean", "Category": "String"}
    new[expr_id] = {"Id": expr_id, "Kind": "Expression",
                    "ExpressionStr": f'{select_field_id} = "Option A"',
                    "Activity": goto_id, "Expression::Node": [root_id]}
    new[goto_id]["Activity::Expression"] = [expr_id]
    new[select_field_id].setdefault("Field::Node", []).append(lhs_id)

    return new, expr_id, goto_id


# ---- baseline sanity --------------------------------------------------------------------------

def test_clean_draft_fixture_is_actually_clean(clean_draft: Draft) -> None:
    assert doctor(clean_draft).ok(), "fixture drift: clean_draft must be clean before any mutation"


# ---- expression_owner ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "node,expected",
    [
        ({"Id": "Expression_SBranch01", "ProcessDef": "ProcessDef_SSample01"}, "branch"),
        ({"Id": "Expression_SGoto01", "Activity": "Activity_SSample01"}, "goto"),
        ({"Id": "Expression_SProp01", "Property": "Property_SSample01"}, "property"),
    ],
)
def test_expression_owner_classifies_by_owner_key(node: dict[str, Any], expected: str) -> None:
    assert expression_owner(node) == expected


def test_expression_owner_raises_when_no_owner_key_present() -> None:
    with pytest.raises(ValueError):
        expression_owner({"Id": "Expression_SOrphan01", "ExpressionStr": "sample"})


def test_expression_owner_raises_when_owner_keys_are_ambiguous() -> None:
    with pytest.raises(ValueError):
        expression_owner({"Id": "Expression_SAmbig01",
                          "ProcessDef": "ProcessDef_SSample01", "Activity": "Activity_SSample01"})


# ---- build_branch_condition -----------------------------------------------------------------

def test_build_branch_condition_full_node_set(
    clean_draft: Draft, branch_pd_id: str, select_field_id: str,
) -> None:
    got = build_branch_condition(clean_draft, process_def_id=branch_pd_id,
                                 field_id=select_field_id, literal="Option A", options=None)

    expr = _one(got, Kind="Expression", ProcessDef=branch_pd_id)
    assert expr["ExpressionStr"] == f'{select_field_id} = "Option A"'
    assert len(expr["Expression::Node"]) == 1
    root_id = expr["Expression::Node"][0]
    root = got[root_id]

    assert root["Type"] == "Function" and root["Value"] == "="
    assert root["Syntax"] == "Infix"
    assert root["DataType"] == "Boolean"
    assert root["Category"] == "String"            # operand class for a Select comparison
    assert root["FieldRefCount"] == 1
    assert root["Expression"] == expr["Id"]         # bidirectional owner back-ref on the root

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
    assert doctor(got).ok()


def test_build_branch_condition_accepts_text_field(
    clean_draft: Draft, branch_pd_id: str, text_field_id: str,
) -> None:
    """Text is the same string-on-the-wire representation as Select — see the _BRANCH_FIELD_
    DATA_TYPE comment in kfforge.expr for why it, and only it besides Select, is included."""
    got = build_branch_condition(clean_draft, process_def_id=branch_pd_id,
                                 field_id=text_field_id, literal="Option A", options=None)
    expr = _one(got, Kind="Expression", ProcessDef=branch_pd_id)
    root_id = expr["Expression::Node"][0]
    assert got[root_id]["Category"] == "String"
    assert doctor(got).ok()


def test_build_branch_condition_input_not_mutated(
    clean_draft: Draft, branch_pd_id: str, select_field_id: str,
) -> None:
    before = copy.deepcopy(clean_draft)
    _ = build_branch_condition(clean_draft, process_def_id=branch_pd_id,
                               field_id=select_field_id, literal="Option A", options=None)
    assert clean_draft == before


def test_build_branch_condition_literal_outside_options_rejected_before_mutation(
    clean_draft: Draft, branch_pd_id: str, select_field_id: str,
) -> None:
    before = copy.deepcopy(clean_draft)
    with pytest.raises(ValueError):
        build_branch_condition(clean_draft, process_def_id=branch_pd_id, field_id=select_field_id,
                               literal="Not A Real Option", options=["Option A", "Option B"])
    assert clean_draft == before, "a literal that cannot match must never be written, not even partially"


def test_build_branch_condition_literal_inside_options_accepted(
    clean_draft: Draft, branch_pd_id: str, select_field_id: str,
) -> None:
    got = build_branch_condition(clean_draft, process_def_id=branch_pd_id, field_id=select_field_id,
                                 literal="Option A", options=["Option A", "Option B"])
    assert doctor(got).ok()


def test_build_branch_condition_options_none_is_allowed(
    clean_draft: Draft, branch_pd_id: str, select_field_id: str,
) -> None:
    """options=None skips validation entirely — the caller owns the risk (CLAUDE.md: "never guess
    a literal", but an explicit None is not a guess, it is the caller's own informed choice)."""
    got = build_branch_condition(clean_draft, process_def_id=branch_pd_id, field_id=select_field_id,
                                 literal="Whatever The Caller Wants", options=None)
    expr = _one(got, Kind="Expression", ProcessDef=branch_pd_id)
    assert expr["ExpressionStr"] == f'{select_field_id} = "Whatever The Caller Wants"'


def test_build_branch_condition_unknown_process_def_rejected(
    clean_draft: Draft, select_field_id: str,
) -> None:
    before = copy.deepcopy(clean_draft)
    with pytest.raises(ValueError):
        build_branch_condition(clean_draft, process_def_id="ProcessDef_DoesNotExist99",
                               field_id=select_field_id, literal="Option A", options=None)
    assert clean_draft == before


def test_build_branch_condition_unknown_field_rejected(clean_draft: Draft, branch_pd_id: str) -> None:
    before = copy.deepcopy(clean_draft)
    with pytest.raises(ValueError):
        build_branch_condition(clean_draft, process_def_id=branch_pd_id,
                               field_id="Field_DoesNotExist99", literal="Option A", options=None)
    assert clean_draft == before


def test_build_branch_condition_rejects_uncaptured_field_type(
    clean_draft: Draft, branch_pd_id: str, boolean_field_id: str,
) -> None:
    """A Boolean field compared via a Static literal is an uncaptured wire shape — build_goto_gate
    owns the Boolean/false() combination, never a Static (CLAUDE.md Expressions)."""
    before = copy.deepcopy(clean_draft)
    with pytest.raises(ValueError):
        build_branch_condition(clean_draft, process_def_id=branch_pd_id,
                               field_id=boolean_field_id, literal="Option A", options=None)
    assert clean_draft == before


def test_build_branch_condition_twice_with_identical_args_does_not_duplicate_backrefs(
    clean_draft: Draft, branch_pd_id: str, select_field_id: str,
) -> None:
    """Ids are deterministic (hash of process_def_id/field_id/literal), so a repeat call with
    identical args overwrites the same Expression/Node dicts idempotently — but the LIST-shaped
    back-refs (ProcessDef::Expression, Field::Node) must not gain a second entry for the same node
    id. No UI-built flow ever produced a back-ref list with a repeated id."""
    once = build_branch_condition(clean_draft, process_def_id=branch_pd_id,
                                  field_id=select_field_id, literal="Option A", options=None)
    twice = build_branch_condition(once, process_def_id=branch_pd_id,
                                   field_id=select_field_id, literal="Option A", options=None)

    pd_expr_ids = twice[branch_pd_id]["ProcessDef::Expression"]
    assert len(pd_expr_ids) == len(set(pd_expr_ids)), "ProcessDef::Expression must not repeat an id"

    field_node_ids = twice[select_field_id]["Field::Node"]
    assert len(field_node_ids) == len(set(field_node_ids)), "Field::Node must not repeat an id"

    assert doctor(twice).ok()


# ---- build_goto_gate --------------------------------------------------------------------------

def test_build_goto_gate_zero_arg_false_literal_shape(
    draft_with_bare_goto: tuple[Draft, str], boolean_field_id: str,
) -> None:
    draft, goto_id = draft_with_bare_goto
    got = build_goto_gate(draft, goto_activity_id=goto_id, field_id=boolean_field_id)

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

    # the zero-arg false() literal: a Function, never a Static — and unlike the infix root, no
    # Syntax and no Node::Node (CLAUDE.md: "No Node::Node, no Syntax key")
    assert rhs["Type"] == "Function" and rhs["Value"] == "false"
    assert rhs["DataType"] == "Boolean" and rhs["Category"] == "Boolean"
    assert "Syntax" not in rhs
    assert "Node::Node" not in rhs

    assert lhs_id in got[boolean_field_id]["Field::Node"]
    assert expr["Id"] in got[goto_id]["Activity::Expression"]
    assert expression_owner(expr) == "goto"
    assert doctor(got).ok()


def test_build_goto_gate_input_not_mutated(
    draft_with_bare_goto: tuple[Draft, str], boolean_field_id: str,
) -> None:
    draft, goto_id = draft_with_bare_goto
    before = copy.deepcopy(draft)
    _ = build_goto_gate(draft, goto_activity_id=goto_id, field_id=boolean_field_id)
    assert draft == before


def test_build_goto_gate_rejects_non_boolean_field(
    draft_with_bare_goto: tuple[Draft, str], select_field_id: str,
) -> None:
    """Gate polarity: an optional Select fails OPEN (silently escapes the loop) — never allowed
    to gate a GotoTask (CLAUDE.md Gate polarity)."""
    draft, goto_id = draft_with_bare_goto
    before = copy.deepcopy(draft)
    with pytest.raises(ValueError):
        build_goto_gate(draft, goto_activity_id=goto_id, field_id=select_field_id)
    assert draft == before


def test_build_goto_gate_unknown_activity_rejected(clean_draft: Draft, boolean_field_id: str) -> None:
    before = copy.deepcopy(clean_draft)
    with pytest.raises(ValueError):
        build_goto_gate(clean_draft, goto_activity_id="Activity_DoesNotExist99",
                        field_id=boolean_field_id)
    assert clean_draft == before


def test_build_goto_gate_unknown_field_rejected(draft_with_bare_goto: tuple[Draft, str]) -> None:
    draft, goto_id = draft_with_bare_goto
    before = copy.deepcopy(draft)
    with pytest.raises(ValueError):
        build_goto_gate(draft, goto_activity_id=goto_id, field_id="Field_DoesNotExist99")
    assert draft == before


# ---- remove_condition -------------------------------------------------------------------------
# The SET-semantics counterpart to build_branch_condition/build_goto_gate: a caller that wants
# "this branch/goto's condition is now X" needs the OLD one gone first, or a re-run with a changed
# field/literal mints a second Expression alongside the stale one (different id, since the id is a
# hash of the args) rather than replacing it.

def test_remove_branch_condition_deletes_expression_and_node_subtree(
    draft_with_branch_condition: tuple[Draft, str], branch_pd_id: str, select_field_id: str,
) -> None:
    draft, expr_id = draft_with_branch_condition
    root_id = draft[expr_id]["Expression::Node"][0]
    lhs_id, rhs_id = draft[root_id]["Node::Node"]

    got = remove_condition(draft, expression_id=expr_id)

    assert expr_id not in got and root_id not in got and lhs_id not in got and rhs_id not in got
    assert expr_id not in (got[branch_pd_id].get("ProcessDef::Expression") or [])
    assert lhs_id not in (got[select_field_id].get("Field::Node") or [])
    assert doctor(got).ok()


def test_remove_goto_condition_deletes_expression_and_node_subtree(
    draft_with_goto_condition: tuple[Draft, str, str], boolean_field_id: str,
) -> None:
    draft, expr_id, goto_id = draft_with_goto_condition
    root_id = draft[expr_id]["Expression::Node"][0]
    lhs_id, rhs_id = draft[root_id]["Node::Node"]

    got = remove_condition(draft, expression_id=expr_id)

    assert expr_id not in got and root_id not in got and lhs_id not in got and rhs_id not in got
    assert expr_id not in (got[goto_id].get("Activity::Expression") or [])
    assert lhs_id not in (got[boolean_field_id].get("Field::Node") or [])
    # doctor still complains the goto has NO condition -- correct, we just removed it on purpose
    assert any("NO condition" in p for p in doctor(got).problems)


def test_remove_condition_input_not_mutated(
    draft_with_branch_condition: tuple[Draft, str],
) -> None:
    draft, expr_id = draft_with_branch_condition
    before = copy.deepcopy(draft)
    _ = remove_condition(draft, expression_id=expr_id)
    assert draft == before


def test_remove_condition_unknown_expression_rejected(clean_draft: Draft) -> None:
    before = copy.deepcopy(clean_draft)
    with pytest.raises(ValueError):
        remove_condition(clean_draft, expression_id="Expression_DoesNotExist99")
    assert clean_draft == before


def test_remove_condition_rejects_property_owned_expression(clean_draft: Draft) -> None:
    draft = copy.deepcopy(clean_draft)
    draft["Property_SamplePrefix01"] = {"Id": "Property_SamplePrefix01", "Kind": "Property",
                                        "Name": "PrefixExpression", "ValueType": "Expression"}
    draft["Expression_SamplePrefix01"] = {
        "Id": "Expression_SamplePrefix01", "Kind": "Expression",
        "ExpressionStr": 'concatenate("SAMPLE")', "Property": "Property_SamplePrefix01",
    }
    before = copy.deepcopy(draft)
    with pytest.raises(ValueError):
        remove_condition(draft, expression_id="Expression_SamplePrefix01")
    assert draft == before


def test_remove_then_build_branch_condition_replaces_not_accumulates(
    clean_draft: Draft, branch_pd_id: str, select_field_id: str,
) -> None:
    """The actual SET workflow: build with one literal, remove, build again with a DIFFERENT
    literal on the SAME branch -> exactly one Expression on that ProcessDef, holding the NEW value,
    never two."""
    first = build_branch_condition(clean_draft, process_def_id=branch_pd_id,
                                   field_id=select_field_id, literal="Option A", options=None)
    first_expr_id = _one(first, Kind="Expression", ProcessDef=branch_pd_id)["Id"]

    cleared = remove_condition(first, expression_id=first_expr_id)
    second = build_branch_condition(cleared, process_def_id=branch_pd_id,
                                    field_id=select_field_id, literal="Option B", options=None)

    exprs = _nodes_of(second, Kind="Expression", ProcessDef=branch_pd_id)
    assert len(exprs) == 1, f"expected exactly one condition on the branch, got {len(exprs)}"
    assert exprs[0]["ExpressionStr"] == f'{select_field_id} = "Option B"'
    assert doctor(second).ok()


def test_remove_condition_recurses_into_a_nested_compound_condition(
    clean_draft: Draft, branch_pd_id: str, select_field_id: str, urgency_field_id: str,
) -> None:
    """No `build_*` function in this module ever writes deeper than root+2-leaves — but
    `apply_branch_conditions` calls `remove_condition` on ANY pre-existing ProcessDef Expression,
    including one a human built in the UI, and a compound AND/OR of two comparisons is a plausible
    deeper shape (uncaptured — this is a synthetic stand-in via raw dict surgery, the same
    convention `draft_with_legacy_select_goto_condition` already uses for an uncaptured shape, NOT
    a claim that "and" is the real captured operator string). A shallow (root, then direct
    children only) walk would delete the AND root and its two comparison sub-roots but strand
    THEIR leaf nodes — this pins that the walk goes all the way down instead.
    """
    draft = copy.deepcopy(clean_draft)
    expr_id = "Expression_SCompound01"
    and_root_id = "Node_SAndRoot01"
    cmp1_root_id, cmp1_lhs_id, cmp1_rhs_id = (
        "Node_SCmp1Root01", "Node_SCmp1Lhs01", "Node_SCmp1Rhs01",
    )
    cmp2_root_id, cmp2_lhs_id, cmp2_rhs_id = (
        "Node_SCmp2Root01", "Node_SCmp2Lhs01", "Node_SCmp2Rhs01",
    )

    draft[cmp1_lhs_id] = {"Id": cmp1_lhs_id, "Kind": "Node", "Type": "Field", "Field": select_field_id,
                          "DataType": "String", "Node": cmp1_root_id}
    draft[cmp1_rhs_id] = {"Id": cmp1_rhs_id, "Kind": "Node", "Type": "Static", "Value": "Option A",
                          "DataType": "String", "Node": cmp1_root_id}
    draft[cmp1_root_id] = {"Id": cmp1_root_id, "Kind": "Node", "Type": "Function", "Value": "=",
                           "Syntax": "Infix", "DataType": "Boolean", "Category": "String",
                           "Node::Node": [cmp1_lhs_id, cmp1_rhs_id], "Node": and_root_id}
    draft[cmp2_lhs_id] = {"Id": cmp2_lhs_id, "Kind": "Node", "Type": "Field", "Field": urgency_field_id,
                          "DataType": "String", "Node": cmp2_root_id}
    draft[cmp2_rhs_id] = {"Id": cmp2_rhs_id, "Kind": "Node", "Type": "Static", "Value": "High",
                          "DataType": "String", "Node": cmp2_root_id}
    draft[cmp2_root_id] = {"Id": cmp2_root_id, "Kind": "Node", "Type": "Function", "Value": "=",
                           "Syntax": "Infix", "DataType": "Boolean", "Category": "String",
                           "Node::Node": [cmp2_lhs_id, cmp2_rhs_id], "Node": and_root_id}
    draft[and_root_id] = {"Id": and_root_id, "Kind": "Node", "Type": "Function", "Value": "and",
                          "Syntax": "Infix", "DataType": "Boolean", "Expression": expr_id,
                          "Node::Node": [cmp1_root_id, cmp2_root_id]}
    draft[expr_id] = {"Id": expr_id, "Kind": "Expression",
                      "ExpressionStr": f'{select_field_id} = "Option A" and {urgency_field_id} = "High"',
                      "ProcessDef": branch_pd_id, "Expression::Node": [and_root_id]}
    draft[branch_pd_id].setdefault("ProcessDef::Expression", []).append(expr_id)
    draft[select_field_id].setdefault("Field::Node", []).append(cmp1_lhs_id)
    draft[urgency_field_id].setdefault("Field::Node", []).append(cmp2_lhs_id)

    got = remove_condition(draft, expression_id=expr_id)

    for nid in (expr_id, and_root_id, cmp1_root_id, cmp1_lhs_id, cmp1_rhs_id,
               cmp2_root_id, cmp2_lhs_id, cmp2_rhs_id):
        assert nid not in got, f"{nid} must be gone -- a shallow walk would strand it"
    assert expr_id not in (got[branch_pd_id].get("ProcessDef::Expression") or [])
    assert cmp1_lhs_id not in (got[select_field_id].get("Field::Node") or [])
    assert cmp2_lhs_id not in (got[urgency_field_id].get("Field::Node") or [])
    assert doctor(got).ok()


# ---- rewire_condition — branch (ProcessDef-owned) -------------------------------------------

def test_rewire_branch_condition_all_six_edits(
    draft_with_branch_condition: tuple[Draft, str], select_field_id: str, urgency_field_id: str,
) -> None:
    draft, expr_id = draft_with_branch_condition
    old_field_node_id = draft[select_field_id]["Field::Node"][0]

    got = rewire_condition(draft, expression_id=expr_id, new_field_id=urgency_field_id,
                           options=["Option A", "Option B"], new_literal="Option B")

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

    assert doctor(got).ok()


def test_rewire_branch_condition_input_not_mutated(
    draft_with_branch_condition: tuple[Draft, str], urgency_field_id: str,
) -> None:
    draft, expr_id = draft_with_branch_condition
    before = copy.deepcopy(draft)
    _ = rewire_condition(draft, expression_id=expr_id, new_field_id=urgency_field_id,
                         options=["Option A", "Option B"], new_literal="Option B")
    assert draft == before


def test_rewire_branch_condition_keeps_old_literal_when_new_literal_omitted(
    draft_with_branch_condition: tuple[Draft, str], urgency_field_id: str,
) -> None:
    draft, expr_id = draft_with_branch_condition
    got = rewire_condition(draft, expression_id=expr_id, new_field_id=urgency_field_id)
    root_id = got[expr_id]["Expression::Node"][0]
    _, rhs_id = got[root_id]["Node::Node"]
    assert got[rhs_id]["Value"] == "Option A"          # carried over from before the rewire
    assert doctor(got).ok()


def test_rewire_branch_condition_literal_outside_options_rejected(
    draft_with_branch_condition: tuple[Draft, str], urgency_field_id: str,
) -> None:
    draft, expr_id = draft_with_branch_condition
    before = copy.deepcopy(draft)
    with pytest.raises(ValueError):
        rewire_condition(draft, expression_id=expr_id, new_field_id=urgency_field_id,
                         options=["Option A", "Option B"], new_literal="Not Real")
    assert draft == before


def test_rewire_branch_condition_rejects_uncaptured_field_type(
    draft_with_branch_condition: tuple[Draft, str], boolean_field_id: str,
) -> None:
    draft, expr_id = draft_with_branch_condition
    before = copy.deepcopy(draft)
    with pytest.raises(ValueError):
        rewire_condition(draft, expression_id=expr_id, new_field_id=boolean_field_id)
    assert draft == before


def test_rewire_unknown_new_field_leaves_draft_untouched(
    draft_with_branch_condition: tuple[Draft, str],
) -> None:
    draft, expr_id = draft_with_branch_condition
    before = copy.deepcopy(draft)
    with pytest.raises(ValueError):
        rewire_condition(draft, expression_id=expr_id, new_field_id="Field_DoesNotExist99")
    assert draft == before


def test_rewire_unknown_expression_leaves_draft_untouched(
    draft_with_branch_condition: tuple[Draft, str], urgency_field_id: str,
) -> None:
    draft, _expr_id = draft_with_branch_condition
    before = copy.deepcopy(draft)
    with pytest.raises(ValueError):
        rewire_condition(draft, expression_id="Expression_DoesNotExist99", new_field_id=urgency_field_id)
    assert draft == before


def test_rewire_rejects_property_owned_expression(clean_draft: Draft, urgency_field_id: str) -> None:
    """A SequenceNumber prefix Expression is Property-owned, not a condition — never rewired
    (CLAUDE.md: three owner keys mean three different things; Property is not routing)."""
    draft = copy.deepcopy(clean_draft)
    draft["Property_SamplePrefix01"] = {"Id": "Property_SamplePrefix01", "Kind": "Property",
                                        "Name": "PrefixExpression", "ValueType": "Expression"}
    draft["Expression_SamplePrefix01"] = {
        "Id": "Expression_SamplePrefix01", "Kind": "Expression",
        "ExpressionStr": 'concatenate("SAMPLE")', "Property": "Property_SamplePrefix01",
    }
    before = copy.deepcopy(draft)
    with pytest.raises(ValueError):
        rewire_condition(draft, expression_id="Expression_SamplePrefix01",
                         new_field_id=urgency_field_id)
    assert draft == before


def test_rewire_condition_rejects_when_literal_child_is_not_static_or_function(
    clean_draft: Draft, branch_pd_id: str, select_field_id: str, urgency_field_id: str,
) -> None:
    """Two Field-type children (a field-vs-field comparison) is a malformed/uncaptured AST that no
    build_* function here ever writes. Silently treating the second Field as "the literal" would
    overwrite a real field reference instead of refusing — this pins the explicit refusal."""
    draft = copy.deepcopy(clean_draft)
    expr_id = "Expression_SMalformed01"
    root_id = "Node_SMalformedRoot01"
    lhs_id = "Node_SMalformedLhs01"
    rhs_id = "Node_SMalformedRhs01"           # also Type Field — malformed, not Static/Function

    draft[lhs_id] = {"Id": lhs_id, "Kind": "Node", "Type": "Field", "Field": select_field_id,
                     "DataType": "String", "Node": root_id}
    draft[rhs_id] = {"Id": rhs_id, "Kind": "Node", "Type": "Field", "Field": urgency_field_id,
                     "DataType": "String", "Node": root_id}
    draft[root_id] = {"Id": root_id, "Kind": "Node", "Type": "Function", "Value": "=",
                      "Syntax": "Infix", "Expression": expr_id, "FieldRefCount": 2,
                      "Node::Node": [lhs_id, rhs_id], "DataType": "Boolean", "Category": "String"}
    draft[expr_id] = {"Id": expr_id, "Kind": "Expression",
                      "ExpressionStr": f"{select_field_id} = {urgency_field_id}",
                      "ProcessDef": branch_pd_id, "Expression::Node": [root_id]}
    draft[branch_pd_id].setdefault("ProcessDef::Expression", []).append(expr_id)
    draft[select_field_id].setdefault("Field::Node", []).append(lhs_id)
    draft[urgency_field_id].setdefault("Field::Node", []).append(rhs_id)

    before = copy.deepcopy(draft)
    with pytest.raises(ValueError):
        rewire_condition(draft, expression_id=expr_id, new_field_id=urgency_field_id)
    assert draft == before


# ---- rewire_condition — goto (Activity-owned) -------------------------------------------------

def test_rewire_goto_condition_all_six_edits(
    draft_with_goto_condition: tuple[Draft, str, str], boolean_field_id: str, deep_done_field_id: str,
) -> None:
    draft, expr_id, _goto_id = draft_with_goto_condition
    old_field_node_id = draft[boolean_field_id]["Field::Node"][0]

    got = rewire_condition(draft, expression_id=expr_id, new_field_id=deep_done_field_id)

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
    assert doctor(got).ok()


def test_rewire_goto_condition_input_not_mutated(
    draft_with_goto_condition: tuple[Draft, str, str], deep_done_field_id: str,
) -> None:
    draft, expr_id, _goto_id = draft_with_goto_condition
    before = copy.deepcopy(draft)
    _ = rewire_condition(draft, expression_id=expr_id, new_field_id=deep_done_field_id)
    assert draft == before


def test_rewire_goto_condition_rejects_non_boolean_new_field(
    draft_with_goto_condition: tuple[Draft, str, str], select_field_id: str,
) -> None:
    draft, expr_id, _goto_id = draft_with_goto_condition
    before = copy.deepcopy(draft)
    with pytest.raises(ValueError):
        rewire_condition(draft, expression_id=expr_id, new_field_id=select_field_id)
    assert draft == before


def test_rewire_goto_condition_rejects_new_literal(
    draft_with_goto_condition: tuple[Draft, str, str], deep_done_field_id: str,
) -> None:
    """A goto gate is always tested against false() — there is no other captured shape, so a
    caller-supplied literal is refused rather than silently ignored."""
    draft, expr_id, _goto_id = draft_with_goto_condition
    before = copy.deepcopy(draft)
    with pytest.raises(ValueError):
        rewire_condition(draft, expression_id=expr_id, new_field_id=deep_done_field_id,
                         new_literal="true")
    assert draft == before


def test_rewire_goto_condition_from_legacy_select_static_to_boolean_false(
    draft_with_legacy_select_goto_condition: tuple[Draft, str, str],
    select_field_id: str, deep_done_field_id: str,
) -> None:
    """Pins the production op the reviewer hand-ran: a goto gated on a Select field with a Static
    literal (the real shape a UI-built flow can carry — research/goto_condition_shape.json's
    original branch-gate capture, before its historical rewire) taken through rewire_condition
    onto a Boolean field. Must land on exactly the shape build_goto_gate itself writes: the
    zero-arg false() Function, with no Syntax and no Node::Node on that leaf.
    """
    draft, expr_id, _goto_id = draft_with_legacy_select_goto_condition
    old_field_node_id = draft[select_field_id]["Field::Node"][-1]

    got = rewire_condition(draft, expression_id=expr_id, new_field_id=deep_done_field_id)

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
    assert doctor(got).ok()
