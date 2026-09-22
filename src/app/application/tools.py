"""Framework-agnostic tool logic (dict in / dict out). Offline + compliant.

Kept separate from server.py so the logic is testable without the MCP framework.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from app.application.engine import plan_change
from app.domain.graph import progressive_matrix, section_layout
from app.domain.types import FieldSpec, FieldType, Visibility


def list_field_types() -> list[str]:
    """The field types THIS ENGINE can build — the guard against 'wrong type' errors.

    Not the platform's catalog: Kissflow's own field palette is much wider (Image, Rich text,
    Signature, Geolocation, Currency, … — see docs/capabilities/, served over MCP by
    forge_capabilities). These are the ones whose wire shape is captured, so they are the ones a
    write here may name; anything else is refused at compile rather than guessed (ADR-0004).
    """
    return [t.value for t in FieldType]


def _to_spec(d: dict[str, Any]) -> FieldSpec:
    # `default_value` (#55, forge_apply_fields extension) is a convenience top-level key that
    # folds into `options["DefaultValue"]` — the SAME wire key `_TYPE_DEFAULTS` already writes for
    # Number, and the platform's own relative-date keyword ("Today") for Date. Absent when not
    # given, so every caller that never used it sees byte-identical FieldSpec.options to before.
    options = dict(d.get("options") or {})
    if d.get("default_value") is not None:
        options["DefaultValue"] = d["default_value"]
    return FieldSpec(
        name=d["name"],
        type=FieldType(d["type"]),  # raises on unknown type -> rejected
        required=bool(d.get("required", False)),
        referred_list=d.get("referred_list"),
        field_id=d.get("field_id"),
        options=options or None,  # opt-in per-type keys (AllowFormatting/CaptureOnly/…)
    )


def plan_step_visibility(draft: dict[str, Any], owners: dict[str, list[str]]) -> dict[str, Any]:
    """DRY-RUN preview (offline): which section is Editable/ReadOnly/Hidden at which step.

    Returns a per-section tally plus the step name each section is editable at, which is the part a
    human can actually check by eye. Writes nothing, makes no network call.
    """
    matrix = progressive_matrix(draft, owners)
    acts = {
        k: v.get("Name", k)
        for k, v in draft.items()
        if isinstance(v, dict) and v.get("Kind") == "Activity"
    }
    out: dict[str, Any] = {"sections": {}, "permission_nodes": 0}
    for section, row in matrix.items():
        tally = Counter(v.value for v in row.values())
        out["sections"][section] = {
            "editable_at": sorted(
                acts.get(a, a) for a, v in row.items() if v is Visibility.EDITABLE
            ),
            **{k.lower(): c for k, c in tally.items()},
        }
    # the REAL pair count the writer will emit: per matrix row, the section's member columns
    # minus the columns the writer skips (no-Permission columns and table hosts — #9, Tables).
    # Field-level overrides would add their own rows, but this preview takes no field_matrix,
    # so nothing is subtracted for them. Sharing section_layout with the writer is what keeps
    # this count truthful (it used to count every member column, silently over-reporting by
    # one column x every step whenever a section held a hidden or SequenceNumber column).
    layout = section_layout(draft)
    out["permission_nodes"] = sum(
        len(
            [
                c
                for c in layout.members.get(layout.section_id_of_name.get(s, ""), ())
                if c not in layout.no_permission_columns and c not in layout.table_host_columns
            ]
        )
        * len(r)
        for s, r in matrix.items()
        if s in layout.section_id_of_name
    )
    return out


def plan_field_change(draft: dict[str, Any], changes: list[dict[str, Any]]) -> dict[str, Any]:
    """DRY-RUN preview (offline): what adding these fields would do. Writes nothing.

    A malformed `changes` entry raises a ValueError naming the entry, its shape and a correct
    example (`coerce_field_specs`) instead of a bare KeyError out of the middle of a destructure —
    the server layer turns that into an `Err("verify", ...)` at the tool boundary.
    """
    diff = plan_change(draft, coerce_field_specs("changes", changes))
    return {
        "adds": [
            {"name": s.name, "type": FieldType(s.type).value, "required": s.required}
            for s in diff.adds
        ],
        "edits": [{"name": s.name} for s in diff.edits],
        "skipped": list(diff.skipped),
        "human_readable": diff.human_readable,
    }


# =================================================================================================
# Boundary shape coercion — doctrine 7 ("errors cross the tool boundary as DATA") for the nested
# arguments the MCP schema can only describe as `list[Any]` / `dict[str, Any]`.
#
# Pydantic already rejects a `changes` that is not a list, or a `styles` that is not an object of
# objects — that much the declared type hints buy for free. What it CANNOT see is the shape INSIDE
# those containers: a `[name, role]` step pair one element short, a field object with no "type", a
# `parallel` block with no "branches". Every one of those used to be destructured straight in a
# server.py tool body, so the single most likely agent mistake produced a bare IndexError/KeyError
# instead of a structured refusal naming what was wrong.
#
# So the destructuring lives HERE, and every coercer raises a ValueError that names the PARAMETER
# (down to the offending index/key), the SHAPE it actually received, and a CORRECT EXAMPLE. The
# thin server layer turns that into `Err("verify", ...)` exactly the way it already turns
# `graph.progressive_matrix`'s ValueErrors into one. Nothing here touches the network or a draft —
# these are pure, offline, and refuse BEFORE any read-verify-write cycle starts.
# =================================================================================================


def _brief(x: Any, limit: int = 120) -> str:
    """A repr short enough to belong in an error message — an agent that passed a 4000-field
    layout does not need it echoed back at it in full to see what was wrong with it."""
    s = repr(x)
    return s if len(s) <= limit else s[:limit] + "…"


def _shape_error(param: str, got: Any, want: str, example: str) -> ValueError:
    return ValueError(
        f"{param}: expected {want}, got {type(got).__name__} {_brief(got)} — "
        f"correct shape: {example}"
    )


def _field_type(param: str, value: Any) -> FieldType:
    """The closed field-type set, refused by NAME at the boundary. Deliberately not just
    `FieldType(value)`: the bare enum's own ValueError says nothing about which parameter, which
    entry, or where the wider platform palette is documented."""
    try:
        return FieldType(value)
    except ValueError:
        raise ValueError(
            f"{param}: {value!r} is not a field type this engine can build — valid: "
            f"{[t.value for t in FieldType]} (kf_list_field_types). The platform's own field "
            f"palette is wider; what is captured of it is in forge_capabilities, and a type "
            f"outside the list above is refused here rather than guessed at (ADR-0004)."
        ) from None


_FIELD_EXAMPLE = '[{"name": "Ticket No", "type": "Text", "required": true}]'


def coerce_field_specs(param: str, value: Any) -> list[FieldSpec]:
    """`fields`/`changes` -> FieldSpec list, every entry named by index when it is wrong."""
    if not isinstance(value, list):
        raise _shape_error(param, value, "a list of field objects", _FIELD_EXAMPLE)
    specs: list[FieldSpec] = []
    for i, d in enumerate(value):
        at = f"{param}[{i}]"
        if not isinstance(d, dict):
            raise _shape_error(at, d, "a field object", _FIELD_EXAMPLE)
        if not isinstance(d.get("name"), str) or not d["name"].strip():
            raise _shape_error(
                f"{at}['name']", d.get("name"), "a non-empty field name", _FIELD_EXAMPLE
            )
        _field_type(f"{at}['type']", d.get("type"))
        opts = d.get("options")
        if opts is not None and not isinstance(opts, dict):
            raise _shape_error(
                f"{at}['options']",
                opts,
                "an object of opt-in per-type Field keys",
                '{"AllowFormatting": true}',
            )
        specs.append(_to_spec(d))
    return specs


def coerce_sections(param: str, value: Any) -> list[tuple[str, list[str]]] | None:
    """`sections` -> the `(title, [field names])` group list apply_fields_full wants. None passes
    through: "state no layout at all" is a legal call, distinct from "state an empty one"."""
    example = '{"Case Info": ["Ticket No", "Urgency"]}'
    if value is None:
        return None
    if not isinstance(value, dict):
        raise _shape_error(param, value, "an object of section title -> field-name list", example)
    for title, names in value.items():
        if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
            raise _shape_error(f"{param}[{title!r}]", names, "a list of field names", example)
    return list(value.items())


def coerce_layout(param: str, value: Any) -> dict[str, list[list[tuple[str, int, int]]]]:
    """`layout` -> `{section: [[(field, Start, End), ...], ...]}`. Only the SHAPE is checked here;
    the grid itself (0 <= Start < End <= 6, no overlap within a row) is `graph.apply_exact_layout`'s
    own first statement, so a legal-shaped but off-grid span is still refused before any write."""
    example = '{"Case Info": [[["Ticket No", 0, 3], ["Urgency", 3, 6]]]}'
    if not isinstance(value, dict):
        raise _shape_error(param, value, "an object of section title -> list of rows", example)
    typed: dict[str, list[list[tuple[str, int, int]]]] = {}
    for section, rows in value.items():
        if not isinstance(rows, list):
            raise _shape_error(
                f"{param}[{section!r}]", rows, "a list of rows, top to bottom", example
            )
        out_rows: list[list[tuple[str, int, int]]] = []
        for ri, row in enumerate(rows):
            if not isinstance(row, list):
                raise _shape_error(
                    f"{param}[{section!r}][{ri}]",
                    row,
                    "a list of [field_name, Start, End] triples",
                    example,
                )
            placed: list[tuple[str, int, int]] = []
            for ci, cell in enumerate(row):
                at = f"{param}[{section!r}][{ri}][{ci}]"
                if not isinstance(cell, (list, tuple)) or len(cell) != 3:
                    raise _shape_error(at, cell, "a [field_name, Start, End] triple", example)
                name, start, end = cell
                if not isinstance(name, str) or not name.strip():
                    raise _shape_error(f"{at}[0]", name, "a field name", example)
                for label, n in (("Start", start), ("End", end)):
                    if isinstance(n, bool) or not isinstance(n, int):
                        raise _shape_error(f"{at} {label}", n, "a whole grid unit (0..6)", example)
                placed.append((name, start, end))
            out_rows.append(placed)
        typed[section] = out_rows
    return typed


def coerce_table_columns(param: str, value: Any) -> list[tuple[str, str, dict[str, Any] | None]]:
    """`columns` -> `[(name, type, options|None), ...]` for a child table."""
    example = '[["Item", "Text"], ["Qty", "Number", {"Decimalpoint": 0}]]'
    if not isinstance(value, list):
        raise _shape_error(
            param,
            value,
            "a list of [name, type] (or [name, type, options]) column entries",
            example,
        )
    cols: list[tuple[str, str, dict[str, Any] | None]] = []
    for i, col in enumerate(value):
        at = f"{param}[{i}]"
        if not isinstance(col, (list, tuple)) or not 2 <= len(col) <= 3:
            raise _shape_error(at, col, "a [name, type] or [name, type, options] entry", example)
        if not isinstance(col[0], str) or not col[0].strip():
            raise _shape_error(f"{at}[0]", col[0], "a column name", example)
        ftype = _field_type(f"{at}[1]", col[1])
        opts = col[2] if len(col) > 2 else None
        if opts is not None and not isinstance(opts, dict):
            raise _shape_error(
                f"{at}[2]",
                opts,
                "an object of opt-in per-column Field keys written verbatim onto the node",
                example,
            )
        cols.append((col[0], ftype.value, opts))
    return cols


def coerce_validation_rules(param: str, value: Any) -> dict[str, list[tuple[str, str]]]:
    """`rules` -> `{field name: [(operator, rhs), ...]}`."""
    example = '{"meeting link": [["CONTAINS", "microsoft"]]}'
    if not isinstance(value, dict):
        raise _shape_error(
            param, value, "an object of field name -> list of [operator, value] rules", example
        )
    norm: dict[str, list[tuple[str, str]]] = {}
    for field, rules in value.items():
        if not isinstance(rules, list):
            raise _shape_error(
                f"{param}[{field!r}]", rules, "a list of [operator, value] rules", example
            )
        pairs: list[tuple[str, str]] = []
        for i, rule in enumerate(rules):
            at = f"{param}[{field!r}][{i}]"
            if not isinstance(rule, (list, tuple)) or len(rule) != 2:
                raise _shape_error(at, rule, "an [operator, value] pair", example)
            if not all(isinstance(x, str) for x in rule):
                raise _shape_error(at, rule, "an [operator, value] pair of two strings", example)
            pairs.append((rule[0], rule[1]))
        norm[field] = pairs
    return norm


_STEPS_EXAMPLE = '[["Manager Approve", "AppRole_ab12"], ["Finance Check", null]]'


def _coerce_step_pairs(param: str, value: Any) -> list[tuple[str, str | None]]:
    if not isinstance(value, list):
        raise _shape_error(
            param, value, "a list of [step name, role id or null] pairs", _STEPS_EXAMPLE
        )
    steps: list[tuple[str, str | None]] = []
    for i, step in enumerate(value):
        at = f"{param}[{i}]"
        if not isinstance(step, (list, tuple)) or len(step) != 2:
            raise _shape_error(at, step, "a [step name, role id or null] pair", _STEPS_EXAMPLE)
        name, role = step
        if not isinstance(name, str) or not name.strip():
            raise _shape_error(f"{at}[0]", name, "a step name", _STEPS_EXAMPLE)
        if role is not None and not isinstance(role, str):
            raise _shape_error(
                f"{at}[1]", role, "an AppRole id, or null for an unassigned step", _STEPS_EXAMPLE
            )
        steps.append((name, role))
    return steps


def coerce_workflow_steps(param: str, value: Any) -> list[tuple[str, str | None]]:
    """`steps` -> `[(step name, role id | None), ...]` for the workflow rebuild."""
    return _coerce_step_pairs(param, value)


def coerce_parallel(
    param: str,
    value: Any,
) -> tuple[str, list[tuple[str, list[tuple[str, str | None]]]]] | None:
    """`parallel` -> `(gateway name, [(branch name, [(step, role), ...]), ...])`. None passes
    through — a workflow with no gateway is the common case, not an error."""
    example = (
        '{"name": "Route", "branches": [["Standard", [["Approve", null]]], '
        '["Express", [["Fast Approve", null]]]]}'
    )
    if value is None:
        return None
    if not isinstance(value, dict):
        raise _shape_error(param, value, "an object with 'name' and 'branches'", example)
    name = value.get("name")
    if not isinstance(name, str) or not name.strip():
        raise _shape_error(f"{param}['name']", name, "the Parallel gateway's name", example)
    branches = value.get("branches")
    if not isinstance(branches, list):
        raise _shape_error(
            f"{param}['branches']", branches, "a list of [branch name, steps] pairs", example
        )
    out: list[tuple[str, list[tuple[str, str | None]]]] = []
    for i, branch in enumerate(branches):
        at = f"{param}['branches'][{i}]"
        if not isinstance(branch, (list, tuple)) or len(branch) != 2:
            raise _shape_error(at, branch, "a [branch name, steps] pair", example)
        if not isinstance(branch[0], str) or not branch[0].strip():
            raise _shape_error(f"{at}[0]", branch[0], "a branch name", example)
        out.append((branch[0], _coerce_step_pairs(f"{at}[1]", branch[1])))
    return (name, out)


def coerce_events(param: str, value: Any) -> dict[str, list[tuple[str | None, str]]]:
    """`events` -> `{field name: [(trigger | None, script), ...]}`. A `None` trigger is the
    RECOMMENDED call (the writer derives it from the source field's live type), so it is a legal
    value here, not a missing one."""
    example = '{"Total": [[null, "kf.form.getField(\'Total\')"]]}'
    if not isinstance(value, dict):
        raise _shape_error(
            param, value, "an object of field name -> list of [trigger, script] pairs", example
        )
    conv: dict[str, list[tuple[str | None, str]]] = {}
    for field, specs in value.items():
        if not isinstance(specs, list):
            raise _shape_error(
                f"{param}[{field!r}]", specs, "a list of [trigger, script] pairs", example
            )
        pairs: list[tuple[str | None, str]] = []
        for i, spec in enumerate(specs):
            at = f"{param}[{field!r}][{i}]"
            if not isinstance(spec, (list, tuple)) or len(spec) != 2:
                raise _shape_error(
                    at,
                    spec,
                    "a [trigger, script] pair — pass null for the "
                    "trigger to derive it from the field's live type",
                    example,
                )
            trigger, script = spec
            if trigger is not None and not isinstance(trigger, str):
                raise _shape_error(
                    f"{at}[0]", trigger, "a trigger string, or null to derive it", example
                )
            if not isinstance(script, str):
                raise _shape_error(f"{at}[1]", script, "the event script source", example)
            pairs.append((trigger, script))
        conv[field] = pairs
    return conv


def coerce_page_steps(param: str, value: Any) -> list[tuple[str, dict[str, Any]]]:
    """`steps` -> `[(kind, kwargs), ...]` for the raw page-build primitive."""
    example = (
        '[{"kind": "widget", "kwargs": {"container_id": "Container001", '
        '"widget": "general/button"}}]'
    )
    if not isinstance(value, list):
        raise _shape_error(param, value, "a list of {kind, kwargs} build steps", example)
    steps: list[tuple[str, dict[str, Any]]] = []
    for i, step in enumerate(value):
        at = f"{param}[{i}]"
        if not isinstance(step, dict):
            raise _shape_error(at, step, "a {kind, kwargs} build step", example)
        kind = step.get("kind")
        if not isinstance(kind, str) or not kind.strip():
            raise _shape_error(
                f"{at}['kind']",
                kind,
                "one of container|widget|popup|event|style|bind|design",
                example,
            )
        kwargs = step.get("kwargs", {})
        if kwargs is None:
            kwargs = {}
        if not isinstance(kwargs, dict):
            raise _shape_error(
                f"{at}['kwargs']", kwargs, "an object of arguments for that builder", example
            )
        steps.append((kind, kwargs))
    return steps


def coerce_case_steps(param: str, value: Any) -> list[dict[str, Any]]:
    """`steps` -> normalized item-walk steps, every key present so the caller never has to
    `.get()` its way through a half-filled dict."""
    example = (
        '[{"name": "Manager Approve", "values": {"Urgency": "High"}, "reject": false, '
        '"comment": ""}]'
    )
    if not isinstance(value, list):
        raise _shape_error(param, value, "a list of walk steps", example)
    plans: list[dict[str, Any]] = []
    for i, step in enumerate(value):
        at = f"{param}[{i}]"
        if not isinstance(step, dict):
            raise _shape_error(at, step, "a walk step object", example)
        name = step.get("name")
        if not isinstance(name, str) or not name.strip():
            raise _shape_error(f"{at}['name']", name, "the step's activity name", example)
        values = step.get("values") or {}
        if not isinstance(values, dict):
            raise _shape_error(
                f"{at}['values']", values, "an object of field name (or id) -> value", example
            )
        comment = step.get("comment", "")
        if not isinstance(comment, str):
            raise _shape_error(f"{at}['comment']", comment, "a comment string", example)
        plans.append(
            {
                "name": name,
                "values": values,
                "reject": bool(step.get("reject", False)),
                "comment": comment,
            }
        )
    return plans
