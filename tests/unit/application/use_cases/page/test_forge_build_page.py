"""`ForgeBuildPage`: ported from `tests/test_pages_live.py`'s
`test_apply_page_build_*` (raw `steps` entry) and `test_apply_build_page_op_*`
(governed `op` entry) cases (pre-refactor), now against the response DTO or
the raised `ApplicationError` and its code, with
`tests.fakes.page.FakePageRepository`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from tests.fakes.page import FakePageRepository
from tests.unit.application.use_cases.test_write_order_contract import (
    assert_write_order,
)

from app.application.exceptions import ApplicationError
from app.application.models.requests.page.forge_build_page_request import (
    ForgeBuildPageRequest,
)
from app.application.use_cases.page.forge_build_page import ForgeBuildPage
from app.domain.entities.page_draft import PageDraft


def _virgin() -> PageDraft:
    return PageDraft.new("Sample Page")


class _StatefulFakePageRepository(FakePageRepository):
    """Real stateful get/put for `get_page_draft`/`put_page_draft`: whatever
    `put_page_draft` stores IS what the next `get_page_draft` returns.

    `PageDraft.add_container`/`add_widget`/... mint RANDOM node ids
    (`secrets.choice`), so a test cannot precompute the "after" draft
    separately and queue it as a canned read-back -- its ids would never
    match what the use case itself mints. Mirrors the pre-refactor
    `FakePageClient(KfClient)`'s own real-storage behaviour.
    """

    def __init__(self, initial: PageDraft) -> None:
        super().__init__()
        self._stored = initial

    async def get_page_draft(self, app_id: str, page_id: str) -> PageDraft:
        self.calls.append(("get_page_draft", (app_id, page_id), {}))
        return self._stored

    async def put_page_draft(
        self, app_id: str, page_id: str, new: PageDraft, expect_version: str | None
    ) -> PageDraft:
        self.calls.append(
            (
                "put_page_draft",
                (app_id, page_id, new),
                {"expect_version": expect_version},
            )
        )
        self._stored = new
        return new


class _MutatingFakePageRepository(_StatefulFakePageRepository):
    """`put_page_draft` "succeeds" (200), but the stored draft is passed
    through `transform` first -- the write-succeeds-but-something-silently-
    never-landed trap THE RULE exists to catch (review fix 4; mirrors the
    old `pages_live.py` tests' own `Dropping*(FakePageClient)` subclasses,
    pre-refactor: the "host kept, content dropped" family of read-back
    traps)."""

    def __init__(
        self,
        initial: PageDraft,
        transform: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> None:
        super().__init__(initial)
        self._transform = transform

    async def put_page_draft(
        self, app_id: str, page_id: str, new: PageDraft, expect_version: str | None
    ) -> PageDraft:
        self.calls.append(
            (
                "put_page_draft",
                (app_id, page_id, new),
                {"expect_version": expect_version},
            )
        )
        self._stored = PageDraft.from_wire(self._transform(new.to_wire()))
        return self._stored


def _drop_kind(kind: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """A `transform` that drops every node of `kind` from the wire dict."""

    def _transform(wire: dict[str, Any]) -> dict[str, Any]:
        return {
            k: v
            for k, v in wire.items()
            if not (isinstance(v, dict) and v.get("Kind") == kind)
        }

    return _transform


def _steps_request(**overrides: Any) -> ForgeBuildPageRequest:
    fields: dict[str, Any] = {
        "app_id": "App1",
        "page_id": "Page_1",
        "steps": [
            {
                "kind": "container",
                "kwargs": {"parent_id": "Container001", "name": "Banner"},
            }
        ],
    }
    fields.update(overrides)
    return ForgeBuildPageRequest(**fields)


def _op(name: str = "Ops Home", **over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "name": name,
        "widgets": ({"slug": "general/label", "config": {"title": "Welcome"}},),
        "kpis": ("Open cases",),
        "actions": ("New Case",),
        "popups": (
            {
                "name": "New Case Form",
                "widgets": ({"slug": "general/label", "config": {"title": "Fill me"}},),
            },
        ),
        "on_click": (
            {
                "action": "New Case",
                "kind": "OpenPopup",
                "target_popup": "New Case Form",
            },
        ),
    }
    base.update(over)
    return base


def _op_request(**overrides: Any) -> ForgeBuildPageRequest:
    fields: dict[str, Any] = {"app_id": "App1", "op": _op()}
    fields.update(overrides)
    return ForgeBuildPageRequest(**fields)


# ============================================================================
# The raw `steps` + `page_id` primitive
# ============================================================================


@pytest.mark.asyncio
async def test_steps_entry_applies_and_verifies() -> None:
    fake = _StatefulFakePageRepository(_virgin())

    resp = await ForgeBuildPage(page=fake).execute(_steps_request())

    assert resp.missing == []
    assert len(resp.applied) == 1
    assert resp.verified == resp.applied
    assert resp.node_counts is not None
    assert [c[0] for c in fake.calls] == [
        "get_page_draft",
        "put_page_draft",
        "get_page_draft",
    ]
    assert_write_order(fake)


@pytest.mark.asyncio
async def test_steps_entry_offline_rejection_never_reaches_put() -> None:
    """Mirrors
    `test_apply_page_build_view_table_needs_full_binding_or_raises_offline`."""
    fake = FakePageRepository()
    fake.results["get_page_draft"] = [_virgin()]

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeBuildPage(page=fake).execute(
            _steps_request(
                steps=[
                    {
                        "kind": "widget",
                        "kwargs": {
                            "container_id": "Container001",
                            "widget": "view/table",
                            "config": {},
                        },
                    }
                ]
            )
        )

    assert exc_info.value.code == "VERIFY_FAILED"
    assert [c[0] for c in fake.calls] == ["get_page_draft"]


@pytest.mark.asyncio
async def test_steps_entry_completely_unchanged_readback_is_verify_failed() -> None:
    """The write "succeeds" but the read-back reflects NONE of it -- the
    simplest member of the silent-discard class; see the more surgical
    "host kept, content dropped" ports below for the trap this whole class
    exists to catch."""
    before = _virgin()
    fake = FakePageRepository()
    fake.results["get_page_draft"] = [before, before]  # unchanged read-back

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeBuildPage(page=fake).execute(_steps_request(publish=True))

    assert exc_info.value.code == "VERIFY_FAILED"
    assert "published=False" in exc_info.value.message
    assert not any(c[0] == "publish_page" for c in fake.calls)
    # Review fix 1: the draft PUT already landed -- a retry of the same
    # `steps` would add every widget again unless the caller can see
    # `page_id` and what was already `applied` (pages_live.py:117-128,
    # pre-refactor: both fields lived in the OLD `isError: true` dict).
    assert "page_id=Page_1" in exc_info.value.message
    assert "applied=" in exc_info.value.message and "container" in (
        exc_info.value.message
    )


@pytest.mark.asyncio
async def test_steps_entry_widget_component_dropped_is_verify_failed() -> None:
    """Mirrors `test_apply_page_build_detects_a_widget_silently_dropped_by_the_write`
    (pages_live.py:480, pre-refactor): the widget's own shell id survives the
    write, but its substance -- the Component node -- silently never lands.
    The shell surviving alone must NOT read as verified."""
    fake = _MutatingFakePageRepository(_virgin(), _drop_kind("Component"))

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeBuildPage(page=fake).execute(
            _steps_request(
                steps=[
                    {
                        "kind": "widget",
                        "kwargs": {
                            "container_id": "Container001",
                            "widget": "general/label",
                            "config": {"title": "Hello"},
                        },
                    }
                ],
                publish=True,
            )
        )

    assert exc_info.value.code == "VERIFY_FAILED"
    assert "published=False" in exc_info.value.message
    assert not any(c[0] == "publish_page" for c in fake.calls)


@pytest.mark.asyncio
async def test_steps_entry_event_mapping_dropped_is_verify_failed() -> None:
    """Mirrors
    `test_apply_page_build_detects_an_event_mapping_silently_dropped_by_the_write`
    (pages_live.py:368, pre-refactor): the PUT succeeds but the EventMapping
    node itself never actually lands on the read-back."""
    fake = _MutatingFakePageRepository(_virgin(), _drop_kind("EventMapping"))

    popup_resp = await ForgeBuildPage(page=fake).execute(
        _steps_request(steps=[{"kind": "popup", "kwargs": {"name": "Detail Popup"}}])
    )
    assert popup_resp.missing == []
    popup_id = next(
        nid
        for nid, node in fake._stored.to_wire().items()
        if isinstance(node, dict) and node.get("Kind") == "Popup"
    )

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeBuildPage(page=fake).execute(
            _steps_request(
                steps=[
                    {
                        "kind": "event",
                        "kwargs": {
                            "container_id": "Container001",
                            "type": "OpenPopup",
                            "popup_id": popup_id,
                        },
                    }
                ],
                publish=True,
            )
        )

    assert exc_info.value.code == "VERIFY_FAILED"
    assert "published=False" in exc_info.value.message
    assert not any(c[0] == "publish_page" for c in fake.calls)


@pytest.mark.asyncio
async def test_steps_entry_event_mapping_property_dropped_is_verify_failed() -> None:
    """Mirrors
    `test_apply_page_build_detects_an_event_mapping_property_silently_dropped_by_the_write`
    (pages_live.py:413, pre-refactor): the EventMapping node is only the
    SHELL -- the real payload (the target popup id) lives on a separate
    Property node (`EventMapping::Property`). A write that keeps the empty
    shell but drops that Property must NOT read as verified."""

    def _drop_event_property(wire: dict[str, Any]) -> dict[str, Any]:
        return {
            k: v
            for k, v in wire.items()
            if not (
                isinstance(v, dict)
                and v.get("Kind") == "Property"
                and v.get("EventMapping") is not None
            )
        }

    fake = _MutatingFakePageRepository(_virgin(), _drop_event_property)

    popup_resp = await ForgeBuildPage(page=fake).execute(
        _steps_request(steps=[{"kind": "popup", "kwargs": {"name": "Detail Popup"}}])
    )
    assert popup_resp.missing == []
    popup_id = next(
        nid
        for nid, node in fake._stored.to_wire().items()
        if isinstance(node, dict) and node.get("Kind") == "Popup"
    )

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeBuildPage(page=fake).execute(
            _steps_request(
                steps=[
                    {
                        "kind": "event",
                        "kwargs": {
                            "container_id": "Container001",
                            "type": "OpenPopup",
                            "popup_id": popup_id,
                        },
                    }
                ],
                publish=True,
            )
        )

    assert exc_info.value.code == "VERIFY_FAILED"
    assert "published=False" in exc_info.value.message
    assert not any(c[0] == "publish_page" for c in fake.calls)


@pytest.mark.asyncio
async def test_steps_entry_bind_value_dropped_is_verify_failed() -> None:
    """Mirrors `test_apply_page_build_detects_a_bind_value_that_never_landed`
    (pages_live.py:679, pre-refactor): the PUT succeeds but the rebound
    Property.Value never actually reflects the requested config."""

    def _drop_rebind_value(wire: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k, v in wire.items():
            if isinstance(v, dict) and v.get("Value") == "Flow_rebind99":
                v = {kk: vv for kk, vv in v.items() if kk != "Value"}
            out[k] = v
        return out

    fake = _MutatingFakePageRepository(_virgin(), lambda w: w)

    widget_resp = await ForgeBuildPage(page=fake).execute(
        _steps_request(
            steps=[
                {
                    "kind": "widget",
                    "kwargs": {
                        "container_id": "Container001",
                        "widget": "view/form",
                        "config": {"flow_type": "Process", "flow_id": "Flow_x"},
                    },
                }
            ]
        )
    )
    assert widget_resp.missing == []
    host = next(
        v["Id"]
        for v in fake._stored.to_wire().values()
        if isinstance(v, dict)
        and v.get("Kind") == "Container"
        and v.get("Container::Component")
    )

    fake._transform = _drop_rebind_value
    with pytest.raises(ApplicationError) as exc_info:
        await ForgeBuildPage(page=fake).execute(
            _steps_request(
                steps=[
                    {
                        "kind": "bind",
                        "kwargs": {
                            "host": host,
                            "config": {"flow_id": "Flow_rebind99"},
                        },
                    }
                ]
            )
        )

    assert exc_info.value.code == "VERIFY_FAILED"


@pytest.mark.asyncio
async def test_steps_entry_publishes_when_requested_and_verified() -> None:
    fake = _StatefulFakePageRepository(_virgin())

    resp = await ForgeBuildPage(page=fake).execute(_steps_request(publish=True))

    assert resp.published is True
    assert [c[0] for c in fake.calls] == [
        "get_page_draft",
        "put_page_draft",
        "get_page_draft",
        "publish_page",
    ]


@pytest.mark.asyncio
async def test_page_id_none_on_the_steps_entry_is_refused() -> None:
    """Belt-and-braces: the DTO's own `model_validator` already refuses this
    shape (see `test_forge_build_page_request.py`); this proves the use
    case's own defensive check too, via `model_construct` to bypass that
    validator."""
    request = ForgeBuildPageRequest.model_construct(
        app_id="App1", page_id=None, steps=[], publish=False, op=None
    )
    fake = FakePageRepository()

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeBuildPage(page=fake).execute(request)

    assert exc_info.value.code == "REFUSED"
    assert fake.calls == []


# ============================================================================
# The governed `op` executor
# ============================================================================


@pytest.mark.asyncio
async def test_op_entry_builds_widgets_popups_actions_and_verifies() -> None:
    fake = _StatefulFakePageRepository(_virgin())
    fake.results["list_pages"] = [[]]
    fake.results["create_page"] = ["Page_new"]

    resp = await ForgeBuildPage(page=fake).execute(_op_request())

    assert resp.page_created is True
    assert resp.page_name == "Ops Home"
    assert resp.missing == []
    assert resp.refused == []
    assert set(resp.built) == {
        "widget:general/label",
        "popup:New Case Form",
        "popup:New Case Form/widget:general/label",
        "action:New Case",
        "on_click:New Case",
    }
    assert resp.skipped and "Known Exclusion" in resp.skipped[0]
    assert [c[0] for c in fake.calls] == [
        "list_pages",
        "create_page",
        "get_page_draft",
        "put_page_draft",
        "get_page_draft",
    ]
    assert_write_order(fake)


@pytest.mark.asyncio
async def test_op_entry_missing_readback_items_is_verify_failed() -> None:
    """Mirrors `test_apply_build_page_op_missing_readback_items`
    (pages_live.py:1115, pre-refactor): the write "succeeds" but a widget's
    own Component silently never lands on the read-back."""
    fake = _MutatingFakePageRepository(_virgin(), _drop_kind("Component"))
    fake.results["list_pages"] = [[]]
    fake.results["create_page"] = ["Page_new"]

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeBuildPage(page=fake).execute(_op_request())

    assert exc_info.value.code == "VERIFY_FAILED"
    assert "widget:general/label" in exc_info.value.message


@pytest.mark.asyncio
async def test_op_entry_publishes_when_requested_and_succeeds() -> None:
    """Mirrors the success half of
    `test_apply_build_page_op_publish_success_and_error`
    (pages_live.py:1082, pre-refactor)."""
    fake = _StatefulFakePageRepository(_virgin())
    fake.results["list_pages"] = [[]]
    fake.results["create_page"] = ["Page_new"]

    resp = await ForgeBuildPage(page=fake).execute(_op_request(publish=True))

    assert resp.published is True
    assert any(c[0] == "publish_page" for c in fake.calls)


@pytest.mark.asyncio
async def test_op_entry_no_name_is_verify_failed_before_any_call() -> None:
    fake = FakePageRepository()

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeBuildPage(page=fake).execute(_op_request(op={}))

    assert exc_info.value.code == "VERIFY_FAILED"
    assert "no 'name'" in exc_info.value.message
    assert fake.calls == []


@pytest.mark.asyncio
async def test_op_entry_no_body_container_is_verify_failed() -> None:
    fake = FakePageRepository()
    fake.results["list_pages"] = [[{"_id": "p1", "Name": "NoBody"}]]
    fake.results["get_page_draft"] = [PageDraft.from_wire({"Root": "Page1"})]

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeBuildPage(page=fake).execute(_op_request(op=_op(name="NoBody")))

    assert exc_info.value.code == "VERIFY_FAILED"
    assert "no Body container" in exc_info.value.message


@pytest.mark.asyncio
async def test_op_entry_refuses_a_dangling_popup_target_and_skips_publish() -> None:
    fake = FakePageRepository()
    fake.results["list_pages"] = [[]]
    fake.results["create_page"] = ["Page_new"]
    fake.results["get_page_draft"] = [_virgin(), _virgin()]

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeBuildPage(page=fake).execute(
            _op_request(op=_op(popups=()), publish=True)
        )

    assert exc_info.value.code == "VERIFY_FAILED"
    assert "unknown popup" in exc_info.value.message
    assert not any(c[0] == "publish_page" for c in fake.calls)
    # Review fix 1: the page was already created and its draft PUT already
    # landed -- pages_live.py:493-507 (pre-refactor) kept page_id,
    # page_created, built and verified in its own `isError: true` dict, so
    # a caller of a failing `op` never has to guess whether it must run
    # forge_create_page again.
    assert "page_id=Page_new" in exc_info.value.message
    assert "page_created=True" in exc_info.value.message
    assert "built=" in exc_info.value.message


@pytest.mark.asyncio
async def test_op_entry_reuses_an_existing_page_by_name() -> None:
    fake = FakePageRepository()
    fake.results["list_pages"] = [[{"_id": "Page_existing", "Name": "Ops Home"}]]
    fake.results["get_page_draft"] = [_virgin(), _virgin()]

    resp = await ForgeBuildPage(page=fake).execute(
        _op_request(op=_op(widgets=(), popups=(), actions=(), on_click=(), kpis=()))
    )

    assert resp.page_created is False
    assert resp.page_id == "Page_existing"
    assert not any(c[0] == "create_page" for c in fake.calls)
    # nothing built -> no put_page_draft, but still reads back once
    assert [c[0] for c in fake.calls] == [
        "list_pages",
        "get_page_draft",
        "get_page_draft",
    ]


@pytest.mark.asyncio
async def test_op_entry_publish_skipped_when_refused() -> None:
    fake = FakePageRepository()
    fake.results["list_pages"] = [[]]
    fake.results["create_page"] = ["Page_new"]
    fake.results["get_page_draft"] = [_virgin(), _virgin()]

    with pytest.raises(ApplicationError):
        await ForgeBuildPage(page=fake).execute(
            _op_request(op=_op(popups=()), publish=True)
        )

    assert not any(c[0] == "publish_page" for c in fake.calls)


@pytest.mark.asyncio
async def test_empty_app_id_is_refused_before_any_call() -> None:
    fake = FakePageRepository()

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeBuildPage(page=fake).execute(_op_request(app_id=""))

    assert exc_info.value.code == "REFUSED"
    assert fake.calls == []
