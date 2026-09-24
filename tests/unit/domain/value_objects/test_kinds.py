"""Pin every closed vocabulary in `app.domain.value_objects.kinds` to its exact member
set.

`client.py` and `server.py` import these aliases rather than defining their own copies
(refactor spec, Stage C shared pieces); a member silently added or removed here would
change the JSON schema every MCP tool that uses it emits, so each one is pinned by
`typing.get_args`.
"""

from __future__ import annotations

from typing import get_args

from app.domain.value_objects import kinds


def test_flow_kind_is_the_three_publishable_kinds() -> None:
    assert get_args(kinds.FlowKind) == ("form", "process", "case")


def test_flow_kind_arg_is_the_same_object_as_flow_kind() -> None:
    """`FlowKindArg` is a re-export, not a second definition -- the two must
    never drift apart."""
    assert kinds.FlowKindArg is kinds.FlowKind


def test_schema_kind_adds_dataset_and_page() -> None:
    assert get_args(kinds.SchemaKind) == ("form", "process", "case", "dataset", "page")


def test_data_kind_adds_dataset_only() -> None:
    assert get_args(kinds.DataKind) == ("form", "process", "case", "dataset")


def test_any_flow_kind_adds_list_and_dataset() -> None:
    assert get_args(kinds.AnyFlowKind) == (
        "form",
        "process",
        "case",
        "list",
        "dataset",
    )


def test_delete_kind_adds_page_and_application() -> None:
    assert get_args(kinds.DeleteKind) == (
        "form",
        "process",
        "case",
        "list",
        "dataset",
        "page",
        "application",
    )


def test_publish_kind_excludes_list_and_dataset() -> None:
    assert get_args(kinds.PublishKind) == (
        "form",
        "process",
        "case",
        "page",
        "application",
    )


def test_create_flow_kind_is_the_five_creatable_kinds() -> None:
    assert get_args(kinds.CreateFlowKind) == (
        "process",
        "form",
        "list",
        "dataset",
        "case",
    )


def test_tier_kind_is_process_and_case_only() -> None:
    assert get_args(kinds.TierKind) == ("process", "case")


def test_tier_is_the_five_rung_ladder() -> None:
    assert get_args(kinds.Tier) == (
        "No access",
        "Initiate",
        "Read-only",
        "Edit",
        "Manage",
    )


def test_dataset_op_is_the_four_crud_verbs() -> None:
    assert get_args(kinds.DatasetOp) == ("create", "update", "delete", "list")


def test_sweep_scope_adds_the_all_fan_out() -> None:
    assert get_args(kinds.SweepScope) == (
        "apps",
        "flows",
        "pages",
        "roles",
        "lists",
        "all",
    )


def test_approval_decision_accepts_only_approve() -> None:
    assert get_args(kinds.ApprovalDecision) == ("approve",)
