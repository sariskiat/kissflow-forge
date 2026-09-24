"""`use_cases.flow._doctor.run_doctor`: ported from the former
`client.run_doctor`.

The first seven tests are ported from `tests/test_client.py`'s run_doctor tests: same
names, same draft shapes, same assertions, now against the flow port's fake.
"""

from __future__ import annotations

from typing import Any

import pytest
from tests.fakes.flow import FakeFlowRepository

from app.application.exceptions import ApplicationError, RepositoryError
from app.application.use_cases.flow._doctor import run_doctor
from app.domain.entities.flow_draft import FlowDraft


def _select_draft(list_id: str) -> FlowDraft:
    return FlowDraft.from_wire(
        {
            "Root": "M1",
            "_meta_version": "v1",
            "M1": {
                "Id": "M1",
                "Kind": "Model",
                "Name": "F",
                "FlowType": "Form",
                "Model::Field": ["Fld1"],
            },
            "Fld1": {
                "Id": "Fld1",
                "Kind": "Field",
                "Type": "Select",
                "Name": "Choice",
                "Model": "M1",
                "ReferredList": list_id,
            },
        }
    )


def _draft_with_an_approle_assignee() -> FlowDraft:
    """A one-step process whose UserTask carries a real AppRole assignee -- the exact
    condition CLAUDE.md > Members first says publish rejects when the flow has NO
    members."""
    return FlowDraft.from_wire(
        {
            "Root": "M1",
            "_meta_version": "v1",
            "M1": {"Id": "M1", "Kind": "Model", "Name": "P", "FlowType": "Process"},
            "Activity_A1": {
                "Id": "Activity_A1",
                "Kind": "Activity",
                "NodeType": "UserTask",
                "Name": "Review",
                "Activity::Resource": ["Resource_R1"],
            },
            "Resource_R1": {
                "Id": "Resource_R1",
                "Kind": "Resource",
                "Activity": "Activity_A1",
                "ValueType": "AppRole",
                "Value": "Ro_lead_0003",
                "DisplayValue": "Lead",
            },
        }
    )


_POPULATED_ROSTER: list[dict[str, Any]] = [
    {
        "_id": "Ro_lead_0003",
        "Name": "Lead",
        "Kind": "AppRole",
        "Role": "Member",
        "Permission": "InitiateItems",
    }
]


async def _doctor(fake: FakeFlowRepository, **kwargs: Any) -> Any:
    return await run_doctor(
        fake,
        app_id="A1",
        flow_id="F1",
        kind="process",
        visibility_role_claims=kwargs.get("visibility_role_claims"),
    )


def _raise(exc: Exception):
    async def _fn(*args: object, **kwargs: object) -> object:
        raise exc

    return _fn


# ---- ported from tests/test_client.py ------------------------------------------------


@pytest.mark.asyncio
async def test_run_doctor_reads_real_list_options_for_every_select_field() -> None:
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [_select_draft("List_1")]
    fake.results["get_list_items"] = [["Yes", "No"]]

    got = await _doctor(fake)

    assert got.list_ids_checked == ("List_1",)
    assert got.list_fetch_errors == {}
    assert isinstance(got.checked, dict)
    assert fake.calls[1] == ("get_list_items", ("A1", "List_1"), {})


@pytest.mark.asyncio
async def test_run_doctor_records_a_list_fetch_failure_without_crashing() -> None:
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [_select_draft("List_Broken")]
    fake.get_list_items = _raise(RepositoryError("list not found"))

    got = await _doctor(fake)

    assert got.list_ids_checked == ()
    assert "List_Broken" in got.list_fetch_errors


@pytest.mark.asyncio
async def test_run_doctor_fails_when_an_approle_assignee_has_no_members() -> None:
    """The blind spot the offline graph cannot close: membership is not in the draft,
    and an assignee with an empty roster is a bare-MetadataError publish failure."""
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [_draft_with_an_approle_assignee()]
    fake.results["get_members"] = [[]]

    got = await _doctor(fake)

    assert got.ok is False
    assert any("ZERO members" in p for p in got.problems), got.problems
    assert got.checked["members"] == 1
    assert got.members_found == 0


@pytest.mark.asyncio
async def test_run_doctor_is_quiet_when_the_roster_is_populated() -> None:
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [_draft_with_an_approle_assignee()]
    fake.results["get_members"] = [_POPULATED_ROSTER]

    got = await _doctor(fake)

    assert not any("ZERO members" in p for p in got.problems), got.problems
    assert got.checked["members"] == 1 and got.members_found == 1


@pytest.mark.asyncio
async def test_run_doctor_never_reads_members_for_a_flow_with_no_approle_assignee() -> (
    None
):
    """No assignee, no membership requirement -- the bucket still says it LOOKED (0),
    and no round trip is spent."""
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [
        FlowDraft.from_wire(
            {
                "Root": "M1",
                "_meta_version": "v1",
                "M1": {
                    "Id": "M1",
                    "Kind": "Model",
                    "Name": "P",
                    "FlowType": "Process",
                },
            }
        )
    ]

    got = await _doctor(fake)

    assert got.checked["members"] == 0
    assert got.members_found is None
    assert "get_members" not in [c[0] for c in fake.calls]


@pytest.mark.asyncio
async def test_run_doctor_records_a_member_fetch_failure_without_falsely_passing() -> (
    None
):
    """A roster this call could not read is UNKNOWN, not healthy: recorded, never
    counted as populated, and the claim it gated lands in `unvalidated`."""
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [_draft_with_an_approle_assignee()]
    fake.get_members = _raise(RepositoryError("member roster fetch failed"))

    got = await _doctor(fake)

    assert got.member_fetch_error == "member roster fetch failed"
    assert not any("ZERO members" in p for p in got.problems), got.problems
    assert any(
        "member" in u and "member roster fetch failed" in u for u in got.unvalidated
    ), f"the un-checkable membership claim landed in NO bucket: {got}"
    assert got.members_found is None  # never counted as populated


@pytest.mark.asyncio
async def test_run_doctor_leaves_the_membership_claim_out_of_unvalidated_when_it_was_read() -> (  # noqa: E501
    None
):
    """A roster that WAS read is validated, so nothing about membership belongs in
    `unvalidated` -- the entry must mean "could not check", not "checked"."""
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [_draft_with_an_approle_assignee()]
    fake.results["get_members"] = [_POPULATED_ROSTER]

    got = await _doctor(fake)

    assert not any("member" in u for u in got.unvalidated), got.unvalidated


# ---- this port's own additions -------------------------------------------------------


@pytest.mark.asyncio
async def test_run_doctor_is_ok_on_a_clean_bare_draft() -> None:
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [
        FlowDraft.from_wire({"Root": "M1", "M1": {"Kind": "Model", "Type": "Root"}})
    ]

    got = await _doctor(fake)

    assert got.ok is True
    assert got.problems == ()
    assert [c[0] for c in fake.calls] == ["get_draft"]


@pytest.mark.asyncio
async def test_run_doctor_fails_every_role_scoped_visibility_claim() -> None:
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [
        FlowDraft.from_wire({"Root": "M1", "M1": {"Kind": "Model"}})
    ]

    got = await _doctor(fake, visibility_role_claims=["Manager can see Approval"])

    assert got.ok is False
    assert any("role-scoped visibility is API-impossible" in p for p in got.problems)


@pytest.mark.asyncio
async def test_run_doctor_treats_a_dict_list_items_body_as_no_options() -> None:
    """Restores `client.py:3892`'s guard: a `get_list_items` body that comes back a
    dict (never the plain list the port promises) must not crash `list(items)` on a
    dict's own keys -- it is recorded as no options, not an unhandled shape."""
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [_select_draft("List_1")]
    fake.results["get_list_items"] = [{"Data": ["Yes", "No"]}]

    got = await _doctor(fake)

    assert got.list_ids_checked == ("List_1",)
    assert got.list_fetch_errors == {}


@pytest.mark.asyncio
async def test_run_doctor_treats_a_none_list_items_body_as_no_options() -> None:
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [_select_draft("List_1")]
    fake.results["get_list_items"] = [None]

    got = await _doctor(fake)

    assert got.list_ids_checked == ("List_1",)
    assert got.list_fetch_errors == {}


@pytest.mark.asyncio
async def test_run_doctor_translates_a_bad_root_key() -> None:
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [FlowDraft.from_wire({})]

    with pytest.raises(ApplicationError) as exc:
        await _doctor(fake)
    assert exc.value.code == "VERIFY_FAILED"
    assert exc.value.message.startswith("doctor could not run: ")
