"""app.application.compare — does the BUILT app match what the INPUT asked for? (#16)

The comparator's axis is spec -> built app, never built app -> reference app: a new diagram has
no oracle to diff against, so fidelity has to be judged against the input itself (map #8, check
2). `forge_doctor` stays the referential-integrity check; THIS module is the fidelity check —
doctor returned `ok` on a build that had wrong field types, a missing event, spurious
Permissions and a misordered table host, because none of those break references (#16 names each
miss; every check below caught a real bug on eval case 1).

Pure and offline: `compare_built_to_spec(draft, spec)` takes the LIVE draft (read back by the
caller — THE RULE) and the approved `AppSpec`. Every finding lands in exactly one bucket:
a `mismatches` sentence, a per-rule `checked` count, or a DECLARED `ignored` exclusion
(PublishedBy, the platform's own User node) — known-benign is stated, never silently skipped.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.application.intake.schema import AppSpec, trigger_for
from app.domain.types import FieldType

Draft = dict[str, Any]

# Node kinds/names the platform itself writes as publish side-effects — declared benign (#16:
# "known-benign exclusions declared, never silently ignored").
_BENIGN_KINDS = ("User",)


@dataclass(frozen=True)
class CompareReport:
    """Every unit examined lands in a bucket: a `mismatches` sentence, a `checked` count, or a
    named `ignored` exclusion."""

    mismatches: tuple[str, ...]
    checked: dict[str, int]
    ignored: tuple[str, ...]

    def ok(self) -> bool:
        return not self.mismatches

    def as_tool_result(self) -> dict[str, Any]:
        return {
            "ok": self.ok(),
            "mismatches": list(self.mismatches),
            "checked": self.checked,
            "ignored": list(self.ignored),
            "isError": not self.ok(),
        }


def _kind(draft: Draft, kind: str) -> dict[str, dict[str, Any]]:
    return {k: v for k, v in draft.items() if isinstance(v, dict) and v.get("Kind") == kind}


def _has_kind(draft: Draft, kind: str) -> bool:
    return any(isinstance(v, dict) and v.get("Kind") == kind for v in draft.values())


def _collect_ignored(draft: Draft) -> list[str]:
    ignored: list[str] = []
    for k in _BENIGN_KINDS:
        if _has_kind(draft, k):
            ignored.append(f"kind {k} (platform publish side-effect)")
    return ignored


def _build_wanted_fields(spec: AppSpec) -> dict[str, tuple[str, str | None]]:
    wanted: dict[str, tuple[str, str | None]] = {}
    for f in spec.data_model.fields:
        wanted[f.name] = (f.type.value, getattr(f, "list_name", None))
    for t in spec.data_model.tables:
        for c in t.columns:
            wanted[c.name] = (c.type.value, None)
    return wanted


def _is_unvalidated_select(ftype: str, list_name: str | None, node: dict[str, Any]) -> bool:
    if ftype != FieldType.SELECT.value or not list_name:
        return False
    return not bool(node.get("ReferredList"))


def _check_field_node(
    name: str,
    ftype: str,
    list_name: str | None,
    node: dict[str, Any] | None,
) -> list[str]:
    if node is None:
        return [f"field {name!r} ({ftype}) asked for by the input is absent"]
    issues: list[str] = []
    if node.get("Type") != ftype:
        issues.append(f"field {name!r} built as {node.get('Type')!r}, input asked {ftype!r}")
    if _is_unvalidated_select(ftype, list_name, node):
        issues.append(
            f"Select {name!r} should reference list {list_name!r} but carries "
            f"no ReferredList — its routing literals are unvalidated free text"
        )
    return issues


def _check_sequence(
    spec: AppSpec,
    fields: dict[str, dict[str, Any]],
    problems: list[str],
    checked: dict[str, int],
) -> None:
    if spec.data_model.sequence is not None:
        checked["sequence"] = 1
        if not any(v.get("Type") == "SequenceNumber" for v in fields.values()):
            problems.append(
                "input asks for an auto-numbered id (sequence) — no SequenceNumber field was built"
            )


def _check_extra_fields(
    fields: dict[str, dict[str, Any]],
    wanted: set[str],
    problems: list[str],
) -> None:
    known_extra = wanted | {""}
    for v in fields.values():
        if v.get("Name") not in known_extra and v.get("Type") != "SequenceNumber":
            problems.append(
                f"field {v.get('Name')!r} ({v.get('Type')}) exists in the build but "
                f"the input never asked for it"
            )


def _check_fields(
    spec: AppSpec,
    fields: dict[str, dict[str, Any]],
    by_name: dict[str, dict[str, Any]],
    problems: list[str],
    checked: dict[str, int],
) -> None:
    wanted = _build_wanted_fields(spec)
    checked["fields"] = len(wanted)
    for name, (ftype, list_name) in wanted.items():
        problems.extend(_check_field_node(name, ftype, list_name, by_name.get(name)))
    _check_sequence(spec, fields, problems, checked)
    _check_extra_fields(fields, set(wanted), problems)


def _first_column_of_row(draft: Draft, row_id: str) -> dict[str, Any]:
    row = draft.get(row_id)
    if not isinstance(row, dict):
        return {}
    cols = row.get("Row::Column")
    if not cols:
        return {}
    col = draft.get(cols[0])
    return col if isinstance(col, dict) else {}


def _extract_row_first_cols(draft: Draft) -> list[dict[str, Any]]:
    root_id = draft.get("Root", "")
    root = draft.get(root_id)
    if not isinstance(root, dict):
        return []
    row_ids = root.get("Model::Row")
    if not row_ids:
        return []
    return [_first_column_of_row(draft, rid) for rid in row_ids]


def _check_sections(
    spec: AppSpec,
    live_sections: set[str],
    problems: list[str],
    checked: dict[str, int],
) -> None:
    checked["sections"] = len(spec.data_model.sections)
    for s in spec.data_model.sections:
        if s.name not in live_sections:
            problems.append(f"section {s.name!r} asked for by the input is absent from the form")


def _check_tables(
    spec: AppSpec,
    hosts: set[str],
    problems: list[str],
    checked: dict[str, int],
) -> None:
    checked["tables"] = len(spec.data_model.tables)
    for t in spec.data_model.tables:
        if t.name not in hosts:
            problems.append(
                f"table {t.name!r} asked for by the input has no host row in root "
                f"Model::Row (built but unregistered, or not built)"
            )


def _is_empty_section(col: dict[str, Any]) -> bool:
    if col.get("Type") != "Section":
        return False
    return not bool(col.get("Column::Row"))


def _next_item(items: list[dict[str, Any]], index: int) -> dict[str, Any]:
    return items[index + 1] if index + 1 < len(items) else {}


def _check_empty_banners(ordered: list[dict[str, Any]], problems: list[str]) -> None:
    for i, col in enumerate(ordered):
        if _is_empty_section(col) and _next_item(ordered, i).get("Type") != "Model":
            problems.append(
                f"empty section {col.get('Name')!r} is not immediately followed by a table "
                f"host — a stranded banner breaks the WHOLE form's render (CLAUDE.md Tables)"
            )


def _collect_names_by_type(items: list[dict[str, Any]], type_name: str) -> set[str]:
    names: set[str] = set()
    for v in items:
        if v.get("Type") == type_name:
            name = v.get("Name")
            if isinstance(name, str):  # a nameless node cannot be compared by name
                names.add(name)
    return names


def _check_layout(
    draft: Draft,
    spec: AppSpec,
    problems: list[str],
    checked: dict[str, int],
) -> None:
    ordered = _extract_row_first_cols(draft)
    live_sections = _collect_names_by_type(ordered, "Section")
    hosts = _collect_names_by_type(ordered, "Model")
    _check_sections(spec, live_sections, problems, checked)
    _check_tables(spec, hosts, problems, checked)
    _check_empty_banners(ordered, problems)


def _col_takes_no_perms(col: dict[str, Any], seq_fields: set[str]) -> bool:
    if col.get("IsHidden") is True:
        return True
    col_fields = col.get("Column::Field") or []
    return any(f in seq_fields for f in col_fields)


def _find_sequence_field_ids(fields: dict[str, dict[str, Any]]) -> set[str]:
    ids: set[str] = set()
    for k, v in fields.items():
        if v.get("Type") == "SequenceNumber":
            ids.add(k)
    return ids


def _find_no_perm_cols(draft: Draft, fields: dict[str, dict[str, Any]]) -> set[str]:
    seq_fields = _find_sequence_field_ids(fields)
    cols: set[str] = set()
    for k, v in _kind(draft, "Column").items():
        if _col_takes_no_perms(v, seq_fields):
            cols.add(k)
    return cols


def _check_permissions(
    draft: Draft,
    fields: dict[str, dict[str, Any]],
    problems: list[str],
    checked: dict[str, int],
) -> None:
    no_perm_cols = _find_no_perm_cols(draft, fields)
    perms = _kind(draft, "Permission")
    checked["permissions"] = len(perms)
    spurious = [k for k, v in perms.items() if v.get("Column") in no_perm_cols]
    if spurious:
        problems.append(
            f"{len(spurious)} Permission(s) sit on SequenceNumber/IsHidden columns, "
            f"which take none (CLAUDE.md Visibility)"
        )


def _check_styles(draft: Draft, problems: list[str], checked: dict[str, int]) -> None:
    apps = _kind(draft, "Appearance")
    checked["style_chains"] = len(apps)
    for k, a in apps.items():
        styles = a.get("Appearance::Style") or []
        if len(styles) != 1:
            problems.append(
                f"Appearance {k} owns {len(styles)} Style "
                f"nodes, must be exactly 1 — an incomplete chain breaks form render"
            )


def _build_event_map(draft: Draft) -> dict[str, list[str]]:
    events = _kind(draft, "Event")
    ev_by_field: dict[str, list[str]] = {}
    for e in events.values():
        fid, trigger = e.get("Field"), e.get("Trigger")
        if isinstance(fid, str) and isinstance(trigger, str):
            ev_by_field.setdefault(fid, []).append(trigger)
    return ev_by_field


def _build_spec_types_by_name(spec: AppSpec) -> dict[str, FieldType]:
    types = {f.name: f.type for f in spec.data_model.fields}
    for t in spec.data_model.tables:
        types.update({c.name: c.type for c in t.columns})
    return types


def _expected_trigger(src_type: FieldType | None) -> str | None:
    return trigger_for(src_type).value if src_type is not None else None


def _check_computed_source(
    target_field: str,
    src: str,
    fid: str | None,
    src_type: FieldType | None,
    ev_by_field: dict[str, list[str]],
    problems: list[str],
) -> None:
    got = ev_by_field.get(fid, [])
    if not got:
        problems.append(
            f"computed {target_field!r}: source {src!r} carries NO event — the value can never compute"
        )
        return
    want = _expected_trigger(src_type)
    if want is not None and want not in got:
        problems.append(
            f"computed {target_field!r}: source {src!r} has trigger(s) "
            f"{got}, its type derives {want!r} — never fires"
        )


def _check_events(
    draft: Draft,
    spec: AppSpec,
    fields: dict[str, dict[str, Any]],
    problems: list[str],
    checked: dict[str, int],
) -> None:
    ev_by_field = _build_event_map(draft)
    field_id_by_name = {v.get("Name"): k for k, v in fields.items()}
    type_by_name = _build_spec_types_by_name(spec)
    checked["computed"] = len(spec.data_model.computed)
    for c in spec.data_model.computed:
        for src in c.source_fields:
            _check_computed_source(
                c.target_field,
                src,
                field_id_by_name.get(src),
                type_by_name.get(src),
                ev_by_field,
                problems,
            )


def _check_stages(
    spec: AppSpec,
    act_names: set[str],
    problems: list[str],
    checked: dict[str, int],
) -> None:
    checked["stages"] = len(spec.stages.stages)
    for s in spec.stages.stages:
        if s.name not in act_names:
            problems.append(f"stage {s.name!r} asked for by the input has no Activity")


def _unconditional_branches(pds: dict[str, dict[str, Any]], branch_ids: list[str]) -> list[str]:
    unconditional: list[str] = []
    for b in branch_ids:
        exprs = pds.get(b, {}).get("ProcessDef::Expression")
        if not exprs:
            unconditional.append(b)
    return unconditional


def _check_gateway_branch_conditions(
    pds: dict[str, dict[str, Any]],
    par: dict[str, Any],
    problems: list[str],
) -> None:
    branch_ids = par.get("Activity::ProcessDef")
    if not branch_ids:
        return
    unconditional = _unconditional_branches(pds, branch_ids)
    if unconditional:
        names = [pds.get(b, {}).get("Name") for b in unconditional]
        problems.append(
            f"gateway {par.get('Name')!r}: branch(es) {names} carry NO condition "
            f"— an unmatched value silently skips the whole gateway (fail-open)"
        )


def _check_gateways(
    draft: Draft,
    spec: AppSpec,
    parallels: list[dict[str, Any]],
    problems: list[str],
    checked: dict[str, int],
) -> None:
    checked["decision_points"] = len(spec.routing.points)
    if len(parallels) < len(spec.routing.points):
        problems.append(
            f"input declares {len(spec.routing.points)} decision point(s), build has "
            f"{len(parallels)} Parallel gateway(s)"
        )
    if not spec.routing.points:
        return
    pds = _kind(draft, "ProcessDef")
    for par in parallels:
        _check_gateway_branch_conditions(pds, par, problems)


def _find_matching_gotos(
    draft: Draft, gotos: list[dict[str, Any]], to_stage: str
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for g in gotos:
        goto_target = draft.get(g.get("Goto", ""), {})
        if goto_target.get("Name") == to_stage:
            matches.append(g)
    return matches


def _check_one_loop(
    draft: Draft,
    lp: Any,
    gotos: list[dict[str, Any]],
    problems: list[str],
) -> None:
    match = _find_matching_gotos(draft, gotos, lp.to_stage)
    if not match:
        problems.append(
            f"loop {lp.from_stage!r}->{lp.to_stage!r} asked for by the input has "
            f"no GotoTask targeting {lp.to_stage!r}"
        )
    elif not any(g.get("Activity::Expression") for g in match):
        problems.append(
            f"loop {lp.from_stage!r}->{lp.to_stage!r}: GotoTask has NO gate "
            f"condition — it loops forever (or never, if suspended)"
        )


def _check_loops(
    draft: Draft,
    spec: AppSpec,
    gotos: list[dict[str, Any]],
    problems: list[str],
    checked: dict[str, int],
) -> None:
    checked["loops"] = len(spec.rework_loops.loops)
    for lp in spec.rework_loops.loops:
        _check_one_loop(draft, lp, gotos, problems)


def _categorize_activities(
    acts: dict[str, dict[str, Any]],
) -> tuple[set[str], list[dict[str, Any]], list[dict[str, Any]]]:
    names: set[str] = set()
    parallels: list[dict[str, Any]] = []
    gotos: list[dict[str, Any]] = []
    for v in acts.values():
        _name = v.get("Name")
        if isinstance(_name, str):
            names.add(_name)
        ntype = v.get("NodeType")
        if ntype == "Parallel":
            parallels.append(v)
        elif ntype == "GotoTask":
            gotos.append(v)
    return names, parallels, gotos


def _check_workflow(
    draft: Draft,
    spec: AppSpec,
    problems: list[str],
    checked: dict[str, int],
) -> None:
    acts = _kind(draft, "Activity")
    act_names, parallels, gotos = _categorize_activities(acts)
    _check_stages(spec, act_names, problems, checked)
    _check_gateways(draft, spec, parallels, problems, checked)
    _check_loops(draft, spec, gotos, problems, checked)


def compare_built_to_spec(draft: Draft, spec: AppSpec) -> CompareReport:
    problems: list[str] = []
    checked: dict[str, int] = {}
    ignored = _collect_ignored(draft)
    fields = _kind(draft, "Field")
    by_name = {n: v for v in fields.values() if isinstance(n := v.get("Name"), str)}

    _check_fields(spec, fields, by_name, problems, checked)
    _check_layout(draft, spec, problems, checked)
    _check_permissions(draft, fields, problems, checked)
    _check_styles(draft, problems, checked)
    _check_events(draft, spec, fields, problems, checked)
    _check_workflow(draft, spec, problems, checked)

    return CompareReport(mismatches=tuple(problems), checked=checked, ignored=tuple(ignored))
