"""Unit tests for the item data plane. NO network: two levels of fake stand in for it.

FakeClient implements DataPlaneClient directly (in-memory, records every call) and exercises the
pure orchestration logic: live_aiid, fill_and_verify, advance, walk. A second, lower-level fake
(_RouteAwareTransport, a KfClient with `_req` stubbed) exercises LiveDataPlane itself, proving the
real implementation builds the documented URLs — in particular the admin-vs-non-admin detail route
(CLAUDE.md: Item data plane — "detail GET .../admin/{flow}/{iid} (non-admin .../{flow}/{iid} 404s)").

Blindness: neutral flow id "Flow_Sample01", field ids "sample_field_a" etc. — no real app identity.
"""
from __future__ import annotations

from typing import Any

from kfforge.client import Err, KfClient, KfConfig
from kfforge.dataplane import (
    FillReport,
    LiveDataPlane,
    StepPlan,
    StepResult,
    WalkReport,
    advance,
    fill_and_verify,
    live_aiid,
    walk,
)

FLOW = "Flow_Sample01"

# The myitems consumed-instance decoy — advance()/walk() must NEVER submit or reject with this.
DECOY_AIID = "DECOY-CONSUMED-AIID"
LIVE_AIID = "LIVE-AIID-1"


def _detail(iid: str, step: str = "Start", *, with_context: bool = True) -> dict[str, Any]:
    d: dict[str, Any] = {"_id": iid, "_current_step": step, "_status": "Draft",
                          "_activity_instance_id": DECOY_AIID}  # myitems-style decoy field
    if with_context:
        d["_current_context"] = [{"_context_activity_instance_id": LIVE_AIID}]
    return d


class FakeClient:
    """In-memory DataPlaneClient. No KfClient, no network — just a dict of items plus a call log.

    `discard_keys` / `mismatch_keys` let a test simulate the Select silent-discard trap (PUT 200s,
    the value never lands) and a value echoed back different, without needing a subclass per case.
    `put_fails` / `create_fails` simulate a transport-level Err from those two calls.
    """

    def __init__(self) -> None:
        self.items: dict[str, dict[str, Any]] = {}
        self._next_id = 1
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.discard_keys: set[str] = set()
        self.mismatch_keys: set[str] = set()
        self.put_fails = False
        self.create_fails = False

    def create_item(self, flow_id: str) -> dict[str, Any] | Err:
        self.calls.append(("create_item", (flow_id,)))
        if self.create_fails:
            return Err("http", "create failed")
        iid = f"ITEM-{self._next_id}"
        self._next_id += 1
        self.items[iid] = _detail(iid)
        return {"_id": iid}

    def put_fields(self, flow_id: str, iid: str, payload: dict[str, Any]) -> dict[str, Any] | Err:
        self.calls.append(("put_fields", (flow_id, iid, dict(payload))))
        if self.put_fails:
            return Err("http", "put failed")
        item = self.items[iid]
        for k, v in payload.items():
            if k in self.discard_keys:
                continue  # PUT 200s, value silently never lands (the Select trap)
            item[k] = f"ECHO-{v!r}" if k in self.mismatch_keys else v
        return {"ok": True}

    def get_detail(self, flow_id: str, iid: str) -> dict[str, Any] | Err:
        self.calls.append(("get_detail", (flow_id, iid)))
        return dict(self.items[iid])

    def submit(self, flow_id: str, iid: str, aiid: str) -> dict[str, Any] | Err:
        self.calls.append(("submit", (flow_id, iid, aiid)))
        self.items[iid]["_current_step"] = "Next"
        return {"ok": True, "aiid_used": aiid}

    def reject(self, flow_id: str, iid: str, aiid: str, comment: str) -> dict[str, Any] | Err:
        self.calls.append(("reject", (flow_id, iid, aiid, comment)))
        self.items[iid]["_status"] = "Rejected"
        return {"ok": True, "aiid_used": aiid, "comment": comment}


# --------------------------------------------------------------------------------- live_aiid
def test_live_aiid_happy_path() -> None:
    got = live_aiid(_detail("ITEM-1"))
    assert got == LIVE_AIID


def test_live_aiid_missing_current_context_is_err_mentions_the_trap() -> None:
    d = _detail("ITEM-1", with_context=False)
    assert "_current_context" not in d
    got = live_aiid(d)
    assert isinstance(got, Err) and got.kind == "verify"
    assert "consumed" in got.message.lower() or "myitems" in got.message.lower()


def test_live_aiid_empty_current_context_list_is_err() -> None:
    d = _detail("ITEM-1")
    d["_current_context"] = []
    got = live_aiid(d)
    assert isinstance(got, Err) and got.kind == "verify"


def test_live_aiid_never_returns_the_myitems_decoy() -> None:
    got = live_aiid(_detail("ITEM-1"))
    assert got != DECOY_AIID


# ---------------------------------------------------------------------------- fill_and_verify
def test_fill_and_verify_all_landed() -> None:
    fake = FakeClient()
    fake.create_item(FLOW)
    rep = fill_and_verify(fake, flow_id=FLOW, iid="ITEM-1",
                          values={"sample_field_a": "x", "sample_field_b": 3})
    assert isinstance(rep, FillReport)
    assert set(rep.landed) == {"sample_field_a", "sample_field_b"}
    assert rep.discarded == () and rep.mismatched == ()
    assert rep.ok() is True


def test_fill_and_verify_silently_discarded_select_like_value() -> None:
    """PUT 200s, but the value never lands on read-back — the reason this function exists."""
    fake = FakeClient()
    fake.create_item(FLOW)
    fake.discard_keys = {"sample_select_field"}
    rep = fill_and_verify(fake, flow_id=FLOW, iid="ITEM-1",
                          values={"sample_field_a": "x", "sample_select_field": "Not An Option"})
    assert isinstance(rep, FillReport)
    assert rep.landed == ("sample_field_a",)
    assert rep.discarded == ("sample_select_field",)
    assert rep.mismatched == ()
    assert rep.ok() is False


def test_fill_and_verify_mismatched_value() -> None:
    fake = FakeClient()
    fake.create_item(FLOW)
    fake.mismatch_keys = {"sample_field_c"}
    rep = fill_and_verify(fake, flow_id=FLOW, iid="ITEM-1", values={"sample_field_c": "sent"})
    assert isinstance(rep, FillReport)
    assert rep.mismatched == ("sample_field_c",)
    assert rep.landed == () and rep.discarded == ()
    assert rep.ok() is False


def test_fill_and_verify_propagates_put_err_without_reading_detail() -> None:
    fake = FakeClient()
    fake.create_item(FLOW)
    fake.put_fails = True
    got = fill_and_verify(fake, flow_id=FLOW, iid="ITEM-1", values={"sample_field_a": "x"})
    assert isinstance(got, Err)
    assert not any(name == "get_detail" for name, _ in fake.calls), \
        "a failed PUT must never be followed by a read-back GET"


# ------------------------------------------------------------------------------------ advance
def test_advance_uses_the_live_aiid_never_the_myitems_decoy() -> None:
    fake = FakeClient()
    fake.create_item(FLOW)
    got = advance(fake, flow_id=FLOW, iid="ITEM-1")
    assert isinstance(got, StepResult)
    assert got.aiid == LIVE_AIID
    submit_calls = [args for name, args in fake.calls if name == "submit"]
    assert submit_calls == [(FLOW, "ITEM-1", LIVE_AIID)]


def test_advance_propagates_missing_context_as_err() -> None:
    fake = FakeClient()
    fake.create_item(FLOW)
    fake.items["ITEM-1"].pop("_current_context")
    got = advance(fake, flow_id=FLOW, iid="ITEM-1")
    assert isinstance(got, Err)
    assert not any(name == "submit" for name, _ in fake.calls), \
        "must never submit without a live aiid"


# --------------------------------------------------------------------------------------- walk
def _plan(name: str, **kw: Any) -> StepPlan:
    return StepPlan(name=name, **kw)


def test_walk_happy_path_counts_reconcile() -> None:
    fake = FakeClient()
    steps = [
        _plan("step-1", values={"sample_field_a": "a1"}),
        _plan("step-2", values={"sample_field_b": "b2"}),
        _plan("step-3", values={"sample_field_c": "c3"}),
    ]
    rep = walk(fake, flow_id=FLOW, steps=steps)
    assert isinstance(rep, WalkReport)
    assert rep.created == 1  # bool is an int in Python — created succeeded exactly once
    assert rep.filled == ("step-1", "step-2", "step-3")
    assert rep.advanced == ("step-1", "step-2", "step-3")
    assert rep.rejected == ()
    assert rep.failed == ()
    assert rep.ok() is True
    # every submit used the live aiid, never the decoy
    assert all(args[2] == LIVE_AIID for name, args in fake.calls if name == "submit")


def test_walk_stops_at_first_failure_and_never_attempts_later_steps() -> None:
    fake = FakeClient()
    fake.discard_keys = {"sample_field_b"}  # step-2's fill will silently fail
    steps = [
        _plan("step-1", values={"sample_field_a": "a1"}),
        _plan("step-2", values={"sample_field_b": "b2"}),
        _plan("step-3", values={"sample_field_c": "c3"}),
    ]
    rep = walk(fake, flow_id=FLOW, steps=steps)
    assert rep.created == 1
    assert rep.filled == ("step-1",)
    assert rep.advanced == ("step-1",)
    assert rep.failed == ("step-2",)
    assert rep.error is not None and "step-2" in rep.error
    assert rep.ok() is False
    # step-3 was never even attempted, and only step-1 ever reached submit
    assert not any(
        name == "put_fields" and "sample_field_c" in args[2] for name, args in fake.calls
    )
    assert sum(1 for name, _ in fake.calls if name == "submit") == 1


def test_walk_reject_path_sets_status_and_is_counted() -> None:
    fake = FakeClient()
    steps = [
        _plan("step-1", values={"sample_field_a": "a1"}),
        _plan("step-2", values={"sample_field_b": "b2"}, reject=True, comment="not good enough"),
    ]
    rep = walk(fake, flow_id=FLOW, steps=steps)
    assert rep.advanced == ("step-1",)
    assert rep.rejected == ("step-2",)
    assert rep.failed == ()
    assert rep.ok() is True
    assert rep.iid is not None
    assert fake.items[rep.iid]["_status"] == "Rejected"
    reject_calls = [args for name, args in fake.calls if name == "reject"]
    assert reject_calls == [(FLOW, rep.iid, LIVE_AIID, "not good enough")]


def test_walk_create_failure_short_circuits_before_any_step() -> None:
    fake = FakeClient()
    fake.create_fails = True
    rep = walk(fake, flow_id=FLOW, steps=[_plan("step-1", values={"sample_field_a": "a1"})])
    assert rep.created == 0
    assert rep.iid is None
    assert rep.filled == () and rep.advanced == () and rep.rejected == () and rep.failed == ()
    assert rep.error is not None
    assert rep.ok() is False
    assert fake.calls == [("create_item", (FLOW,))]


def test_walk_empty_step_list_still_creates() -> None:
    fake = FakeClient()
    rep = walk(fake, flow_id=FLOW, steps=[])
    assert rep.created == 1 and rep.iid is not None
    assert rep.filled == () and rep.advanced == () and rep.failed == ()
    assert rep.ok() is True


# ------------------------------------------------------------------- LiveDataPlane (real impl)
class _RouteAwareTransport(KfClient):
    """A KfClient with the raw HTTP verb stubbed, so LiveDataPlane's real URL construction can be
    checked without touching a socket. Any URL lacking '/admin/' 404s, mirroring the live API
    (CLAUDE.md: 'detail GET .../admin/{flow}/{iid} (non-admin .../{flow}/{iid} 404s)') — proving
    LiveDataPlane.get_detail actually hits the admin path, not just that it 200s somewhere.
    """

    def __init__(self) -> None:
        super().__init__(KfConfig(key_id="k", key_secret="s", account="Acc",
                                  domain="dev-x.example.com", app_id="App"))
        self.requested_urls: list[str] = []

    def _req(self, method: str, url: str, data: Any | None = None) -> tuple[int, str]:  # type: ignore[override]
        self.requested_urls.append(url)
        if "/admin/" not in url:
            return 404, '{"error": "not found"}'
        return 200, '{"_id": "ITEM-1", "_current_step": "Start"}'


def test_live_data_plane_get_detail_uses_the_admin_route() -> None:
    transport = _RouteAwareTransport()
    live = LiveDataPlane(transport)
    got = live.get_detail(FLOW, "ITEM-1")
    assert isinstance(got, dict) and got["_id"] == "ITEM-1"
    assert all("/admin/" in u for u in transport.requested_urls)


def test_live_data_plane_builds_every_documented_route() -> None:
    """Every LiveDataPlane call matches CLAUDE.md's Item data plane table byte-for-byte."""
    transport = _RouteAwareTransport()
    live = LiveDataPlane(transport)

    live.create_item(FLOW)
    live.put_fields(FLOW, "ITEM-1", {"sample_field_a": "x"})
    live.get_detail(FLOW, "ITEM-1")
    live.submit(FLOW, "ITEM-1", "AIID-1")
    live.reject(FLOW, "ITEM-1", "AIID-1", "no good")

    base = "https://dev-x.example.com/process/2/Acc"
    assert transport.requested_urls == [
        f"{base}/{FLOW}",
        f"{base}/admin/{FLOW}/ITEM-1",
        f"{base}/admin/{FLOW}/ITEM-1",
        f"{base}/{FLOW}/ITEM-1/AIID-1/submit",
        f"{base}/{FLOW}/ITEM-1/AIID-1/reject",
    ]
