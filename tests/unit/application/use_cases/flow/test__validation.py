"""`_validation`: the read-back audit helpers `ForgeAddFieldValidation` uses.
Ported from `tests/test_client.py`'s `apply_field_validation` audit cases
(pre-refactor)."""

from __future__ import annotations

from app.application.use_cases.flow._validation import (
    _audit_all_field_rules,
    _calc_missing,
    _condition_rule,
    _criteria_conditions,
    _field_live_rules,
    _field_map,
    _node_child_ids,
)


def _draft() -> dict:
    return {
        "Field1": {
            "Kind": "Field",
            "Name": "Notes",
            "FieldValidation::Criteria": ["Crit1"],
        },
        "Crit1": {"Kind": "Criteria", "Criteria::Condition": ["Cond1", "Cond2"]},
        "Cond1": {"Operator": "CONTAINS", "RHSValue": "important"},
        "Cond2": {"Operator": "MAX_LENGTH", "RHSValue": "200"},
    }


def test_node_child_ids_reads_the_relation_list() -> None:
    draft = _draft()
    assert _node_child_ids(draft, "Crit1", "Criteria::Condition") == [
        "Cond1",
        "Cond2",
    ]


def test_node_child_ids_empty_when_node_missing_or_malformed() -> None:
    draft = _draft()
    assert _node_child_ids(draft, "Ghost", "Criteria::Condition") == []
    assert _node_child_ids(draft, "Field1", "Criteria::Condition") == []


def test_condition_rule_reads_operator_and_stringifies_the_value() -> None:
    assert _condition_rule({"Operator": "CONTAINS", "RHSValue": "x"}) == (
        "CONTAINS",
        "x",
    )
    assert _condition_rule({"Operator": "GT", "RHSValue": 5}) == ("GT", "5")


def test_condition_rule_none_for_a_malformed_condition() -> None:
    assert _condition_rule("not a dict") is None
    assert _condition_rule({"RHSValue": "x"}) is None  # no Operator


def test_criteria_conditions_unions_every_child_rule() -> None:
    draft = _draft()
    assert _criteria_conditions(draft, "Crit1") == {
        ("CONTAINS", "important"),
        ("MAX_LENGTH", "200"),
    }


def test_field_live_rules_reads_through_every_criteria() -> None:
    draft = _draft()
    assert _field_live_rules(draft, draft["Field1"]) == {
        ("CONTAINS", "important"),
        ("MAX_LENGTH", "200"),
    }


def test_field_live_rules_empty_when_no_criteria_list() -> None:
    assert _field_live_rules({}, {"Name": "X"}) == set()


def test_field_map_keys_every_field_node_by_name() -> None:
    draft = _draft()
    assert _field_map(draft) == {"Notes": draft["Field1"]}


def test_audit_all_field_rules_flattens_and_verifies() -> None:
    draft = _draft()
    flat, verified = _audit_all_field_rules(
        draft, {"Notes": [("CONTAINS", "important"), ("MAX_LENGTH", "200")]}
    )
    assert flat == [("CONTAINS", "important"), ("MAX_LENGTH", "200")]
    assert verified == [("CONTAINS", "important"), ("MAX_LENGTH", "200")]


def test_audit_all_field_rules_reports_a_rule_that_never_landed() -> None:
    draft = _draft()
    flat, verified = _audit_all_field_rules(draft, {"Notes": [("CONTAINS", "xyz")]})
    assert flat == [("CONTAINS", "xyz")]
    assert verified == []


def test_calc_missing_is_flat_minus_verified_in_flat_order() -> None:
    flat = [("A", "1"), ("B", "2"), ("C", "3")]
    verified = [("B", "2")]
    assert _calc_missing(flat, verified) == (("A", "1"), ("C", "3"))


def test_calc_missing_empty_when_everything_verified() -> None:
    flat = [("A", "1")]
    assert _calc_missing(flat, flat) == ()
