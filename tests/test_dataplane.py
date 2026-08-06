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
    wait_new_aiid,
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


# --------------------------------------------------------------------------- wait_new_aiid
# Node G addition: walk() has no step-transition wait at all, submitting and immediately moving on
# to the next fill. This is the bounded poll a caller can run BETWEEN walk steps to close that gap
# (CLAUDE.md-adjacent trap: a fresh submit does not always show a rolled-over _current_context on
# the very first read-back). `_StepTransitionFake` only implements get_detail — the one call
# wait_new_aiid actually makes — returning a STALE aiid for the first `stale_calls` reads, then a
# NEW one, so the retry loop's own behavior is what gets proven, not live network timing.

class _StepTransitionFake:
    def __init__(self, *, stale_calls: int, old_aiid: str, new_aiid: str,
                 fail_first: bool = False) -> None:
        self.stale_calls = stale_calls
        self.old_aiid = old_aiid
        self.new_aiid = new_aiid
        self.fail_first = fail_first
        self.get_detail_calls = 0

    def get_detail(self, flow_id: str, iid: str) -> dict[str, Any] | Err:
        self.get_detail_calls += 1
        if self.fail_first and self.get_detail_calls == 1:
            return Err("http", "transient get_detail failure")
        aiid = self.old_aiid if self.get_detail_calls <= self.stale_calls else self.new_aiid
        return {"_id": iid, "_current_step": "Whatever",
                "_current_context": [{"_context_activity_instance_id": aiid}]}


def test_wait_new_aiid_returns_as_soon_as_the_aiid_changes() -> None:
    fake = _StepTransitionFake(stale_calls=3, old_aiid="AIID-OLD", new_aiid="AIID-NEW")
    sleeps: list[float] = []
    got = wait_new_aiid(fake, flow_id=FLOW, iid="ITEM-1", prev_aiid="AIID-OLD",
                        tries=8, delay=0.5, sleep_fn=sleeps.append)
    assert got == "AIID-NEW"
    assert fake.get_detail_calls == 4, "3 stale reads + 1 that finally showed the new aiid"
    assert sleeps == [0.5, 0.5, 0.5], "slept BETWEEN attempts, never before the first"


def test_wait_new_aiid_first_read_succeeding_needs_no_sleep_at_all() -> None:
    fake = _StepTransitionFake(stale_calls=0, old_aiid="AIID-OLD", new_aiid="AIID-NEW")
    sleeps: list[float] = []
    got = wait_new_aiid(fake, flow_id=FLOW, iid="ITEM-1", prev_aiid="AIID-OLD",
                        tries=8, delay=1.0, sleep_fn=sleeps.append)
    assert got == "AIID-NEW"
    assert fake.get_detail_calls == 1
    assert sleeps == [], "no need to ever sleep if the very first read already shows the new aiid"


def test_wait_new_aiid_gives_up_after_tries_exhausted() -> None:
    fake = _StepTransitionFake(stale_calls=999, old_aiid="AIID-OLD", new_aiid="AIID-NEW")
    sleeps: list[float] = []
    got = wait_new_aiid(fake, flow_id=FLOW, iid="ITEM-1", prev_aiid="AIID-OLD",
                        tries=3, delay=0.1, sleep_fn=sleeps.append)
    assert isinstance(got, Err) and got.kind == "verify"
    assert "AIID-OLD" in got.message
    assert fake.get_detail_calls == 3, "never more reads than the tries budget allows"
    assert sleeps == [0.1, 0.1], "tries-1 sleeps: after attempt 1 and 2, none after the last"


def test_wait_new_aiid_never_returns_prev_aiid_as_if_it_were_success() -> None:
    fake = _StepTransitionFake(stale_calls=999, old_aiid="AIID-OLD", new_aiid="AIID-NEW")
    got = wait_new_aiid(fake, flow_id=FLOW, iid="ITEM-1", prev_aiid="AIID-OLD",
                        tries=2, delay=0, sleep_fn=lambda s: None)
    assert got != "AIID-OLD"
    assert isinstance(got, Err)


def test_wait_new_aiid_retries_through_a_transient_get_detail_error() -> None:
    """A transport Err from get_detail is treated as "not ready yet", not a hard failure —
    exactly the class of transient state a bounded poll exists to absorb."""
    fake = _StepTransitionFake(stale_calls=0, old_aiid="AIID-OLD", new_aiid="AIID-NEW",
                               fail_first=True)
    got = wait_new_aiid(fake, flow_id=FLOW, iid="ITEM-1", prev_aiid="AIID-OLD",
                        tries=8, delay=0, sleep_fn=lambda s: None)
    assert got == "AIID-NEW"
    assert fake.get_detail_calls == 2


# --------------------------------------------------------------------- walk(poll_after_transition)
# Node G addition: extending walk() itself with an OPTIONAL poll hook, rather than the Robot/
# caller layer polling between steps — forge_simulate_case wraps the ENTIRE walk in one atomic MCP
# call, so there is no seam outside walk() to inject a poll between its internal steps.

class _DelayedTransitionFakeClient(FakeClient):
    """Same as FakeClient, but get_detail's aiid goes stale for `stale_reads_per_submit` calls
    after EVERY submit, before rolling over to a fresh one — regardless of which code path is
    asking (fill_and_verify's own read-back, advance's aiid fetch, or the poll itself), modeling
    "the transition takes about K reads' worth of latency to become visible" realistically enough
    to prove the poll hook actually gates the NEXT step's advance on a truly fresh aiid.
    """

    def __init__(self, *, stale_reads_per_submit: int) -> None:
        super().__init__()
        self.stale_reads_per_submit = stale_reads_per_submit
        self._pending_stale = 0
        self._generation = 0

    def submit(self, flow_id: str, iid: str, aiid: str) -> dict[str, Any] | Err:
        self.calls.append(("submit", (flow_id, iid, aiid)))
        self.items[iid]["_current_step"] = "Next"
        self._generation += 1
        self._pending_stale = self.stale_reads_per_submit
        return {"ok": True, "aiid_used": aiid}

    def get_detail(self, flow_id: str, iid: str) -> dict[str, Any] | Err:
        self.calls.append(("get_detail", (flow_id, iid)))
        item = dict(self.items[iid])
        if self._pending_stale > 0:
            self._pending_stale -= 1
            aiid = LIVE_AIID if self._generation <= 1 else f"AIID-GEN-{self._generation - 1}"
        else:
            aiid = f"AIID-GEN-{self._generation}" if self._generation else LIVE_AIID
        item["_current_context"] = [{"_context_activity_instance_id": aiid}]
        return item


def test_walk_poll_retries_until_the_aiid_changes_then_succeeds() -> None:
    fake = _DelayedTransitionFakeClient(stale_reads_per_submit=2)
    sleeps: list[float] = []
    steps = [_plan("step-1", values={"sample_field_a": "a1"})]
    rep = walk(fake, flow_id=FLOW, steps=steps, poll_after_transition=True, poll_tries=8,
              poll_delay=0.5, poll_sleep_fn=sleeps.append)
    assert rep.ok() is True
    assert rep.advanced == ("step-1",)
    assert sleeps == [0.5, 0.5], "exactly the 2 sleeps the one delayed transition needed"


def test_walk_poll_lets_the_next_step_submit_with_the_fresh_aiid_not_a_stale_one() -> None:
    """THE integration property this whole hook exists for: without polling, step-2's own advance()
    would re-derive whatever aiid get_detail happens to show at that moment — which, against a
    slow-to-transition server, could still be step-1's. With polling, step-1's loop iteration does
    not move on until the NEW aiid is confirmed, so step-2 submits with it."""
    fake = _DelayedTransitionFakeClient(stale_reads_per_submit=2)
    steps = [_plan("step-1", values={"sample_field_a": "a1"}),
            _plan("step-2", values={"sample_field_b": "b2"})]
    rep = walk(fake, flow_id=FLOW, steps=steps, poll_after_transition=True, poll_tries=8,
              poll_delay=0, poll_sleep_fn=lambda s: None)
    assert rep.ok() is True
    submit_calls = [args for name, args in fake.calls if name == "submit"]
    assert submit_calls[0] == (FLOW, "ITEM-1", LIVE_AIID)
    assert submit_calls[1] == (FLOW, "ITEM-1", "AIID-GEN-1")


def test_walk_poll_disabled_by_default_makes_no_extra_calls() -> None:
    """poll_after_transition defaults False -- every EXISTING caller/test (a fake with no such
    latency) must see IDENTICAL behavior to before this hook existed."""
    fake = FakeClient()
    steps = [_plan("step-1", values={"sample_field_a": "a1"}),
            _plan("step-2", values={"sample_field_b": "b2"})]
    rep = walk(fake, flow_id=FLOW, steps=steps)
    assert rep.ok() is True
    get_detail_calls = sum(1 for name, _ in fake.calls if name == "get_detail")
    assert get_detail_calls == 4, "1 fill-verify read + 1 advance aiid-fetch, per step, x 2 steps"


def test_walk_poll_failure_is_reported_as_the_failed_step_not_a_false_success() -> None:
    fake = FakeClient()  # constant aiid -- the poll can never see a change
    steps = [_plan("step-1", values={"sample_field_a": "a1"}),
            _plan("step-2", values={"sample_field_b": "b2"})]
    rep = walk(fake, flow_id=FLOW, steps=steps, poll_after_transition=True, poll_tries=2,
              poll_delay=0, poll_sleep_fn=lambda s: None)
    assert rep.ok() is False
    assert rep.advanced == ("step-1",), "step-1 itself DID advance -- only the post-transition poll failed"
    assert rep.failed == ("step-1",)
    assert rep.error is not None and "poll failed" in rep.error
    assert not any("sample_field_b" in args[2] for name, args in fake.calls if name == "put_fields"), \
        "step-2 must never be attempted once the poll fails"


def test_wait_new_aiid_missing_current_context_is_treated_as_not_ready_yet() -> None:
    """live_aiid's own trap-guard (no _current_context yet) must not be a hard failure here — it
    is exactly the "not rolled over yet" state this poll exists to wait out."""
    class _SlowRollover:
        def __init__(self) -> None:
            self.calls = 0

        def get_detail(self, flow_id: str, iid: str) -> dict[str, Any]:
            self.calls += 1
            if self.calls < 3:
                return {"_id": iid, "_current_step": "Whatever"}  # no _current_context yet
            return {"_id": iid, "_current_step": "Whatever",
                    "_current_context": [{"_context_activity_instance_id": "AIID-NEW"}]}

    fake = _SlowRollover()
    got = wait_new_aiid(fake, flow_id=FLOW, iid="ITEM-1", prev_aiid="AIID-OLD",
                        tries=8, delay=0, sleep_fn=lambda s: None)
    assert got == "AIID-NEW"
    assert fake.calls == 3
