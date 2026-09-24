"""Spec for app.application.use_cases.app.forge_create_template_app.

Ports the matching cases of `tests/test_template_app.py` onto the new
fake-port architecture. `test_scoped_to_app_mints_a_new_client_with_the_same_identity`
is NOT ported: `KfClient.scoped_to_app` no longer exists -- every port method
already takes an explicit `app_id` (`FlowRepository`'s own docstring, spec G7
Part 1), so there is no "scoped client" concept left to test.

Order under test is the proven build order (CLAUDE.md > Build order): create
application -> create process flow -> members FIRST -> write transplanted graph
(assignees ride in it) -> publish process -> publish app -> doctor read-back ->
URL.
"""

from __future__ import annotations

from typing import Any

import pytest
from tests.fakes.app import FakeAppRepository
from tests.fakes.flow import FakeFlowRepository

from app.application.exceptions import ApplicationError, RepositoryError
from app.application.models.requests.app.forge_create_template_app_request import (
    ForgeCreateTemplateAppRequest,
)
from app.application.use_cases.app.forge_create_template_app import (
    ForgeCreateTemplateApp,
)
from app.domain.entities.flow_draft import FlowDraft
from app.domain.entities.navigation import Navigation

APP_NAME = "Sample Template App"
BASE_URL = "https://dev-x.example.com"


def _bare_process_draft() -> FlowDraft:
    return FlowDraft.from_wire(
        {
            "Root": "M1",
            "_meta_version": "v1",
            "M1": {
                "Id": "M1",
                "Kind": "Model",
                "Name": APP_NAME,
                "FlowType": "Process",
            },
        }
    )


class _StatefulFlow(FakeFlowRepository):
    """A STATEFUL `FlowRepository` fake for this one use case's own
    integration-style tests: `put_draft` really persists, so every later
    `get_draft` read-back (the graph verify AND `doctor_report`'s own read)
    reflects what was actually written -- ported from
    `tests/test_template_app.py::_TemplateAppClient`'s own pattern.
    """

    def __init__(self, draft: FlowDraft) -> None:
        super().__init__()
        self.draft = draft
        self.put_draft_error: RepositoryError | None = None
        self.drop_put = False
        self._get_draft_calls = 0
        self.fail_get_draft_on_call: int | None = None

    async def get_draft(self, app_id: str, kind: str, flow_id: str) -> FlowDraft:  # type: ignore[override]
        self._get_draft_calls += 1
        self.calls.append(("get_draft", (app_id, kind, flow_id), {}))
        if self._get_draft_calls == self.fail_get_draft_on_call:
            raise RepositoryError("doctor read failed")
        return self.draft

    async def put_draft(  # type: ignore[override]
        self, app_id: str, kind: str, flow_id: str, new: FlowDraft, expect_version
    ) -> FlowDraft:
        self.calls.append(
            (
                "put_draft",
                (app_id, kind, flow_id, new),
                {"expect_version": expect_version},
            )
        )
        if self.put_draft_error is not None:
            raise self.put_draft_error
        if not self.drop_put:
            self.draft = new
        return new


def _app_for_happy_path(
    role_name: str, cls: type[FakeAppRepository] = FakeAppRepository
) -> FakeAppRepository:
    app = cls()
    app.results["create_application"] = ["App_1"]
    app.results["list_applications"] = [[], [{"_id": "App_1", "Name": APP_NAME}]]
    app.results["create_app_role"] = ["R1"]
    app.results["list_app_roles"] = [[{"_id": "R1", "Name": role_name}]]
    app.results["get_app_draft"] = [
        Navigation.from_wire({}),
        Navigation.from_wire({"_meta_version": "appv2"}),
    ]
    return app


def _flow_for_happy_path() -> _StatefulFlow:
    flow = _StatefulFlow(_bare_process_draft())
    flow.results["create_flow"] = ["F1"]
    roster = [{"_id": "R1", "Role": "DataAdmin"}]
    flow.results["get_members"] = [roster, roster]
    flow.results["get_flow_detail"] = [{"_id": "F1", "Status": "Live"}]
    return flow


async def _run(app: FakeAppRepository, flow: _StatefulFlow) -> Any:
    return await ForgeCreateTemplateApp(app=app, flow=flow, base_url=BASE_URL).execute(
        ForgeCreateTemplateAppRequest(name=APP_NAME)
    )


# ---- happy path ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_path_reports_every_promised_key() -> None:
    role_name = f"{APP_NAME} Role"
    app = _app_for_happy_path(role_name)
    flow = _flow_for_happy_path()

    resp = await _run(app, flow)

    assert resp.app_id == "App_1"
    assert resp.flow_id == "F1"
    assert resp.role_id == "R1"
    assert resp.role_name == role_name
    assert resp.process_status == "Live"
    assert resp.app_publish["published"] is True
    assert resp.app_publish["meta_version"] == "appv2"
    assert resp.doctor["flow_id"] == "F1"
    assert "problems" in resp.doctor and "ok" in resp.doctor
    assert resp.app_url == f"{BASE_URL}/view/app/App_1"
    assert resp.process_url == f"{BASE_URL}/view/process/F1"
    assert resp.url_verified is False
    # The pre-transplant process draft's own version (review fix 7) -- the
    # same `pre_draft.version` passed in as `expect_version` for the graph
    # write, never a bare `None`.
    assert resp.snapshot_version == "v1"
    expected_nodes = sum(
        1 for k in flow.draft.to_wire() if k not in ("Root", "_meta_version")
    )
    assert resp.graph_nodes_verified == expected_nodes


@pytest.mark.asyncio
async def test_role_is_scoped_to_the_created_app_not_a_session_default() -> None:
    role_name = f"{APP_NAME} Role"
    app = _app_for_happy_path(role_name)
    flow = _flow_for_happy_path()

    await _run(app, flow)

    create_role_calls = [c for c in app.calls if c[0] == "create_app_role"]
    assert create_role_calls == [("create_app_role", (role_name,), {"app_id": "App_1"})]


@pytest.mark.asyncio
async def test_members_are_granted_before_the_graph_write() -> None:
    role_name = f"{APP_NAME} Role"
    app = _app_for_happy_path(role_name)
    flow = _flow_for_happy_path()

    await _run(app, flow)

    names = [c[0] for c in flow.calls]
    assert "post_member_batch" in names and "put_draft" in names
    assert names.index("post_member_batch") < names.index("put_draft"), (
        "members must land BEFORE the transplanted graph (assignees ride in that "
        "write) — CLAUDE.md > Members first"
    )


@pytest.mark.asyncio
async def test_transplanted_graph_lands_with_assignee_on_the_created_role() -> None:
    role_name = f"{APP_NAME} Role"
    app = _app_for_happy_path(role_name)
    flow = _flow_for_happy_path()

    resp = await _run(app, flow)

    wire = flow.draft.to_wire()
    resources = [
        v
        for v in wire.values()
        if isinstance(v, dict)
        and v.get("Kind") == "Resource"
        and v.get("ValueType") == "AppRole"
    ]
    assert resources, (
        "the transplanted graph must carry the workflow's Resource assignee node"
    )
    assert all(r.get("Value") == resp.role_id for r in resources), (
        "every UserTask assignee must be re-pointed at the created dev AppRole"
    )
    activities = [
        v for v in wire.values() if isinstance(v, dict) and v.get("Kind") == "Activity"
    ]
    assert len(activities) == 5, (
        "the full template carries 5 Activities (quirks included)"
    )


# ---- failure paths -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_duplicate_app_name_surfaces_the_platform_error_loud() -> None:
    class _Refusing(FakeAppRepository):
        async def create_application(self, name: str) -> str:  # type: ignore[override]
            raise RepositoryError("POST .../application -> FlowNameAlreadyExists")

    app = _Refusing()
    app.results["list_applications"] = [[]]
    flow = _flow_for_happy_path()

    with pytest.raises(RepositoryError, match="FlowNameAlreadyExists"):
        await _run(app, flow)
    assert not any(
        c[0] in ("create_app_role", "create_flow") for c in app.calls + flow.calls
    ), (
        "nothing downstream may run after the create is refused — no auto-rename, "
        "no retry"
    )


@pytest.mark.asyncio
async def test_midway_failure_deletes_the_half_built_app_and_role() -> None:
    role_name = f"{APP_NAME} Role"
    app = _app_for_happy_path(role_name)
    app.results["list_applications"].append([])  # abandon's own verify read
    flow = _flow_for_happy_path()
    flow.put_draft_error = RepositoryError("PUT draft -> 500")

    with pytest.raises(ApplicationError) as exc_info:
        await _run(app, flow)
    assert exc_info.value.code == "REPOSITORY_ERROR"
    assert "cleanup" in exc_info.value.message
    assert [c[0] for c in app.calls][-3:] == [
        "delete_application",
        "list_applications",
        "delete_app_role",
    ]


@pytest.mark.asyncio
async def test_graph_write_readback_failure_is_verify_failed_and_cleans_up() -> None:
    """Old (`client.py:5597`): a failed read-back of the graph write itself was
    reclassified as `Err("verify", f"graph write read-back failed:
    {read_back.message}")`, regardless of the underlying port failure's own
    kind -- never left as a bare `REPOSITORY_ERROR`."""
    role_name = f"{APP_NAME} Role"
    app = _app_for_happy_path(role_name)
    app.results["list_applications"].append([])
    flow = _flow_for_happy_path()
    # Call 1 is the pre-transplant read; call 2 is the graph write's own
    # read-back -- make ONLY that one fail.
    flow.fail_get_draft_on_call = 2

    with pytest.raises(ApplicationError) as exc_info:
        await _run(app, flow)
    assert exc_info.value.code == "VERIFY_FAILED"
    assert exc_info.value.message.startswith(
        "graph write read-back failed: doctor read failed [cleanup:"
    )


@pytest.mark.asyncio
async def test_process_publish_readback_not_live_fails_and_cleans_up() -> None:
    role_name = f"{APP_NAME} Role"
    app = _app_for_happy_path(role_name)
    app.results["list_applications"].append([])
    flow = _flow_for_happy_path()
    flow.results["get_flow_detail"] = [{"_id": "F1", "Status": "Draft"}]

    with pytest.raises(ApplicationError) as exc_info:
        await _run(app, flow)
    assert exc_info.value.code == "VERIFY_FAILED"
    assert "not Live" in exc_info.value.message
    # Old (`tests/test_template_app.py:234-240`): the half-built app (and its
    # created AppRole) must actually be gone, not just reported as an error.
    assert [c[0] for c in app.calls][-3:] == [
        "delete_application",
        "list_applications",
        "delete_app_role",
    ]


class _FailingFlowDetailReadback(_StatefulFlow):
    """`get_flow_detail` always fails -- the process publish's own status
    read-back, distinct from the graph-write read-back above."""

    async def get_flow_detail(  # type: ignore[override]
        self, app_id: str, kind: str, flow_id: str
    ) -> dict[str, Any]:
        self.calls.append(("get_flow_detail", (app_id, kind, flow_id), {}))
        raise RepositoryError("GET flow detail -> 500")


@pytest.mark.asyncio
async def test_publish_status_readback_failure_is_verify_failed_and_cleans_up() -> None:
    """Old (`client.py:5619`): a failed status read-back after publish was
    reclassified as `Err("verify", f"publish succeeded but status read-back
    failed: {detail.message}")`, never left as a bare `REPOSITORY_ERROR`."""
    role_name = f"{APP_NAME} Role"
    app = _app_for_happy_path(role_name)
    app.results["list_applications"].append([])
    flow = _FailingFlowDetailReadback(_bare_process_draft())
    flow.results["create_flow"] = ["F1"]
    roster = [{"_id": "R1", "Role": "DataAdmin"}]
    flow.results["get_members"] = [roster, roster]

    with pytest.raises(ApplicationError) as exc_info:
        await _run(app, flow)
    assert exc_info.value.code == "VERIFY_FAILED"
    assert exc_info.value.message.startswith(
        "publish succeeded but status read-back failed: GET flow detail -> 500 "
        "[cleanup:"
    )


@pytest.mark.asyncio
async def test_silently_dropped_graph_write_is_caught_by_read_back() -> None:
    """The silent-discard trap this codebase exists to catch: a PUT that 200s
    while persisting nothing must fail the run, not report success (THE RULE)."""
    role_name = f"{APP_NAME} Role"
    app = _app_for_happy_path(role_name)
    app.results["list_applications"].append([])
    flow = _flow_for_happy_path()
    flow.drop_put = True

    with pytest.raises(ApplicationError) as exc_info:
        await _run(app, flow)
    assert exc_info.value.code == "VERIFY_FAILED"
    assert "did not land" in exc_info.value.message


@pytest.mark.asyncio
async def test_member_grant_not_landing_the_role_fails_and_cleans_up() -> None:
    role_name = f"{APP_NAME} Role"
    app = _app_for_happy_path(role_name)
    app.results["list_applications"].append([])
    flow = _flow_for_happy_path()
    flow.results["get_members"] = [[]]  # roster stays empty after the grant

    with pytest.raises(ApplicationError) as exc_info:
        await _run(app, flow)
    assert exc_info.value.code == "VERIFY_FAILED"
    assert "member grant did not land" in exc_info.value.message
    # Old (`tests/test_template_app.py:266-272`): both the half-built app AND
    # its created AppRole must actually be gone.
    assert [c[0] for c in app.calls][-3:] == [
        "delete_application",
        "list_applications",
        "delete_app_role",
    ]


class _FailingAppDraftReadback(FakeAppRepository):
    """`get_app_draft` succeeds once (the write-order invariant's own leading
    read), then fails on the SECOND call (the real post-publish read-back)."""

    def __init__(self) -> None:
        super().__init__()
        self._get_app_draft_calls = 0

    async def get_app_draft(self, app_id: str) -> Navigation:  # type: ignore[override]
        self._get_app_draft_calls += 1
        self.calls.append(("get_app_draft", (app_id,), {}))
        if self._get_app_draft_calls == 1:
            return Navigation.from_wire({})
        raise RepositoryError("GET app draft -> 500")


@pytest.mark.asyncio
async def test_app_publish_readback_failure_cleans_up() -> None:
    role_name = f"{APP_NAME} Role"
    app = _app_for_happy_path(role_name, cls=_FailingAppDraftReadback)
    flow = _flow_for_happy_path()
    app.results["list_applications"].append([])

    with pytest.raises(ApplicationError) as exc_info:
        await _run(app, flow)
    assert exc_info.value.code == "VERIFY_FAILED"
    # Old (`client.py:5633`): `create_template_app` re-wrapped
    # `publish_application_verified`'s own read-back failure once more, with
    # its OWN "app publish read-back failed: " prefix -- never left as the
    # inner "publish succeeded but read-back failed: ..." message alone.
    assert exc_info.value.message.startswith(
        "app publish read-back failed: publish succeeded but read-back "
        "failed: GET app draft -> 500 [cleanup:"
    )
    # Old (`tests/test_template_app.py:275-281`): both the half-built app AND
    # its created AppRole must actually be gone.
    assert [c[0] for c in app.calls][-3:] == [
        "delete_application",
        "list_applications",
        "delete_app_role",
    ]


@pytest.mark.asyncio
async def test_doctor_read_failure_fails_the_run_and_cleans_up() -> None:
    role_name = f"{APP_NAME} Role"
    app = _app_for_happy_path(role_name)
    app.results["list_applications"].append([])
    flow = _flow_for_happy_path()
    # calls 1 and 2 are the graph write's own pre-read and read-back; call 3 is
    # `doctor_report`'s own `get_draft` -- make ONLY that one fail.
    flow.fail_get_draft_on_call = 3

    with pytest.raises(ApplicationError, match="doctor read failed") as exc_info:
        await _run(app, flow)
    assert exc_info.value.code == "REPOSITORY_ERROR"
    assert [c[0] for c in app.calls][-3:] == [
        "delete_application",
        "list_applications",
        "delete_app_role",
    ]
