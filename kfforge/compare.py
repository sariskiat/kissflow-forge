"""kfforge.compare — does the BUILT app match what the INPUT asked for? (#16)

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

from .intake.schema import AppSpec, trigger_for
from .types import FieldType

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
        return {"ok": self.ok(), "mismatches": list(self.mismatches),
                "checked": self.checked, "ignored": list(self.ignored),
                "isError": not self.ok()}


def _kind(draft: Draft, kind: str) -> dict[str, dict[str, Any]]:
    return {k: v for k, v in draft.items() if isinstance(v, dict) and v.get("Kind") == kind}


def compare_built_to_spec(draft: Draft, spec: AppSpec) -> CompareReport:  # noqa: C901
    problems: list[str] = []
    checked: dict[str, int] = {}
    ignored: list[str] = [f"kind {k} (platform publish side-effect)" for k in _BENIGN_KINDS
                          if any(isinstance(v, dict) and v.get("Kind") == k
                                 for v in draft.values())]

    fields = _kind(draft, "Field")
    by_name = {v.get("Name"): v for v in fields.values()}

    # 1. field inventory by (name, TYPE, ReferredList) — a count-only check once reported
    #    "64 = 64, parity reached" while 11 fields had the wrong type (#16).
    wanted: dict[str, tuple[str, str | None]] = {}
    for f in spec.data_model.fields:
        wanted[f.name] = (f.type.value, getattr(f, "list_name", None))
    for t in spec.data_model.tables:
        for c in t.columns:
            wanted[c.name] = (c.type.value, None)
    checked["fields"] = len(wanted)
    for name, (ftype, list_name) in wanted.items():
        node = by_name.get(name)
        if node is None:
            problems.append(f"field {name!r} ({ftype}) asked for by the input is absent")
            continue
        if node.get("Type") != ftype:
            problems.append(f"field {name!r} built as {node.get('Type')!r}, input asked {ftype!r}")
        if ftype == FieldType.SELECT.value and list_name and not node.get("ReferredList"):
            problems.append(f"Select {name!r} should reference list {list_name!r} but carries "
                            f"no ReferredList — its routing literals are unvalidated free text")
    if spec.data_model.sequence is not None:
        checked["sequence"] = 1
        if not any(v.get("Type") == "SequenceNumber" for v in fields.values()):
            problems.append("input asks for an auto-numbered id (sequence) — no SequenceNumber "
                            "field was built")
    known_extra = set(wanted) | {""}
    for v in fields.values():
        if v.get("Name") not in known_extra and v.get("Type") != "SequenceNumber":
            problems.append(f"field {v.get('Name')!r} ({v.get('Type')}) exists in the build but "
                            f"the input never asked for it")

    # 2. sections + root Model::Row order INCLUDING table hosts (#10/#16: the section-only order
    #    check was the comparator blind spot that let an unrenderable form read as '1 gap').
    root = draft.get(draft.get("Root", ""), {})
    row_first_col: dict[str, dict[str, Any]] = {}
    for rid in root.get("Model::Row") or []:
        cols = (draft.get(rid) or {}).get("Row::Column") or []
        row_first_col[rid] = draft.get(cols[0], {}) if cols else {}
    live_sections = {v.get("Name") for v in row_first_col.values() if v.get("Type") == "Section"}
    checked["sections"] = len(spec.data_model.sections)
    for s in spec.data_model.sections:
        if s.name not in live_sections:
            problems.append(f"section {s.name!r} asked for by the input is absent from the form")
    checked["tables"] = len(spec.data_model.tables)
    hosts = {v.get("Name") for v in row_first_col.values() if v.get("Type") == "Model"}
    for t in spec.data_model.tables:
        if t.name not in hosts:
            problems.append(f"table {t.name!r} asked for by the input has no host row in root "
                            f"Model::Row (built but unregistered, or not built)")
    ordered = list(row_first_col.values())
    for i, col in enumerate(ordered):
        if col.get("Type") == "Section" and not (col.get("Column::Row") or []):
            nxt = ordered[i + 1] if i + 1 < len(ordered) else {}
            if nxt.get("Type") != "Model":
                problems.append(
                    f"empty section {col.get('Name')!r} is not immediately followed by a table "
                    f"host — a stranded banner breaks the WHOLE form's render (CLAUDE.md Tables)")

    # 3. Permissions on no-Permission columns (#9 — publish/doctor both accepted them).
    no_perm_cols = set()
    seq_fields = {k for k, v in fields.items() if v.get("Type") == "SequenceNumber"}
    for k, v in _kind(draft, "Column").items():
        if v.get("IsHidden") is True or any(f in seq_fields for f in (v.get("Column::Field") or [])):
            no_perm_cols.add(k)
    perms = _kind(draft, "Permission")
    checked["permissions"] = len(perms)
    spurious = [k for k, v in perms.items() if v.get("Column") in no_perm_cols]
    if spurious:
        problems.append(f"{len(spurious)} Permission(s) sit on SequenceNumber/IsHidden columns, "
                        f"which take none (CLAUDE.md Visibility)")

    # 4. style-chain completeness per owner — an Appearance with an empty Appearance::Style
    #    breaks the whole form's render (CLAUDE.md render-breakers, proven live 2026-08-12).
    apps = _kind(draft, "Appearance")
    checked["style_chains"] = len(apps)
    for k, a in apps.items():
        if len(a.get("Appearance::Style") or []) != 1:
            problems.append(f"Appearance {k} owns {len(a.get('Appearance::Style') or [])} Style "
                            f"nodes, must be exactly 1 — an incomplete chain breaks form render")

    # 5. event inventory by (source field, trigger) — a wrong trigger never fires (#12).
    events = _kind(draft, "Event")
    ev_by_field = {}
    for e in events.values():
        ev_by_field.setdefault(e.get("Field"), []).append(e.get("Trigger"))
    field_id_by_name = {v.get("Name"): k for k, v in fields.items()}
    type_by_name = {f.name: f.type for f in spec.data_model.fields}
    for t in spec.data_model.tables:
        type_by_name.update({c.name: c.type for c in t.columns})
    checked["computed"] = len(spec.data_model.computed)
    for c in spec.data_model.computed:
        for src in c.source_fields:
            fid = field_id_by_name.get(src)
            src_type = type_by_name.get(src)
            want_trigger = trigger_for(src_type).value if src_type is not None else None
            got = ev_by_field.get(fid, [])
            if not got:
                problems.append(f"computed {c.target_field!r}: source {src!r} carries NO event "
                                f"— the value can never compute")
            elif want_trigger and want_trigger not in got:
                problems.append(f"computed {c.target_field!r}: source {src!r} has trigger(s) "
                                f"{got}, its type derives {want_trigger!r} — never fires")

    # 6. workflow: every stage an Activity; every decision point a conditional gateway; every
    #    loop a gated GotoTask (a branch without a condition is the silent fail-open).
    acts = _kind(draft, "Activity")
    act_names = {v.get("Name") for v in acts.values()}
    checked["stages"] = len(spec.stages.stages)
    for s in spec.stages.stages:
        if s.name not in act_names:
            problems.append(f"stage {s.name!r} asked for by the input has no Activity")
    parallels = [v for v in acts.values() if v.get("NodeType") == "Parallel"]
    checked["decision_points"] = len(spec.routing.points)
    if len(parallels) < len(spec.routing.points):
        problems.append(f"input declares {len(spec.routing.points)} decision point(s), build has "
                        f"{len(parallels)} Parallel gateway(s)")
    pds = _kind(draft, "ProcessDef")
    if spec.routing.points:
        for par in parallels:
            branch_ids = par.get("Activity::ProcessDef") or []
            unconditional = [b for b in branch_ids
                             if not (pds.get(b, {}).get("ProcessDef::Expression") or [])]
            if branch_ids and unconditional:
                problems.append(
                    f"gateway {par.get('Name')!r}: branch(es) "
                    f"{[pds.get(b, {}).get('Name') for b in unconditional]} carry NO condition "
                    f"— an unmatched value silently skips the whole gateway (fail-open)")
    gotos = [v for v in acts.values() if v.get("NodeType") == "GotoTask"]
    checked["loops"] = len(spec.rework_loops.loops)
    for lp in spec.rework_loops.loops:
        match = [g for g in gotos
                 if (draft.get(g.get("Goto", "")) or {}).get("Name") == lp.to_stage]
        if not match:
            problems.append(f"loop {lp.from_stage!r}->{lp.to_stage!r} asked for by the input has "
                            f"no GotoTask targeting {lp.to_stage!r}")
        elif not any(g.get("Activity::Expression") for g in match):
            problems.append(f"loop {lp.from_stage!r}->{lp.to_stage!r}: GotoTask has NO gate "
                            f"condition — it loops forever (or never, if suspended)")

    return CompareReport(mismatches=tuple(problems), checked=checked, ignored=tuple(ignored))
