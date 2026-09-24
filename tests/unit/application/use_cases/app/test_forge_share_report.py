"""Spec for app.application.use_cases.app.forge_share_report.

Ports `tests/test_client.py::
test_apply_report_members_posts_and_reports_unverified_honestly` onto the new
fake-port architecture.
"""

from __future__ import annotations

import pytest
from tests.fakes.flow import FakeFlowRepository
from tests.unit.application.use_cases.test_write_order_contract import (
    assert_write_order,
)

from app.application.exceptions import ApplicationError, RepositoryError
from app.application.models.requests.app.forge_share_report_request import (
    ForgeShareReportRequest,
)
from app.application.use_cases.app.forge_share_report import ForgeShareReport

_MEMBERS = [
    {
        "_id": "m1",
        "Name": "Lead",
        "Kind": "AppRole",
        "Role": "Ro_lead",
        "Permission": "Member",
    }
]


@pytest.mark.asyncio
async def test_posts_and_reports_unverified_honestly() -> None:
    fake = FakeFlowRepository()
    fake.results["post_report_member_batch"] = [{"ok": True}]

    resp = await ForgeShareReport(fake).execute(
        ForgeShareReportRequest(
            flow_id="F1", report_id="Rep1", members=_MEMBERS, app_id="A1"
        )
    )

    assert resp.verified is None, "no documented read-back route -- must not fake True"
    assert resp.posted == {"ok": True}
    assert resp.requested == _MEMBERS
    assert resp.snapshot_version is None
    # Byte-for-byte against `client.py:4400-4401`.
    assert resp.note == (
        "no documented GET route for a report's own member list — not "
        "independently read-back verified, unlike every other apply_* in "
        "this module"
    )
    post_calls = [c for c in fake.calls if c[0] == "post_report_member_batch"]
    assert post_calls == [
        ("post_report_member_batch", ("A1", "F1", "Rep1", _MEMBERS), {})
    ]
    assert_write_order(fake)


@pytest.mark.asyncio
async def test_a_repository_error_propagates_unchanged() -> None:
    class _Failing(FakeFlowRepository):
        async def post_report_member_batch(  # type: ignore[override]
            self, app_id, flow_id, report_id, members
        ):
            raise RepositoryError("500 Internal Server Error")

    with pytest.raises(RepositoryError):
        await ForgeShareReport(_Failing()).execute(
            ForgeShareReportRequest(
                flow_id="F1", report_id="Rep1", members=[], app_id="A1"
            )
        )


@pytest.mark.asyncio
async def test_no_app_id_is_refused_before_any_port_call() -> None:
    fake = FakeFlowRepository()

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeShareReport(fake).execute(
            ForgeShareReportRequest(
                flow_id="F1", report_id="Rep1", members=[], app_id=""
            )
        )
    assert exc_info.value.code == "REFUSED"
    assert fake.calls == []
