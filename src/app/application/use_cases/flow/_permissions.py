"""Private helpers for the two step-permission use cases (`ForgeSetVisibility`,
`KfSetStepVisibility`).

Ported from `app.infrastructure.kissflow.client`'s `_permission_nodes` /
`_permission_pairs` / `_malformed_permissions` / `_PairNames` / `_pair_names` /
`_uncovered_sections` / `_permission_rollup` / `_StepPermissionDeltas` /
`_StepPermissionAudit` / `_format_pairs` / `_format_named_pairs` /
`_step_permission_collateral` / `_step_permission_deltas` /
`_audit_step_permissions` / `_assemble_step_permission_report` /
`apply_step_permissions` (refactor spec, Stage D group `d3_flow_workflow`).

The old functions read a raw wire `dict`; these do too, on purpose (lesson from
the shared brief: never read a `FlowDraft`'s `.nodes` from outside the domain --
every wire dict a function here touches comes from an explicit `.to_wire()`
call at the use case, never from reaching into the entity). `write_step_permissions`
is the one orchestration entrypoint both use cases call, after they have
already taken their own snapshot and computed the offline `Matrix`.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from app.application.exceptions import VERIFY_FAILED, ApplicationError
from app.application.use_cases.flow._fields import raise_if_write_failed
from app.application.use_cases.flow._write_order import WriteOrder
from app.domain.entities.flow_draft import FlowDraft, Matrix, SectionLayout
from app.domain.value_objects.field_type import Visibility

_META_VERSION = "_meta_version"


def _kind(wire: dict[str, Any], kind: str) -> dict[str, dict[str, Any]]:
    """Every node of one `Kind` in a wire graph, keyed by node id. Pure, generic --
    no business rule of its own, so it stays local here rather than reaching into
    the domain's own private `_flow_ops._kind`."""
    return {
        k: v for k, v in wire.items() if isinstance(v, dict) and v.get("Kind") == kind
    }


def _permission_nodes(wire: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """(node id, node) for every Permission node in a graph, well-formed or not."""
    return [
        (k, v)
        for k, v in wire.items()
        if isinstance(v, dict) and v.get("Kind") == "Permission"
    ]


def _permission_pairs(wire: dict[str, Any]) -> dict[tuple[str, str], str]:
    """(column id, activity id) -> visibility, for every WELL-FORMED Permission node.

    A Permission node missing `Column` or `Activity` is not a pair and is
    SKIPPED, never a `KeyError` -- this runs inside a write's damage count,
    before any write, so an unguarded subscript here must never escape as a
    bare traceback. `_malformed_permissions` counts the same nodes by id, so a
    Permission node still lands in exactly one bucket.
    """
    return {
        (n["Column"], n["Activity"]): n.get("Permission", "")
        for _k, n in _permission_nodes(wire)
        if isinstance(n.get("Column"), str) and isinstance(n.get("Activity"), str)
    }


def _malformed_permissions(wire: dict[str, Any]) -> tuple[str, ...]:
    """Node ids of every Permission `_permission_pairs` could not read as a (column,
    step) pair -- no `Column`, no `Activity`, or one of them not a string."""
    return tuple(
        sorted(
            k
            for k, n in _permission_nodes(wire)
            if not (
                isinstance(n.get("Column"), str) and isinstance(n.get("Activity"), str)
            )
        )
    )


@dataclass(frozen=True)
class _PairNames:
    """Id -> human NAME resolution for one draft's (column, activity) permission
    pairs."""

    field_of_column: dict[str, str]
    section_of_column: dict[str, str]
    step_of_activity: dict[str, str]

    def column(self, cid: str) -> str:
        return self.field_of_column.get(cid, cid)

    def section(self, cid: str) -> str:
        return self.section_of_column.get(cid, "(no section)")

    def step(self, aid: str) -> str:
        return self.step_of_activity.get(aid, aid)

    def pair(self, cid: str, aid: str) -> str:
        """`Intake / Ticket No @ Ticket arrives` -- the section, the field, the
        step. Falls back to the raw id for anything that does not resolve."""
        return f"{self.section(cid)} / {self.column(cid)} @ {self.step(aid)}"


def _pair_names(wire: dict[str, Any]) -> _PairNames:
    """Resolve every column and activity id in `wire` to its human name. Pure."""
    layout = FlowDraft.from_wire(wire).section_layout()
    cols = _kind(wire, "Column")
    field_of_column: dict[str, str] = {}
    for f in _kind(wire, "Field").values():
        cid, fname = f.get("Column"), f.get("Name")
        if isinstance(cid, str) and isinstance(fname, str):
            field_of_column[cid] = fname
    # a SECTION column is itself a legal Permission target and carries its own
    # Name -- a field column carries None, hence the walk above.
    for cid, col in cols.items():
        if cid not in field_of_column and isinstance(col.get("Name"), str):
            field_of_column[cid] = col["Name"]
    section_of_column = {
        cid: s for cid in cols if (s := layout.owner_section(cid)) is not None
    }
    step_of_activity = {
        aid: n
        for aid, a in _kind(wire, "Activity").items()
        if isinstance(n := a.get("Name"), str)
    }
    return _PairNames(field_of_column, section_of_column, step_of_activity)


def _uncovered_sections(
    wire: dict[str, Any], matrix: Matrix, field_matrix: Matrix | None
) -> tuple[str, ...]:
    """Every section this matrix leaves editable at NO step.

    Deliberately never folded into an error -- a caller may leave a section
    alone on purpose. Two exclusions: a section covered by a field-level
    override, and a section governing no permissionable column at all.
    """
    layout: SectionLayout = FlowDraft.from_wire(wire).section_layout()
    editable_cols: set[str] = set()
    for fname, row in (field_matrix or {}).items():
        for f in _kind(wire, "Field").values():
            if (
                f.get("Name") == fname
                and isinstance(f.get("Column"), str)
                and any(Visibility(v) is Visibility.EDITABLE for v in row.values())
            ):
                editable_cols.add(f["Column"])
    covered_by_field = {
        s for cid in editable_cols if (s := layout.owner_section(cid)) is not None
    }

    out: list[str] = []
    for name, row in matrix.items():
        if any(Visibility(v) is Visibility.EDITABLE for v in row.values()):
            continue
        if name in covered_by_field:
            continue
        sid = layout.section_id_of_name.get(name)
        governed = [
            c
            for c in layout.members.get(sid or "", ())
            if c not in layout.no_permission_columns
            and c not in layout.table_host_columns
            and c not in layout.table_child_columns
        ]
        if not governed:
            continue
        out.append(name)
    return tuple(sorted(out))


def _format_pairs(pairs: Iterable[tuple[str, str]]) -> tuple[str, ...]:
    return tuple(sorted(f"{c}@{a}" for c, a in pairs))


def _format_named_pairs(
    names: _PairNames, pairs: Iterable[tuple[str, str]]
) -> tuple[str, ...]:
    return tuple(sorted(names.pair(c, a) for c, a in pairs))


def _permission_rollup(
    pairs: Iterable[tuple[str, str]],
    names: _PairNames,
    verified: set[tuple[str, str]],
    missing: set[tuple[str, str]],
    by: str,
) -> tuple[str, ...]:
    """One summary line per section (`by="section"`) or per step (`by="step"`)."""
    buckets: dict[str, list[int]] = {}
    for cid, aid in pairs:
        key = names.section(cid) if by == "section" else names.step(aid)
        row = buckets.setdefault(key, [0, 0, 0])
        row[0] += 1
        row[1] += (cid, aid) in verified
        row[2] += (cid, aid) in missing
    return tuple(
        f"{key}: {n} pair(s) written, {ok} verified, {bad} missing"
        for key, (n, ok, bad) in sorted(buckets.items())
    )


@dataclass(frozen=True)
class _StepPermissionDeltas:
    added: tuple[str, ...]
    skipped: tuple[str, ...]
    added_named: tuple[str, ...]
    skipped_named: tuple[str, ...]


@dataclass(frozen=True)
class _StepPermissionAudit:
    verified_pairs: set[tuple[str, str]]
    missing_pairs: set[tuple[str, str]]
    verified: tuple[str, ...]
    missing: tuple[str, ...]
    missing_named: tuple[str, ...]
    verified_named: tuple[str, ...]


def _step_permission_deltas(
    before: dict[tuple[str, str], str],
    wanted: dict[tuple[str, str], str],
    names: _PairNames,
) -> _StepPermissionDeltas:
    added_pairs: list[tuple[str, str]] = []
    skipped_pairs: list[tuple[str, str]] = []
    for pair, v in wanted.items():
        if before.get(pair) == v:
            skipped_pairs.append(pair)
        else:
            added_pairs.append(pair)
    return _StepPermissionDeltas(
        added=_format_pairs(added_pairs),
        skipped=_format_pairs(skipped_pairs),
        added_named=_format_named_pairs(names, added_pairs),
        skipped_named=_format_named_pairs(names, skipped_pairs),
    )


def _audit_step_permissions(
    wanted: dict[tuple[str, str], str],
    live: dict[tuple[str, str], str],
    names: _PairNames,
) -> _StepPermissionAudit:
    verified_pairs: set[tuple[str, str]] = set()
    missing_pairs: set[tuple[str, str]] = set()
    for pair, v in wanted.items():
        if live.get(pair) == v:
            verified_pairs.add(pair)
        else:
            missing_pairs.add(pair)
    return _StepPermissionAudit(
        verified_pairs=verified_pairs,
        missing_pairs=missing_pairs,
        verified=_format_pairs(verified_pairs),
        missing=_format_pairs(missing_pairs),
        missing_named=_format_named_pairs(names, missing_pairs),
        verified_named=_format_named_pairs(names, verified_pairs),
    )


def _malformed_permission_collateral(wire: dict[str, Any]) -> tuple[str, ...]:
    return tuple(
        f"deleted malformed Permission {nid} (no readable Column/Activity pair) — "
        "it was never in the before-matrix and no rebuilt pair replaces it"
        for nid in _malformed_permissions(wire)
    )


def _step_permission_collateral(
    wire: dict[str, Any],
    before: dict[tuple[str, str], str],
    wanted: dict[tuple[str, str], str],
    names: _PairNames,
) -> tuple[str, ...]:
    dropped: list[str] = []
    for (c, a), v in before.items():
        if (c, a) not in wanted:
            dropped.append(
                f"deleted Permission {c}@{a} ({names.pair(c, a)}) (was {v!r}) — the "
                "rebuild covers this pair no longer"
            )
    return tuple(sorted(dropped)) + _malformed_permission_collateral(wire)


def _assemble_step_permission_report(
    *,
    flow_id: str,
    draft_wire: dict[str, Any],
    read_back_wire: dict[str, Any],
    matrix: Matrix,
    field_matrix: Matrix | None,
    names: _PairNames,
    wanted: dict[tuple[str, str], str],
    audit: _StepPermissionAudit,
    published: bool,
    include_pairs: bool,
) -> dict[str, Any]:
    """The `StepPermissionReport.as_tool_result()`-equivalent dict, minus `isError`
    (G6/G10: a real failure now raises; this dict is always a normal, successful
    return)."""
    before = _permission_pairs(draft_wire)
    deltas = _step_permission_deltas(before, wanted, names)
    collateral = _step_permission_collateral(draft_wire, before, wanted, names)
    remediation = ("forge_set_visibility",) if collateral else ()
    summarised = (
        len(deltas.added) + len(deltas.skipped) + len(audit.verified) + len(collateral)
    )

    out: dict[str, Any] = {
        "flow_id": flow_id,
        "pair_counts": {
            "added": len(deltas.added),
            "skipped": len(deltas.skipped),
            "verified": len(audit.verified),
            "missing": len(audit.missing),
            "collateral": len(collateral),
        },
        "missing": list(audit.missing_named),
        "by_section": list(
            _permission_rollup(
                wanted, names, audit.verified_pairs, audit.missing_pairs, "section"
            )
        ),
        "by_step": list(
            _permission_rollup(
                wanted, names, audit.verified_pairs, audit.missing_pairs, "step"
            )
        ),
        "uncovered_sections": list(
            _uncovered_sections(draft_wire, matrix, field_matrix)
        ),
        "remediation": list(remediation),
        "summarised": 0 if include_pairs else summarised,
        "meta_version": read_back_wire.get(_META_VERSION),
        "published": published,
    }
    if include_pairs:
        out["pairs"] = {
            "added": list(deltas.added_named),
            "skipped": list(deltas.skipped_named),
            "verified": list(audit.verified_named),
            "missing": list(audit.missing_named),
        }
        out["collateral"] = list(collateral)
        out["note"] = (
            f"{summarised} pair entries listed in full (include_pairs=True). "
            f"`missing` is always listed in full either way."
        )
    else:
        out["note"] = (
            f"{summarised} pair entries summarised into `pair_counts` / `by_section` / "
            f"`by_step` — nothing was dropped; re-run with include_pairs=true for the "
            f"full (column, activity) list. `missing` is ALWAYS listed in full and is "
            f"empty here."
            if not audit.missing
            else f"{summarised} written/skipped/verified/collateral entries summarised "
            f"into `pair_counts` / `by_section` / `by_step`; the {len(audit.missing)} "
            f"FAILED pairs are listed in full above. Re-run with include_pairs=true "
            f"for everything."
        )
    return out


async def write_step_permissions(
    order: WriteOrder[FlowDraft],
    draft: FlowDraft,
    *,
    flow_id: str,
    matrix: Matrix,
    field_matrix: Matrix | None,
    publish: bool,
    include_pairs: bool,
) -> dict[str, Any]:
    """Rebuild a flow's per-step Permission matrix, given an already-taken snapshot.

    `order.snapshot()` must already have run (its return value is `draft`).
    Offline rebuild -> guarded write -> read-back audit -> optional publish.

    Args:
        order: A `WriteOrder` already past its own `snapshot()` call.
        draft: The snapshot `order.snapshot()` returned.
        flow_id: The flow's id (for the report only).
        matrix: Section (or field) name -> activity id -> `Visibility`.
        field_matrix: Per-field override rows layered on top of `matrix`.
        publish: Publish the flow once the matrix is written and clean.
        include_pairs: Return every (column, activity) pair in full.

    Returns:
        The report dict (see `_assemble_step_permission_report`), without
        `snapshot_version` -- the caller adds that from `order.snapshot_version`.
        Only returned when every wanted pair verified on read-back (the
        shared brief's rule 7); `pair_counts["missing"]` is always `0` and
        `missing` is always `[]` in a returned dict.

    Raises:
        ApplicationError: `matrix`/`field_matrix` was rejected offline, or
            one or more wanted (column, activity) pairs did not verify on
            read-back (`code=VERIFY_FAILED`).
    """
    draft_wire = draft.to_wire()
    try:
        new_entity = draft.set_step_permissions(matrix, field_matrix)
    except ValueError as exc:
        raise ApplicationError(
            f"offline apply rejected the matrix: {exc}", code=VERIFY_FAILED
        ) from exc
    wanted = _permission_pairs(new_entity.to_wire())

    await order.apply(new_entity)
    read_back = await order.read_back()
    read_back_wire = read_back.to_wire()

    names = _pair_names(draft_wire)
    live = _permission_pairs(read_back_wire)
    audit = _audit_step_permissions(wanted, live, names)

    published = False
    if publish and not audit.missing_pairs:
        await order.publish()
        published = True

    before = _permission_pairs(draft_wire)
    collateral = _step_permission_collateral(draft_wire, before, wanted, names)
    remediation = ("forge_set_visibility",) if collateral else ()
    raise_if_write_failed(
        published=published,
        missing=audit.missing_named,
        collateral=collateral,
        remediation=remediation,
    )

    return _assemble_step_permission_report(
        flow_id=flow_id,
        draft_wire=draft_wire,
        read_back_wire=read_back_wire,
        matrix=matrix,
        field_matrix=field_matrix,
        names=names,
        wanted=wanted,
        audit=audit,
        published=published,
        include_pairs=include_pairs,
    )
