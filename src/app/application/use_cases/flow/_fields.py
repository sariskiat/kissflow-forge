"""app.application.use_cases.flow._fields — pure helpers shared by this group's six
field use cases (`kf_apply_field_change`, `forge_apply_fields`, `forge_apply_layout`,
`forge_set_required`, `forge_rename_fields`, `forge_delete_fields`).

Ported from `app.infrastructure.kissflow.client` (Stage D group 1, flow/fields).
Every function here takes a raw wire-format node-graph dict (`Draft`), never a
`FlowDraft` entity's own `.nodes` reached from outside the domain — a use case gets
that dict from the entity's own `to_wire()` (CLAUDE.md's own review lesson: never read
an entity's `.nodes` from outside the domain).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from app.application.exceptions import REFUSED, VERIFY_FAILED, ApplicationError
from app.application.models.requests.flow._field_spec_in import FieldSpecIn
from app.domain.value_objects.field_spec import FieldSpec
from app.domain.value_objects.field_type import FieldType

Draft = dict[str, Any]

NO_APP_SELECTED = (
    "no app selected — pass app_id (see forge_list_apps for valid ids), or set "
    "the KF_APP env var as a single-app default"
)


def require_app_id(app_id: str) -> None:
    """Refuse an empty resolved `app_id` -- the tool resolves it, this checks it.

    Args:
        app_id: The tool-resolved app id (see `brief_stage_d_common.md`, "The
            app id"): the per-call argument, else `settings.kf_app`, else `""`.

    Raises:
        ApplicationError: `app_id` is empty, `code=REFUSED`.
    """
    if not app_id:
        raise ApplicationError(NO_APP_SELECTED, code=REFUSED)


def raise_if_write_failed(
    *,
    published: bool | str,
    remediation: Sequence[str] = (),
    collateral: Sequence[str] = (),
    left_on_tenant: str | None = None,
    **buckets: Sequence[Any],
) -> None:
    """Raise when a write did not fully land (`brief_stage_d_common.md`, rule 7): a
    caller must never read a failed write as a success.

    Every write use case in the flow family (the field, structure and
    workflow use cases, and every lifecycle use case that writes,
    `use_cases/flow/_lifecycle.py`) calls this once, after it has computed
    its own output-invariant buckets and attempted (or skipped) its publish,
    and before it builds its response. A non-empty bucket here is exactly
    what used to set the old report's `isError: true` -- the difference is
    this raises instead of returning it.

    Args:
        published: Whether this write went on to publish. A short statement
            (for example "n/a (a word list is born live, no publish step)")
            for a kind that has no publish step at all.
        remediation: Tool names the caller can run next, when any. Folded
            into the message so it is not lost now that the response never
            returns on this path.
        collateral: Human-readable lines describing side effects the write
            already caused (a deleted Permission, a relocated SequenceNumber
            stamp, a field that moved section), when any. Never itself a
            reason to raise -- collateral is documented, intended fallout,
            not a failure bucket -- but folded into the message so it is not
            lost on the one path where this call never reaches its own
            response DTO.
        left_on_tenant: The id of the record a CREATE already wrote to the
            tenant before this failure was discovered, when the caller has
            no other way to learn it -- a raise never reaches the response
            DTO that would otherwise have carried the id. CLAUDE.md's own
            rule: a failed create must name what it left on the tenant.
        **buckets: Each output-invariant bucket that means failure when
            non-empty (for example `missing=(...)`, `surviving=(...)`),
            keyed by its own response field name.

    Raises:
        ApplicationError: At least one bucket in `buckets` is non-empty,
            `code=VERIFY_FAILED`. The message names every non-empty bucket
            with its items, whether anything published, `left_on_tenant`,
            `collateral` and `remediation` when given.
    """
    failing = {name: list(items) for name, items in buckets.items() if items}
    if not failing:
        return
    named = "; ".join(f"{name}={items}" for name, items in failing.items())
    ident = f"; left_on_tenant={left_on_tenant!r}" if left_on_tenant else ""
    coll = f"; collateral={list(collateral)}" if collateral else ""
    tail = f"; remediation={list(remediation)}" if remediation else ""
    raise ApplicationError(
        f"write did not fully land ({named}){ident}{coll}; published={published}{tail}",
        code=VERIFY_FAILED,
    )


def field_spec_from(spec: FieldSpecIn) -> FieldSpec:
    """Convert one validated `FieldSpecIn` into the domain `FieldSpec`
    `FlowDraft.apply_changes` wants.

    Mirrors the old `app.application.tools._to_spec`: `default_value` folds
    into `options["DefaultValue"]`, the same wire key the offline builder
    already writes for a Number default and the platform's own relative-date
    keyword ("Today") on a Date field.

    Args:
        spec: One validated requested field.

    Returns:
        The equivalent domain `FieldSpec`.
    """
    options = dict(spec.options or {})
    if spec.default_value is not None:
        options["DefaultValue"] = spec.default_value
    return FieldSpec(
        name=spec.name,
        type=spec.type,
        required=spec.required,
        referred_list=spec.referred_list,
        field_id=spec.field_id,
        options=options or None,
    )


# =====================================================================================
# The F2 fact base (kf_apply_field_change, forge_apply_fields): which requested specs
# the create-only apply path silently drops, because they match an existing name but
# ask for something different.
# =====================================================================================

#: `options` keys the offline builder deliberately moves OFF the Field node onto a
#: sibling in the field's own configuration cluster (`LHSModel` -> the User field's
#: `QueryDefinition`). Diffing them against the Field node would read `None` on a
#: field written exactly as asked.
_RELOCATED_OPTION_KEYS = frozenset({"LHSModel"})


@dataclass(frozen=True)
class IgnoredChanges:
    """Every requested spec that matched a live field by name but asked for
    something different from what is actually there (F2)."""

    entries: tuple[str, ...]
    names: frozenset[str]
    remediation: tuple[str, ...]


def _field_nodes_by_name(draft: Draft) -> dict[str, list[dict[str, Any]]]:
    """Field NAME -> every live Field node carrying it (not unique: a form field and
    a table child can share one)."""
    out: dict[str, list[dict[str, Any]]] = {}
    for node in draft.values():
        if isinstance(node, dict) and node.get("Kind") == "Field":
            out.setdefault(node.get("Name", ""), []).append(node)
    return out


def _spec_diff(spec: FieldSpec, node: dict[str, Any]) -> list[tuple[str, Any, Any]]:
    """(attribute, requested, live) for every way `spec` disagrees with one live
    Field node. Compares only what the caller actually stated."""
    diffs: list[tuple[str, Any, Any]] = []
    want_type = FieldType(spec.type).value
    if node.get("Type") != want_type:
        diffs.append(("Type", want_type, node.get("Type")))
    if bool(node.get("Required", False)) != bool(spec.required):
        diffs.append(
            ("Required", bool(spec.required), bool(node.get("Required", False)))
        )
    if (
        spec.referred_list is not None
        and node.get("ReferredList") != spec.referred_list
    ):
        diffs.append(("ReferredList", spec.referred_list, node.get("ReferredList")))
    for key, value in (spec.options or {}).items():
        if key in _RELOCATED_OPTION_KEYS:
            continue
        if node.get(key) != value:
            diffs.append((key, value, node.get(key)))
    return diffs


def changed_ignored(draft: Draft, specs: list[FieldSpec]) -> IgnoredChanges:
    """The F2 bucket: every requested spec that matched a live field BY NAME but
    asked for something different from what is actually there.

    `FlowDraft.apply_changes` only ever creates -- a spec whose name already
    exists is skipped outright. Requesting a different Type or Required flag
    for an EXISTING name is therefore a silent no-op; naming it here keeps
    that record out of both `skipped` and `verified` at once.

    Args:
        draft: The pre-write draft, as a wire-format dict.
        specs: The requested field specs.

    Returns:
        The `IgnoredChanges` fact base.
    """
    live = _field_nodes_by_name(draft)
    entries: list[str] = []
    names: list[str] = []
    remediation: list[str] = []
    for spec in specs:
        nodes = live.get(spec.name)
        if not nodes:
            continue
        per_node = [_spec_diff(spec, n) for n in nodes]
        if any(not d for d in per_node):
            continue
        attrs = {a for diffs in per_node for a, _w, _l in diffs}
        want = ", ".join(f"{a}={w!r}" for a, w, _l in per_node[0])
        seen = ", ".join(
            " ".join(f"{a}={live_v!r}" for a, _w, live_v in diffs) for diffs in per_node
        )
        entries.append(
            f"{spec.name}: requested {want}, live {seen} — NOT applied "
            "(apply_changes only creates; an existing name is never edited)"
        )
        names.append(spec.name)
        if attrs == {"Required"}:
            remediation.append("forge_set_required")
        else:
            remediation.extend(("forge_delete_fields", "forge_apply_fields"))
    return IgnoredChanges(
        tuple(entries), frozenset(names), tuple(dict.fromkeys(remediation))
    )


# =====================================================================================
# Layout collateral (forge_apply_fields).
# =====================================================================================


def _field_placements(draft: Draft) -> dict[str, tuple[str, int, int, int]]:
    """Field NAME -> (section title, row index, Start, End): where a field actually
    sits on the 6-unit form grid. A name is recorded once, its first placement."""
    name_of_col = {
        n["Column"]: n.get("Name", "")
        for n in draft.values()
        if isinstance(n, dict)
        and n.get("Kind") == "Field"
        and isinstance(n.get("Column"), str)
    }

    def _leaves(
        row_ids: list[str],
        title: str,
        ri: int,
        out: dict[str, tuple[str, int, int, int]],
    ) -> None:
        for rid in row_ids:
            for cid in (draft.get(rid) or {}).get("Row::Column") or []:
                col = draft.get(cid) or {}
                if cid in name_of_col:
                    out.setdefault(
                        name_of_col[cid],
                        (title, ri, int(col.get("Start", 0)), int(col.get("End", 0))),
                    )
                elif col.get("Column::Row"):
                    _leaves(list(col["Column::Row"]), title, ri, out)

    out: dict[str, tuple[str, int, int, int]] = {}
    for sec in draft.values():
        if not (
            isinstance(sec, dict)
            and sec.get("Kind") == "Column"
            and sec.get("Type") == "Section"
        ):
            continue
        title = sec.get("Name", "")
        for ri, rid in enumerate(sec.get("Column::Row") or []):
            _leaves([rid], title, ri, out)
    return out


def layout_collateral(
    before: Draft, after: Draft, exclude: Iterable[str] = ()
) -> tuple[str, ...]:
    """Every field whose grid placement changed across a write, named with both
    coordinates.

    Args:
        before: The pre-write draft, as a wire-format dict.
        after: The post-write (read-back) draft, as a wire-format dict.
        exclude: Names this write ADDED -- a field that did not exist before
            did not move.

    Returns:
        One human-readable sentence per moved (or dropped) field.
    """
    was = _field_placements(before)
    now = _field_placements(after)
    skip = set(exclude)
    out: list[str] = []
    for name in sorted(was):
        if name in skip or was[name] == now.get(name):
            continue
        if name not in now:
            out.append(
                f"{name!r} was laid out in section {was[name][0]!r} and is now "
                "in no section at all — the rebuild dropped it off the form"
            )
            continue
        (ws, wr, wa, wb), (ns, nr, na, nb) = was[name], now[name]
        out.append(
            f"{name!r} moved: {ws!r} row {wr} cols {wa}-{wb} -> {ns!r} row {nr} "
            f"cols {na}-{nb} — regroup_into_sections re-tiles every section at "
            "a uniform width, so any custom grid an earlier forge_apply_layout "
            "wrote is gone"
        )
    return tuple(out)


# =====================================================================================
# forge_apply_layout's own collateral (a field left off a stated section's layout).
# =====================================================================================


def section_field_names(draft: Draft, section_name: str) -> tuple[str, ...]:
    """The field NAMES currently laid out in one section, in row/column order.

    Args:
        draft: The pre-write draft, as a wire-format dict.
        section_name: The section title to look up.

    Returns:
        Every field name in that section, in display order. `()` for an
        unknown section name -- `FlowDraft.apply_exact_layout` owns that
        refusal and states it better.
    """
    name_of_col = {
        n["Column"]: n.get("Name", "")
        for n in draft.values()
        if isinstance(n, dict)
        and n.get("Kind") == "Field"
        and isinstance(n.get("Column"), str)
    }
    sid = next(
        (
            k
            for k, v in draft.items()
            if isinstance(v, dict)
            and v.get("Kind") == "Column"
            and v.get("Type") == "Section"
            and v.get("Name") == section_name
        ),
        None,
    )
    if sid is None:
        return ()
    out: list[str] = []
    seen: set[str] = set()
    for rid in draft[sid].get("Column::Row") or []:
        for cid in (draft.get(rid) or {}).get("Row::Column") or []:
            if cid in name_of_col and cid not in seen:
                seen.add(cid)
                out.append(name_of_col[cid])
    return tuple(out)


# =====================================================================================
# forge_rename_fields / forge_delete_fields.
# =====================================================================================


def live_names(draft: Draft) -> tuple[set[str], set[str]]:
    """(every Field name, every table-host name) in a draft.

    Args:
        draft: The draft to read, as a wire-format dict.

    Returns:
        The two namespaces a delete/rename audit reads back against. Table
        hosts are `Column{Type:"Model"}`, never Fields.
    """
    return (
        {
            v.get("Name", "")
            for v in draft.values()
            if isinstance(v, dict) and v.get("Kind") == "Field"
        },
        {
            v.get("Name", "")
            for v in draft.values()
            if isinstance(v, dict)
            and v.get("Kind") == "Column"
            and v.get("Type") == "Model"
        },
    )


# =====================================================================================
# forge_set_required.
# =====================================================================================


def root_field_nodes(draft: Draft) -> dict[str, dict[str, Any]]:
    """ROOT-model field NAME -> node -- the exact population `FlowDraft.set_required`
    rewrites.

    Args:
        draft: The draft to read, as a wire-format dict.

    Returns:
        Every root-model Field node, keyed by name.
    """
    root = draft.get("Root")
    return {
        v.get("Name", ""): v
        for v in draft.values()
        if isinstance(v, dict) and v.get("Kind") == "Field" and v.get("Model") == root
    }


def _unfillable_required_reason(node: dict[str, Any]) -> str | None:
    if node.get("Field::Expression"):
        return "computed"
    return "SequenceNumber" if node.get("Type") == "SequenceNumber" else None


def unsatisfiable_required_fields(
    root_fields: dict[str, dict[str, Any]], wanted: set[str]
) -> list[str]:
    """Every wanted name that a human can never fill in (computed or
    SequenceNumber) -- refused before any write.

    Args:
        root_fields: `root_field_nodes(draft)`.
        wanted: The requested Required set.

    Returns:
        One `"name (reason)"` entry per unfillable field, sorted by name.
    """
    unsatisfiable: list[str] = []
    for name in sorted(wanted):
        node = root_fields.get(name)
        reason = _unfillable_required_reason(node) if node is not None else None
        if reason is not None:
            unsatisfiable.append(f"{name} ({reason})")
    return unsatisfiable


def cleared_required_fields(
    root_fields: dict[str, dict[str, Any]], wanted: set[str]
) -> tuple[str, ...]:
    """Fields that were Required before this call and are not in `wanted` -- the SET
    semantics' own collateral.

    Args:
        root_fields: `root_field_nodes(draft)`, read BEFORE the write.
        wanted: The requested Required set.

    Returns:
        Every field name that loses its Required flag, sorted.
    """
    cleared = [
        name
        for name, node in root_fields.items()
        if node.get("Required") and name not in wanted
    ]
    return tuple(sorted(cleared))


def _is_required_verified(node: dict[str, Any] | None, wanted: bool) -> bool:
    return node is not None and bool(node.get("Required", False)) is wanted


def audit_required_readback(
    live: dict[str, dict[str, Any]], wanted: set[str]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(verified, missing) over the UNION of the read-back's own root fields and
    every requested name.

    The union matters: a requested name that was on the form before the
    write and is absent from the read-back must still land in `missing`,
    never silently in no bucket at all.

    Args:
        live: `root_field_nodes(read_back_draft)`.
        wanted: The requested Required set.

    Returns:
        `(verified, missing)`, each sorted by name.
    """
    verified: list[str] = []
    missing: list[str] = []
    for name in sorted(set(live) | wanted):
        target = (
            verified
            if _is_required_verified(live.get(name), name in wanted)
            else missing
        )
        target.append(name)
    return tuple(verified), tuple(missing)
