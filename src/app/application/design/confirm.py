"""app.application.design.confirm -- the approval protocol.

This is the actual gate CLAUDE.md's "THE RULE THAT COST THIS PROJECT A WHOLE SESSION" describes:
an HTTP 200 from the builder API proves nothing, so nothing downstream of a spec is allowed to
write to Kissflow until a human has SEEN the design (the diagrams + HTML mockups from diagram.py/
mockup.py) and typed back an explicit "approve". This module is that checkpoint: it packages the
artifacts, derives one plain-language question per risky choice the spec makes, computes a digest
that is guaranteed to change whenever the spec does, and applies a small, explicit vocabulary of
revisions a customer might ask for after reading the questions.

Every function here is READ-ONLY except `apply_revisions`, which returns a NEW spec-like object
rather than mutating its input (`dataclasses.replace`, never in-place assignment) -- matching the
pure/never-mutate convention the rest of the engine (domain/graph.py, domain/pages.py, domain/nav.py) already follows.
Duck-typed against app.application.design.AppSpecLike throughout, via `app.application.design.diagram._seq()`/
`_seq_replace()` for every dimension that app.application.intake.schema wraps in its own container
(`Stages`/`Routing`/`ReworkLoops`/`TestCases`) -- never imports app.application.intake (see the package
docstring for why).
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, cast

from app.application.design.diagram import (
    _loop_direction,
    _seq,
    _seq_replace,
    _stage_index,
    _terminal_stages,
    flow_diagram_xml,
    schema_diagram_xml,
)
from app.application.design.mockup import design_bundle_html

if TYPE_CHECKING:
    from app.application.design import AppSpecLike


@dataclasses.dataclass(frozen=True)
class ConfirmationRequest:
    """Everything a human needs to approve or send back a spec.

    `spec_digest` changes whenever the spec's content does (see `_digest` for how) -- the
    intended caller pattern is to key stored (digest, decision) pairs by it, so an "approve"
    recorded for one version of a spec can never be mistaken for approval of a later revision;
    see `is_approved`'s own docstring and the digest-focused tests in tests/test_design.py.
    """

    spec_digest: str
    artifacts: dict[str, str]
    questions: tuple[str, ...]


# ---------------------------------------------------------------------------------------------
# Digest: a canonical, content-only snapshot of the spec, hashed.
# ---------------------------------------------------------------------------------------------


def _freeze(value: Any) -> Any:
    """JSON-safe canonical snapshot of an arbitrary duck-typed object.

    Dataclasses (both app.application.intake's real AppSpec -- including every dimension WRAPPER, e.g.
    `Stages`/`Routing` -- and any caller's own stub, per tests/test_design.py) are unpacked field
    by field via stdlib reflection (`dataclasses.fields`) -- this needs no knowledge of
    app.application.intake's actual shape, or even of this package's own Protocol attribute names, since
    it walks whatever fields are really there; a wrapper is just one more dataclass layer to
    recurse through, no special-casing required. Mappings/sequences recurse structurally;
    sequence ORDER is preserved deliberately (re-ordering stages is a real spec change and must
    change the digest), only dict keys are order-normalised (`sort_keys=True` at the json.dumps
    call site). Anything left over (a plain object with a `__dict__`, or nothing recognisable at
    all) falls back to its `__dict__` or finally `str()` -- belt-and-suspenders for a shape this
    function was not specifically told about; every input this package is actually asked to
    digest is a dataclass and never reaches that fallback.
    """
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: _freeze(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, Mapping):
        return {str(k): _freeze(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_freeze(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    attrs = getattr(value, "__dict__", None)
    if attrs is not None:
        return {k: _freeze(v) for k, v in attrs.items()}
    return str(value)


def _digest(spec: AppSpecLike) -> str:
    canonical = json.dumps(_freeze(spec), sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def spec_digest(spec: AppSpecLike) -> str:
    """Public accessor for this module's own digest computation. Added for `app.infrastructure.mcp.server`'s
    `forge_approve_spec` MCP tool, which needs to check whether a spec's CURRENT digest still
    matches the one a customer was shown -- without paying to re-render two diagrams and an HTML
    bundle just to get one hash back out, which calling the full `request_confirmation` would
    otherwise require. Same computation `ConfirmationRequest.spec_digest` already carries; this is
    only a name for it that doesn't require rebuilding the whole request to reach.
    """
    return _digest(spec)


# ---------------------------------------------------------------------------------------------
# Questions: one per risky choice, in Thai, covering routing literals / loop gates / terminal
# states / required fields / master-data list values.
# ---------------------------------------------------------------------------------------------

_LOOP_DIRECTION_NOTE_TH: dict[str, str] = {
    "forward": "ไปข้างหน้า ไม่ใช่ย้อนกลับ",
    "self": "วนกลับมาที่ตัวเอง",
    "unknown": "ไม่สามารถระบุทิศทางได้ (ชื่อขั้นตอนไม่อยู่ใน stages ที่ทราบ)",
}


def _routing_questions(spec: AppSpecLike) -> list[str]:
    questions = []
    for rp in _seq(spec.routing):
        mapping = dict(rp.route_per_option)
        for option in rp.options:
            route_seq = mapping.get(
                option
            )  # a branch is a stage SEQUENCE now (P1); show "A → B → C"
            target = " → ".join(route_seq) if route_seq else "(ยังไม่ระบุปลายทาง / not yet specified)"
            questions.append(
                f'ที่ขั้นตอน "{rp.at_stage}" ถ้าฟิลด์ "{rp.field_name}" ตอบว่า "{option}" '
                f'ระบบจะส่งงานต่อไปที่ "{target}" ใช่หรือไม่? (ยืนยัน / ขอแก้ไข)'
            )
    return questions


def _loop_questions(spec: AppSpecLike) -> list[str]:
    idx = _stage_index(spec)
    questions = []
    for lp in _seq(spec.rework_loops):
        direction = _loop_direction(idx, lp)
        if direction == "backward":
            questions.append(
                f'จาก "{lp.from_stage}" ระบบจะวนกลับไปที่ "{lp.to_stage}" ตราบใดที่ "{lp.gate_field}" '
                f"ยังไม่ถูกติ๊ก (ยังเป็นเท็จ) -- และจะไปขั้นตอนถัดไปก็ต่อเมื่อติ๊กแล้วเท่านั้น ใช่หรือไม่? (ยืนยัน / ขอแก้ไข)"
            )
        else:
            # minor 10: never assert "loops back" for something that isn't -- say what the spec
            # actually encodes and flag it as worth checking.
            questions.append(
                f'จาก "{lp.from_stage}" ไปยัง "{lp.to_stage}" (ควบคุมด้วย "{lp.gate_field}") '
                f'{_LOOP_DIRECTION_NOTE_TH[direction]} -- โดยปกติ "loop" ควรวนย้อนกลับ ไม่ใช่แบบนี้ '
                f"ถูกต้องตามที่ต้องการหรือไม่? (ยืนยัน / ขอแก้ไข)"
            )
    return questions


def _terminal_questions(spec: AppSpecLike) -> list[str]:
    return [
        f'สถานะ "{name}" คือจุดจบของงาน (ไม่มีขั้นตอนต่อจากนี้) ใช่หรือไม่? (ยืนยัน / ขอแก้ไข)'
        for name in _terminal_stages(spec)
    ]


def _required_field_questions(spec: AppSpecLike) -> list[str]:
    return [
        f'ฟิลด์ "{f.name}" ที่ขั้นตอน "{f.stage}" ต้องกรอกทุกครั้งก่อนไปขั้นตอนถัดไป ใช่หรือไม่? (ยืนยัน / ขอแก้ไข)'
        for f in _seq(spec.data_model.fields)
        if f.required
    ]


def _master_data_questions(spec: AppSpecLike) -> list[str]:
    """Blocker 2: a mis-cased option literal is CLAUDE.md's own live bug class, and list values
    are the single highest-value thing a human can proofread -- one question per list, asking
    for a byte-exact (case-sensitive) confirmation of every value."""
    questions = []
    for lst in _seq(spec.master_data.lists):
        values = ", ".join(str(v) for v in _seq(lst.values))
        questions.append(
            f'รายการตัวเลือก "{lst.name}" มีค่าตรงตามนี้ทุกตัวอักษร (case-sensitive) ใช่หรือไม่: '
            f"{values}? (ยืนยัน / ขอแก้ไข)"
        )
    return questions


def request_confirmation(spec: AppSpecLike) -> ConfirmationRequest:
    """Build everything a human needs to approve or send back a spec: the two draw.io diagrams,
    the combined HTML bundle, a content digest, and one Thai confirm/revise question per risky
    choice (each routing literal, each loop gate, each terminal state, each required field, each
    master-data list's values)."""
    artifacts = {
        "flow_diagram.drawio": flow_diagram_xml(spec),
        "schema_diagram.drawio": schema_diagram_xml(spec),
        "design.html": design_bundle_html(spec),
    }
    questions = (
        *_routing_questions(spec),
        *_loop_questions(spec),
        *_terminal_questions(spec),
        *_required_field_questions(spec),
        *_master_data_questions(spec),
    )
    return ConfirmationRequest(spec_digest=_digest(spec), artifacts=artifacts, questions=questions)


def is_approved(spec: AppSpecLike, decision: str) -> bool:
    """True only for the EXPLICIT literal "approve" -- a typo, "Approve", "approved", a revise
    request, or silence are all treated as not-yet-approved, never guessed into a yes.

    `spec` is accepted (rather than just `decision`) to keep this function's signature symmetric
    with the rest of the module and to leave room for a future stricter check; the current
    contract only inspects `decision`. The real non-carry-over guarantee -- an approval for one
    version of a spec never silently applying to a revised one -- lives in `spec_digest` (see
    `ConfirmationRequest`/`_digest`): a caller is expected to key stored decisions by digest and
    re-check it against the CURRENT spec, not to rely on is_approved() noticing a spec changed
    underneath it, which a bare decision string has no way to encode.
    """
    return decision == "approve"


# ---------------------------------------------------------------------------------------------
# Revisions: an explicit key vocabulary (not a general dotted-path setter), each key targeting
# exactly the kind of choice request_confirmation() turns into a question -- every question this
# module generates has a matching revision key here (major 7).
# ---------------------------------------------------------------------------------------------

_VALID_REVISION_KEYS = (
    "app_name",
    "stage:<stage name>:owner_role",
    "stage:<stage name>:what_happens",
    "stage:<stage name>:rename",
    "routing-target:<at_stage>:<option>",
    "routing-option:<at_stage>:<old option>",
    "loop:<from_stage>:<to_stage>:gate_field",
    "loop:<from_stage>:<to_stage>:from_stage",
    "loop:<from_stage>:<to_stage>:to_stage",
    "field:<stage>:<field name>:required",
    "field:<stage>:<field name>:rename",
    "list:<list name>:value:<old value>",
    "table:<table name>:max_rows",
)

# NOT covered, logged rather than silently missing (out of the "at least" list this vocabulary
# was widened to cover): a terminal-state question ("is X really the end?") has no matching
# revision key because a terminal state is DERIVED (app.application.design.diagram._terminal_stages),
# never stored -- answering "no" to it is a topology change (add a routing point, extend the
# stage list), not a single attribute edit a flat key/value pair can express. A caller whose
# customer disputes a terminal state should re-open dimension 3/4 with app.application.intake, not expect
# apply_revisions to handle it. A field's own TYPE and TableReq.max_rows'/ListSpec's OWNER role
# are similarly out of scope: none of this module's own questions ask about them.


def _mapping_like(original: Any, new_dict: dict) -> Any:
    """Preserve `route_per_option`'s original collection shape when writing back a revised
    mapping: app.application.intake's real DecisionPoint stores it as a tuple of (key, value) pairs (this
    package's own frozen-collections convention -- see app.application.intake.schema's module docstring),
    while this package's minimal protocol/tests may use a plain dict. Round-tripping through
    `dict()` for lookup/mutation is always safe (dict() accepts either shape), but writing back
    must match whichever shape came in, or a `dataclasses.replace` would silently swap the
    field's collection type from what the rest of app.application.intake expects."""
    if isinstance(original, tuple):
        return tuple(new_dict.items())
    return new_dict


# The type parameter is bound to the protocol but PRESERVED through the call: hand it an
# app.application.intake AppSpec and you get an AppSpec back, not a widened AppSpecLike that
# compile_spec() then rejects. PEP 695 bounds are lazily evaluated, so the TYPE_CHECKING-only
# AppSpecLike name is fine here.
def apply_revisions[SpecT: AppSpecLike](spec: SpecT, revisions: Mapping[str, str]) -> SpecT:
    """Return a NEW spec-like object with each revision applied -- `dataclasses.replace` at every
    level from the changed leaf up to the root, never in-place mutation. `spec` (and any nested
    piece a key addresses) must be a real dataclass instance for that to work, which both
    app.application.intake's AppSpec and the protocol-shaped stubs in tests/test_design.py are.

    Known limitation, logged rather than silently wrong: key parts are colon-delimited, so a
    stage/option/field/list name that itself contains a literal `:` cannot be addressed by this
    v1 grammar -- none of this package's own domain vocabulary does, and widening the grammar
    (e.g. an escape rule) is straightforward to add later if a real spec ever needs it (YAGNI).

    `"stage:<name>:rename"` cascades the new name into every place a stage name is referenced by
    STRING (routing targets/at_stage, loop from/to, field.stage/.section, TableReq.stage,
    SectionReq.stage, VisibilityEntry.stage/.section, and every test case's expected_path/
    StepFill.stage) so a renamed spec still round-trips through app.application.intake's own
    `compile_spec()` -- a revision that produces a spec the compiler rejects is a defect in this
    function, not a customer error (a first review round proved a bare rename without the
    visibility/test-case legs did exactly that).

    That contract is NOT yet met everywhere. `"field:<stage>:<name>:rename"` cascades nothing (see
    `_revise_field_rename`) and returns an uncompilable spec whenever the field is referenced
    elsewhere. Five further keys accept a value the compiler then rejects without validating it
    here: `stage:X:owner_role` (unknown role), both `loop:` endpoints (can make the loop forward),
    `loop:…:gate_field` (can name a non-Boolean), `field:…:required=true` (with no Editable entry
    at that stage), and `routing-option` (a literal absent from the backing list). Those five are
    arguably customer input errors rather than defects, but nothing here says so at the time --
    always run `compile_spec()` on a revised spec before treating it as approved.

    `"list:<name>:value:<old>"` cascades similarly: any Select field backed by that list, if it
    ALSO drives a routing point, has the renamed literal follow through into that point's
    `options`/`route_per_option`; any test case filling that field with the old literal is
    updated too -- otherwise the master-data fix alone desynchronizes the spec from its own
    routing/test cases and `compile_spec()` raises on the very literal this revision just "fixed".

    An unknown key raises ValueError naming the valid key PATTERNS (`_VALID_REVISION_KEYS`); a
    syntactically valid key whose identifier does not exist in THIS spec (e.g. a stage name that
    was never there) raises its own, more specific ValueError instead.
    """
    result: AppSpecLike = spec
    for key, value in revisions.items():
        result = _apply_one_revision(result, key, value)
    # Every mutation path above is a `dataclasses.replace`, which returns the SAME concrete class
    # it was given — so the input type really does survive the round trip. The individual helpers
    # fan out through branches that can only be typed against the protocol, so the knowledge is
    # re-stated here once rather than threaded through all of them.
    return cast("SpecT", result)


def _apply_one_revision(spec: AppSpecLike, key: str, value: str) -> AppSpecLike:
    if key == "app_name":
        return dataclasses.replace(spec, app_name=value)

    parts = key.split(":")

    if len(parts) == 3 and parts[0] == "stage" and parts[2] == "owner_role":
        return _replace_stage_attr(spec, parts[1], "owner_role", value)
    if len(parts) == 3 and parts[0] == "stage" and parts[2] == "what_happens":
        return _replace_stage_attr(spec, parts[1], "what_happens", value)
    if len(parts) == 3 and parts[0] == "stage" and parts[2] == "rename":
        return _rename_stage(spec, parts[1], value)

    if len(parts) == 3 and parts[0] == "routing-target":
        return _revise_routing_target(spec, parts[1], parts[2], value)
    if len(parts) == 3 and parts[0] == "routing-option":
        return _revise_routing_option(spec, parts[1], parts[2], value)

    if (
        len(parts) == 4
        and parts[0] == "loop"
        and parts[3] in ("gate_field", "from_stage", "to_stage")
    ):
        return _revise_loop_attr(spec, parts[1], parts[2], parts[3], value)

    if len(parts) == 4 and parts[0] == "field" and parts[3] == "required":
        return _revise_field_required(spec, parts[1], parts[2], value)
    if len(parts) == 4 and parts[0] == "field" and parts[3] == "rename":
        return _revise_field_rename(spec, parts[1], parts[2], value)

    if len(parts) == 4 and parts[0] == "list" and parts[2] == "value":
        return _revise_list_value(spec, parts[1], parts[3], value)

    if len(parts) == 3 and parts[0] == "table" and parts[2] == "max_rows":
        return _revise_table_max_rows(spec, parts[1], value)

    valid = ", ".join(repr(k) for k in _VALID_REVISION_KEYS)
    raise ValueError(f"unknown revision key {key!r}; valid keys: {valid}")


def _replace_stage_attr(spec: AppSpecLike, stage_name: str, attr: str, value: str) -> AppSpecLike:
    stages_seq = _seq(spec.stages)
    if not any(st.name == stage_name for st in stages_seq):
        raise ValueError(f"no stage named {stage_name!r} in this spec")
    new_stages = [
        dataclasses.replace(st, **{attr: value}) if st.name == stage_name else st
        for st in stages_seq
    ]
    return dataclasses.replace(spec, stages=_seq_replace(spec.stages, new_stages))


def _rename_field_stage_and_section(f: Any, old_name: str, new_name: str) -> Any:
    """Cascade helper for `_rename_stage`: updates `.stage` when it matches, and `.section` too
    (via `hasattr`, since this package's own minimal `FieldLike` protocol does not require it --
    passing an unknown keyword to `dataclasses.replace` raises) when a field wrote out the
    renamed stage's own implicit default section as an explicit string rather than leaving it
    `None`."""
    changes: dict[str, str] = {}
    if f.stage == old_name:
        changes["stage"] = new_name
    if hasattr(f, "section") and f.section == old_name:
        changes["section"] = new_name
    return dataclasses.replace(f, **changes) if changes else f


def _rename_stage(spec: AppSpecLike, old_name: str, new_name: str) -> AppSpecLike:
    """Cascades a stage rename into every place app.application.intake.schema stores a stage name as a
    plain string reference. Proven necessary, not speculative: a first review round built a real
    AppSpec, renamed one stage via this function, and fed the result to app.application.intake.compile.
    compile_spec() -- it raised, because the returned spec still had a VisibilityEntry and a
    CaseWalk pointing at the OLD name. Every leg below closes one such reference:
    stages/routing/rework_loops/fields/tables (already covered before this round) plus
    data_model.sections, visibility.entries (.stage AND .section, the latter for the common case
    of a VisibilityEntry naming a stage's own implicit default section), and every test case's
    expected_path/StepFill.stage.
    """
    stages_seq = _seq(spec.stages)
    if not any(st.name == old_name for st in stages_seq):
        raise ValueError(f"no stage named {old_name!r} in this spec")

    def _swap(n: str) -> str:
        return new_name if n == old_name else n

    new_stages = [
        dataclasses.replace(st, name=new_name) if st.name == old_name else st for st in stages_seq
    ]
    result = dataclasses.replace(spec, stages=_seq_replace(spec.stages, new_stages))

    new_routing = []
    for rp in _seq(result.routing):
        # A route value is a stage SEQUENCE now (P1) — swap the renamed stage inside EACH element,
        # not the sequence as a whole (a bare _swap(seq) would compare a tuple to a name, never
        # match, and silently leave a renamed stage stale in every branch it appears in).
        mapping = {k: tuple(_swap(s) for s in v) for k, v in dict(rp.route_per_option).items()}
        new_routing.append(
            dataclasses.replace(
                rp,
                at_stage=_swap(rp.at_stage),
                route_per_option=_mapping_like(rp.route_per_option, mapping),
            )
        )
    result = dataclasses.replace(result, routing=_seq_replace(result.routing, new_routing))

    new_loops = [
        dataclasses.replace(lp, from_stage=_swap(lp.from_stage), to_stage=_swap(lp.to_stage))
        for lp in _seq(result.rework_loops)
    ]
    result = dataclasses.replace(result, rework_loops=_seq_replace(result.rework_loops, new_loops))

    new_fields = [
        _rename_field_stage_and_section(f, old_name, new_name)
        for f in _seq(result.data_model.fields)
    ]
    # TableReq.stage exists on the real schema but this package never reads or renders it (tables
    # live in their own section, not grouped under a stage) -- patched defensively via hasattr so
    # a real spec's tables stay consistent, without requiring TableLike.stage's presence check to
    # be anything other than defensive here (it IS in this package's Protocol now, for the
    # table-visibility lookup mockup.py needs -- see __init__.py -- but this stays defensive in
    # case a caller's own stub predates that).
    new_tables = [
        dataclasses.replace(t, stage=new_name) if getattr(t, "stage", None) == old_name else t
        for t in _seq(result.data_model.tables)
    ]
    new_sections = [
        dataclasses.replace(sec, stage=new_name) if sec.stage == old_name else sec
        for sec in _seq(result.data_model.sections)
    ]
    new_data_model = dataclasses.replace(
        result.data_model,
        fields=_seq_replace(result.data_model.fields, new_fields),
        tables=_seq_replace(result.data_model.tables, new_tables),
        sections=_seq_replace(result.data_model.sections, new_sections),
    )
    result = dataclasses.replace(result, data_model=new_data_model)

    # VisibilityEntry.stage, and .section too when it names this stage's own implicit default
    # section (the common shape: a field with section=None resolves to its stage's name, and a
    # VisibilityEntry governing that whole section spells the SAME string out explicitly).
    new_entries = [
        dataclasses.replace(e, stage=_swap(e.stage), section=_swap(e.section))
        for e in _seq(result.visibility)
    ]
    result = dataclasses.replace(result, visibility=_seq_replace(result.visibility, new_entries))

    # Every test case's expected_path (a tuple of stage names) and each StepFill's own .stage.
    new_cases = []
    for case in _seq(result.test_cases):
        new_fills = [
            dataclasses.replace(fill, stage=new_name) if fill.stage == old_name else fill
            for fill in _seq(case.fills)
        ]
        new_cases.append(
            dataclasses.replace(
                case,
                expected_path=tuple(_swap(s) for s in case.expected_path),
                fills=_seq_replace(case.fills, new_fills),
            )
        )
    result = dataclasses.replace(result, test_cases=_seq_replace(result.test_cases, new_cases))

    return result


def _revise_routing_target(
    spec: AppSpecLike, at_stage: str, option: str, new_target: str
) -> AppSpecLike:
    """M9 fix: the option-existence check used to sit INSIDE the per-routing-point loop, so a
    SIBLING decision point at the same stage that legitimately lacks `option` (two decision
    points commonly ask about two different fields) raised first, on the first mismatch, making
    the post-loop check below dead code -- on any spec with two decision points sharing a stage,
    this raised on every call, including the mis-cased-literal fix these questions exist to
    elicit. Now: every routing point at `at_stage` is checked for the option; those that HAVE it
    are revised, those that don't are left untouched (not an error -- a sibling simply doesn't
    concern this option); only if NONE of them have it does this raise, after checking them all.
    """
    routing_seq = _seq(spec.routing)
    if not any(rp.at_stage == at_stage for rp in routing_seq):
        raise ValueError(f"no routing point at stage {at_stage!r} in this spec")
    new_routing = []
    matched = False
    for rp in routing_seq:
        mapping = dict(rp.route_per_option)
        if rp.at_stage != at_stage or option not in mapping:
            new_routing.append(rp)
            continue
        matched = True
        mapping[option] = (new_target,)  # a route value is a stage SEQUENCE now (P1); this v1
        # revision grammar still names a single target, so it becomes a one-element sequence.
        new_routing.append(
            dataclasses.replace(rp, route_per_option=_mapping_like(rp.route_per_option, mapping))
        )
    if not matched:
        raise ValueError(f"no option {option!r} at any routing point on stage {at_stage!r}")
    return dataclasses.replace(spec, routing=_seq_replace(spec.routing, new_routing))


def _revise_routing_option(
    spec: AppSpecLike, at_stage: str, old_option: str, new_option: str
) -> AppSpecLike:
    """Rename the OPTION LITERAL itself (e.g. fixing a mis-cased value), preserving its target --
    distinct from `_revise_routing_target`, which changes where an (unchanged) option routes to.

    M9 fix: see `_revise_routing_target`'s docstring for the same bug (raise-inside-the-loop
    making the post-loop `matched` check dead code) fixed the same way here.
    """
    routing_seq = _seq(spec.routing)
    if not any(rp.at_stage == at_stage for rp in routing_seq):
        raise ValueError(f"no routing point at stage {at_stage!r} in this spec")
    new_routing = []
    matched = False
    for rp in routing_seq:
        if rp.at_stage != at_stage or old_option not in rp.options:
            new_routing.append(rp)
            continue
        matched = True
        new_options = tuple(new_option if o == old_option else o for o in rp.options)
        mapping = dict(rp.route_per_option)
        if old_option in mapping:
            mapping[new_option] = mapping.pop(old_option)
        new_routing.append(
            dataclasses.replace(
                rp,
                options=new_options,
                route_per_option=_mapping_like(rp.route_per_option, mapping),
            )
        )
    if not matched:
        raise ValueError(f"no option {old_option!r} at any routing point on stage {at_stage!r}")
    return dataclasses.replace(spec, routing=_seq_replace(spec.routing, new_routing))


def _revise_loop_attr(
    spec: AppSpecLike, from_stage: str, to_stage: str, attr: str, value: str
) -> AppSpecLike:
    loops_seq = _seq(spec.rework_loops)
    if not any(lp.from_stage == from_stage and lp.to_stage == to_stage for lp in loops_seq):
        raise ValueError(f"no loop {from_stage!r} -> {to_stage!r} in this spec")
    new_loops = [
        dataclasses.replace(lp, **{attr: value})
        if lp.from_stage == from_stage and lp.to_stage == to_stage
        else lp
        for lp in loops_seq
    ]
    return dataclasses.replace(spec, rework_loops=_seq_replace(spec.rework_loops, new_loops))


def _parse_bool_token(value: str, *, key_desc: str) -> bool:
    token = value.strip().lower()
    if token in ("true", "yes", "1", "required"):
        return True
    if token in ("false", "no", "0", "optional"):
        return False
    raise ValueError(f"cannot parse {value!r} as {key_desc} (use true/false)")


def _revise_field_required(spec: AppSpecLike, stage: str, name: str, value: str) -> AppSpecLike:
    fields_seq = _seq(spec.data_model.fields)
    if not any(f.stage == stage and f.name == name for f in fields_seq):
        raise ValueError(f"no field named {name!r} at stage {stage!r} in this spec")
    required = _parse_bool_token(value, key_desc="a required flag")
    new_fields = [
        dataclasses.replace(f, required=required) if f.stage == stage and f.name == name else f
        for f in fields_seq
    ]
    new_dm = dataclasses.replace(
        spec.data_model, fields=_seq_replace(spec.data_model.fields, new_fields)
    )
    return dataclasses.replace(spec, data_model=new_dm)


def _revise_field_rename(
    spec: AppSpecLike, stage: str, old_name: str, new_name: str
) -> AppSpecLike:
    """Renames only the FieldReq's own `.name`. KNOWN DEFECT, not merely an omission: a field name
    is referenced from FIVE other places -- a routing point's `field_name`, a loop's `gate_field`,
    a `ComputedReq`'s target/source, a `VisibilityEntry.field`, and the keys of every `StepFill`'s
    values -- and none is cascaded, so if the renamed field is named by ANY of them the returned
    spec is one `compile_spec()` REJECTS. That contradicts `apply_revisions`' own contract above
    (a revision must never hand back an uncompilable spec); the honest reading is that this key is
    safe only for a field nothing else references. Same class as the stage-rename and list-value
    cascades, which were fixed; this one is not. Verify with `compile_spec()` after using it."""
    fields_seq = _seq(spec.data_model.fields)
    if not any(f.stage == stage and f.name == old_name for f in fields_seq):
        raise ValueError(f"no field named {old_name!r} at stage {stage!r} in this spec")
    new_fields = [
        dataclasses.replace(f, name=new_name) if f.stage == stage and f.name == old_name else f
        for f in fields_seq
    ]
    new_dm = dataclasses.replace(
        spec.data_model, fields=_seq_replace(spec.data_model.fields, new_fields)
    )
    return dataclasses.replace(spec, data_model=new_dm)


def _revise_list_value(
    spec: AppSpecLike, list_name: str, old_value: str, new_value: str
) -> AppSpecLike:
    """M11 fix: renaming a list value in isolation used to desynchronize the spec from itself --
    any Select field backed by this list that ALSO drives a routing point still tested the OLD
    literal (compile.py's `_check_routing_literals` then raises: the option no longer matches any
    value in the renamed list), and any test case filling that field with the old literal would
    fail `_check_test_cases` the same way. Cascades into both: a routing point's `options`/
    `route_per_option` key, and every StepFill value, for any field whose `list_name` names this
    list -- proven against a real AppSpec via the cross-tree verification script's post-revision
    `compile_spec()` assertion.
    """
    lists_seq = _seq(spec.master_data.lists)
    match = next((lst for lst in lists_seq if lst.name == list_name), None)
    if match is None:
        raise ValueError(f"no list named {list_name!r} in this spec")
    values = list(_seq(match.values))
    if old_value not in values:
        raise ValueError(f"no value {old_value!r} in list {list_name!r}")
    new_values = [new_value if v == old_value else v for v in values]
    new_list = dataclasses.replace(match, values=_seq_replace(match.values, new_values))
    new_lists = [new_list if lst.name == list_name else lst for lst in lists_seq]
    new_md = dataclasses.replace(
        spec.master_data, lists=_seq_replace(spec.master_data.lists, new_lists)
    )
    result = dataclasses.replace(spec, master_data=new_md)

    backed_field_names = {
        f.name for f in _seq(result.data_model.fields) if getattr(f, "list_name", None) == list_name
    }
    if not backed_field_names:
        return result

    new_routing = []
    for rp in _seq(result.routing):
        if rp.field_name not in backed_field_names or old_value not in rp.options:
            new_routing.append(rp)
            continue
        new_options = tuple(new_value if o == old_value else o for o in rp.options)
        mapping = dict(rp.route_per_option)
        if old_value in mapping:
            mapping[new_value] = mapping.pop(old_value)
        new_routing.append(
            dataclasses.replace(
                rp,
                options=new_options,
                route_per_option=_mapping_like(rp.route_per_option, mapping),
            )
        )
    result = dataclasses.replace(result, routing=_seq_replace(result.routing, new_routing))

    new_cases = []
    for case in _seq(result.test_cases):
        new_fills = []
        for fill in _seq(case.fills):
            fv = dict(fill.values)
            changed = False
            for fname in backed_field_names:
                if fv.get(fname) == old_value:
                    fv[fname] = new_value
                    changed = True
            new_fills.append(
                dataclasses.replace(fill, values=_mapping_like(fill.values, fv))
                if changed
                else fill
            )
        new_cases.append(dataclasses.replace(case, fills=_seq_replace(case.fills, new_fills)))
    result = dataclasses.replace(result, test_cases=_seq_replace(result.test_cases, new_cases))

    return result


def _revise_table_max_rows(spec: AppSpecLike, table_name: str, value: str) -> AppSpecLike:
    tables_seq = _seq(spec.data_model.tables)
    match = next((t for t in tables_seq if t.name == table_name), None)
    if match is None:
        raise ValueError(f"no table named {table_name!r} in this spec")
    token = value.strip().lower()
    if token in ("none", "no cap", "nocap", ""):
        new_max: int | None = None
    else:
        try:
            new_max = int(value)
        except ValueError:
            raise ValueError(
                f"cannot parse {value!r} as a row cap (use an integer, or 'none' for no cap)"
            ) from None
    new_table = dataclasses.replace(match, max_rows=new_max)
    new_tables = [new_table if t.name == table_name else t for t in tables_seq]
    new_dm = dataclasses.replace(
        spec.data_model, tables=_seq_replace(spec.data_model.tables, new_tables)
    )
    return dataclasses.replace(spec, data_model=new_dm)
