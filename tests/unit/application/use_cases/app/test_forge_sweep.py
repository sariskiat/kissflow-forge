"""Spec for app.application.use_cases.app.forge_sweep.

Ports `tests/test_p4_surface.py`'s `run_sweep` tests onto the new fake-port
architecture. `test_sweep_unknown_scope_rejected` is NOT ported here: the
closed `SweepScope` literal on `ForgeSweepRequest` now refuses it before this
use case ever runs (see
`tests/unit/application/models/requests/app/test_forge_sweep_request.py`).
"""

from __future__ import annotations

import pytest
from tests.fakes.app import FakeAppRepository
from tests.fakes.flow import FakeFlowRepository
from tests.fakes.page import FakePageRepository

from app.application.exceptions import REFUSED, ApplicationError, RepositoryError
from app.application.models.requests.app.forge_sweep_request import ForgeSweepRequest
from app.application.use_cases.app.forge_sweep import ForgeSweep


def _sweep(
    app: FakeAppRepository | None = None,
    flow: FakeFlowRepository | None = None,
    page: FakePageRepository | None = None,
) -> ForgeSweep:
    return ForgeSweep(
        app=app or FakeAppRepository(),
        flow=flow or FakeFlowRepository(),
        page=page or FakePageRepository(),
    )


@pytest.mark.asyncio
async def test_sweep_apps_reads_the_application_inventory() -> None:
    app = FakeAppRepository()
    app.results["list_applications"] = [[{"_id": "App_1", "Name": "Demo"}]]

    resp = await _sweep(app=app).execute(
        ForgeSweepRequest(scope="apps", app_id="App_1")
    )

    assert resp.ok is True
    assert resp.results["apps"] == {
        "status": "read",
        "count": 1,
        "items": [{"_id": "App_1", "Name": "Demo"}],
        "error": None,
    }


@pytest.mark.asyncio
async def test_sweep_flows_covers_every_kind_and_stays_scoped() -> None:
    flow = FakeFlowRepository()
    flow.results["list_flows"] = [
        [{"_id": "P1"}],  # process
        [],  # form
        [{"_id": "C1"}, {"_id": "C2"}],  # case
        [],  # list
        [],  # dataset
    ]

    resp = await _sweep(flow=flow).execute(
        ForgeSweepRequest(scope="flows", app_id="App_1")
    )

    assert resp.ok is True
    assert resp.results["flows"]["process"]["count"] == 1
    assert resp.results["flows"]["case"]["count"] == 2
    assert resp.results["flows"]["form"]["count"] == 0
    assert all(c[1][0] == "App_1" for c in flow.calls if c[0] == "list_flows")


@pytest.mark.asyncio
async def test_sweep_refuses_before_any_port_call_when_no_app_id_resolved() -> None:
    """Mirrors `server.py:2039`'s `_client(app_id)` with `require_app=True`:
    the OLD tool refused with the "no app selected" message before ANY
    tenant call, for every scope -- not only the ones that need an app id.
    Without this gate, `scope="all"` would call `list_flows("", kind)` and
    `list_lists("")`, the two whole-account leak routes CLAUDE.md names.
    """
    app = FakeAppRepository()
    flow = FakeFlowRepository()
    page = FakePageRepository()

    with pytest.raises(ApplicationError) as exc_info:
        await _sweep(app=app, flow=flow, page=page).execute(
            ForgeSweepRequest(scope="all", app_id="")
        )

    assert exc_info.value.code == REFUSED
    assert "no app selected" in exc_info.value.message
    assert app.calls == []
    assert flow.calls == []
    assert page.calls == []


@pytest.mark.asyncio
async def test_sweep_pages_reads_when_an_app_id_is_available() -> None:
    page = FakePageRepository()
    page.results["list_pages"] = [[{"_id": "Page_1"}]]

    resp = await _sweep(page=page).execute(
        ForgeSweepRequest(scope="pages", app_id="App_1")
    )

    assert resp.results["pages"] == {
        "status": "read",
        "count": 1,
        "items": [{"_id": "Page_1"}],
        "error": None,
    }


@pytest.mark.asyncio
async def test_sweep_roles_and_lists_under_all() -> None:
    app = FakeAppRepository()
    flow = FakeFlowRepository()
    app.results["list_applications"] = [[]]
    app.results["list_app_roles"] = [[{"_id": "R1", "Name": "Reviewer"}]]
    flow.results["list_flows"] = [[], [], [], [], []]
    flow.results["list_lists"] = [[{"_id": "List_1", "Name": "Priority"}]]
    page = FakePageRepository()
    page.results["list_pages"] = [[]]

    resp = await _sweep(app=app, flow=flow, page=page).execute(
        ForgeSweepRequest(scope="all", app_id="App")
    )

    assert resp.results["roles"]["count"] == 1
    assert resp.results["lists"]["count"] == 1


@pytest.mark.asyncio
async def test_sweep_lists_unwraps_a_data_envelope() -> None:
    """`list_lists`'s raw route sometimes answers `{"Data": [...]}` rather than a
    bare list -- `run_sweep`'s own defensive unwrap, carried forward."""
    flow = FakeFlowRepository()
    flow.results["list_lists"] = [{"Data": [{"_id": "List_1"}]}]

    resp = await _sweep(flow=flow).execute(ForgeSweepRequest(scope="lists", app_id="A"))

    assert resp.results["lists"] == {
        "status": "read",
        "count": 1,
        "items": [{"_id": "List_1"}],
        "error": None,
    }


@pytest.mark.asyncio
async def test_sweep_error_propagates_as_error_bucket_never_swallowed() -> None:
    class _Failing(FakeAppRepository):
        async def list_applications(self):  # type: ignore[override]
            raise RepositoryError("boom")

    resp = await _sweep(app=_Failing()).execute(
        ForgeSweepRequest(scope="apps", app_id="App_1")
    )

    assert resp.ok is False
    assert resp.results["apps"]["status"] == "error"
    assert "boom" in resp.results["apps"]["error"]
