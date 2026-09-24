"""`use_cases.flow.forge_publish.ForgePublish`."""

from __future__ import annotations

import pytest
from tests.fakes.app import FakeAppRepository
from tests.fakes.flow import FakeFlowRepository
from tests.fakes.page import FakePageRepository
from tests.unit.application.use_cases.test_write_order_contract import (
    assert_write_order,
)

from app.application.exceptions import ApplicationError, RepositoryError
from app.application.models.requests.flow.forge_publish_request import (
    ForgePublishRequest,
)
from app.application.use_cases.flow.forge_publish import ForgePublish
from app.domain.entities.flow_draft import FlowDraft
from app.domain.entities.navigation import Navigation
from app.domain.entities.page_draft import PageDraft


@pytest.mark.asyncio
async def test_publishes_a_process_and_reads_back_its_status() -> None:
    flow = FakeFlowRepository()
    flow.results["get_draft"] = [FlowDraft.from_wire({"_meta_version": "v1"})]
    flow.results["get_flow_detail"] = [{"Status": "Live"}]
    uc = ForgePublish(flow, FakePageRepository(), FakeAppRepository())

    resp = await uc.execute(
        ForgePublishRequest(
            kind="process", flow_id="F1", app_id="A1", app_id_given=True
        )
    )

    assert resp.published is True
    assert resp.status == "Live"
    assert resp.snapshot_version == "v1"
    assert_write_order(flow)


@pytest.mark.asyncio
async def test_a_flow_publish_raises_when_the_readback_status_is_not_live() -> None:
    """Lesson 7: a publish whose read-back status is not "Live" is a failure, never
    a success carrying that status (matches the former `status != "Live"` isError
    rule)."""
    flow = FakeFlowRepository()
    flow.results["get_draft"] = [FlowDraft.from_wire({"_meta_version": "v1"})]
    flow.results["get_flow_detail"] = [{"Status": "Draft"}]
    uc = ForgePublish(flow, FakePageRepository(), FakeAppRepository())

    with pytest.raises(ApplicationError) as exc:
        await uc.execute(
            ForgePublishRequest(
                kind="process", flow_id="F1", app_id="A1", app_id_given=True
            )
        )
    assert exc.value.code == "VERIFY_FAILED"
    assert "Draft" in exc.value.message
    assert "write did not fully land" in exc.value.message
    assert "published=True" in exc.value.message
    assert "--" not in exc.value.message, "product text uses an em dash, never '--'"


@pytest.mark.asyncio
async def test_publishes_a_page_when_app_id_was_explicitly_given() -> None:
    page = FakePageRepository()
    page.results["get_page_draft"] = [PageDraft.from_wire({"_meta_version": "v2"})]
    uc = ForgePublish(FakeFlowRepository(), page, FakeAppRepository())

    resp = await uc.execute(
        ForgePublishRequest(kind="page", flow_id="P1", app_id="A1", app_id_given=True)
    )

    assert resp.kind == "page"
    assert resp.status is None
    assert resp.snapshot_version == "v2"
    assert_write_order(page)


@pytest.mark.asyncio
async def test_publishing_a_page_is_refused_when_app_id_was_not_given() -> None:
    page = FakePageRepository()
    uc = ForgePublish(FakeFlowRepository(), page, FakeAppRepository())

    with pytest.raises(ApplicationError) as exc:
        await uc.execute(
            ForgePublishRequest(
                kind="page", flow_id="P1", app_id="KF_APP_DEFAULT", app_id_given=False
            )
        )
    assert exc.value.code == "VERIFY_FAILED"
    assert page.calls == []


@pytest.mark.asyncio
async def test_publishes_an_application_using_flow_id_as_its_own_target() -> None:
    app = FakeAppRepository()
    app.results["get_app_draft"] = [Navigation.from_wire({"_meta_version": "v3"})]
    uc = ForgePublish(FakeFlowRepository(), FakePageRepository(), app)

    resp = await uc.execute(
        ForgePublishRequest(
            kind="application", flow_id="App1", app_id="A1", app_id_given=True
        )
    )

    assert resp.id == "App1"
    assert resp.snapshot_version == "v3"
    assert app.calls == [
        ("get_app_draft", ("App1",), {}),
        ("publish_app", ("App1",), {}),
    ]


@pytest.mark.asyncio
async def test_no_app_selected_is_refused_for_every_kind() -> None:
    uc = ForgePublish(FakeFlowRepository(), FakePageRepository(), FakeAppRepository())
    with pytest.raises(ApplicationError) as exc:
        await uc.execute(
            ForgePublishRequest(
                kind="application", flow_id="App1", app_id="", app_id_given=False
            )
        )
    assert exc.value.code == "REFUSED"


def _raise(exc: Exception):
    async def _fn(*args: object, **kwargs: object) -> object:
        raise exc

    return _fn


def _uc(
    flow: FakeFlowRepository | None = None,
    page: FakePageRepository | None = None,
    app: FakeAppRepository | None = None,
) -> ForgePublish:
    return ForgePublish(
        flow or FakeFlowRepository(),
        page or FakePageRepository(),
        app or FakeAppRepository(),
    )


# ---- ported from tests/test_p2_server.py ---------------------------------------------


@pytest.mark.asyncio
async def test_forge_publish_reports_success_when_status_reads_back_live() -> None:
    """The old dict was {kind, id, published, status, isError: False}; the success
    DTO drops isError and adds the snapshot version."""
    flow = FakeFlowRepository()
    flow.results["get_draft"] = [FlowDraft.from_wire({"_meta_version": "v1"})]
    flow.results["get_flow_detail"] = [{"_id": "F1", "Status": "Live"}]

    resp = await _uc(flow=flow).execute(
        ForgePublishRequest(
            kind="process", flow_id="F1", app_id="A1", app_id_given=False
        )
    )

    assert resp.model_dump() == {
        "kind": "process",
        "id": "F1",
        "published": True,
        "status": "Live",
        "snapshot_version": "v1",
    }


@pytest.mark.asyncio
async def test_a_failed_status_readback_says_the_publish_itself_succeeded() -> None:
    """The former tool said "publish succeeded but status read-back failed: ...", so
    a caller never re-publishes blind. That sentence survives, now as a failure."""
    flow = FakeFlowRepository()
    flow.results["get_draft"] = [FlowDraft.from_wire({"_meta_version": "v1"})]
    flow.get_flow_detail = _raise(RepositoryError("GET flow detail -> 503"))

    with pytest.raises(ApplicationError) as exc:
        await _uc(flow=flow).execute(
            ForgePublishRequest(
                kind="process", flow_id="F1", app_id="A1", app_id_given=False
            )
        )

    assert exc.value.code == "VERIFY_FAILED"
    assert (
        "publish succeeded but status read-back failed: GET flow detail -> 503"
        in exc.value.message
    )
    assert "published=True" in exc.value.message
    assert "--" not in exc.value.message, "product text uses an em dash, never '--'"
    assert [c[0] for c in flow.calls] == ["get_draft", "publish"]


@pytest.mark.asyncio
async def test_forge_publish_page_kind_requires_app_id() -> None:
    page = FakePageRepository()

    with pytest.raises(ApplicationError) as exc:
        await _uc(page=page).execute(
            ForgePublishRequest(
                kind="page", flow_id="Page1", app_id="A_DEFAULT", app_id_given=False
            )
        )

    assert exc.value.message == "app_id is required to publish a page"
    assert page.calls == []


@pytest.mark.asyncio
async def test_forge_publish_page_kind_happy_path() -> None:
    page = FakePageRepository()
    page.results["get_page_draft"] = [PageDraft.from_wire({"_meta_version": "v2"})]

    resp = await _uc(page=page).execute(
        ForgePublishRequest(
            kind="page", flow_id="Page1", app_id="App1", app_id_given=True
        )
    )

    # the old dict never carried a `status` key for a page publish at all
    # (server.py's own literal dict) -- the response DTO leaves it out too.
    assert resp.model_dump() == {
        "kind": "page",
        "id": "Page1",
        "published": True,
        "snapshot_version": "v2",
    }
    assert page.calls[1] == ("publish_page", ("App1", "Page1"), {})


@pytest.mark.asyncio
async def test_forge_publish_page_kind_propagates_publish_failure() -> None:
    page = FakePageRepository()
    page.results["get_page_draft"] = [PageDraft.from_wire({"_meta_version": "v2"})]
    page.publish_page = _raise(RepositoryError("POST page publish -> 500"))

    with pytest.raises(ApplicationError) as exc:
        await _uc(page=page).execute(
            ForgePublishRequest(
                kind="page", flow_id="Page1", app_id="App1", app_id_given=True
            )
        )

    assert "500" in exc.value.message


@pytest.mark.asyncio
async def test_forge_publish_application_kind_happy_path() -> None:
    app = FakeAppRepository()
    app.results["get_app_draft"] = [Navigation.from_wire({"_meta_version": "v3"})]

    resp = await _uc(app=app).execute(
        ForgePublishRequest(
            kind="application", flow_id="App1", app_id="A1", app_id_given=False
        )
    )

    # the old dict never carried a `status` key for an application publish
    # either -- the response DTO leaves it out too.
    assert resp.model_dump() == {
        "kind": "application",
        "id": "App1",
        "published": True,
        "snapshot_version": "v3",
    }
    assert app.calls[1] == ("publish_app", ("App1",), {})


@pytest.mark.asyncio
async def test_forge_publish_application_kind_propagates_publish_failure() -> None:
    app = FakeAppRepository()
    app.results["get_app_draft"] = [Navigation.from_wire({"_meta_version": "v3"})]
    app.publish_app = _raise(RepositoryError("POST app publish -> 500"))

    with pytest.raises(ApplicationError) as exc:
        await _uc(app=app).execute(
            ForgePublishRequest(
                kind="application", flow_id="App1", app_id="A1", app_id_given=False
            )
        )

    assert "500" in exc.value.message
