"""`app.application.use_cases.item._walk`: ported from
`tests/test_dataplane.py` (pre-refactor) -- `live_aiid`/`usable_aiid` (now
raising `ValueError` instead of returning `Err`), `fill_and_verify`,
`advance`, `wait_new_aiid`, `field_name_index`/`resolve_value_keys`, and
`walk` itself, all now async over the `ItemService` port.

`_FakeItem` is the async, exception-raising port of `test_dataplane.py`'s own
`FakeClient` -- a real in-memory item store, not a canned-queue fake,
because `walk` reads a step's own `get_detail` more than once (fill-verify,
then the aiid derivation) and the state genuinely evolves between calls.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.application.exceptions import ExternalServiceError
from app.application.interfaces.item import ItemService
from app.application.use_cases.item._walk import (
    FillReport,
    StepPlan,
    StepResult,
    WalkReport,
    _detail_and_live_aiid,
    advance,
    field_name_index,
    fill_and_verify,
    live_aiid,
    resolve_value_keys,
    usable_aiid,
    wait_new_aiid,
    walk,
)

FLOW = "Flow_Sample01"
DECOY_AIID = "DECOY-CONSUMED-AIID"
LIVE_AIID = "LIVE-AIID-1"


def _detail(
    iid: str, step: str = "Start", *, with_context: bool = True
) -> dict[str, Any]:
    d: dict[str, Any] = {
        "_id": iid,
        "_current_step": step,
        "_status": "Draft",
        "_activity_instance_id": DECOY_AIID,
    }
    if with_context:
        d["_current_context"] = [{"_context_activity_instance_id": LIVE_AIID}]
    return d


class _FakeItem(ItemService):
    """In-memory `ItemService`. No network, no fastmcp -- a duck-typed stand-in
    exercising `walk`'s real orchestration offline."""

    def __init__(self) -> None:
        self.items: dict[str, dict[str, Any]] = {}
        self._next_id = 1
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.discard_keys: set[str] = set()
        self.mismatch_keys: set[str] = set()
        self.put_fails = False
        self.create_fails = False

    async def create_item(self, flow_id: str) -> dict[str, Any]:
        self.calls.append(("create_item", (flow_id,)))
        if self.create_fails:
            raise ExternalServiceError("create failed")
        iid = f"ITEM-{self._next_id}"
        self._next_id += 1
        self.items[iid] = _detail(iid)
        return {"_id": iid}

    async def put_fields(
        self, flow_id: str, iid: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        self.calls.append(("put_fields", (flow_id, iid, dict(payload))))
        if self.put_fails:
            raise ExternalServiceError("put failed")
        item = self.items[iid]
        for k, v in payload.items():
            if k in self.discard_keys:
                continue
            item[k] = f"ECHO-{v!r}" if k in self.mismatch_keys else v
        return {"ok": True}

    async def get_detail(self, flow_id: str, iid: str) -> dict[str, Any]:
        self.calls.append(("get_detail", (flow_id, iid)))
        return dict(self.items[iid])

    async def submit(self, flow_id: str, iid: str, aiid: str) -> dict[str, Any]:
        self.calls.append(("submit", (flow_id, iid, aiid)))
        self.items[iid]["_current_step"] = "Next"
        return {"ok": True, "aiid_used": aiid}

    async def reject(
        self, flow_id: str, iid: str, aiid: str, comment: str
    ) -> dict[str, Any]:
        self.calls.append(("reject", (flow_id, iid, aiid, comment)))
        self.items[iid]["_status"] = "Rejected"
        return {"ok": True, "aiid_used": aiid, "comment": comment}


def _plan(name: str, **kw: Any) -> StepPlan:
    return StepPlan(name=name, **kw)


# ------------------------------------------------------------------- live_aiid


def test_live_aiid_happy_path() -> None:
    assert live_aiid(_detail("ITEM-1")) == LIVE_AIID


def test_live_aiid_missing_current_context_raises_mentioning_the_trap() -> None:
    d = _detail("ITEM-1", with_context=False)
    with pytest.raises(ValueError, match="consumed|myitems") as exc_info:
        live_aiid(d)
    assert (
        "consumed" in str(exc_info.value).lower()
        or "myitems" in str(exc_info.value).lower()
    )


def test_live_aiid_empty_current_context_list_raises() -> None:
    d = _detail("ITEM-1")
    d["_current_context"] = []
    with pytest.raises(ValueError):
        live_aiid(d)


def test_live_aiid_never_returns_the_myitems_decoy() -> None:
    assert live_aiid(_detail("ITEM-1")) != DECOY_AIID


# ---------------------------------------------------------------- usable_aiid


def test_usable_aiid_prefers_live_context_over_the_create_fallback() -> None:
    got = usable_aiid(_detail("ITEM-1"), create_aiid="SOME-CREATE-AIID")
    assert got == LIVE_AIID


def test_usable_aiid_falls_back_to_create_aiid_when_context_is_absent() -> None:
    d = _detail("ITEM-1", with_context=False)
    assert usable_aiid(d, create_aiid="SOME-CREATE-AIID") == "SOME-CREATE-AIID"


def test_usable_aiid_without_a_fallback_behaves_exactly_like_live_aiid() -> None:
    d = _detail("ITEM-1", with_context=False)
    with pytest.raises(ValueError) as usable_exc:
        usable_aiid(d)
    with pytest.raises(ValueError) as live_exc:
        live_aiid(d)
    assert str(usable_exc.value) == str(live_exc.value)


def test_usable_aiid_fallback_never_shadows_the_myitems_decoy_check() -> None:
    got = usable_aiid(_detail("ITEM-1"), create_aiid=DECOY_AIID)
    assert got == LIVE_AIID and got != DECOY_AIID


# ------------------------------------------------------------- fill_and_verify


@pytest.mark.asyncio
async def test_fill_and_verify_all_landed() -> None:
    fake = _FakeItem()
    await fake.create_item(FLOW)
    rep = await fill_and_verify(
        fake,
        flow_id=FLOW,
        iid="ITEM-1",
        values={"sample_field_a": "x", "sample_field_b": 3},
    )
    assert isinstance(rep, FillReport)
    assert set(rep.landed) == {"sample_field_a", "sample_field_b"}
    assert rep.discarded == () and rep.mismatched == ()
    assert rep.ok() is True


@pytest.mark.asyncio
async def test_fill_and_verify_silently_discarded_select_like_value() -> None:
    fake = _FakeItem()
    await fake.create_item(FLOW)
    fake.discard_keys = {"sample_select_field"}
    rep = await fill_and_verify(
        fake,
        flow_id=FLOW,
        iid="ITEM-1",
        values={"sample_field_a": "x", "sample_select_field": "Not An Option"},
    )
    assert rep.landed == ("sample_field_a",)
    assert rep.discarded == ("sample_select_field",)
    assert rep.ok() is False


@pytest.mark.asyncio
async def test_fill_and_verify_mismatched_value() -> None:
    fake = _FakeItem()
    await fake.create_item(FLOW)
    fake.mismatch_keys = {"sample_field_c"}
    rep = await fill_and_verify(
        fake, flow_id=FLOW, iid="ITEM-1", values={"sample_field_c": "sent"}
    )
    assert rep.mismatched == ("sample_field_c",)
    assert rep.ok() is False


@pytest.mark.asyncio
async def test_fill_and_verify_propagates_put_failure_without_reading_detail() -> None:
    fake = _FakeItem()
    await fake.create_item(FLOW)
    fake.put_fails = True
    with pytest.raises(ExternalServiceError):
        await fill_and_verify(
            fake, flow_id=FLOW, iid="ITEM-1", values={"sample_field_a": "x"}
        )
    assert not any(name == "get_detail" for name, _ in fake.calls), (
        "a failed PUT must never be followed by a read-back GET"
    )


# -------------------------------------------------------------------- advance


@pytest.mark.asyncio
async def test_advance_uses_the_live_aiid_never_the_myitems_decoy() -> None:
    fake = _FakeItem()
    await fake.create_item(FLOW)
    got = await advance(fake, flow_id=FLOW, iid="ITEM-1")
    assert isinstance(got, StepResult)
    assert got.aiid == LIVE_AIID
    submit_calls = [args for name, args in fake.calls if name == "submit"]
    assert submit_calls == [(FLOW, "ITEM-1", LIVE_AIID)]


@pytest.mark.asyncio
async def test_advance_propagates_missing_context_as_valueerror() -> None:
    fake = _FakeItem()
    await fake.create_item(FLOW)
    fake.items["ITEM-1"].pop("_current_context")
    with pytest.raises(ValueError):
        await advance(fake, flow_id=FLOW, iid="ITEM-1")
    assert not any(name == "submit" for name, _ in fake.calls)


@pytest.mark.asyncio
async def test_advance_uses_the_create_aiid_fallback_when_context_missing() -> None:
    fake = _FakeItem()
    await fake.create_item(FLOW)
    fake.items["ITEM-1"].pop("_current_context")
    got = await advance(
        fake, flow_id=FLOW, iid="ITEM-1", create_aiid="CREATE-AIID-DIRECT"
    )
    assert got.aiid == "CREATE-AIID-DIRECT"


@pytest.mark.asyncio
async def test_advance_prefers_live_context_over_create_aiid_when_both_available() -> (
    None
):
    fake = _FakeItem()
    await fake.create_item(FLOW)
    got = await advance(
        fake, flow_id=FLOW, iid="ITEM-1", create_aiid="SHOULD-NOT-BE-USED"
    )
    assert got.aiid == LIVE_AIID


# ----------------------------------------------------------------------- walk


@pytest.mark.asyncio
async def test_walk_happy_path_counts_reconcile() -> None:
    fake = _FakeItem()
    steps = [
        _plan("step-1", values={"sample_field_a": "a1"}),
        _plan("step-2", values={"sample_field_b": "b2"}),
        _plan("step-3", values={"sample_field_c": "c3"}),
    ]
    rep = await walk(fake, flow_id=FLOW, steps=steps)
    assert isinstance(rep, WalkReport)
    assert rep.created is True
    assert rep.filled == ("step-1", "step-2", "step-3")
    assert rep.advanced == ("step-1", "step-2", "step-3")
    assert rep.rejected == () and rep.failed == ()
    assert rep.ok() is True
    assert all(args[2] == LIVE_AIID for name, args in fake.calls if name == "submit")


@pytest.mark.asyncio
async def test_walk_stops_at_first_failure_and_never_attempts_later_steps() -> None:
    fake = _FakeItem()
    fake.discard_keys = {"sample_field_b"}
    steps = [
        _plan("step-1", values={"sample_field_a": "a1"}),
        _plan("step-2", values={"sample_field_b": "b2"}),
        _plan("step-3", values={"sample_field_c": "c3"}),
    ]
    rep = await walk(fake, flow_id=FLOW, steps=steps)
    assert rep.filled == ("step-1",)
    assert rep.advanced == ("step-1",)
    assert rep.failed == ("step-2",)
    assert rep.error is not None and "step-2" in rep.error
    assert rep.ok() is False
    assert sum(1 for name, _ in fake.calls if name == "submit") == 1
    # Byte-exact against the pre-refactor `dataplane.walk`'s own f-string:
    # a tuple's repr (`('sample_field_b',)`), never `list(...)`'s (THE RULE,
    # product-text parity).
    assert rep.error == (
        "step-2: fill not verified — discarded=('sample_field_b',) mismatched=()"
    )


@pytest.mark.asyncio
async def test_walk_reject_path_sets_status_and_is_counted() -> None:
    fake = _FakeItem()
    steps = [
        _plan("step-1", values={"sample_field_a": "a1"}),
        _plan(
            "step-2",
            values={"sample_field_b": "b2"},
            reject=True,
            comment="not good enough",
        ),
    ]
    rep = await walk(fake, flow_id=FLOW, steps=steps)
    assert rep.advanced == ("step-1",)
    assert rep.rejected == ("step-2",)
    assert rep.ok() is True
    assert rep.iid is not None
    assert fake.items[rep.iid]["_status"] == "Rejected"
    reject_calls = [args for name, args in fake.calls if name == "reject"]
    assert reject_calls == [(FLOW, rep.iid, LIVE_AIID, "not good enough")]


@pytest.mark.asyncio
async def test_walk_create_failure_short_circuits_before_any_step() -> None:
    fake = _FakeItem()
    fake.create_fails = True
    rep = await walk(fake, flow_id=FLOW, steps=[_plan("step-1", values={"a": "a1"})])
    assert rep.created is False
    assert rep.iid is None
    assert rep.filled == () and rep.advanced == () and rep.failed == ()
    assert rep.error is not None
    assert rep.ok() is False
    assert fake.calls == [("create_item", (FLOW,))]


@pytest.mark.asyncio
async def test_walk_empty_step_list_still_creates() -> None:
    fake = _FakeItem()
    rep = await walk(fake, flow_id=FLOW, steps=[])
    assert rep.created is True and rep.iid is not None
    assert rep.ok() is True


# ------------------------------------------------ walk from Draft: two-phase aiid rule


class _TwoPhaseFakeItem(ItemService):
    """No `_current_context` until the first submit lands."""

    def __init__(self) -> None:
        self.create_aiid = "CREATE-AIID"
        self.context_aiid = "CONTEXT-AIID-1"
        self.submitted = False
        self.submit_calls: list[str] = []
        self.fields: dict[str, Any] = {}

    async def create_item(self, flow_id: str) -> dict[str, Any]:
        return {"_id": "ITEM-1", "_activity_instance_id": self.create_aiid}

    async def put_fields(
        self, flow_id: str, iid: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        self.fields.update(payload)
        return {"ok": True}

    async def get_detail(self, flow_id: str, iid: str) -> dict[str, Any]:
        base: dict[str, Any] = {"_id": iid, **self.fields}
        if not self.submitted:
            base["_current_step"] = "Start"
        else:
            base["_current_step"] = "Next"
            base["_current_context"] = [
                {"_context_activity_instance_id": self.context_aiid}
            ]
        return base

    async def submit(self, flow_id: str, iid: str, aiid: str) -> dict[str, Any]:
        self.submit_calls.append(aiid)
        self.submitted = True
        return {"ok": True}

    async def reject(
        self, flow_id: str, iid: str, aiid: str, comment: str
    ) -> dict[str, Any]:
        raise NotImplementedError("not exercised by this test")


@pytest.mark.asyncio
async def test_walk_uses_create_response_aiid_for_hop_one_then_context_after() -> None:
    fake = _TwoPhaseFakeItem()
    steps = [
        _plan("Step One", values={"sample_field_a": "a1"}),
        _plan("Step Two", values={"sample_field_b": "b2"}),
    ]
    rep = await walk(fake, flow_id=FLOW, steps=steps)
    assert rep.ok() is True
    assert rep.advanced == ("Step One", "Step Two")
    assert fake.submit_calls == ["CREATE-AIID", "CONTEXT-AIID-1"]


class _NeverRolloverFakeItem(ItemService):
    """Context NEVER shows up, even after a submit succeeds."""

    def __init__(self) -> None:
        self.submit_calls: list[str] = []
        self.fields: dict[str, Any] = {}

    async def create_item(self, flow_id: str) -> dict[str, Any]:
        return {"_id": "ITEM-1", "_activity_instance_id": "CREATE-AIID"}

    async def put_fields(
        self, flow_id: str, iid: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        self.fields.update(payload)
        return {"ok": True}

    async def get_detail(self, flow_id: str, iid: str) -> dict[str, Any]:
        return {"_id": iid, "_current_step": "Whatever", **self.fields}

    async def submit(self, flow_id: str, iid: str, aiid: str) -> dict[str, Any]:
        self.submit_calls.append(aiid)
        return {"ok": True}

    async def reject(
        self, flow_id: str, iid: str, aiid: str, comment: str
    ) -> dict[str, Any]:
        raise NotImplementedError("not exercised by this test")


@pytest.mark.asyncio
async def test_walk_never_reuses_create_aiid_past_the_first_hop() -> None:
    fake = _NeverRolloverFakeItem()
    steps = [
        _plan("Step One", values={"sample_field_a": "a1"}),
        _plan("Step Two", values={"sample_field_b": "b2"}),
    ]
    rep = await walk(fake, flow_id=FLOW, steps=steps)
    assert rep.advanced == ("Step One",)
    assert rep.failed == ("Step Two",)
    assert rep.ok() is False
    assert fake.submit_calls == ["CREATE-AIID"]


# ----------------------------------------------------------------- wait_new_aiid


class _StepTransitionFake(ItemService):
    def __init__(
        self,
        *,
        stale_calls: int,
        old_aiid: str,
        new_aiid: str,
        fail_first: bool = False,
    ) -> None:
        self.stale_calls = stale_calls
        self.old_aiid = old_aiid
        self.new_aiid = new_aiid
        self.fail_first = fail_first
        self.get_detail_calls = 0

    async def create_item(self, flow_id: str) -> dict[str, Any]:
        raise NotImplementedError("not exercised by this test")

    async def put_fields(
        self, flow_id: str, iid: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        raise NotImplementedError("not exercised by this test")

    async def get_detail(self, flow_id: str, iid: str) -> dict[str, Any]:
        self.get_detail_calls += 1
        if self.fail_first and self.get_detail_calls == 1:
            raise ExternalServiceError("transient get_detail failure")
        aiid = (
            self.old_aiid
            if self.get_detail_calls <= self.stale_calls
            else self.new_aiid
        )
        return {
            "_id": iid,
            "_current_step": "Whatever",
            "_current_context": [{"_context_activity_instance_id": aiid}],
        }

    async def submit(self, flow_id: str, iid: str, aiid: str) -> dict[str, Any]:
        raise NotImplementedError("not exercised by this test")

    async def reject(
        self, flow_id: str, iid: str, aiid: str, comment: str
    ) -> dict[str, Any]:
        raise NotImplementedError("not exercised by this test")


@pytest.mark.asyncio
async def test_wait_new_aiid_returns_as_soon_as_the_aiid_changes() -> None:
    fake = _StepTransitionFake(stale_calls=3, old_aiid="AIID-OLD", new_aiid="AIID-NEW")
    sleeps: list[float] = []

    async def _sleep(s: float) -> None:
        sleeps.append(s)

    got = await wait_new_aiid(
        fake,
        flow_id=FLOW,
        iid="ITEM-1",
        prev_aiid="AIID-OLD",
        tries=8,
        delay=0.5,
        sleep_fn=_sleep,
    )
    assert got == "AIID-NEW"
    assert fake.get_detail_calls == 4
    assert sleeps == [0.5, 0.5, 0.5]


@pytest.mark.asyncio
async def test_wait_new_aiid_first_read_succeeding_needs_no_sleep_at_all() -> None:
    fake = _StepTransitionFake(stale_calls=0, old_aiid="AIID-OLD", new_aiid="AIID-NEW")
    sleeps: list[float] = []

    async def _sleep(s: float) -> None:
        sleeps.append(s)

    got = await wait_new_aiid(
        fake,
        flow_id=FLOW,
        iid="ITEM-1",
        prev_aiid="AIID-OLD",
        tries=8,
        delay=1.0,
        sleep_fn=_sleep,
    )
    assert got == "AIID-NEW"
    assert fake.get_detail_calls == 1
    assert sleeps == []


@pytest.mark.asyncio
async def test_wait_new_aiid_gives_up_after_tries_exhausted() -> None:
    fake = _StepTransitionFake(
        stale_calls=999, old_aiid="AIID-OLD", new_aiid="AIID-NEW"
    )

    async def _sleep(s: float) -> None:
        pass

    with pytest.raises(ValueError, match="AIID-OLD"):
        await wait_new_aiid(
            fake,
            flow_id=FLOW,
            iid="ITEM-1",
            prev_aiid="AIID-OLD",
            tries=3,
            delay=0.1,
            sleep_fn=_sleep,
        )
    assert fake.get_detail_calls == 3


@pytest.mark.asyncio
async def test_wait_new_aiid_retries_through_a_transient_get_detail_error() -> None:
    fake = _StepTransitionFake(
        stale_calls=0, old_aiid="AIID-OLD", new_aiid="AIID-NEW", fail_first=True
    )

    async def _sleep(s: float) -> None:
        pass

    got = await wait_new_aiid(
        fake,
        flow_id=FLOW,
        iid="ITEM-1",
        prev_aiid="AIID-OLD",
        tries=8,
        delay=0,
        sleep_fn=_sleep,
    )
    assert got == "AIID-NEW"
    assert fake.get_detail_calls == 2


class _TerminalStatusFake(ItemService):
    def __init__(
        self, *, stale_calls: int, terminal_status: str, old_aiid: str
    ) -> None:
        self.stale_calls = stale_calls
        self.terminal_status = terminal_status
        self.old_aiid = old_aiid
        self.get_detail_calls = 0

    async def create_item(self, flow_id: str) -> dict[str, Any]:
        raise NotImplementedError("not exercised by this test")

    async def put_fields(
        self, flow_id: str, iid: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        raise NotImplementedError("not exercised by this test")

    async def get_detail(self, flow_id: str, iid: str) -> dict[str, Any]:
        self.get_detail_calls += 1
        if self.get_detail_calls <= self.stale_calls:
            return {
                "_id": iid,
                "_status": "InProgress",
                "_current_step": "Whatever",
                "_current_context": [{"_context_activity_instance_id": self.old_aiid}],
            }
        return {"_id": iid, "_status": self.terminal_status, "_current_step": None}

    async def submit(self, flow_id: str, iid: str, aiid: str) -> dict[str, Any]:
        raise NotImplementedError("not exercised by this test")

    async def reject(
        self, flow_id: str, iid: str, aiid: str, comment: str
    ) -> dict[str, Any]:
        raise NotImplementedError("not exercised by this test")


@pytest.mark.asyncio
async def test_wait_new_aiid_returns_immediately_on_a_terminal_status() -> None:
    fake = _TerminalStatusFake(
        stale_calls=0, terminal_status="Completed", old_aiid="AIID-OLD"
    )

    async def _sleep(s: float) -> None:
        pass

    got = await wait_new_aiid(
        fake,
        flow_id=FLOW,
        iid="ITEM-1",
        prev_aiid="AIID-OLD",
        tries=8,
        delay=0,
        sleep_fn=_sleep,
    )
    assert got == "Completed"
    assert fake.get_detail_calls == 1


@pytest.mark.asyncio
async def test_wait_new_aiid_treats_rejected_as_terminal_too() -> None:
    fake = _TerminalStatusFake(
        stale_calls=0, terminal_status="Rejected", old_aiid="AIID-OLD"
    )

    async def _sleep(s: float) -> None:
        pass

    got = await wait_new_aiid(
        fake,
        flow_id=FLOW,
        iid="ITEM-1",
        prev_aiid="AIID-OLD",
        tries=8,
        delay=0,
        sleep_fn=_sleep,
    )
    assert got == "Rejected"


# ------------------------------------------------------ field-name resolution


_DRAFT_WITH_TABLE: dict[str, Any] = {
    "Model_root": {
        "Id": "Model_root",
        "Kind": "Model",
        "RootProcessDef": "ProcessDef_1",
    },
    "Field_bu": {
        "Id": "Field_bu",
        "Kind": "Field",
        "Name": "Business Unit ID",
        "Type": "Text",
        "Model": "Model_root",
    },
    "Field_sev": {
        "Id": "Field_sev",
        "Kind": "Field",
        "Name": "Severity",
        "Type": "Select",
        "Model": "Model_root",
    },
    "Model_table": {"Id": "Model_table", "Kind": "Model", "Column": "Column_host"},
    "Field_tbl_sev": {
        "Id": "Field_tbl_sev",
        "Kind": "Field",
        "Name": "Severity",
        "Type": "Text",
        "Model": "Model_table",
    },
}


def test_field_name_index_maps_root_fields_and_excludes_table_fields() -> None:
    idx = field_name_index(_DRAFT_WITH_TABLE)
    assert idx == {"Business Unit ID": "Field_bu", "Severity": "Field_sev"}


@pytest.mark.asyncio
async def test_walk_resolves_field_names_so_fill_put_receives_ids() -> None:
    fake = _FakeItem()
    idx = field_name_index(_DRAFT_WITH_TABLE)
    steps = [_plan("step-1", values={"Business Unit ID": "BU-42"})]
    rep = await walk(fake, flow_id=FLOW, steps=steps, field_index=idx)
    assert rep.ok() is True
    puts = [args[2] for name, args in fake.calls if name == "put_fields"]
    assert puts == [{"Field_bu": "BU-42"}]


@pytest.mark.asyncio
async def test_walk_unknown_field_name_fails_loud_listing_available_names() -> None:
    fake = _FakeItem()
    idx = field_name_index(_DRAFT_WITH_TABLE)
    steps = [_plan("step-1", values={"Buisness Unit": "BU-42"})]
    rep = await walk(fake, flow_id=FLOW, steps=steps, field_index=idx)
    assert rep.ok() is False
    assert rep.failed == ("step-1",)
    assert rep.error is not None
    assert "Buisness Unit" in rep.error
    assert "Business Unit ID" in rep.error and "Severity" in rep.error
    assert not any(name == "put_fields" for name, _ in fake.calls)


def test_resolve_value_keys_leaves_select_value_literal_untouched() -> None:
    idx = field_name_index(_DRAFT_WITH_TABLE)
    resolved = resolve_value_keys({"Severity": "High"}, idx)
    assert resolved == {"Field_sev": "High"}


# ------------------------------------------------------------- poll_after_transition


@pytest.mark.asyncio
async def test_walk_poll_disabled_by_default_makes_no_extra_calls() -> None:
    fake = _FakeItem()
    steps = [
        _plan("step-1", values={"sample_field_a": "a1"}),
        _plan("step-2", values={"sample_field_b": "b2"}),
    ]
    rep = await walk(fake, flow_id=FLOW, steps=steps)
    assert rep.ok() is True
    get_detail_calls = sum(1 for name, _ in fake.calls if name == "get_detail")
    assert get_detail_calls == 4  # 1 fill-verify read + 1 advance aiid-fetch, per step


@pytest.mark.asyncio
async def test_walk_poll_failure_is_reported_as_the_failed_step() -> None:
    fake = _FakeItem()  # constant aiid -- the poll can never see a change

    async def _sleep(s: float) -> None:
        pass

    steps = [
        _plan("step-1", values={"sample_field_a": "a1"}),
        _plan("step-2", values={"sample_field_b": "b2"}),
    ]
    rep = await walk(
        fake,
        flow_id=FLOW,
        steps=steps,
        poll_after_transition=True,
        poll_tries=2,
        poll_delay=0,
        poll_sleep_fn=_sleep,
    )
    assert rep.ok() is False
    assert rep.advanced == ("step-1",)
    assert rep.failed == ("step-1",)
    assert rep.error is not None and "poll failed" in rep.error
    assert not any(
        "sample_field_b" in args[2] for name, args in fake.calls if name == "put_fields"
    )


# ------------------------------------------------------------- _detail_and_live_aiid


@pytest.mark.asyncio
async def test_detail_and_live_aiid_returns_the_pair() -> None:
    fake = _FakeItem()
    await fake.create_item(FLOW)
    detail, aiid = await _detail_and_live_aiid(fake, flow_id=FLOW, iid="ITEM-1")
    assert detail["_id"] == "ITEM-1"
    assert aiid == LIVE_AIID
