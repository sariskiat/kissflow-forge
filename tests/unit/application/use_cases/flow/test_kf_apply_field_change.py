"""Spec for app.application.use_cases.flow.kf_apply_field_change.

Ports the matching cases of `tests/test_client.py`'s `apply_fields` suite (the
function behind `kf_apply_field_change`) onto the new fake-port architecture. A
`FakeFlowRepository` is stateless (it returns queued values, it does not replay an
evolving draft), so where the old suite ran `apply_fields` twice against one mutating
`FakeClient` to reach an "already exists" scenario, these tests instead build the
"already exists" draft directly and drive the use case once -- the same scenario, a
different way to reach it.

Rule 7 (`brief_stage_d_common.md`): a case that used to assert a non-empty `missing`
or `changed_ignored` bucket on a returned response now asserts the call raises
`ApplicationError(code=VERIFY_FAILED)` instead -- a write that did not fully land is
a failure, never a success response with the failure sitting quietly inside a bucket.
"""

from __future__ import annotations

from typing import Any

import pytest
from tests.fakes.flow import FakeFlowRepository
from tests.unit.application.use_cases.test_write_order_contract import (
    assert_write_order,
)

from app.application.exceptions import ApplicationError
from app.application.models.requests.flow.kf_apply_field_change_request import (
    KfApplyFieldChangeRequest,
)
from app.application.use_cases.flow.kf_apply_field_change import KfApplyFieldChange
from app.domain.entities.flow_draft import FlowDraft
from app.domain.value_objects.field_spec import FieldSpec
from app.domain.value_objects.field_type import FieldType


def _bare_form_draft(version: str = "v1") -> dict[str, Any]:
    return {
        "Root": "M1",
        "_meta_version": version,
        "M1": {"Id": "M1", "Kind": "Model", "Name": "M", "FlowType": "Form"},
    }


def _request(**overrides: object) -> KfApplyFieldChangeRequest:
    base: dict[str, object] = {
        "flow_kind": "form",
        "flow_id": "F1",
        "changes": [{"name": "alpha", "type": "Textarea"}],
        "publish": False,
        "app_id": "A1",
    }
    base.update(overrides)
    return KfApplyFieldChangeRequest.model_validate(base)


@pytest.mark.asyncio
async def test_adds_and_verifies() -> None:
    before = FlowDraft.from_wire(_bare_form_draft())
    after = before.apply_changes([FieldSpec(name="alpha", type=FieldType.TEXTAREA)])
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, after]

    resp = await KfApplyFieldChange(fake).execute(_request())

    assert resp.added == ["alpha"] and resp.verified == ["alpha"]
    assert resp.missing == [] and resp.skipped == []
    assert resp.changed_ignored == [] and resp.collateral == []
    assert resp.snapshot_version == "v1"
    assert_write_order(fake)


@pytest.mark.asyncio
async def test_publish_true_succeeds_for_a_publishable_kind() -> None:
    before = FlowDraft.from_wire(_bare_form_draft())
    after = before.apply_changes([FieldSpec(name="alpha", type=FieldType.TEXTAREA)])
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, after]

    resp = await KfApplyFieldChange(fake).execute(_request(publish=True))

    assert resp.published is True
    publish_calls = [c for c in fake.calls if c[0] == "publish"]
    assert publish_calls == [("publish", ("A1", "form", "F1"), {})]


@pytest.mark.asyncio
async def test_an_unbound_select_is_rejected_before_any_write() -> None:
    before = FlowDraft.from_wire(_bare_form_draft())
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before]

    with pytest.raises(ApplicationError) as exc_info:
        await KfApplyFieldChange(fake).execute(
            _request(changes=[{"name": "Region", "type": "Select"}])
        )

    assert exc_info.value.code == "VERIFY_FAILED"
    assert "offline apply rejected the change set" in exc_info.value.message
    put_calls = [c for c in fake.calls if c[0] == "put_draft"]
    assert put_calls == []


@pytest.mark.asyncio
async def test_is_idempotent_and_writes_nothing_when_the_name_already_exists() -> None:
    before = FlowDraft.from_wire(_bare_form_draft()).apply_changes(
        [FieldSpec(name="alpha", type=FieldType.TEXT)]
    )
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, before]

    resp = await KfApplyFieldChange(fake).execute(
        _request(changes=[{"name": "alpha", "type": "Text"}])
    )

    assert resp.added == []
    assert resp.skipped == ["alpha"]
    assert resp.verified == ["alpha"]
    put_calls = [c for c in fake.calls if c[0] == "put_draft"]
    assert put_calls == [], "re-applying an existing field must not issue a PUT"


@pytest.mark.asyncio
async def test_a_field_missing_on_read_back_is_a_failure_not_a_success() -> None:
    """Rule 7: never publish, and never RETURN, a draft that failed verification."""
    before = FlowDraft.from_wire(_bare_form_draft())
    fake = FakeFlowRepository()
    # The read-back is queued as the UNCHANGED before-draft: the PUT was "accepted"
    # but the field never actually landed.
    fake.results["get_draft"] = [before, before]

    with pytest.raises(ApplicationError) as exc_info:
        await KfApplyFieldChange(fake).execute(
            _request(
                changes=[{"name": "ghost", "type": "Text"}],
                publish=True,
            )
        )

    assert exc_info.value.code == "VERIFY_FAILED"
    assert "missing=['ghost']" in exc_info.value.message
    assert "published=False" in exc_info.value.message
    publish_calls = [c for c in fake.calls if c[0] == "publish"]
    assert publish_calls == []


@pytest.mark.asyncio
async def test_refuses_to_publish_a_born_live_kind_instead_of_404ing() -> None:
    before = FlowDraft.from_wire(_bare_form_draft())
    after = before.apply_changes([FieldSpec(name="alpha", type=FieldType.TEXT)])
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, after]

    with pytest.raises(ApplicationError) as exc_info:
        await KfApplyFieldChange(fake).execute(
            _request(flow_kind="dataset", publish=True)
        )

    assert exc_info.value.code == "VERIFY_FAILED"
    assert "no publish route" in exc_info.value.message
    publish_calls = [c for c in fake.calls if c[0] == "publish"]
    assert publish_calls == []


@pytest.mark.asyncio
async def test_publish_false_on_a_born_live_kind_still_succeeds() -> None:
    before = FlowDraft.from_wire(_bare_form_draft())
    after = before.apply_changes([FieldSpec(name="alpha", type=FieldType.TEXT)])
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, after]

    resp = await KfApplyFieldChange(fake).execute(_request(flow_kind="dataset"))

    assert resp.verified == ["alpha"] and resp.published is False


@pytest.mark.asyncio
async def test_an_ignored_type_change_is_a_failure_not_a_verified_field() -> None:
    """F2: `FlowDraft.apply_changes` only creates. Asking for a different type on an
    existing name is a silent no-op that used to be counted under `skipped` AND
    `verified` at once -- and, before rule 7, was still a returned "success" with the
    problem sitting in `changed_ignored`."""
    before = FlowDraft.from_wire(_bare_form_draft()).apply_changes(
        [FieldSpec(name="alpha", type=FieldType.TEXT)]
    )
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, before]

    with pytest.raises(ApplicationError) as exc_info:
        await KfApplyFieldChange(fake).execute(
            _request(changes=[{"name": "alpha", "type": "Number"}])
        )

    assert exc_info.value.code == "VERIFY_FAILED"
    assert "changed_ignored=" in exc_info.value.message
    assert "alpha" in exc_info.value.message
    assert "'Number'" in exc_info.value.message
    assert "'Text'" in exc_info.value.message
    put_calls = [c for c in fake.calls if c[0] == "put_draft"]
    assert put_calls == [], "nothing was written -- that is the problem being reported"


@pytest.mark.asyncio
async def test_ignored_required_change_names_the_tool_that_can_do_it() -> None:
    before = FlowDraft.from_wire(_bare_form_draft()).apply_changes(
        [FieldSpec(name="alpha", type=FieldType.TEXT, required=False)]
    )
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, before]

    with pytest.raises(ApplicationError) as exc_info:
        await KfApplyFieldChange(fake).execute(
            _request(changes=[{"name": "alpha", "type": "Text", "required": True}])
        )

    assert "Required" in exc_info.value.message
    assert "remediation=['forge_set_required']" in exc_info.value.message


@pytest.mark.asyncio
async def test_ignored_type_change_names_the_delete_and_recreate_route() -> None:
    before = FlowDraft.from_wire(_bare_form_draft()).apply_changes(
        [FieldSpec(name="alpha", type=FieldType.TEXT)]
    )
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, before]

    with pytest.raises(ApplicationError) as exc_info:
        await KfApplyFieldChange(fake).execute(
            _request(changes=[{"name": "alpha", "type": "Number"}])
        )

    assert "remediation=['forge_delete_fields', 'forge_apply_fields']" in (
        exc_info.value.message
    )


@pytest.mark.asyncio
async def test_an_identical_respec_is_still_a_plain_skip() -> None:
    """The idempotent re-run must not regress into a false alarm."""
    before = FlowDraft.from_wire(_bare_form_draft()).apply_changes(
        [FieldSpec(name="alpha", type=FieldType.TEXT, required=True)]
    )
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, before]

    resp = await KfApplyFieldChange(fake).execute(
        _request(changes=[{"name": "alpha", "type": "Text", "required": True}])
    )

    assert (
        resp.changed_ignored == []
        and resp.skipped == ["alpha"]
        and resp.verified == ["alpha"]
    )


@pytest.mark.asyncio
async def test_compares_only_options_the_caller_actually_named() -> None:
    """A Number field carries engine-written defaults no FieldSpec ever mentions -- a
    blind key diff would flag every one of them as an ignored change."""
    before = FlowDraft.from_wire(_bare_form_draft()).apply_changes(
        [FieldSpec(name="score", type=FieldType.NUMBER)]
    )
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, before]

    resp = await KfApplyFieldChange(fake).execute(
        _request(changes=[{"name": "score", "type": "Number"}])
    )
    assert resp.changed_ignored == []

    fake2 = FakeFlowRepository()
    fake2.results["get_draft"] = [before, before]
    with pytest.raises(ApplicationError) as exc_info:
        await KfApplyFieldChange(fake2).execute(
            _request(
                changes=[
                    {
                        "name": "score",
                        "type": "Number",
                        "options": {"DefaultValue": "7"},
                    }
                ]
            )
        )

    assert exc_info.value.code == "VERIFY_FAILED"
    assert "DefaultValue" in exc_info.value.message


@pytest.mark.asyncio
async def test_never_publishes_when_a_change_was_ignored() -> None:
    before = FlowDraft.from_wire(_bare_form_draft()).apply_changes(
        [FieldSpec(name="alpha", type=FieldType.TEXT)]
    )
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, before]

    with pytest.raises(ApplicationError) as exc_info:
        await KfApplyFieldChange(fake).execute(
            _request(changes=[{"name": "alpha", "type": "Number"}], publish=True)
        )

    assert "published=False" in exc_info.value.message
    publish_calls = [c for c in fake.calls if c[0] == "publish"]
    assert publish_calls == []


@pytest.mark.asyncio
async def test_no_app_id_is_refused_before_any_port_call() -> None:
    fake = FakeFlowRepository()

    with pytest.raises(ApplicationError) as exc_info:
        await KfApplyFieldChange(fake).execute(_request(app_id=""))

    assert exc_info.value.code == "REFUSED"
    assert fake.calls == []


@pytest.mark.asyncio
async def test_user_field_reapply_is_idempotent_not_a_changed_ignored_error() -> None:
    """D1: `apply_changes` deliberately pops `LHSModel` off the Field node onto the
    User field's mandatory QueryDefinition sibling, so it reads back as `None` on the
    Field forever. The changed-ignored diff must not compare the requested value
    against that `None` and flag a field written exactly as asked."""
    spec = {"name": "Requester", "type": "User", "options": {"LHSModel": "_employee"}}
    before = FlowDraft.from_wire(_bare_form_draft()).apply_changes(
        [FieldSpec(name="Requester", type=FieldType.USER, options={"LHSModel": "_e"})]
    )
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, before]

    resp = await KfApplyFieldChange(fake).execute(_request(changes=[spec]))

    assert resp.changed_ignored == []
    assert resp.skipped == ["Requester"]


@pytest.mark.asyncio
async def test_a_genuinely_changed_option_key_is_still_reported() -> None:
    """The control: excluding the relocated `LHSModel` key must not blind the diff to
    a real change."""
    before = FlowDraft.from_wire(_bare_form_draft()).apply_changes(
        [FieldSpec(name="Qty", type=FieldType.NUMBER)]
    )
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, before]

    with pytest.raises(ApplicationError) as exc_info:
        await KfApplyFieldChange(fake).execute(
            _request(changes=[{"name": "Qty", "type": "Text"}])
        )

    assert exc_info.value.code == "VERIFY_FAILED"
    assert "changed_ignored=" in exc_info.value.message
