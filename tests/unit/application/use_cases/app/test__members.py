"""Spec for app.application.use_cases.app._members.

Ports `tests/test_client.py`'s `discover_member_source`/`apply_member_batch`/
`apply_member_roles` tests and `tests/test_p4_surface.py`'s `RoleUsersClient`-shaped
cases onto the async, port-driven, explicit-`app_id` shapes.
"""

from __future__ import annotations

import pytest
from tests.fakes.app import FakeAppRepository
from tests.fakes.flow import FakeFlowRepository

from app.application.exceptions import ApplicationError
from app.application.use_cases.app._members import (
    MemberOutcome,
    apply_own_app_roles,
    create_then_grant_roles,
    discover_member_source,
    harvest_from_source,
    member_outcome_as_dict,
    raise_if_incomplete,
)

APP_ID = "App1"


# ---- discover_member_source ----


@pytest.mark.asyncio
async def test_discover_member_source_finds_the_first_other_flow_with_members() -> None:
    flow = FakeFlowRepository()
    flow.results["list_flows"] = [
        [{"_id": "F_target"}, {"_id": "F_empty"}, {"_id": "F_source"}]
    ]
    flow.results["get_members"] = [[], [{"Role": "Ro_x"}]]
    got = await discover_member_source(flow, APP_ID, "process", "F_target")
    assert got == "F_source"


@pytest.mark.asyncio
async def test_discover_member_source_returns_none_on_an_empty_app() -> None:
    flow = FakeFlowRepository()
    flow.results["list_flows"] = [[]]
    got = await discover_member_source(flow, APP_ID, "process", "F_target")
    assert got is None


# ---- apply_own_app_roles (the account-level fallback) ----


@pytest.mark.asyncio
async def test_apply_own_app_roles_reports_a_clear_note_when_nothing_is_usable() -> (
    None
):
    app = FakeAppRepository()
    app.results["list_app_roles"] = [[]]
    flow = FakeFlowRepository()
    outcome = await apply_own_app_roles(flow, app, APP_ID, "F_target", "process")
    assert outcome.harvested == () and outcome.applied == () and outcome.role_ids == ()
    assert outcome.note is not None
    assert "no existing flow" in outcome.note
    # The note names the tool that fixes it, never a dead end for a human.
    assert "forge_create_app_role" in outcome.note
    assert "builder UI" not in outcome.note
    assert "a human must" not in outcome.note
    raise_if_incomplete(outcome, "forge_member_batch")  # empty missing: does not raise


@pytest.mark.asyncio
async def test_apply_own_app_roles_states_how_many_it_saw_versus_granted() -> None:
    """Live finding: two roles existed and one was granted, silently. The report
    states both numbers, always, so a discovery gap reads apart from a grant gap."""
    app = FakeAppRepository()
    app.results["list_app_roles"] = [
        [
            {"_id": "RoE2MFjIipw3", "Name": "Repair Technician"},
            {"_id": "RoE2MFsjHKHA", "Name": "Requester"},
        ]
    ]
    flow = FakeFlowRepository()
    flow.results["get_members"] = [[{"_id": "RoE2MFjIipw3"}, {"_id": "RoE2MFsjHKHA"}]]
    outcome = await apply_own_app_roles(flow, app, APP_ID, "F_target", "process")
    assert outcome.roles_seen == 2 and outcome.roles_granted == 2
    assert outcome.roles_unusable == ()
    assert outcome.note is not None
    assert "saw 2" in outcome.note and "granted 2" in outcome.note


@pytest.mark.asyncio
async def test_apply_own_app_roles_counts_a_non_dict_even_when_nothing_is_usable() -> (
    None
):
    app = FakeAppRepository()
    app.results["list_app_roles"] = [["not-a-dict"]]
    flow = FakeFlowRepository()
    outcome = await apply_own_app_roles(flow, app, APP_ID, "F_target", "process")
    assert outcome.applied == () and outcome.roles_seen == 1
    assert len(outcome.roles_unusable) == 1
    assert "not-a-dict" in outcome.roles_unusable[0]
    assert outcome.roles_seen == len(outcome.applied) + len(outcome.roles_unusable)
    assert flow.calls == [], "nothing usable means nothing posted"


@pytest.mark.asyncio
async def test_apply_own_app_roles_grants_every_usable_role_scoped_to_the_app() -> None:
    app = FakeAppRepository()
    app.results["list_app_roles"] = [
        [
            {"_id": "RoA", "Name": "Admin", "Applications": [{"_id": APP_ID}]},
            {"_id": "RoB", "Name": "User", "Applications": [{"_id": APP_ID}]},
        ]
    ]
    flow = FakeFlowRepository()
    flow.results["get_members"] = [
        [{"_id": "RoA", "Role": "DataAdmin"}, {"_id": "RoB", "Role": "DataAdmin"}]
    ]
    outcome = await apply_own_app_roles(flow, app, APP_ID, "F_target", "process")
    assert outcome.role_ids == ("RoA", "RoB")
    assert outcome.verified == ("RoA", "RoB") and outcome.missing == ()
    assert outcome.note is not None and "account level" in outcome.note
    _posted_app, posted_kind, posted_flow, posted_members = flow.calls[-2][1]
    assert posted_kind == "process" and posted_flow == "F_target"
    assert posted_members == [
        {
            "_id": "RoA",
            "Name": "Admin",
            "Kind": "AppRole",
            "Role": "DataAdmin",
            "Permission": ["InitiateItems"],
        },
        {
            "_id": "RoB",
            "Name": "User",
            "Kind": "AppRole",
            "Role": "DataAdmin",
            "Permission": ["InitiateItems"],
        },
    ]


@pytest.mark.asyncio
async def test_apply_own_app_roles_reports_missing_on_a_partial_readback() -> None:
    app = FakeAppRepository()
    app.results["list_app_roles"] = [
        [
            {"_id": "RoA", "Name": "Admin", "Applications": [{"_id": APP_ID}]},
            {"_id": "RoB", "Name": "User", "Applications": [{"_id": APP_ID}]},
        ]
    ]
    flow = FakeFlowRepository()
    flow.results["get_members"] = [[{"_id": "RoA", "Role": "DataAdmin"}]]  # RoB absent
    outcome = await apply_own_app_roles(flow, app, APP_ID, "F_target", "process")
    assert outcome.verified == ("RoA",) and outcome.missing == ("RoB",)
    with pytest.raises(ApplicationError) as exc_info:
        raise_if_incomplete(outcome, "forge_member_batch")
    assert exc_info.value.code == "VERIFY_FAILED"
    assert "RoB" in exc_info.value.message


@pytest.mark.asyncio
async def test_apply_own_app_roles_counts_an_unusable_record_seen_but_not_granted() -> (
    None
):
    """seen == granted + unusable, always (the output-invariant audit)."""
    app = FakeAppRepository()
    app.results["list_app_roles"] = [
        [
            {"_id": "RoGood", "Name": "Requester"},
            {"Name": "Nameless Id"},  # no _id
            {"_id": "RoNoName"},  # no Name
        ]
    ]
    flow = FakeFlowRepository()
    flow.results["get_members"] = [[{"_id": "RoGood", "Role": "DataAdmin"}]]
    outcome = await apply_own_app_roles(flow, app, APP_ID, "F_target", "process")
    assert outcome.roles_seen == 3
    assert outcome.applied == ("RoGood",)
    assert len(outcome.roles_unusable) == 2
    assert outcome.roles_seen == len(outcome.applied) + len(outcome.roles_unusable)
    assert outcome.note is not None and "seen but NOT granted" in outcome.note


@pytest.mark.asyncio
async def test_apply_own_app_roles_counts_a_non_dict_record_too() -> None:
    app = FakeAppRepository()
    app.results["list_app_roles"] = [["not-a-dict", {"_id": "R1", "Name": "Tech"}]]
    flow = FakeFlowRepository()
    flow.results["get_members"] = [[{"_id": "R1", "Role": "DataAdmin"}]]
    outcome = await apply_own_app_roles(flow, app, APP_ID, "F_target", "process")
    assert outcome.roles_seen == 2
    assert outcome.applied == ("R1",)
    assert len(outcome.roles_unusable) == 1
    assert "not-a-dict" in outcome.roles_unusable[0]


# ---- harvest_from_source ----


@pytest.mark.asyncio
async def test_harvest_from_source_normalizes_and_verifies() -> None:
    flow = FakeFlowRepository()
    flow.results["get_members"] = [
        [
            {
                "_id": "m1",
                "Name": "Front Desk",
                "Kind": "AppRole",
                "Role": "Ro_front_001",
                "Permission": "Editable",
                "_created_at": "2026-01-01",
            },
            {"_id": "m2", "Name": "Junk"},  # no Role -> dropped
        ],
        [{"_id": "m1", "Role": "Ro_front_001"}],  # read-back
    ]
    outcome = await harvest_from_source(flow, APP_ID, "F_target", "F_source", "process")
    assert outcome.harvested == ("Ro_front_001",)
    assert outcome.verified == ("Ro_front_001",) and outcome.missing == ()
    assert outcome.role_ids == ("m1",)
    posted = flow.calls[-2][1][3]
    assert posted == [
        {
            "_id": "m1",
            "Name": "Front Desk",
            "Kind": "AppRole",
            "Role": "Ro_front_001",
            "Permission": "Editable",
        }
    ]


@pytest.mark.asyncio
async def test_harvest_from_source_stays_quiet_when_every_record_was_granted() -> None:
    """The control: a clean harvest must not grow a note it never had."""
    member = {
        "_id": "RoA",
        "Name": "Admin",
        "Kind": "AppRole",
        "Role": "DataAdmin",
        "Permission": ["InitiateItems"],
    }
    flow = FakeFlowRepository()
    flow.results["get_members"] = [[member], [member]]
    outcome = await harvest_from_source(flow, APP_ID, "F_target", "F_source", "process")
    assert outcome.note is None and outcome.roles_unusable == ()
    assert outcome.roles_seen == 1 and outcome.roles_granted == 1


@pytest.mark.asyncio
async def test_harvest_from_source_with_no_usable_members_is_reported_not_raised() -> (
    None
):
    flow = FakeFlowRepository()
    flow.results["get_members"] = [[]]
    outcome = await harvest_from_source(flow, APP_ID, "F_target", "F_source", "process")
    assert outcome.harvested == ()
    assert outcome.note is not None and "no AppRole members" in outcome.note
    raise_if_incomplete(outcome, "forge_member_batch")  # does not raise


@pytest.mark.asyncio
async def test_harvest_from_source_states_seen_versus_granted_on_a_dropped_record() -> (
    None
):
    flow = FakeFlowRepository()
    flow.results["get_members"] = [
        [
            {
                "_id": "RoA",
                "Name": "Admin",
                "Kind": "AppRole",
                "Role": "DataAdmin",
                "Permission": ["InitiateItems"],
            },
            {"_id": "RoJunk", "Name": "No Role Key", "Kind": "AppRole"},
        ],
        [{"_id": "RoA", "Role": "DataAdmin"}],
    ]
    outcome = await harvest_from_source(flow, APP_ID, "F_target", "F_source", "process")
    assert outcome.roles_seen == 2
    assert outcome.applied == ("DataAdmin",)
    assert len(outcome.roles_unusable) == 1 and "RoJunk" in outcome.roles_unusable[0]
    assert outcome.note is not None and "seen but NOT granted" in outcome.note


# ---- create_then_grant_roles (forge_add_member_roles) ----


@pytest.mark.asyncio
async def test_create_then_grant_roles_reuses_an_existing_same_name_role() -> None:
    app = FakeAppRepository()
    app.results["list_app_roles"] = [
        [{"_id": "RoExist", "Name": "FDE"}],
        [{"_id": "RoExist", "Name": "FDE"}],
    ]
    flow = FakeFlowRepository()
    outcome = await create_then_grant_roles(
        app, flow, APP_ID, "F_target", {"RoForeign": "FDE"}, "process"
    )
    assert outcome.missing == ()
    assert dict(outcome.resolved) == {"FDE": "RoExist"}
    assert outcome.role_ids == ("RoExist",)
    create_calls = [c for c in app.calls if c[0] == "create_app_role"]
    assert create_calls == [], "an existing same-name role must be reused"


@pytest.mark.asyncio
async def test_create_then_grant_roles_creates_a_missing_role_for_the_app() -> None:
    app = FakeAppRepository()
    app.results["list_app_roles"] = [[], [{"_id": "RoNew1", "Name": "Requester"}]]
    app.results["create_app_role"] = ["RoNew1"]
    flow = FakeFlowRepository()
    outcome = await create_then_grant_roles(
        app, flow, APP_ID, "F_target", {"RoX": "Requester"}, "process"
    )
    assert dict(outcome.resolved) == {"Requester": "RoNew1"}
    assert outcome.note is not None and "created 1" in outcome.note
    assert app.calls[1] == ("create_app_role", ("Requester",), {"app_id": APP_ID})
    # the snapshot read on the flow port happens before the grant write
    assert flow.calls[0][0] == "get_members"
    assert flow.calls[1][0] == "post_member_batch"


@pytest.mark.asyncio
async def test_create_then_grant_roles_leaves_roles_seen_at_zero() -> None:
    """Old `apply_member_roles` (`client.py:4366-4376`) never passed `roles_seen`
    to `MemberReport`, leaving it at its documented default `0` --
    `MemberReport.roles_seen`'s own docstring (`client.py:4008-4013`) names
    this path explicitly: "0 on any path that discovers nothing -- the
    sibling harvest, and apply_member_roles' caller-named set." `roles_seen`
    is meant to count records DISCOVERY received before any filter, kept
    equal to `len(applied) + len(roles_unusable)` (the same field's own
    invariant) -- this path never discovers candidates at all, it grants
    exactly the caller-named `roles`, so counting the WHOLE account-scoped
    role list here (most of which were never requested and are neither
    `applied` nor `roles_unusable`) would break that invariant."""
    app = FakeAppRepository()
    app.results["list_app_roles"] = [
        [{"_id": "R1", "Name": "Other"}, {"_id": "R2", "Name": "AndAnother"}],
        [{"_id": "RoNew1", "Name": "Requester"}],
    ]
    app.results["create_app_role"] = ["RoNew1"]
    flow = FakeFlowRepository()

    outcome = await create_then_grant_roles(
        app, flow, APP_ID, "F_target", {"RoX": "Requester"}, "process"
    )

    # `roles_unusable` is likewise never populated on this path -- the
    # invariant "seen == applied + unusable" is scoped to the two
    # discovery-based paths (`apply_own_app_roles`, `harvest_from_source`),
    # never this caller-named one.
    assert outcome.roles_unusable == ()
    assert outcome.applied == ("RoNew1",)
    assert outcome.roles_seen == 0


# ---- MemberOutcome / raise_if_incomplete ----


def test_roles_granted_is_the_count_of_applied() -> None:
    outcome = MemberOutcome(
        target_flow_id="F1", source_flow_id=None, applied=("A", "B")
    )
    assert outcome.roles_granted == 2


def test_raise_if_incomplete_is_a_no_op_when_missing_is_empty() -> None:
    outcome = MemberOutcome(target_flow_id="F1", source_flow_id=None, missing=())
    raise_if_incomplete(outcome, "forge_member_batch")  # does not raise


def test_member_outcome_as_dict_shape() -> None:
    """The same 12-key shape `client.MemberReport.as_tool_result()` produced,
    minus `isError` (rule 2, `brief_stage_d_common.md`) -- shared by
    `forge_member_batch`/`forge_add_member_roles`'s own field-by-field
    response construction AND `forge_create_template_app`'s embedded
    `members` dict (review fix 8: one copy of this shape, not two)."""
    outcome = MemberOutcome(
        target_flow_id="F1",
        source_flow_id=None,
        harvested=("Reviewers",),
        applied=("R1",),
        verified=("R1",),
        missing=(),
        role_ids=("R1",),
        resolved=(("Reviewers", "R1"),),
        roles_seen=1,
        roles_unusable=(),
        note="granted 1 KF_APP-scoped AppRole(s): Reviewers",
    )
    assert member_outcome_as_dict(outcome) == {
        "target_flow_id": "F1",
        "source_flow_id": None,
        "harvested": ["Reviewers"],
        "applied": ["R1"],
        "verified": ["R1"],
        "missing": [],
        "note": "granted 1 KF_APP-scoped AppRole(s): Reviewers",
        "role_ids": ["R1"],
        "resolved": {"Reviewers": "R1"},
        "roles_seen": 1,
        "roles_granted": 1,
        "roles_unusable": [],
    }
