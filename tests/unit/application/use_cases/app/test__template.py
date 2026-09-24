"""Spec for app.application.use_cases.app._template.

Ports the matching cases of `tests/test_client.py`'s `run_doctor` tests onto
the new fake-port architecture. The "members FIRST" grant itself
(`tests/test_template_app.py`'s account-level fallback path) now lives in
`app.application.use_cases.app._members.apply_own_app_roles`, shared with
`forge_member_batch` (review fix 8) -- see `test__members.py` for its own
coverage.
"""

from __future__ import annotations

import pytest
from tests.fakes.app import FakeAppRepository
from tests.fakes.flow import FakeFlowRepository

from app.application.exceptions import VERIFY_FAILED, ApplicationError, RepositoryError
from app.application.use_cases.app._template import (
    abandon,
    doctor_report,
    run_step,
)
from app.domain.entities.flow_draft import FlowDraft
from app.domain.value_objects.field_spec import FieldSpec
from app.domain.value_objects.field_type import FieldType


def _bare_process_draft() -> FlowDraft:
    return FlowDraft.from_wire(
        {
            "Root": "M1",
            "_meta_version": "v1",
            "M1": {"Id": "M1", "Kind": "Model", "Name": "P", "FlowType": "Process"},
        }
    )


# ---- doctor_report -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_doctor_report_is_clean_on_a_bare_draft() -> None:
    flow = FakeFlowRepository()
    flow.results["get_draft"] = [_bare_process_draft()]

    report = await doctor_report(flow, "App_1", "F1")

    assert report["ok"] is True
    assert report["problems"] == []
    assert report["members_found"] is None


@pytest.mark.asyncio
async def test_doctor_report_flags_an_assignee_with_zero_members() -> None:
    draft = _bare_process_draft().apply_changes(
        [FieldSpec(name="Done", type=FieldType.BOOLEAN)]
    )
    wire = draft.to_wire()
    wire["Resource_1"] = {
        "Id": "Resource_1",
        "Kind": "Resource",
        "ValueType": "AppRole",
        "Value": "R1",
    }
    draft = FlowDraft.from_wire(wire)
    flow = FakeFlowRepository()
    flow.results["get_draft"] = [draft]
    flow.results["get_members"] = [[]]

    report = await doctor_report(flow, "App_1", "F1")

    assert report["ok"] is False
    assert report["members_found"] == 0
    assert any("ZERO members" in p for p in report["problems"])


@pytest.mark.asyncio
async def test_doctor_report_raises_verify_failed_when_the_draft_has_no_root() -> None:
    """`FlowDraft.problems()` raises a bare `ValueError` when the draft has no
    valid `Root` key. The old `client.run_doctor` (`client.py:3894-3900`)
    caught it and returned `Err("verify", f"doctor could not run: {e}")` --
    `doctor_report` must do the same, as `use_cases/flow/_doctor.py:98`
    already does, so a caller of `forge_create_template_app` gets a
    `VERIFY_FAILED` it can act on (and `run_step` can abandon the half-built
    app on) instead of an unhandled `ValueError` escaping the use case.
    """
    flow = FakeFlowRepository()
    flow.results["get_draft"] = [FlowDraft.from_wire({})]

    with pytest.raises(ApplicationError) as exc_info:
        await doctor_report(flow, "App_1", "F1")

    assert exc_info.value.code == VERIFY_FAILED
    assert exc_info.value.message == (
        "doctor could not run: draft has no Root key — not a flow draft?"
    )


# ---- abandon -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_abandon_deletes_and_verifies_then_returns_the_original_error() -> None:
    app = FakeAppRepository()
    app.results["list_applications"] = [[]]

    exc = await abandon(
        app, "App_1", "R1", "member grant did not land", "VERIFY_FAILED"
    )

    assert isinstance(exc, ApplicationError)
    assert exc.code == "VERIFY_FAILED"
    assert "member grant did not land" in exc.message
    assert "app App_1 deleted+verified" in exc.message
    assert [c[0] for c in app.calls] == [
        "delete_application",
        "list_applications",
        "delete_app_role",
    ]


@pytest.mark.asyncio
async def test_abandon_reports_when_the_delete_itself_fails() -> None:
    class _Failing(FakeAppRepository):
        async def delete_application(  # type: ignore[override]
            self, app_id: str, archive_first: bool = True
        ) -> None:
            raise RepositoryError("500 Internal Server Error")

    app = _Failing()

    exc = await abandon(app, "App_1", None, "publish failed", "VERIFY_FAILED")

    assert "NOT deleted" in exc.message
    assert "500 Internal Server Error" in exc.message


@pytest.mark.asyncio
async def test_abandon_skips_role_cleanup_when_no_role_was_ever_created() -> None:
    app = FakeAppRepository()
    app.results["list_applications"] = [[]]

    await abandon(app, "App_1", None, "create_app_role failed", "REPOSITORY_ERROR")

    assert "delete_app_role" not in [c[0] for c in app.calls]


# ---- run_step ------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_step_passes_through_the_awaited_value_on_success() -> None:
    app = FakeAppRepository()

    async def _ok() -> str:
        return "F1"

    got = await run_step(app, "App_1", None, _ok())

    assert got == "F1"
    assert app.calls == []


@pytest.mark.asyncio
async def test_run_step_abandons_and_reraises_on_failure() -> None:
    app = FakeAppRepository()
    app.results["list_applications"] = [[]]

    async def _boom() -> str:
        raise RepositoryError("create_flow failed")

    with pytest.raises(ApplicationError) as exc_info:
        await run_step(app, "App_1", "R1", _boom())
    assert "create_flow failed" in exc_info.value.message
    assert "cleanup" in exc_info.value.message
    assert app.calls[0][0] == "delete_application"
