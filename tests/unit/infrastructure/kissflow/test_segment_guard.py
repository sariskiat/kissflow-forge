"""Regression guard over every adapter's `_segment()`-bound path arguments (round 3,
security-judge nit 1: "no test stops a later edit from dropping the guard").

Source: caller ids reaching a public adapter method (`flow_id`, `app_id`, `page_id`,
`role_id`, `report_id`, `list_id`, `iid`, `aiid`, ...). Sink: the f-string-built
request URL each of `flow.py`/`app.py`/`page.py`/`dataset.py`/`item.py`/`copilot.py`
builds. Guard: `quote_path_segment` (`_http.py`), reached through each adapter's own
`_segment()`.

Before this module, only six of the dozens of `_segment()`-guarded call sites carried
a refusal test at all: `test_flow.py`'s `delete_member`, `test_app.py`'s
`delete_app_role`, `test_item.py`'s `put_fields`, and `test_page.py`'s `delete_page`/
`publish_page`/`put_page_draft`. Nothing stopped a later edit from dropping
`self._segment(...)` off any OTHER call site and shipping it clean: on a scratch copy
(never committed to this repository -- see the round-3 hardening report for the
transcript), removing the guard from `KissflowFlowRepository.get_flow_detail` and
from `KissflowAppRepository.archive_application` left every test in the suite,
including those six, green.

`_ADAPTERS` below carries one row per public method of the six adapter classes, and
each row lists every keyword argument that reaches `self._segment(...)`.
`test_the_table_covers_every_public_method` fails the moment a new adapter method
ships with no row. `test_refuses_unsafe_path_segment` fails the moment any listed
argument's `self._segment(...)` call is ever removed, for both `""` and `".."` -- the
two values `quote_path_segment` refuses outright, before any percent-encoding runs.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
from tests.unit.infrastructure.kissflow._fixtures import BASE_URL, settings

from app.application.exceptions import (
    ApplicationError,
    ExternalServiceError,
    RepositoryError,
)
from app.domain.entities.flow_draft import FlowDraft
from app.domain.entities.navigation import Navigation
from app.domain.entities.page_draft import PageDraft
from app.infrastructure.kissflow.app import KissflowAppRepository
from app.infrastructure.kissflow.copilot import KissflowCopilotService
from app.infrastructure.kissflow.dataset import KissflowDatasetRepository
from app.infrastructure.kissflow.flow import KissflowFlowRepository
from app.infrastructure.kissflow.item import KissflowItemService
from app.infrastructure.kissflow.page import KissflowPageRepository

_FLOW_DRAFT = FlowDraft.from_wire({"_meta_version": "v1"})
_PAGE_DRAFT = PageDraft.from_wire({"_meta_version": "v1"})
_NAVIGATION = Navigation.from_wire({"_meta_version": "v1"})


@dataclass(frozen=True)
class _Case:
    """One public adapter method: a valid call, and which kwargs are path segments.

    Attributes:
        kwargs: Every keyword argument the method needs, all set to a valid
            value.
        segment_args: The names of the `kwargs` entries that reach
            `self._segment(...)` -- the ones this module poisons, one at a
            time, to prove the guard still fires.
    """

    kwargs: dict[str, Any]
    segment_args: tuple[str, ...] = ()


_FLOW_CASES: dict[str, _Case] = {
    "get_draft": _Case(dict(app_id="A1", kind="process", flow_id="F1"), ("flow_id",)),
    "create_flow": _Case(dict(app_id="A1", kind="process", name="N")),
    "delete_flow": _Case(
        dict(app_id="A1", kind="process", flow_id="F1", archive_first=False),
        ("flow_id",),
    ),
    "publish": _Case(dict(app_id="A1", kind="process", flow_id="F1"), ("flow_id",)),
    "get_flow_detail": _Case(
        dict(app_id="A1", kind="process", flow_id="F1"), ("flow_id",)
    ),
    "list_flows": _Case(dict(app_id="A1", kind="process")),
    "get_members": _Case(dict(app_id="A1", kind="process", flow_id="F1"), ("flow_id",)),
    "delete_member": _Case(
        dict(app_id="A1", kind="process", flow_id="F1", role_id="R1"),
        ("flow_id", "role_id"),
    ),
    "post_member_batch": _Case(
        dict(app_id="A1", kind="process", flow_id="F1", members=[{"_id": "R1"}]),
        ("flow_id",),
    ),
    "post_report_member_batch": _Case(
        dict(app_id="A1", flow_id="F1", report_id="RP1", members=[{"_id": "R1"}]),
        ("flow_id", "report_id"),
    ),
    "get_list_items": _Case(dict(app_id="A1", list_id="L1"), ("list_id",)),
    "list_lists": _Case(dict(app_id="A1")),
    "create_list": _Case(dict(app_id="A1", name="N")),
    "set_list_items": _Case(dict(list_id="L1", items=["x"]), ("list_id",)),
    "create_dataset": _Case(dict(app_id="A1", name="N")),
    "create_case": _Case(dict(app_id="A1", name="N", item_type="Case", prefix="PFX")),
    "put_draft": _Case(
        dict(
            app_id="A1",
            kind="process",
            flow_id="F1",
            new=_FLOW_DRAFT,
            expect_version="v1",
        ),
        ("flow_id",),
    ),
}

_APP_CASES: dict[str, _Case] = {
    "list_app_roles": _Case(dict()),
    "get_app_role": _Case(dict(role_id="R1"), ("role_id",)),
    "put_app_role": _Case(dict(app_id="A1", role_id="R1", body={}), ("role_id",)),
    "get_assignee": _Case(dict(query="q")),
    "create_app_role": _Case(dict(name="N", app_id="A1")),
    "delete_app_role": _Case(dict(role_id="R1"), ("role_id",)),
    "list_applications": _Case(dict()),
    "create_application": _Case(dict(name="N")),
    "delete_application": _Case(dict(app_id="A1", archive_first=False), ("app_id",)),
    "get_app_draft": _Case(dict(app_id="A1"), ("app_id",)),
    "put_app_draft": _Case(
        dict(app_id="A1", new=_NAVIGATION, expect_version="v1"), ("app_id",)
    ),
    "publish_app": _Case(dict(app_id="A1"), ("app_id",)),
}

_PAGE_CASES: dict[str, _Case] = {
    "list_pages": _Case(dict(app_id="A1"), ("app_id",)),
    "create_page": _Case(dict(app_id="A1", name="N"), ("app_id",)),
    "delete_page": _Case(dict(app_id="A1", page_id="P1"), ("app_id", "page_id")),
    "get_page_draft": _Case(dict(app_id="A1", page_id="P1"), ("app_id", "page_id")),
    "put_page_draft": _Case(
        dict(app_id="A1", page_id="P1", new=_PAGE_DRAFT, expect_version="v1"),
        ("app_id", "page_id"),
    ),
    "publish_page": _Case(dict(app_id="A1", page_id="P1"), ("app_id", "page_id")),
}

_DATASET_CASES: dict[str, _Case] = {
    "create_dataset_record": _Case(
        dict(app_id="A1", flow_id="F1", record={}), ("flow_id",)
    ),
    "list_dataset_records": _Case(dict(app_id="A1", flow_id="F1"), ("flow_id",)),
    "update_dataset_record": _Case(
        dict(app_id="A1", flow_id="F1", record_id="RC1", record={}), ("flow_id",)
    ),
    "delete_dataset_record": _Case(
        dict(app_id="A1", flow_id="F1", record_id="RC1", name="N"), ("flow_id",)
    ),
}

_ITEM_CASES: dict[str, _Case] = {
    "create_item": _Case(dict(flow_id="F1"), ("flow_id",)),
    "put_fields": _Case(dict(flow_id="F1", iid="I1", payload={}), ("flow_id", "iid")),
    "get_detail": _Case(dict(flow_id="F1", iid="I1"), ("flow_id", "iid")),
    "submit": _Case(
        dict(flow_id="F1", iid="I1", aiid="AI1"), ("flow_id", "iid", "aiid")
    ),
    "reject": _Case(
        dict(flow_id="F1", iid="I1", aiid="AI1", comment="c"),
        ("flow_id", "iid", "aiid"),
    ),
}

_COPILOT_CASES: dict[str, _Case] = {
    "copilot_send": _Case(dict(app_id="A1", message="m"), ("app_id",)),
    "copilot_conversations": _Case(dict(app_id="A1"), ("app_id",)),
}


@dataclass(frozen=True)
class _AdapterUnderTest:
    """One adapter family: its class, its error class, and its method table."""

    cls: type
    error_cls: type[ApplicationError]
    cases: dict[str, _Case]


_ADAPTERS: dict[str, _AdapterUnderTest] = {
    "flow": _AdapterUnderTest(KissflowFlowRepository, RepositoryError, _FLOW_CASES),
    "app": _AdapterUnderTest(KissflowAppRepository, RepositoryError, _APP_CASES),
    "page": _AdapterUnderTest(KissflowPageRepository, RepositoryError, _PAGE_CASES),
    "dataset": _AdapterUnderTest(
        KissflowDatasetRepository, RepositoryError, _DATASET_CASES
    ),
    "item": _AdapterUnderTest(KissflowItemService, ExternalServiceError, _ITEM_CASES),
    "copilot": _AdapterUnderTest(
        KissflowCopilotService, ExternalServiceError, _COPILOT_CASES
    ),
}


def _public_methods(cls: type) -> set[str]:
    """The public methods `cls` itself defines -- not inherited, not private."""
    return {
        name
        for name, value in vars(cls).items()
        if not name.startswith("_") and inspect.isfunction(value)
    }


# =====================================================================
# 1. Completeness: a new adapter method with no row fails here, not
#    silently.
# =====================================================================


@pytest.mark.parametrize("adapter_name", sorted(_ADAPTERS))
def test_the_table_covers_every_public_method(adapter_name: str) -> None:
    adapter = _ADAPTERS[adapter_name]
    public = _public_methods(adapter.cls)
    table = set(adapter.cases)
    assert table == public, (
        f"{adapter.cls.__name__}: table rows {table - public} name no public "
        f"method; public methods {public - table} have no row"
    )


# =====================================================================
# 2. Every `_segment()`-bound argument still refuses `".."` and `""`, with
#    no request sent.
# =====================================================================

_REFUSAL_CASES: list[tuple[str, str, str]] = [
    (adapter_name, method_name, arg_name)
    for adapter_name, adapter in _ADAPTERS.items()
    for method_name, case in adapter.cases.items()
    for arg_name in case.segment_args
]


@pytest.mark.asyncio
@pytest.mark.parametrize("poison", ["..", ""], ids=["dotdot", "empty"])
@pytest.mark.parametrize(
    "adapter_name,method_name,arg_name",
    _REFUSAL_CASES,
    ids=[f"{a}.{m}.{arg}" for a, m, arg in _REFUSAL_CASES],
)
async def test_refuses_unsafe_path_segment(
    adapter_name: str, method_name: str, arg_name: str, poison: str
) -> None:
    adapter = _ADAPTERS[adapter_name]
    case = adapter.cases[method_name]
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200, json={"_id": "x", "_meta_version": "v1", "status": "success"}
        )

    kwargs = {**case.kwargs, arg_name: poison}
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        instance = adapter.cls(client=client, base_url=BASE_URL, settings=settings())
        with pytest.raises(adapter.error_cls) as excinfo:
            await getattr(instance, method_name)(**kwargs)

    assert excinfo.value.code == "REFUSED"
    assert calls == [], (
        f"{adapter_name}.{method_name}({arg_name}={poison!r}) reached the "
        f"wrong resource: {[str(c.url) for c in calls]}"
    )
