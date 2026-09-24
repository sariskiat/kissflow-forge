"""`_table`: the read-back audit helpers `ForgeAddTable` uses to find a
table's host Column, its nested Model, and partition wanted columns into
verified/missing. Ported from `tests/test_client.py`'s `apply_table` audit
cases (pre-refactor)."""

from __future__ import annotations

from app.application.use_cases.flow._table import (
    _audit_table_columns,
    _find_table_host,
    _is_table_host,
    _table_child_field_names,
    _table_live_columns,
    _table_model_node,
)


def _table_draft() -> dict:
    return {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Type": "Model", "Model::Row": ["R1"]},
        "R1": {"Id": "R1", "Kind": "Row", "Row::Column": ["Host1"]},
        "Host1": {
            "Id": "Host1",
            "Kind": "Column",
            "Type": "Model",
            "Name": "Rounds",
            "Column::Model": ["Table1"],
        },
        "Table1": {
            "Id": "Table1",
            "Kind": "Model",
            "Type": "Model",
            "Model::Field": ["F1", "F2"],
        },
        "F1": {"Id": "F1", "Kind": "Field", "Name": "Round"},
        "F2": {"Id": "F2", "Kind": "Field", "Name": "Notes"},
    }


def test_is_table_host_matches_a_model_column_by_name() -> None:
    draft = _table_draft()
    assert _is_table_host(draft["Host1"], "Rounds") is True
    assert _is_table_host(draft["Host1"], "Other") is False
    assert _is_table_host("not a dict", "Rounds") is False
    assert _is_table_host({"Type": "Section", "Name": "Rounds"}, "Rounds") is False


def test_find_table_host_returns_none_when_absent() -> None:
    draft = _table_draft()
    assert _find_table_host(draft, "Rounds") is draft["Host1"]
    assert _find_table_host(draft, "NoSuchTable") is None


def test_table_model_node_resolves_through_column_model() -> None:
    draft = _table_draft()
    node = _table_model_node(draft, draft["Host1"])
    assert node is draft["Table1"]


def test_table_model_node_none_when_no_column_model_ids() -> None:
    draft = _table_draft()
    assert _table_model_node(draft, {"Id": "Host2"}) is None


def test_table_model_node_none_when_the_referenced_id_does_not_resolve() -> None:
    draft = _table_draft()
    host = {"Id": "Host2", "Column::Model": ["Missing"]}
    assert _table_model_node(draft, host) is None


def test_table_child_field_names_skips_unresolved_or_nameless_ids() -> None:
    draft = _table_draft()
    table = dict(draft["Table1"])
    table["Model::Field"] = ["F1", "F2", "Ghost", "Malformed"]
    draft["Malformed"] = {"Id": "Malformed"}  # a dict with no Name key
    names = _table_child_field_names(draft, table)
    assert names == {"Round", "Notes"}


def test_table_live_columns_end_to_end() -> None:
    draft = _table_draft()
    assert _table_live_columns(draft, "Rounds") == {"Round", "Notes"}


def test_table_live_columns_empty_when_host_missing() -> None:
    draft = _table_draft()
    assert _table_live_columns(draft, "NoSuchTable") == set()


def test_table_live_columns_empty_when_table_model_missing() -> None:
    draft = _table_draft()
    draft["Host1"]["Column::Model"] = []
    assert _table_live_columns(draft, "Rounds") == set()


def test_audit_table_columns_partitions_every_wanted_name() -> None:
    verified, missing = _audit_table_columns(
        ("Round", "Notes", "Ghost"), {"Round", "Notes"}
    )
    assert verified == ("Round", "Notes")
    assert missing == ("Ghost",)


def test_audit_table_columns_empty_wanted_is_empty_both_ways() -> None:
    verified, missing = _audit_table_columns((), {"Round"})
    assert verified == ()
    assert missing == ()
