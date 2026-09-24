"""Private helpers shared by the flow-lifecycle use cases (`kf_create_process`,
`forge_create_process`, `forge_create_flow`, `forge_create_list`).

Ported from the former `app.infrastructure.kissflow.client` module-level
functions of the same shape (`create_process`, `create_flow_any`,
`apply_word_list`, and their private field-diffing/scaffold-inventory
helpers) -- never imported from there (Stage D rule: no new code imports
the old `client.py`). Every helper here is self-contained, built only from
`FlowRepository` and the public `FlowDraft`/`FieldSpec` surface -- never a
`FlowDraft.nodes` read or a `domain.entities._flow_ops`/`_flow_rules`
import (those stay private to the domain); node-graph reasoning here goes
through `FlowDraft.to_wire()` copies instead.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import Any

from app.application.exceptions import ApplicationError, RepositoryError
from app.application.interfaces.flow import FlowRepository
from app.application.use_cases.flow._fields import (
    changed_ignored,
    raise_if_write_failed,
    root_field_nodes,
)
from app.domain.entities.flow_draft import NO_PERMISSION_NODETYPES, FlowDraft
from app.domain.value_objects.field_spec import FieldSpec
from app.domain.value_objects.kinds import CreateFlowKind, FlowKind

# =====================================================================================
# Scaffold inventory -- what a freshly scaffolded process actually contains, read
# back off the live draft. Ported from
# `client.ScaffoldInventory`/`client.scaffold_inventory`.
# =====================================================================================


@dataclass(frozen=True)
class ScaffoldInventory:
    """Sections, Required root fields and workflow step names a scaffold put on a
    draft, read back off the live graph (never off the template file that was sent)."""

    sections: tuple[str, ...]
    required_fields: tuple[str, ...]
    steps: tuple[str, ...]


def scaffold_inventory(draft: FlowDraft) -> ScaffoldInventory:
    """Sections, Required root fields and workflow step names on `draft`.

    Sections are `Column{Type:"Section"}` by name -- the exact population
    `forge_set_visibility`'s `owners` map has to cover. Steps exclude the
    nodes that render no form and take no Permission (StartEvent/EndEvent
    included, since "Start" is a legal owner).

    Args:
        draft: The live draft to inventory.

    Returns:
        The sections, Required root fields and step names, each sorted.
    """
    wire = draft.to_wire()
    sections = tuple(
        sorted(
            n
            for v in wire.values()
            if isinstance(v, dict)
            and v.get("Kind") == "Column"
            and v.get("Type") == "Section"
            and isinstance(n := v.get("Name"), str)
            and n
        )
    )
    # `root_field_nodes` keys by NAME (`_fields.py`, shared with
    # `forge_set_required`'s own read) -- two live Field nodes sharing one
    # name must collapse to a single entry, matching the former
    # `client._root_field_nodes(draft).items()` dedup (review, fix 8).
    required = tuple(
        sorted(
            name
            for name, node in root_field_nodes(wire).items()
            if name and node.get("Required")
        )
    )
    steps = tuple(
        sorted(
            n
            for v in wire.values()
            if isinstance(v, dict)
            and v.get("Kind") == "Activity"
            and v.get("NodeType") not in NO_PERMISSION_NODETYPES
            and isinstance(n := v.get("Name"), str)
            and n
        )
    )
    return ScaffoldInventory(sections=sections, required_fields=required, steps=steps)


async def _read_scaffold_inventory(
    flow_repo: FlowRepository, app_id: str, flow_id: str
) -> tuple[ScaffoldInventory, str | None]:
    """Inventory the scaffold off one more live read of the process, never off the
    write response or the template file that was sent (THE RULE).

    A failed read is stated, not raised: every write already landed, so the
    process exists and the former reports kept `isError: false` here. The
    buckets come back empty because nothing was read, and the error says so
    (the former `ProcessCreateReport`/`FlowCreateReport.template_read_error`).

    Args:
        flow_repo: The flow port.
        app_id: The application the process belongs to.
        flow_id: The process's id.

    Returns:
        The inventory and `None`, or three empty buckets and the read's own
        error message.
    """
    try:
        final = await flow_repo.get_draft(app_id, "process", flow_id)
    except RepositoryError as exc:
        return ScaffoldInventory((), (), ()), exc.message
    return scaffold_inventory(final), None


def process_create_note(
    *,
    from_template: bool,
    template_read_error: str | None,
    sections: int,
    required: int,
) -> str | None:
    """The `note` field `kf_create_process`/`forge_create_process` carry, matching
    the former `ProcessCreateReport.as_tool_result()` verbatim.

    Args:
        from_template: Whether the identity shell was cloned.
        template_read_error: The inventory read-back's own error, if any.
        sections: How many sections the template inventory found.
        required: How many Required fields the template inventory found.

    Returns:
        The note text, or `None` when neither condition applies.
    """
    if template_read_error:
        return (
            f"could not read the scaffold back to inventory it: "
            f"{template_read_error} — the three template_* buckets are empty "
            f"because nothing was READ, not because the shell brought nothing in"
        )
    if from_template:
        return (
            f"the process template shell brought in {sections} section(s) "
            f"and {required} Required field(s) you did not ask for. "
            f"forge_set_visibility's `owners` must cover EVERY section listed above or "
            f"that section is editable at no step; a Required field that is never "
            f"editable makes its step permanently unsubmittable. Pass "
            f"from_template=False for a bare shell."
        )
    return None


def flow_create_note(
    *,
    from_template: bool,
    template_read_error: str | None,
    sections: int,
    required: int,
) -> str | None:
    """The `note` field `forge_create_flow` carries, matching the former
    `FlowCreateReport.as_tool_result()` verbatim (a different closing sentence from
    `process_create_note`'s own).

    Args:
        from_template: Whether the identity shell was cloned.
        template_read_error: The inventory read-back's own error, if any.
        sections: How many sections the template inventory found.
        required: How many Required fields the template inventory found.

    Returns:
        The note text, or `None` when neither condition applies.
    """
    if template_read_error:
        return (
            f"could not read the scaffold back to inventory it: "
            f"{template_read_error} — the three template_* buckets are empty "
            f"because nothing was READ, not because the shell brought nothing in"
        )
    if from_template:
        return (
            f"the process template shell brought in {sections} section(s) "
            f"and {required} Required field(s) you did not ask for. "
            f"forge_set_visibility's `owners` must cover EVERY section listed above or "
            f"that section is editable at no step. Pass "
            f"extra={{'from_template': False}} for a bare shell."
        )
    return None


@dataclass(frozen=True)
class FieldApplyResult:
    """The field-apply audit: every requested name lands in exactly one bucket."""

    added: tuple[str, ...]
    skipped: tuple[str, ...]
    verified: tuple[str, ...]
    missing: tuple[str, ...]
    changed_ignored: tuple[str, ...]
    remediation: tuple[str, ...]
    meta_version: str | None
    published: bool


async def apply_specs_to_flow(
    flow_repo: FlowRepository,
    *,
    app_id: str,
    kind: FlowKind,
    flow_id: str,
    draft: FlowDraft,
    specs: list[FieldSpec],
    publish: bool,
) -> FieldApplyResult:
    """Apply field specs to an already-read draft: offline apply, guarded write,
    read-back verify, optional publish.

    Ported from the former `client.apply_fields`, specialised to the one kind
    (`"process"`) this family's callers ever pass -- the old multi-kind
    "no publish route for this kind" refusal is dead code for a fresh
    process and is not reproduced here.

    Args:
        flow_repo: The flow port.
        app_id: The application the flow belongs to.
        kind: The flow kind.
        flow_id: The flow's id.
        draft: The draft already read for this write; its version becomes
            `expect_version`.
        specs: The field specs to reconcile onto the draft.
        publish: Publish the flow once the write is verified.

    Returns:
        The field-apply audit.

    Raises:
        ApplicationError: The offline apply rejected the change set
            (`code="VERIFY_FAILED"`).
    """
    wire = draft.to_wire()
    before = draft.field_names()
    version = draft.version
    requested = [s.name for s in specs]
    ignored = changed_ignored(wire, specs)
    skipped = tuple(n for n in requested if n in before and n not in ignored.names)

    try:
        new_draft = draft.apply_changes(specs)
    except (ValueError, NotImplementedError) as exc:
        raise ApplicationError(
            f"offline apply rejected the change set: {exc}", code="VERIFY_FAILED"
        ) from exc

    added = tuple(n for n in requested if n not in before)
    if added:
        await flow_repo.put_draft(app_id, kind, flow_id, new_draft, version)

    read_back = await flow_repo.get_draft(app_id, kind, flow_id)
    live_names = read_back.field_names()
    verified = tuple(n for n in requested if n in live_names and n not in ignored.names)
    missing = tuple(n for n in requested if n not in live_names)

    published = False
    if publish and not (missing or ignored.entries):
        await flow_repo.publish(app_id, kind, flow_id)
        published = True

    return FieldApplyResult(
        added=added,
        skipped=skipped,
        verified=verified,
        missing=missing,
        changed_ignored=ignored.entries,
        remediation=ignored.remediation,
        meta_version=read_back.version,
        published=published,
    )


# =====================================================================================
# create_process -- ported from `client.create_process`. Shared by kf_create_process
# (real specs) and forge_create_process (always specs=[], steps=("Draft",)).
# =====================================================================================


@dataclass(frozen=True)
class ProcessCreateResult:
    """`FieldApplyResult` plus the scaffold's own template inventory and the
    snapshot version this write was planned against."""

    flow_id: str
    added: tuple[str, ...]
    skipped: tuple[str, ...]
    verified: tuple[str, ...]
    missing: tuple[str, ...]
    changed_ignored: tuple[str, ...]
    remediation: tuple[str, ...]
    meta_version: str | None
    published: bool
    from_template: bool
    template_sections: tuple[str, ...]
    template_required_fields: tuple[str, ...]
    template_steps: tuple[str, ...]
    template_read_error: str | None
    snapshot_version: str | None


# The grant every account-level AppRole member gets (CLAUDE.md > Members first); the
# same pair `use_cases/app/_members.py` sends.
_TEMPLATE_ROLE_GRANT = {"Role": "DataAdmin", "Permission": ["InitiateItems"]}


async def _grant_template_role(
    flow_repo: FlowRepository, app_id: str, flow_id: str, role: tuple[str, str]
) -> None:
    """Make `role` a member of the new flow and prove it by read-back.

    Only this one role is granted: in an existing app, granting every app role
    would widen who can start the process.

    Raises:
        ApplicationError: The role is not on the member read-back
            (`code=VERIFY_FAILED`).
    """
    role_id, role_name = role
    await flow_repo.post_member_batch(
        app_id,
        "process",
        flow_id,
        [
            {
                "_id": role_id,
                "Name": role_name,
                "Kind": "AppRole",
                **_TEMPLATE_ROLE_GRANT,
            }
        ],
    )
    members = await flow_repo.get_members(app_id, "process", flow_id)
    if not any(isinstance(m, dict) and m.get("_id") == role_id for m in members):
        raise ApplicationError(
            f"member grant did not land AppRole {role_id!r} on {flow_id!r}",
            code="VERIFY_FAILED",
        )


async def create_process(
    flow_repo: FlowRepository,
    *,
    app_id: str,
    name: str,
    steps: tuple[str, ...],
    specs: list[FieldSpec],
    publish: bool,
    from_template: bool,
    template_path: str | None,
    template_role: tuple[str, str] | None = None,
) -> ProcessCreateResult:
    """Create a process from zero: shell -> scaffold -> fields -> verify -> publish.

    Ported from the former `client.create_process`. On any failure after the
    flow shell exists, the half-built process is archived+deleted
    (best-effort; a cleanup failure never masks the original error), so a
    failed run leaves no junk behind in the tenant.

    Args:
        flow_repo: The flow port.
        app_id: The application to create the process in.
        name: The process's display name.
        steps: The UserTask step names, used only when `from_template` is
            `False`.
        specs: The field specs to add once the scaffold is in place.
        publish: Publish the process once the fields are verified.
        from_template: Clone the process-template identity shell instead of
            the bare `ensure_process_def` scaffold.
        template_path: A file path to a `shapes/*.json`-shaped capture, or
            `None` for the shipped default.
        template_role: `(role_id, role_name)` of an AppRole in `app_id`. With
            `from_template`, it switches the scaffold from the identity shell to
            the FULL template transplant (shapes/process_template_full.json):
            the role is granted as a flow member first (CLAUDE.md > Members
            first) and becomes the approver of every UserTask step.

    Returns:
        The full create-process audit.

    Raises:
        ApplicationError: The create, scaffold or field-apply step failed.
    """
    await flow_repo.list_flows(app_id, "process")  # write-order invariant: a read first

    flow_id = await flow_repo.create_flow(app_id, "process", name)

    try:
        draft = await flow_repo.get_draft(app_id, "process", flow_id)
        snapshot_version = draft.version

        role = template_role if from_template else None
        if role is not None:
            await _grant_template_role(flow_repo, app_id, flow_id, role)

        try:
            if role is not None:
                scaffolded = draft.transplant_template(app_role=role)
            elif from_template:
                scaffolded = draft.clone_template_shell(template_path)
            else:
                scaffolded = draft.ensure_process_def(steps)
        except ValueError as exc:
            raise ApplicationError(str(exc), code="VERIFY_FAILED") from exc

        await flow_repo.put_draft(app_id, "process", flow_id, scaffolded, draft.version)

        fields_before = await flow_repo.get_draft(app_id, "process", flow_id)
        result = await apply_specs_to_flow(
            flow_repo,
            app_id=app_id,
            kind="process",
            flow_id=flow_id,
            draft=fields_before,
            specs=specs,
            publish=publish,
        )
    except ApplicationError:
        with contextlib.suppress(ApplicationError):
            await flow_repo.delete_flow(app_id, "process", flow_id)
        raise

    inventory, read_error = await _read_scaffold_inventory(flow_repo, app_id, flow_id)

    raise_if_write_failed(
        published=result.published,
        missing=result.missing,
        changed_ignored=result.changed_ignored,
        remediation=result.remediation,
        left_on_tenant=flow_id,
    )

    return ProcessCreateResult(
        flow_id=flow_id,
        added=result.added,
        skipped=result.skipped,
        verified=result.verified,
        missing=result.missing,
        changed_ignored=result.changed_ignored,
        remediation=result.remediation,
        meta_version=result.meta_version,
        published=result.published,
        from_template=from_template,
        template_sections=inventory.sections,
        template_required_fields=inventory.required_fields,
        template_steps=inventory.steps,
        template_read_error=read_error,
        snapshot_version=snapshot_version,
    )


# =====================================================================================
# create_flow_any -- ported from `client.create_flow_any`. Backs forge_create_flow.
# =====================================================================================


@dataclass(frozen=True)
class FlowCreateResult:
    """What `create_flow_any` made. The three `template_*` buckets are populated only
    on the `process` branch, the one that clones the identity shell."""

    kind: str
    flow_id: str
    name: str
    status: str | None
    born_live: bool
    from_template: bool
    template_sections: tuple[str, ...]
    template_required_fields: tuple[str, ...]
    template_steps: tuple[str, ...]
    template_read_error: str | None
    snapshot_version: str | None


async def create_flow_any(
    flow_repo: FlowRepository,
    *,
    app_id: str,
    kind: CreateFlowKind,
    name: str,
    extra: dict[str, Any] | None,
) -> FlowCreateResult:
    """Unified create for `kind` in process|form|list|dataset|case.

    Ported from the former `client.create_flow_any`. A thin dispatcher: every
    branch calls the same port methods the kind-specific tools already use.

    Args:
        flow_repo: The flow port.
        app_id: The application to create the flow in.
        kind: The flow kind to create.
        name: The flow's display name.
        extra: `kind="process"` reads `from_template`/`template_path`/
            `steps`; `kind="case"` requires `item_type` and `prefix`.

    Returns:
        The create audit.

    Raises:
        ApplicationError: The create, scaffold step, or a missing required
            `extra` key for `kind="case"` (`code="VERIFY_FAILED"`).
    """
    extra = extra or {}
    no_template = FlowCreateResult(
        kind=kind,
        flow_id="",
        name=name,
        status=None,
        born_live=False,
        from_template=False,
        template_sections=(),
        template_required_fields=(),
        template_steps=(),
        template_read_error=None,
        snapshot_version=None,
    )

    if kind == "form":
        await flow_repo.list_flows(app_id, "form")
        flow_id = await flow_repo.create_flow(app_id, "form", name)
        return _replace_id(no_template, flow_id=flow_id, status="Draft")

    if kind == "process":
        await flow_repo.list_flows(app_id, "process")
        flow_id = await flow_repo.create_flow(app_id, "process", name)
        try:
            draft = await flow_repo.get_draft(app_id, "process", flow_id)
            snapshot_version = draft.version
            try:
                if extra.get("from_template", True):
                    scaffolded = draft.clone_template_shell(extra.get("template_path"))
                else:
                    scaffolded = draft.ensure_process_def(
                        tuple(extra.get("steps") or ("Review",))
                    )
            except ValueError as exc:
                raise ApplicationError(str(exc), code="VERIFY_FAILED") from exc
            await flow_repo.put_draft(
                app_id, "process", flow_id, scaffolded, draft.version
            )
        except ApplicationError:
            with contextlib.suppress(ApplicationError):
                await flow_repo.delete_flow(app_id, "process", flow_id)
            raise
        inventory, read_error = await _read_scaffold_inventory(
            flow_repo, app_id, flow_id
        )
        return FlowCreateResult(
            kind="process",
            flow_id=flow_id,
            name=name,
            status="Draft",
            born_live=False,
            from_template=bool(extra.get("from_template", True)),
            template_sections=inventory.sections,
            template_required_fields=inventory.required_fields,
            template_steps=inventory.steps,
            template_read_error=read_error,
            snapshot_version=snapshot_version,
        )

    if kind == "list":
        await flow_repo.list_lists(app_id)
        created = await flow_repo.create_list(app_id, name)
        flow_id = _require_created_id(kind, created)
        return _replace_id(
            no_template, flow_id=flow_id, status=created.get("Status"), born_live=True
        )

    if kind == "dataset":
        await flow_repo.list_flows(app_id, "dataset")
        created = await flow_repo.create_dataset(app_id, name)
        flow_id = _require_created_id(kind, created)
        return _replace_id(
            no_template, flow_id=flow_id, status=created.get("Status"), born_live=True
        )

    if kind == "case":
        item_type = extra.get("item_type")
        prefix = extra.get("prefix")
        if not item_type or not prefix:
            raise ApplicationError(
                "create_flow_any(kind='case') requires extra={'item_type': "
                "'Board'|'Case', 'prefix': <2-4 char string>} — both are mandatory "
                "on the write API (400 MissingRequiredFieldError without them)",
                code="VERIFY_FAILED",
            )
        await flow_repo.list_flows(app_id, "case")
        created = await flow_repo.create_case(app_id, name, item_type, prefix)
        flow_id = _require_created_id(kind, created)
        return _replace_id(
            no_template, flow_id=flow_id, status=created.get("Status"), born_live=True
        )

    raise ApplicationError(
        f"create_flow_any: unknown kind {kind!r} — valid: process, form, list, "
        f"dataset, case",
        code="VERIFY_FAILED",
    )


def _require_created_id(kind: str, created: dict[str, Any]) -> str:
    """The born-live create response's own `_id` -- lesson 7: a response that
    carried no usable id is a failed write, never a success with an empty
    `flow_id` (matching the former `FlowCreateReport.as_tool_result()`'s
    `"isError": not self.flow_id`).

    Args:
        kind: The flow kind that was requested (named in the message).
        created: The create endpoint's own parsed response body.

    Returns:
        The created record's `_id`.

    Raises:
        ApplicationError: `created` carries no non-empty `_id`
            (`code="VERIFY_FAILED"`).
    """
    flow_id = created.get("_id", "")
    if not flow_id:
        raise_if_write_failed(
            published="n/a (a born-live kind has no publish step)",
            no_usable_id=(
                f"create_flow_any(kind={kind!r}): the create response carried "
                f"no usable id: {created!r}",
            ),
        )
        raise AssertionError("unreachable")  # pragma: no cover
    return flow_id


def _replace_id(
    base: FlowCreateResult, *, flow_id: str, status: str | None, born_live: bool = False
) -> FlowCreateResult:
    """`base` with `flow_id`/`status`/`born_live` swapped in -- a small helper so
    each born-live branch above states only what makes it different."""
    return FlowCreateResult(
        kind=base.kind,
        flow_id=flow_id,
        name=base.name,
        status=status,
        born_live=born_live,
        from_template=base.from_template,
        template_sections=base.template_sections,
        template_required_fields=base.template_required_fields,
        template_steps=base.template_steps,
        template_read_error=base.template_read_error,
        snapshot_version=base.snapshot_version,
    )


# =====================================================================================
# apply_word_list -- ported from `client.apply_word_list`. Backs forge_create_list.
# =====================================================================================


@dataclass(frozen=True)
class ListApplyResult:
    """Output-invariant audit for `forge_create_list`: every requested item value
    lands in exactly one bucket after the read-back."""

    list_id: str
    name: str
    created: bool
    items: tuple[str, ...]
    verified_items: tuple[str, ...]
    missing_items: tuple[str, ...]


async def apply_word_list(
    flow_repo: FlowRepository, *, app_id: str, name: str, items: list[str]
) -> ListApplyResult:
    """Create-or-reuse a word list by NAME, set its items, read back every value.

    Args:
        flow_repo: The flow port.
        app_id: The application the word list belongs to.
        name: The word list's display name.
        items: The complete new set of legal values.

    Returns:
        The list-apply audit.

    Raises:
        ApplicationError: The list could not be resolved to an id
            (`code="VERIFY_FAILED"`).
    """
    inventory = await flow_repo.list_lists(app_id)
    rows = (
        inventory.get("Data", inventory) if isinstance(inventory, dict) else inventory
    )
    existing = {r.get("Name"): r.get("_id") for r in rows if isinstance(r, dict)}

    created = name not in existing
    if created:
        made = await flow_repo.create_list(app_id, name)
        list_id = made.get("_id", "")
    else:
        list_id = existing[name]

    if not list_id:
        raise ApplicationError(
            f"list {name!r}: no _id resolvable from create/inventory",
            code="VERIFY_FAILED",
        )

    await flow_repo.set_list_items(list_id, items)

    live = await flow_repo.get_list_items(app_id, list_id)
    live_set = set(live)
    missing_items = tuple(v for v in items if v not in live_set)

    raise_if_write_failed(
        published="n/a (a word list is born live, no publish step)",
        missing_items=missing_items,
        left_on_tenant=list_id,
    )

    return ListApplyResult(
        list_id=list_id,
        name=name,
        created=created,
        items=tuple(items),
        verified_items=tuple(v for v in items if v in live_set),
        missing_items=missing_items,
    )
