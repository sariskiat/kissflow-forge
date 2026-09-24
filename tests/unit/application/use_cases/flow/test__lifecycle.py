"""`use_cases.flow._lifecycle`: the shared create-process / create-flow-any /
create-list helpers, ported from the former `client.py` module-level
functions of the same shape."""

from __future__ import annotations

import pytest
from tests.fakes.flow import FakeFlowRepository
from tests.fakes.flow_lifecycle import (
    PersistingFlowRepository,
)
from tests.unit.application.use_cases.test_write_order_contract import (
    assert_write_order,
)

from app.application.exceptions import ApplicationError, RepositoryError
from app.application.use_cases.flow._lifecycle import (
    ProcessCreateResult,
    apply_specs_to_flow,
    apply_word_list,
    create_flow_any,
    create_process,
    flow_create_note,
    process_create_note,
    scaffold_inventory,
)
from app.domain.entities.flow_draft import FlowDraft
from app.domain.value_objects.field_spec import FieldSpec
from app.domain.value_objects.field_type import FieldType


def _process_draft(version: str = "v1") -> FlowDraft:
    return FlowDraft.from_wire(
        {
            "_meta_version": version,
            "Root": "M1",
            "M1": {"Kind": "Model", "Type": "Root"},
        }
    )


# `require_app_id` and the write-did-not-land raise are the shared
# `use_cases.flow._fields` helpers now (brief_stage_d_common.md lesson 14):
# see tests/unit/application/use_cases/flow/test__fields.py for their own
# unit tests. This module only proves the lifecycle helpers still call them.


# ---- scaffold_inventory -------------------------------------------------------------


def test_scaffold_inventory_deduplicates_required_fields_by_name() -> None:
    """`brief_stage_d_common.md` review fix 8: the old `client.scaffold_inventory`
    read its required-field bucket off `_root_field_nodes(draft).items()`, a
    dict keyed by NAME -- two live Field nodes sharing one name collapse to a
    single entry. A bucket read straight off every node instead lists the
    name once per node."""
    draft = FlowDraft.from_wire(
        {
            "Root": "M1",
            "M1": {"Kind": "Model", "Type": "Root"},
            "F1": {
                "Kind": "Field",
                "Model": "M1",
                "Name": "Dept",
                "Required": True,
            },
            "F2": {
                "Kind": "Field",
                "Model": "M1",
                "Name": "Dept",
                "Required": True,
            },
        }
    )
    inv = scaffold_inventory(draft)
    assert inv.required_fields == ("Dept",)


def test_scaffold_inventory_reads_sections_required_fields_and_steps() -> None:
    draft = FlowDraft.from_wire(
        {
            "Root": "M1",
            "M1": {"Kind": "Model", "Type": "Root"},
            "C1": {"Kind": "Column", "Type": "Section", "Name": "Case Info"},
            "F1": {"Kind": "Field", "Model": "M1", "Name": "Urgency", "Required": True},
            "F2": {"Kind": "Field", "Model": "M1", "Name": "Notes", "Required": False},
            "A1": {"Kind": "Activity", "Name": "Start", "NodeType": "StartEvent"},
            "A2": {"Kind": "Activity", "Name": "Review", "NodeType": "UserTask"},
        }
    )
    inv = scaffold_inventory(draft)
    assert inv.sections == ("Case Info",)
    assert inv.required_fields == ("Urgency",)
    # NO_PERMISSION_NODETYPES is ("Parallel", "SendBackToInitiator", "GotoTask") --
    # StartEvent/EndEvent are legal (and, for the first section, mandatory) owners.
    assert inv.steps == ("Review", "Start")


# ---- process_create_note / flow_create_note -----------------------------------------


def test_process_create_note_is_none_when_not_from_template() -> None:
    assert (
        process_create_note(
            from_template=False, template_read_error=None, sections=0, required=0
        )
        is None
    )


def test_process_create_note_states_the_read_error() -> None:
    note = process_create_note(
        from_template=True, template_read_error="boom", sections=0, required=0
    )
    assert note is not None
    assert "boom" in note
    assert "nothing was READ" in note


def test_process_create_note_states_the_template_counts() -> None:
    note = process_create_note(
        from_template=True, template_read_error=None, sections=2, required=1
    )
    assert note == (
        "the process template shell brought in 2 section(s) "
        "and 1 Required field(s) you did not ask for. "
        "forge_set_visibility's `owners` must cover EVERY section listed above or "
        "that section is editable at no step; a Required field that is never "
        "editable makes its step permanently unsubmittable. Pass "
        "from_template=False for a bare shell."
    )


def test_flow_create_note_has_its_own_closing_sentence() -> None:
    note = flow_create_note(
        from_template=True, template_read_error=None, sections=1, required=0
    )
    assert note == (
        "the process template shell brought in 1 section(s) "
        "and 0 Required field(s) you did not ask for. "
        "forge_set_visibility's `owners` must cover EVERY section listed above or "
        "that section is editable at no step. Pass "
        "extra={'from_template': False} for a bare shell."
    )


def test_flow_create_note_states_the_read_error() -> None:
    note = flow_create_note(
        from_template=True, template_read_error="boom", sections=0, required=0
    )
    assert note == (
        "could not read the scaffold back to inventory it: boom — the three "
        "template_* buckets are empty because nothing was READ, not because the "
        "shell brought nothing in"
    )


def test_flow_create_note_is_none_when_not_from_template() -> None:
    assert (
        flow_create_note(
            from_template=False, template_read_error=None, sections=0, required=0
        )
        is None
    )


# ---- apply_specs_to_flow -------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_specs_to_flow_adds_a_new_field_and_verifies_it() -> None:
    fake = FakeFlowRepository()
    draft = _process_draft()
    fake.results["get_draft"] = [draft]  # the read-back after put_draft

    result = await apply_specs_to_flow(
        fake,
        app_id="A1",
        kind="process",
        flow_id="F1",
        draft=draft,
        specs=[FieldSpec(name="Ticket No", type=FieldType.TEXT)],
        publish=False,
    )

    assert result.added == ("Ticket No",)
    assert [c[0] for c in fake.calls] == ["put_draft", "get_draft"]


@pytest.mark.asyncio
async def test_apply_specs_to_flow_skips_an_existing_field() -> None:
    fake = FakeFlowRepository()
    draft = FlowDraft.from_wire(
        {
            "_meta_version": "v1",
            "Root": "M1",
            "M1": {"Kind": "Model", "Type": "Root"},
            "F1": {
                "Kind": "Field",
                "Model": "M1",
                "Name": "Ticket No",
                "Type": "Text",
                "Required": False,
            },
        }
    )
    fake.results["get_draft"] = [draft]

    result = await apply_specs_to_flow(
        fake,
        app_id="A1",
        kind="process",
        flow_id="F1",
        draft=draft,
        specs=[FieldSpec(name="Ticket No", type=FieldType.TEXT)],
        publish=False,
    )

    assert result.added == ()
    assert result.skipped == ("Ticket No",)
    assert result.verified == ("Ticket No",)
    # no field was added, so no put_draft call at all
    assert [c[0] for c in fake.calls] == ["get_draft"]


@pytest.mark.asyncio
async def test_apply_specs_to_flow_reports_a_changed_ignored_collision() -> None:
    fake = FakeFlowRepository()
    draft = FlowDraft.from_wire(
        {
            "_meta_version": "v1",
            "Root": "M1",
            "M1": {"Kind": "Model", "Type": "Root"},
            "F1": {
                "Kind": "Field",
                "Model": "M1",
                "Name": "Ticket No",
                "Type": "Number",
                "Required": False,
            },
        }
    )
    fake.results["get_draft"] = [draft]

    result = await apply_specs_to_flow(
        fake,
        app_id="A1",
        kind="process",
        flow_id="F1",
        draft=draft,
        specs=[FieldSpec(name="Ticket No", type=FieldType.TEXT)],
        publish=False,
    )

    assert result.added == ()
    assert result.skipped == ()
    assert len(result.changed_ignored) == 1
    assert "NOT applied" in result.changed_ignored[0]
    assert "forge_apply_fields" in result.remediation


@pytest.mark.asyncio
async def test_apply_specs_remediates_a_required_collision_by_set_required() -> None:
    """A collision on the Required flag alone has its own live op, so the
    remediation names forge_set_required, never delete-and-recreate."""
    fake = FakeFlowRepository()
    draft = FlowDraft.from_wire(
        {
            "_meta_version": "v1",
            "Root": "M1",
            "M1": {"Kind": "Model", "Type": "Root"},
            "F1": {
                "Kind": "Field",
                "Model": "M1",
                "Name": "Ticket No",
                "Type": "Text",
                "Required": False,
            },
        }
    )
    fake.results["get_draft"] = [draft]

    result = await apply_specs_to_flow(
        fake,
        app_id="A1",
        kind="process",
        flow_id="F1",
        draft=draft,
        specs=[FieldSpec(name="Ticket No", type=FieldType.TEXT, required=True)],
        publish=False,
    )

    assert result.changed_ignored == (
        "Ticket No: requested Required=True, live Required=False — NOT applied "
        "(apply_changes only creates; an existing name is never edited)",
    )
    assert result.remediation == ("forge_set_required",)


@pytest.mark.asyncio
async def test_apply_specs_to_flow_diffs_referred_list_and_stated_options() -> None:
    """Only what the caller stated is compared: ReferredList when given, each
    `options` key when given -- and never `LHSModel`, which the builder moves off
    the Field node onto its QueryDefinition sibling."""
    fake = FakeFlowRepository()
    draft = FlowDraft.from_wire(
        {
            "_meta_version": "v1",
            "Root": "M1",
            "M1": {"Kind": "Model", "Type": "Root"},
            "F1": {
                "Kind": "Field",
                "Model": "M1",
                "Name": "Priority",
                "Type": "Select",
                "Required": False,
                "ReferredList": "L1",
            },
        }
    )
    fake.results["get_draft"] = [draft]

    result = await apply_specs_to_flow(
        fake,
        app_id="A1",
        kind="process",
        flow_id="F1",
        draft=draft,
        specs=[
            FieldSpec(
                name="Priority",
                type=FieldType.SELECT,
                referred_list="L2",
                options={"LHSModel": "M9", "AllowFormatting": True},
            )
        ],
        publish=False,
    )

    assert result.changed_ignored == (
        "Priority: requested ReferredList='L2', AllowFormatting=True, live "
        "ReferredList='L1' AllowFormatting=None — NOT applied (apply_changes only "
        "creates; an existing name is never edited)",
    )
    assert result.remediation == ("forge_delete_fields", "forge_apply_fields")


@pytest.mark.asyncio
async def test_apply_specs_to_flow_publishes_when_requested_and_clean() -> None:
    fake = FakeFlowRepository()
    draft = _process_draft()
    # the read-back after put_draft must show the field as landed, or it is
    # reported `missing` and publish is correctly withheld -- the fake does not
    # simulate persistence, so the queued response states it explicitly.
    read_back = FlowDraft.from_wire(
        {
            "_meta_version": "v2",
            "Root": "M1",
            "M1": {"Kind": "Model", "Type": "Root"},
            "F1": {
                "Kind": "Field",
                "Model": "M1",
                "Name": "Ticket No",
                "Type": "Text",
                "Required": False,
            },
        }
    )
    fake.results["get_draft"] = [read_back]

    result = await apply_specs_to_flow(
        fake,
        app_id="A1",
        kind="process",
        flow_id="F1",
        draft=draft,
        specs=[FieldSpec(name="Ticket No", type=FieldType.TEXT)],
        publish=True,
    )

    assert result.missing == ()
    assert result.published is True
    assert [c[0] for c in fake.calls] == ["put_draft", "get_draft", "publish"]


@pytest.mark.asyncio
async def test_apply_specs_to_flow_translates_a_bad_change_set() -> None:
    fake = FakeFlowRepository()
    draft = _process_draft()

    with pytest.raises(ApplicationError) as exc:
        await apply_specs_to_flow(
            fake,
            app_id="A1",
            kind="process",
            flow_id="F1",
            draft=draft,
            specs=[FieldSpec(name="Bad Select", type=FieldType.SELECT)],
            publish=False,
        )
    assert exc.value.code == "VERIFY_FAILED"


# ---- create_process ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_process_happy_path_from_template() -> None:
    fake = FakeFlowRepository()
    fake.results["create_flow"] = ["F1"]
    fake.results["get_draft"] = [
        _process_draft("v1"),  # the initial snapshot
        _process_draft("v2"),  # the read after scaffold, before fields
        _process_draft("v3"),  # the read-back after apply_specs_to_flow's put
        _process_draft("v3"),  # the final inventory read
    ]

    result = await create_process(
        fake,
        app_id="A1",
        name="Expense Approval",
        steps=("Draft",),
        specs=[],
        publish=False,
        from_template=False,
        template_path=None,
    )

    assert result.flow_id == "F1"
    assert result.snapshot_version == "v1"
    assert_write_order(fake)


@pytest.mark.asyncio
async def test_create_process_raises_when_a_field_is_missing_on_readback() -> None:
    """Lesson 7: a create whose fields did not fully land is a failure, never a
    success carrying a non-empty `missing` bucket. The flow itself is NOT
    abandoned -- only a hard failure during the write sequence triggers cleanup."""
    fake = FakeFlowRepository()
    fake.results["create_flow"] = ["F1"]
    fake.results["get_draft"] = [
        _process_draft("v1"),
        _process_draft("v2"),
        _process_draft("v2"),  # read-back never gained the requested field
        _process_draft("v2"),
    ]

    with pytest.raises(ApplicationError) as exc:
        await create_process(
            fake,
            app_id="A1",
            name="Expense Approval",
            steps=("Draft",),
            specs=[FieldSpec(name="Ticket No", type=FieldType.TEXT)],
            publish=False,
            from_template=False,
            template_path=None,
        )
    assert exc.value.code == "VERIFY_FAILED"
    assert "Ticket No" in exc.value.message
    assert "left_on_tenant='F1'" in exc.value.message, (
        "a caller that never sees the response must still learn the id of "
        "the process this failed create left on the tenant (fix 6)"
    )
    assert [c[0] for c in fake.calls][-1] != "delete_flow"  # the flow is kept


@pytest.mark.asyncio
async def test_create_process_names_remediation_on_a_changed_ignored_collision() -> (
    None
):
    """`brief_stage_d_common.md` review fix 6: the old `ProcessCreateReport`
    returned `remediation` alongside `flow_id`; a raise that never reaches
    the response DTO must still fold it into the message, as
    `kf_apply_field_change` does."""
    fake = FakeFlowRepository()
    fake.results["create_flow"] = ["F1"]
    existing_field_draft = FlowDraft.from_wire(
        {
            "_meta_version": "v2",
            "Root": "M1",
            "M1": {"Kind": "Model", "Type": "Root"},
            "F1": {
                "Kind": "Field",
                "Model": "M1",
                "Name": "Ticket No",
                "Type": "Number",
                "Required": False,
            },
        }
    )
    fake.results["get_draft"] = [
        _process_draft("v1"),
        existing_field_draft,
        existing_field_draft,
        existing_field_draft,
    ]

    with pytest.raises(ApplicationError) as exc:
        await create_process(
            fake,
            app_id="A1",
            name="Expense Approval",
            steps=("Draft",),
            specs=[FieldSpec(name="Ticket No", type=FieldType.TEXT)],
            publish=False,
            from_template=False,
            template_path=None,
        )
    assert exc.value.code == "VERIFY_FAILED"
    assert "left_on_tenant='F1'" in exc.value.message
    assert "remediation=['forge_delete_fields', 'forge_apply_fields']" in (
        exc.value.message
    )


@pytest.mark.asyncio
async def test_create_process_abandons_the_flow_on_a_scaffold_failure() -> None:
    fake = FakeFlowRepository()
    fake.results["create_flow"] = ["F1"]
    # ensure_process_def raises ValueError on an empty steps tuple
    fake.results["get_draft"] = [_process_draft("v1")]

    with pytest.raises(ApplicationError) as exc:
        await create_process(
            fake,
            app_id="A1",
            name="Expense Approval",
            steps=(),
            specs=[],
            publish=False,
            from_template=False,
            template_path=None,
        )
    assert exc.value.code == "VERIFY_FAILED"
    assert [c[0] for c in fake.calls][-1] == "delete_flow"
    assert fake.calls[-1] == (
        "delete_flow",
        ("A1", "process", "F1"),
        {"archive_first": True},
    )


@pytest.mark.asyncio
async def test_create_process_abandon_swallows_its_own_cleanup_failure() -> None:
    """The cleanup delete raising must never mask the error that triggered it."""
    fake = FakeFlowRepository()
    fake.results["create_flow"] = ["F1"]
    fake.results["get_draft"] = [_process_draft("v1")]

    async def _failing_delete(*args: object, **kwargs: object) -> None:
        fake.calls.append(("delete_flow", args, kwargs))
        raise RepositoryError("cleanup also failed")

    fake.delete_flow = _failing_delete  # type: ignore

    with pytest.raises(ApplicationError) as exc:
        await create_process(
            fake,
            app_id="A1",
            name="Expense Approval",
            steps=(),  # ensure_process_def refuses an empty step tuple
            specs=[],
            publish=False,
            from_template=False,
            template_path=None,
        )
    # the ORIGINAL scaffold error propagates, not the cleanup failure
    assert exc.value.code == "VERIFY_FAILED"
    assert "cleanup also failed" not in exc.value.message
    assert fake.calls[-1][0] == "delete_flow"


# ---- create_flow_any --------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_flow_any_form_is_born_draft() -> None:
    fake = FakeFlowRepository()
    fake.results["create_flow"] = ["F1"]

    result = await create_flow_any(
        fake, app_id="A1", kind="form", name="Intake Form", extra=None
    )

    assert result.kind == "form"
    assert result.flow_id == "F1"
    assert result.status == "Draft"
    assert result.born_live is False
    assert_write_order(fake)


@pytest.mark.asyncio
async def test_create_flow_any_list_is_born_live() -> None:
    fake = FakeFlowRepository()
    fake.results["create_list"] = [{"_id": "L1", "Status": "Live"}]

    result = await create_flow_any(
        fake, app_id="A1", kind="list", name="Priorities", extra=None
    )

    assert result.kind == "list"
    assert result.flow_id == "L1"
    assert result.born_live is True
    assert_write_order(fake)


@pytest.mark.asyncio
async def test_create_flow_any_raises_when_the_create_response_has_no_id() -> None:
    """Lesson 7: a create response with no usable id is a failure, never a success
    with an empty `flow_id` (matches the former `not self.flow_id` isError rule)."""
    fake = FakeFlowRepository()
    fake.results["create_list"] = [{"Status": "Live"}]  # no "_id" key

    with pytest.raises(ApplicationError) as exc:
        await create_flow_any(
            fake, app_id="A1", kind="list", name="Priorities", extra=None
        )
    assert exc.value.code == "VERIFY_FAILED"
    assert "write did not fully land" in exc.value.message
    assert "published=n/a (a born-live kind has no publish step)" in exc.value.message
    assert "--" not in exc.value.message, "product text uses an em dash, never '--'"


@pytest.mark.asyncio
async def test_create_flow_any_case_requires_item_type_and_prefix() -> None:
    fake = FakeFlowRepository()

    with pytest.raises(ApplicationError) as exc:
        await create_flow_any(
            fake, app_id="A1", kind="case", name="Support", extra=None
        )
    assert exc.value.code == "VERIFY_FAILED"
    assert fake.calls == []  # refused before any port call


@pytest.mark.asyncio
async def test_create_flow_any_case_happy_path() -> None:
    fake = FakeFlowRepository()
    fake.results["create_case"] = [{"_id": "K1", "Status": "Live"}]

    result = await create_flow_any(
        fake,
        app_id="A1",
        kind="case",
        name="Support",
        extra={"item_type": "Board", "prefix": "SUP"},
    )

    assert result.flow_id == "K1"
    assert result.born_live is True


@pytest.mark.asyncio
async def test_create_flow_any_process_reads_the_scaffold_inventory() -> None:
    fake = FakeFlowRepository()
    fake.results["create_flow"] = ["F1"]
    fake.results["get_draft"] = [_process_draft("v1"), _process_draft("v2")]

    result = await create_flow_any(
        fake,
        app_id="A1",
        kind="process",
        name="Expense Approval",
        extra={"from_template": False, "steps": ["Review"]},
    )

    assert result.flow_id == "F1"
    assert result.from_template is False
    assert result.snapshot_version == "v1"
    assert_write_order(fake)


@pytest.mark.asyncio
async def test_create_flow_any_process_clones_the_template_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`extra` absent means from_template=True: the identity shell is cloned, with
    `extra["template_path"]` passed through (None when absent)."""
    fake = FakeFlowRepository()
    fake.results["create_flow"] = ["F1"]
    fake.results["get_draft"] = [_process_draft("v1"), _process_draft("v2")]
    captured: list[str | None] = []

    def _fake_clone(self: FlowDraft, template_path: str | None) -> FlowDraft:
        captured.append(template_path)
        return self

    monkeypatch.setattr(FlowDraft, "clone_template_shell", _fake_clone)

    result = await create_flow_any(
        fake, app_id="A1", kind="process", name="N", extra=None
    )

    assert captured == [None]
    assert result.from_template is True
    assert result.status == "Draft"


@pytest.mark.asyncio
async def test_create_flow_any_process_abandons_the_flow_on_a_scaffold_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeFlowRepository()
    fake.results["create_flow"] = ["F1"]
    fake.results["get_draft"] = [_process_draft("v1")]

    def _bad_clone(self: FlowDraft, template_path: str | None) -> FlowDraft:
        raise ValueError("template path does not resolve")

    monkeypatch.setattr(FlowDraft, "clone_template_shell", _bad_clone)

    with pytest.raises(ApplicationError) as exc:
        await create_flow_any(fake, app_id="A1", kind="process", name="N", extra=None)
    assert exc.value.code == "VERIFY_FAILED"
    assert exc.value.message == "template path does not resolve"
    assert fake.calls[-1] == (
        "delete_flow",
        ("A1", "process", "F1"),
        {"archive_first": True},
    )


@pytest.mark.asyncio
async def test_create_flow_any_process_abandons_the_flow_on_a_write_conflict() -> None:
    """A port failure after the shell exists (here, a version conflict on the
    scaffold write) also abandons the half-built flow, and the original error
    propagates unchanged -- even when the cleanup delete itself fails."""
    fake = FakeFlowRepository()
    fake.results["create_flow"] = ["F1"]
    fake.results["get_draft"] = [_process_draft("v1")]
    conflict = RepositoryError("draft changed under us", code="CONFLICT")

    async def _conflicting_put(*args: object, **kwargs: object) -> FlowDraft:
        raise conflict

    async def _failing_delete(*args: object, **kwargs: object) -> None:
        fake.calls.append(("delete_flow", args, kwargs))
        raise RepositoryError("cleanup also failed")

    fake.put_draft = _conflicting_put  # type: ignore
    fake.delete_flow = _failing_delete  # type: ignore

    with pytest.raises(RepositoryError) as exc:
        await create_flow_any(
            fake,
            app_id="A1",
            kind="process",
            name="N",
            extra={"from_template": False, "steps": ["Review"]},
        )
    assert exc.value is conflict
    assert fake.calls[-1][0] == "delete_flow"


@pytest.mark.asyncio
async def test_create_flow_any_unknown_kind_is_refused() -> None:
    fake = FakeFlowRepository()
    with pytest.raises(ApplicationError):
        await create_flow_any(
            fake,
            app_id="A1",
            kind="bogus",  # type: ignore
            name="x",
            extra=None,
        )


# ---- apply_word_list --------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_word_list_creates_a_new_list_and_verifies_items() -> None:
    fake = FakeFlowRepository()
    fake.results["list_lists"] = [[]]
    fake.results["create_list"] = [{"_id": "L1"}]
    fake.results["get_list_items"] = [["Low", "High"]]

    result = await apply_word_list(
        fake, app_id="A1", name="Priorities", items=["Low", "High"]
    )

    assert result.created is True
    assert result.list_id == "L1"
    assert result.verified_items == ("Low", "High")
    assert result.missing_items == ()
    assert_write_order(fake)


@pytest.mark.asyncio
async def test_apply_word_list_reuses_an_existing_list_by_name() -> None:
    fake = FakeFlowRepository()
    fake.results["list_lists"] = [[{"Name": "Priorities", "_id": "L1"}]]
    fake.results["get_list_items"] = [["Low"]]

    result = await apply_word_list(fake, app_id="A1", name="Priorities", items=["Low"])

    assert result.created is False
    assert result.list_id == "L1"
    assert [c[0] for c in fake.calls] == [
        "list_lists",
        "set_list_items",
        "get_list_items",
    ]


@pytest.mark.asyncio
async def test_apply_word_list_refuses_when_no_list_id_resolves() -> None:
    """A create response with no `_id` is refused before any item write."""
    fake = FakeFlowRepository()
    fake.results["list_lists"] = [[]]
    fake.results["create_list"] = [{}]

    with pytest.raises(ApplicationError) as exc:
        await apply_word_list(fake, app_id="A1", name="Priorities", items=["Low"])
    assert exc.value.code == "VERIFY_FAILED"
    assert exc.value.message == (
        "list 'Priorities': no _id resolvable from create/inventory"
    )
    assert "set_list_items" not in [c[0] for c in fake.calls]


@pytest.mark.asyncio
async def test_apply_word_list_raises_on_missing_items_on_read_back() -> None:
    """Lesson 7: a write with a non-empty `missing_items` bucket is a failure, never
    a success response carrying that bucket."""
    fake = FakeFlowRepository()
    fake.results["list_lists"] = [[]]
    fake.results["create_list"] = [{"_id": "L1"}]
    fake.results["get_list_items"] = [[]]  # write "landed" but read-back is empty

    with pytest.raises(ApplicationError) as exc:
        await apply_word_list(fake, app_id="A1", name="Priorities", items=["Low"])
    assert exc.value.code == "VERIFY_FAILED"
    assert exc.value.message == (
        "write did not fully land (missing_items=['Low']); "
        "left_on_tenant='L1'; "
        "published=n/a (a word list is born live, no publish step)"
    )


# =====================================================================================
# Ported from tests/test_client.py (create_process / create_flow_any / apply_word_list)
# and tests/test_p4_surface.py (forge_create_flow). Same names, same assertions, now
# against the flow port through `PersistingFlowRepository` (the port form of the old
# `_CreateProcessClient` / `CreateFlowClient`, which persisted every write).
# =====================================================================================

_SHELL_SECTIONS = (
    "In-Kissflow Template",
    "Public Form Template",
    "Request Details",
    "Request Info",
    "System",
)
_SHELL_STEPS = ("Completed", "Manager Approve", "Start")


async def _create_process(
    fake: PersistingFlowRepository,
    *,
    steps: tuple[str, ...] = ("Draft",),
    from_template: bool = True,
) -> ProcessCreateResult:
    return await create_process(
        fake,
        app_id="A1",
        name="Expense Approval",
        steps=steps,
        specs=[],
        publish=False,
        from_template=from_template,
        template_path=None,
    )


@pytest.mark.asyncio
async def test_create_process_from_template_default_seeds_the_identity_shell() -> None:
    fake = PersistingFlowRepository()
    result = await _create_process(fake)

    assert result.flow_id == "F1"
    wire = fake.draft.to_wire()
    m = wire["M1"]
    assert len(m.get("Model::Field", [])) == 28, (
        "identity shell fields must be on the draft"
    )
    pd = wire[m["RootProcessDef"]]
    acts = [wire[a] for a in pd["ProcessDef::Activity"]]
    assert [a["NodeType"] for a in acts] == ["StartEvent", "UserTask", "EndEvent"]
    assert acts[1]["Name"] == "Manager Approve"
    assert_write_order(fake)


@pytest.mark.asyncio
async def test_create_process_from_template_false_yields_the_bare_scaffold() -> None:
    fake = PersistingFlowRepository()
    await _create_process(fake, steps=("Review",), from_template=False)

    wire = fake.draft.to_wire()
    m = wire["M1"]
    assert m.get("Model::Field", []) == [], "the bare scaffold carries no fields"
    pd = wire[m["RootProcessDef"]]
    acts = [wire[a] for a in pd["ProcessDef::Activity"]]
    assert [a["Name"] for a in acts] == ["Start", "Review", "Completed"]


@pytest.mark.asyncio
async def test_create_flow_any_process_from_template_default() -> None:
    fake = PersistingFlowRepository()
    result = await create_flow_any(
        fake, app_id="A1", kind="process", name="Expense Approval", extra=None
    )

    assert result.flow_id == "F1"
    assert len(fake.draft.to_wire()["M1"].get("Model::Field", [])) == 28


@pytest.mark.asyncio
async def test_create_flow_any_process_from_template_false() -> None:
    fake = PersistingFlowRepository()
    result = await create_flow_any(
        fake,
        app_id="A1",
        kind="process",
        name="Expense Approval",
        extra={"from_template": False, "steps": ("Review",)},
    )

    assert result.flow_id == "F1"
    wire = fake.draft.to_wire()
    m = wire["M1"]
    assert m.get("Model::Field", []) == []
    pd = wire[m["RootProcessDef"]]
    acts = [wire[a] for a in pd["ProcessDef::Activity"]]
    assert [a["Name"] for a in acts] == ["Start", "Review", "Completed"]


@pytest.mark.asyncio
async def test_create_process_states_the_sections_the_template_injected() -> None:
    """The report used to be all empty tuples, so the caller was blind to the
    sections and Required fields the DEFAULT put on their flow. (The `note` half of
    the old assertion is ported onto the use case, test_forge_create_process.py.)"""
    result = await _create_process(PersistingFlowRepository())

    assert result.from_template is True
    assert result.template_sections == _SHELL_SECTIONS
    assert result.template_steps == _SHELL_STEPS
    assert result.template_read_error is None


@pytest.mark.asyncio
async def test_create_process_states_the_required_fields_the_template_injected() -> (
    None
):
    """A Required field that is never editable makes its step permanently
    unsubmittable -- the caller cannot cover a field it was never told about."""
    fake = PersistingFlowRepository()
    result = await _create_process(fake)

    wire = fake.draft.to_wire()
    live = tuple(
        sorted(
            v["Name"]
            for v in wire.values()
            if isinstance(v, dict)
            and v.get("Kind") == "Field"
            and v.get("Model") == wire["Root"]
            and v.get("Required")
        )
    )
    assert result.template_required_fields == live
    assert live, "precondition: the shipped shell really does carry Required fields"


@pytest.mark.asyncio
async def test_from_template_false_reports_an_empty_template_inventory() -> None:
    """The control: the bare scaffold brings in no section and no Required field,
    and says so rather than pretending it did."""
    result = await _create_process(
        PersistingFlowRepository(), steps=("Review",), from_template=False
    )

    assert result.from_template is False
    assert result.template_sections == () and result.template_required_fields == ()
    assert result.template_steps == ("Completed", "Review", "Start")


@pytest.mark.asyncio
async def test_an_unreadable_scaffold_is_stated_not_reported_as_an_empty_template() -> (
    None
):
    """Buckets that are empty because nothing was READ must never look identical to
    buckets that are empty because nothing was there -- and an unreadable inventory
    is not a failed create (the old report kept `isError: false`)."""
    # reads: the post-create snapshot, the field step's own two -- the 4th dies
    fake = PersistingFlowRepository(failing_read_from=4)
    result = await _create_process(fake)

    assert result.flow_id == "F1"
    assert result.template_sections == () and result.template_required_fields == ()
    assert result.template_read_error is not None
    assert "503" in result.template_read_error
    assert "delete_flow" not in [c[0] for c in fake.calls]  # nothing abandoned


@pytest.mark.asyncio
async def test_create_flow_any_process_also_states_the_template_inventory() -> None:
    """The OTHER tool that runs the same clone -- forge_create_flow(kind='process')."""
    result = await create_flow_any(
        PersistingFlowRepository(),
        app_id="A1",
        kind="process",
        name="Expense Approval",
        extra=None,
    )

    assert result.from_template is True
    assert result.template_sections == _SHELL_SECTIONS
    assert result.template_steps == _SHELL_STEPS
    assert result.template_required_fields == (
        "Branch",
        "Department",
        "Description",
        "Manager Display Name",
        "Requestor Employee Id Alt",
    )


@pytest.mark.asyncio
async def test_create_flow_any_inventories_the_live_draft_never_the_put_response() -> (
    None
):
    """THE RULE: an inventory that can fall back to what the caller SENT is not
    evidence -- it must come off a real read of the flow, even when the write
    answers with a bare ack."""
    result = await create_flow_any(
        PersistingFlowRepository(ack_put=True),
        app_id="A1",
        kind="process",
        name="Expense Approval",
        extra=None,
    )

    assert result.template_sections == _SHELL_SECTIONS
    assert result.template_steps == _SHELL_STEPS
    assert result.template_required_fields, (
        "the shipped shell really does carry Required fields"
    )
    assert result.template_read_error is None


@pytest.mark.asyncio
async def test_create_flow_any_states_an_unreadable_template_read() -> None:
    """The sibling half of the same distinction, on forge_create_flow's path."""
    fake = PersistingFlowRepository(failing_read_from=2)  # the read-back dies
    result = await create_flow_any(
        fake, app_id="A1", kind="process", name="Expense Approval", extra=None
    )

    assert result.flow_id == "F1", (
        "the flow was created -- an unreadable read-back is not a failure"
    )
    assert result.template_sections == () and result.template_required_fields == ()
    assert result.template_read_error is not None
    assert "503" in result.template_read_error


@pytest.mark.asyncio
async def test_create_flow_any_born_live_kinds_carry_no_template_inventory() -> None:
    """The control: a list/dataset/case has no scaffold to inventory and must not
    invent one. (The `note` half is on the use case, test_forge_create_flow.py.)"""
    result = await create_flow_any(
        PersistingFlowRepository(),
        app_id="A1",
        kind="list",
        name="Urgency Levels",
        extra=None,
    )

    assert result.from_template is False and result.template_sections == ()


@pytest.mark.asyncio
async def test_apply_word_list_creates_sets_and_verifies() -> None:
    fake = PersistingFlowRepository()
    result = await apply_word_list(
        fake, app_id="A1", name="Priorities", items=["High", "Medium", "Low"]
    )

    assert result.created is True
    assert result.verified_items == ("High", "Medium", "Low")
    assert result.missing_items == ()


@pytest.mark.asyncio
async def test_apply_word_list_reuses_existing_by_name_and_replaces_items() -> None:
    """REPLACE semantics (live-proven 2026-08-12): a second call with a changed value
    set replaces the array outright -- no duplicate list, no stale leftovers."""
    fake = PersistingFlowRepository()
    first = await apply_word_list(
        fake, app_id="A1", name="Priorities", items=["High", "Low"]
    )
    result = await apply_word_list(
        fake, app_id="A1", name="Priorities", items=["Critical", "High", "Low"]
    )

    assert result.created is False, "reused by name, never a second list"
    assert result.list_id == first.list_id
    assert fake.list_items[result.list_id] == ["Critical", "High", "Low"]


@pytest.mark.asyncio
async def test_apply_word_list_missing_value_lands_in_missing_bucket() -> None:
    """A requested value absent on read-back is never silent. Lesson 7: it is now a
    raised failure naming the bucket, where the old report returned it with
    `isError: true`."""
    fake = PersistingFlowRepository()
    fake.drop_list_values = {"Ghost"}

    with pytest.raises(ApplicationError) as exc:
        await apply_word_list(
            fake, app_id="A1", name="Priorities", items=["High", "Ghost"]
        )
    assert exc.value.code == "VERIFY_FAILED"
    assert "missing_items=['Ghost']" in exc.value.message


# ---- ported from tests/test_p4_surface.py (forge_create_flow) -----------------------


@pytest.mark.asyncio
async def test_create_flow_process_starts_draft() -> None:
    result = await create_flow_any(
        PersistingFlowRepository(),
        app_id="A1",
        kind="process",
        name="Expense Approval",
        extra=None,
    )

    assert result.status == "Draft" and result.born_live is False and result.flow_id


@pytest.mark.asyncio
async def test_create_flow_process_seeds_the_processdef_scaffold() -> None:
    """Regression for the Mode-A bug (2026-08-12): a bare process draft 500s on the
    next write until it carries a ProcessDef."""
    fake = PersistingFlowRepository()
    await create_flow_any(
        fake, app_id="A1", kind="process", name="Expense Approval", extra=None
    )

    assert fake.puts >= 1, (
        "process create must PUT a scaffolded draft, not just POST a bare flow"
    )
    kinds = {
        n.get("Kind") for n in fake.draft.to_wire().values() if isinstance(n, dict)
    }
    assert "ProcessDef" in kinds, "scaffolded draft must contain a ProcessDef"


@pytest.mark.asyncio
async def test_create_flow_list_is_born_live() -> None:
    result = await create_flow_any(
        PersistingFlowRepository(),
        app_id="A1",
        kind="list",
        name="Priority",
        extra=None,
    )

    assert result.status == "Live" and result.born_live is True


@pytest.mark.asyncio
async def test_create_flow_dataset_is_born_live() -> None:
    result = await create_flow_any(
        PersistingFlowRepository(),
        app_id="A1",
        kind="dataset",
        name="Vendors",
        extra=None,
    )

    assert result.status == "Live" and result.born_live is True


@pytest.mark.asyncio
async def test_create_flow_case_requires_item_type_and_prefix() -> None:
    with pytest.raises(ApplicationError) as exc:
        await create_flow_any(
            PersistingFlowRepository(),
            app_id="A1",
            kind="case",
            name="Support Tickets",
            extra=None,
        )
    assert exc.value.code == "VERIFY_FAILED"
    assert "item_type" in exc.value.message and "prefix" in exc.value.message


@pytest.mark.asyncio
async def test_create_flow_case_with_extra_succeeds() -> None:
    result = await create_flow_any(
        PersistingFlowRepository(),
        app_id="A1",
        kind="case",
        name="Support Tickets",
        extra={"item_type": "Board", "prefix": "SUP"},
    )

    assert result.status == "Live" and result.born_live is True


@pytest.mark.asyncio
async def test_create_flow_unknown_kind_rejected() -> None:
    with pytest.raises(ApplicationError) as exc:
        await create_flow_any(
            PersistingFlowRepository(),
            app_id="A1",
            kind="wizardry",  # type: ignore
            name="x",
            extra=None,
        )
    assert exc.value.code == "VERIFY_FAILED"


@pytest.mark.asyncio
async def test_apply_word_list_unwraps_a_data_envelope_inventory() -> None:
    """Restores `client.py:2310-2313`'s unwrap: `list_lists` can come back
    `{"Data": [...]}` rather than a bare array, and a caller must still resolve an
    existing name to its id instead of creating a duplicate list."""
    fake = FakeFlowRepository()
    fake.results["list_lists"] = [{"Data": [{"Name": "Priorities", "_id": "L1"}]}]
    fake.results["get_list_items"] = [["High"]]

    result = await apply_word_list(fake, app_id="A1", name="Priorities", items=["High"])

    assert result.created is False
    assert result.list_id == "L1"
    assert "create_list" not in [c[0] for c in fake.calls]
