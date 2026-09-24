"""
app.application.design.mockup -- self-contained HTML the business owner can open in
any browser.

No external assets: one inline `<style>` block, no `<link>`/`<script src>` to
anywhere, no CDN fonts -- everything a caller needs is in the single string these
functions return. Every function is READ-ONLY over its `spec` argument (duck-typed
per app.application.design.AppSpecLike; see the package docstring for why this never
imports app.application.intake) and never touches the network. Collection access
goes through `app.application.design.diagram._seq()` throughout, so a wrapped
dimension (app.application.intake.schema's
`Stages`/`Routing`/`ReworkLoops`/`TestCases`/`VisibilityMatrix`) and a bare sequence
(this package's own minimal protocol / a caller's stub) both work unchanged.

FAITHFUL, not just legible, is the actual design goal: a first review round proved
that a field the built app HIDES (or makes read-only) at a step, and a field the app
COMPUTES rather than lets the user type, both used to render as a plain live input
-- indistinguishable from an ordinary editable field. That is strictly worse than
omitting the field: it invites the customer to approve a form that does not match
what gets built. Every field row here resolves its EFFECTIVE permission
(`_effective_permission`, the same field-then-section resolution
app.application.intake. compile._check_required_fields_editable uses) and whether it
is a computed target (`DataModel.computed`) BEFORE deciding how to render it. Select
controls render their ACTUAL options, read from the backing master-data list -- not
a generic placeholder; a mis-cased option value is exactly the live bug class
CLAUDE.md's own "THE RULE" section describes, and the whole point of this module is
to put it somewhere a human proofreads it before a write API call is ever made.
Fields are grouped by their resolved SectionReq (not flattened to one
undifferentiated per-stage list), tables respect the same visibility lever a field's
section does, and a plain- language process summary gives a non-technical reader the
DECISION/LOOP/END-STATE design, not only the data-entry design -- distinguishing the
business's own DECLARED end states/outcomes from the topology-DERIVED list this
module computes on its own. Thai-friendly throughout -- UTF-8 declared, a font stack
that includes a Thai-capable family (confirm.py's own questions are written in Thai
for the same reason; this module's own structural/glue text stays English, matching
the rest of the package, while business text embedded from the spec is rendered
verbatim in whatever language it was written in).
"""

from __future__ import annotations

import dataclasses
import html
from typing import TYPE_CHECKING, Any

from app.application.use_cases.design._diagram import (
    _loop_direction,
    _max_rows_label,
    _seq,
    _stage_index,
    _terminal_stages,
    flow_diagram_xml,
    schema_diagram_xml,
)

if TYPE_CHECKING:
    from app.application.use_cases.design._bundle import (
        AppSpecLike,
        ComputedLike,
        FieldLike,
        PageLike,
        PersonaViewLike,
        SectionLike,
        StageLike,
        TableLike,
    )

_HIDDEN, _READONLY, _EDITABLE = "Hidden", "ReadOnly", "Editable"

_CSS = (
    """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body {
  margin: 0; padding: 24px; background: #f4f6f8; color: #1f2933;
  font-family: "Noto Sans Thai", "Leelawadee UI", "Segoe UI", Tahoma, Arial, sans-serif;
  line-height: 1.5;
}
.kf-design { max-width: 1100px; margin: 0 auto; }
h1 { font-size: 1.6rem; margin: 0 0 4px; }
h2 { font-size: 1.2rem; margin: 32px 0 12px; border-bottom: 2px solid #cbd5e0; """
    """padding-bottom: 6px; }
h3 { font-size: 1.05rem; margin: 16px 0 8px; }
h4 { font-size: 0.95rem; margin: 0 0 8px; }
.kf-card-grid, .kf-page-grid {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 16px;
}
.kf-card, .kf-page, .kf-table, .kf-list {
  background: #ffffff; border: 1px solid #d7dee5; border-radius: 10px; padding: 16px;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.06);
}
.kf-card.kf-offspine { border-style: dashed; border-color: #d6b656; background: """
    """#fffdf5; }
.kf-owner { display: inline-block; background: #e6f0ff; color: #1d4ed8; """
    """border-radius: 999px;
  padding: 2px 10px; font-size: 0.8rem; margin: 4px 0 8px; }
.kf-what { font-size: 0.88rem; color: #52606d; margin: 0 0 12px; }
.kf-fields { display: flex; flex-direction: column; gap: 10px; }
.kf-field { display: flex; flex-direction: column; gap: 4px; font-size: 0.88rem; """
    """font-weight: 600; }
.kf-field-hidden, .kf-field-computed { font-size: 0.88rem; font-weight: 600; """
    """padding: 4px 0; }
.kf-field input, .kf-field select, .kf-field textarea {
  font: inherit; padding: 7px 9px; border: 1px solid #cbd5e0; border-radius: """
    """6px; background: #fbfcfd;
}
.kf-field input[type="checkbox"] { width: 18px; height: 18px; align-self: flex-start; }
.kf-field input:disabled, .kf-field select:disabled, .kf-field textarea:disabled {
  opacity: 0.65; background: #eef1f4; }
.required-marker { color: #c0392b; margin-left: 2px; }
.kf-field-type { font-weight: 400; color: #7b8794; font-size: 0.82rem; }
.kf-type-warning { color: #c0392b; font-size: 0.72rem; font-weight: 700; }
.kf-permission-tag { display: inline-block; background: #fef3c7; color: #92400e; """
    """border-radius: 999px;
  padding: 1px 8px; font-size: 0.72rem; font-weight: 700; margin-left: 4px; }
.kf-field-hidden .kf-permission-tag { background: #fee2e2; color: #991b1b; }
.kf-field-computed .kf-permission-tag { background: #dbeafe; color: #1e40af; }
.kf-computed-intent { font-size: 0.8rem; color: #52606d; font-weight: 400; """
    """margin: 4px 0 0; }
.kf-section { border-top: 1px dashed #d7dee5; margin-top: 10px; padding-top: 10px; }
.kf-section:first-child { border-top: none; margin-top: 0; padding-top: 0; }
.kf-section-name { margin: 0 0 2px; }
.kf-section-desc { font-size: 0.8rem; color: #52606d; margin: 0 0 8px; }
.kf-sequence-note { font-size: 0.85rem; color: #1d4ed8; font-weight: 600; """
    """margin: 0 0 16px; }
.kf-tables, .kf-master-data, .kf-process { margin-top: 8px; }
.kf-table.kf-table-hidden { border-style: dashed; }
table { border-collapse: collapse; width: 100%; margin-top: 6px; font-size: 0.85rem; }
th, td { border: 1px solid #d7dee5; padding: 6px 8px; text-align: left; }
th { background: #eef2f6; }
.kf-rowcap { font-size: 0.8rem; color: #52606d; margin: 8px 0 0; }
.kf-list-values { font-size: 0.85rem; color: #1f2933; word-break: break-word; }
.kf-kpi-row { display: flex; flex-wrap: wrap; gap: 8px; margin: 8px 0; }
.kf-kpi { background: #f0fdf4; border: 1px solid #bbf7d0; color: #166534; """
    """border-radius: 8px;
  padding: 6px 10px; font-size: 0.82rem; font-weight: 600; }
.kf-actions { display: flex; flex-wrap: wrap; gap: 8px; margin: 8px 0; }
.kf-actions button { font: inherit; background: #1d4ed8; color: #fff; border: none;
  border-radius: 6px; padding: 7px 12px; cursor: pointer; }
.kf-widgets { margin: 8px 0 0; padding-left: 18px; font-size: 0.82rem; color: #52606d; }
.kf-decisions ul, .kf-loops ul, .kf-terminals ul { font-size: 0.88rem; """
    """padding-left: 20px; }
.kf-decisions li, .kf-loops li { margin-bottom: 6px; }
.kf-declared { font-weight: 700; margin: 4px 0; }
.kf-derived { font-size: 0.8rem; color: #7b8794; margin: 10px 0 4px; }
.kf-diagrams details { background: #fff; border: 1px solid #d7dee5; border-radius: 10px;
  padding: 10px 14px; margin-bottom: 10px; }
.kf-diagrams pre { overflow-x: auto; font-size: 0.75rem; background: #0f172a; """
    """color: #e2e8f0;
  padding: 12px; border-radius: 8px; }
@media (max-width: 480px) {
  body { padding: 12px; }
  .kf-card, .kf-page, .kf-table, .kf-list { padding: 12px; }
}
"""
)

_TEXT_LIKE_CONTROL: dict[str, Any] = {
    "Text": lambda d: f'<input type="text"{d}>',
    "Textarea": lambda d: f'<textarea rows="3"{d}></textarea>',
    "Number": lambda d: f'<input type="number"{d}>',
    "Date": lambda d: f'<input type="date"{d}>',
    "Boolean": lambda d: f'<input type="checkbox"{d}>',
    "Attachment": lambda d: f'<input type="file"{d}>',
}
# M5: every type this module renders a DEDICATED control for. Anything else (e.g.
# "User") still gets a usable fallback (a plain text input) but is flagged in the field
# row -- a first review round proved an unmapped type rendered pixel-identical to Text,
# giving the customer nothing to notice.
_KNOWN_TYPES = frozenset(_TEXT_LIKE_CONTROL) | {"Select"}


@dataclasses.dataclass(frozen=True)
class _OffSpineStage:
    """
    A synthetic stand-in for a stage name that owns fields but never appears in
    `spec.stages` (e.g. an off-spine routing terminal like "Closed - Rejected").
    Exists purely so `_stage_card` has a StageLike-shaped object to render without
    silently dropping those fields (major 3).
    """

    name: str
    owner_role: str
    what_happens: str


def _label(item: Any) -> str:
    """
    Best-effort human label for an item whose exact shape the protocol leaves open
    (kpis/ actions are plain strings on the real PersonaView, but this stays
    defensive against a richer object too) -- prefer `.name` if present, else str().
    """
    name = getattr(item, "name", None)
    return str(name) if name is not None else str(item)


def _widget_label(w: Any) -> str:
    """
    Human label + plain-words binding for one page widget.

    app.application.intake.schema.WidgetIntent has no `.name` -- it is identified by
    `.slug` (the Script.web string, e.g. "view/table") plus `.config` (key/value
    binding pairs) and `.row_fields` (repeater's own extra config). Falling back to
    the generic `_label()` here would leak a raw `WidgetIntent(slug=..., config=...,
    row_fields=...)` dataclass repr once a real spec reaches this code (minor 14) --
    `.slug` is checked FIRST and formatted with its binding in plain words; `.name`
    (this package's own minimal protocol) and a bare string both still work as
    fallbacks.
    """
    slug = getattr(w, "slug", None)
    if slug is not None:
        cfg = dict(getattr(w, "config", ()) or ())
        bits = [f"{k}: {v}" for k, v in cfg.items()]
        row_fields = _seq(getattr(w, "row_fields", ()) or ())
        if row_fields:
            bits.append("rows: " + ", ".join(str(r) for r in row_fields))
        return f"{slug} ({'; '.join(bits)})" if bits else str(slug)
    name = getattr(w, "name", None)
    return str(name) if name is not None else str(w)


def _effective_permission(spec: AppSpecLike, field: FieldLike) -> str | None:
    """
    The field's effective visibility permission at its OWN stage, resolved the same
    way app.application.intake.compile._check_required_fields_editable does: a
    field-level VisibilityEntry (same stage, `.field == this field's name`) wins if
    present; else the entry for its resolved SECTION (explicit `.section`, or the
    stage's own implicit default) at that stage, with `.field is None`; else `None`
    -- no entry at all, rendered the same as the platform default (an ordinary
    editable control), matching app.application.intake.schema's own documented
    semantics for an unmentioned field.

    Blocker 1: with none of this applied, a Hidden field rendered as a plain live
    input -- the customer proofread a form containing a field the built app actually
    hides.
    """
    section = getattr(field, "section", None) or field.stage
    entries = _seq(spec.visibility)
    field_entry = next(
        (e for e in entries if e.stage == field.stage and e.field == field.name),
        None,
    )
    if field_entry is not None:
        return str(field_entry.permission)
    section_entry = next(
        (
            e
            for e in entries
            if e.stage == field.stage and e.section == section and e.field is None
        ),
        None,
    )
    return str(section_entry.permission) if section_entry is not None else None


def _table_permission(spec: AppSpecLike, table: TableLike) -> str | None:
    """
    A table is ALSO a legal `VisibilityEntry.section` target
    (app.application.intake.compile. _section_names: a TableReq is its own
    banner+table pairing), so a table can be hidden or made read-only at a step
    exactly like a field's section can -- looked up the same way a section- level
    (not field-level) entry is.
    """
    table_stage = getattr(table, "stage", None)
    entries = _seq(spec.visibility)
    entry = next(
        (
            e
            for e in entries
            if e.stage == table_stage and e.section == table.name and e.field is None
        ),
        None,
    )
    return str(entry.permission) if entry is not None else None


def _select_control(
    field: FieldLike, lists_by_name: dict[str, tuple[str, ...]], *, disabled: str = ""
) -> str:
    """
    A real `<select>` with the field's ACTUAL options, read from the master-data
    list its `.list_name` names (app.application.intake.schema.FieldReq.list_name)
    -- blocker 2 (round 1): a generic "-- select --" placeholder gives a
    proof-reader nothing to check, and a mis-cased option value is exactly
    CLAUDE.md's own live bug class. `list_name` is read defensively (this package's
    own minimal protocol does not require it); an unresolvable or absent list_name
    falls back to just the placeholder rather than crashing -- the field is still
    visibly a dropdown, it is simply missing its backing list, which is itself worth
    the reader noticing.
    """
    list_name = getattr(field, "list_name", None)
    values = lists_by_name.get(list_name, ()) if list_name else ()
    options = "".join(
        f'<option value="{html.escape(str(v))}">{html.escape(str(v))}</option>'
        for v in values
    )
    return f'<select{disabled}><option value="">-- select --</option>{options}</select>'


def _field_control(
    field: FieldLike,
    lists_by_name: dict[str, tuple[str, ...]],
    *,
    readonly: bool = False,
) -> str:
    """
    A real HTML control for the field's `.type`, disabled when the field's effective
    permission is ReadOnly. An unmapped type still gets a usable (plain text)
    control -- this is a mockup, not a validator -- but `_field_row` flags it
    separately in words (M5), rather than letting it render pixel-identical to a
    real Text field.
    """
    kind = str(field.type)
    d = " disabled" if readonly else ""
    if kind == "Select":
        return _select_control(field, lists_by_name, disabled=d)
    builder = _TEXT_LIKE_CONTROL.get(kind)
    if builder is not None:
        return builder(d)
    return f'<input type="text"{d}>'


def _field_row(
    f: FieldLike,
    lists_by_name: dict[str, tuple[str, ...]],
    spec: AppSpecLike,
    computed_by_target: dict[str, ComputedLike],
) -> str:
    """
    One field's row, in priority order: a COMPUTED target (blocker 2: never a live
    input the user types into, always shown as auto-calculated with its
    formula_intent) : a HIDDEN field (blocker 1: no editable control at all, shown
    as explicitly hidden) : an ordinary field (real control, disabled + tagged when
    ReadOnly). The type is always stated in words (M5), with an extra warning when
    it has no dedicated control here.
    """
    kind = str(f.type)
    marker = ' <span class="required-marker">*</span>' if f.required else ""
    type_tag = f' <span class="kf-field-type">({html.escape(kind)})</span>'
    if kind not in _KNOWN_TYPES:
        type_tag += (
            ' <span class="kf-type-warning">no dedicated control for this type</span>'
        )
    label_html = f"{html.escape(f.name)}{marker}{type_tag}"

    # a field row's wrapper tag varies (label for an ordinary control, div for
    # hidden/computed) -- this marker lets a caller (a test, or any other tool)
    # locate ANY field's own row unambiguously regardless of which one it is.
    marker = f"<!-- field:{html.escape(f.name)} -->"

    computed = computed_by_target.get(f.name)
    if computed is not None:
        sources = ", ".join(str(s) for s in _seq(computed.source_fields))
        source_note = f" (from {html.escape(sources)})" if sources else ""
        return (
            f'{marker}<div class="kf-field kf-field-computed">{label_html} '
            f'<span class="kf-permission-tag">auto-calculated</span>'
            f'<p class="kf-computed-intent">'
            f"{html.escape(computed.formula_intent)}{source_note}</p>"
            f"</div>"
        )

    effective = _effective_permission(spec, f)
    if effective == _HIDDEN:
        return (
            f'{marker}<div class="kf-field kf-field-hidden">{label_html} '
            f'<span class="kf-permission-tag">hidden at this step</span></div>'
        )

    readonly = effective == _READONLY
    control = _field_control(f, lists_by_name, readonly=readonly)
    perm_tag = ' <span class="kf-permission-tag">read-only</span>' if readonly else ""
    return f'{marker}<label class="kf-field">{label_html}{perm_tag}{control}</label>'


def _html_shell(title: str, body: str) -> str:
    return (
        "<!doctype html>"
        '<html lang="th"><head>'
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{html.escape(title)}</title>"
        f"<style>{_CSS}</style>"
        "</head><body>"
        f'<div class="kf-design"><h1>{html.escape(title)}</h1>{body}</div>'
        "</body></html>"
    )


def _stage_card(
    stage: StageLike,
    fields: list[FieldLike],
    lists_by_name: dict[str, tuple[str, ...]],
    spec: AppSpecLike,
    sections_by_name: dict[str, SectionLike],
    computed_by_target: dict[str, ComputedLike],
    *,
    off_spine: bool = False,
) -> str:
    """
    Fields are grouped by their RESOLVED section (M3: `.section` when explicitly
    set, else the stage's own implicit default) -- a stage with two explicit
    SectionReq's used to render as one undifferentiated card, and the section's own
    `.name`/`.description` is now shown for any group that is a real,
    distinctly-named SectionReq (the implicit default section gets no redundant
    sub-heading, since the card's own heading already names the stage).
    """
    groups: dict[str, list[FieldLike]] = {}
    order: list[str] = []
    for f in fields:
        sec_name = getattr(f, "section", None) or stage.name
        if sec_name not in groups:
            groups[sec_name] = []
            order.append(sec_name)
        groups[sec_name].append(f)

    blocks = []
    for sec_name in order:
        rows = "".join(
            _field_row(f, lists_by_name, spec, computed_by_target)
            for f in groups[sec_name]
        )
        sec = sections_by_name.get(sec_name)
        if sec is not None and sec_name != stage.name:
            blocks.append(
                f'<div class="kf-section">'
                f'<h4 class="kf-section-name">{html.escape(sec.name)}'
                f'</h4><p class="kf-section-desc">{html.escape(sec.description)}</p>'
                f'<div class="kf-fields">{rows}</div></div>'
            )
        else:
            blocks.append(f'<div class="kf-fields">{rows}</div>')

    card_class = "kf-card kf-offspine" if off_spine else "kf-card"
    return (
        f"<!-- stage:{html.escape(stage.name)} -->"
        f'<div class="{card_class}">'
        f"<h3>{html.escape(stage.name)}</h3>"
        f'<span class="kf-owner">{html.escape(stage.owner_role)}</span>'
        f'<p class="kf-what">{html.escape(stage.what_happens)}</p>'
        f"{''.join(blocks)}"
        "</div>"
    )


def _column_header_label(col: Any) -> str:
    """
    "name : type" (+ "*" when required) -- M4: matches diagram._column_label's
    convention exactly. These two used to disagree (this function showed
    name+required only; the schema diagram already showed type), so the SAME table
    column read differently depending on which artifact the customer happened to
    open.
    """
    name = getattr(col, "name", None)
    if name is None:
        return _label(col)
    ctype = getattr(col, "type", None)
    label = f"{name} : {ctype}" if ctype is not None else str(name)
    if getattr(col, "required", False):
        label += " *"
    return label


def _table_grid(table: TableLike, spec: AppSpecLike) -> str:
    permission = _table_permission(spec, table)
    if permission == _HIDDEN:
        return (
            f"<!-- table:{html.escape(table.name)} -->"
            '<div class="kf-table kf-table-hidden">'
            f"<h4>{html.escape(table.name)}</h4>"
            '<p class="kf-permission-tag">hidden at this step</p></div>'
        )
    cols = [_column_header_label(c) for c in _seq(table.columns)]
    header = "".join(f"<th>{html.escape(c)}</th>" for c in cols)
    blank_row = "".join("<td></td>" for _ in cols) or "<td></td>"
    perm_tag = (
        ' <span class="kf-permission-tag">read-only</span>'
        if permission == _READONLY
        else ""
    )
    return (
        f"<!-- table:{html.escape(table.name)} -->"
        '<div class="kf-table">'
        f"<h4>{html.escape(table.name)}{perm_tag}</h4>"
        f"<table><thead><tr>{header}</tr></thead>"
        f"<tbody><tr>{blank_row}</tr></tbody></table>"
        f'<p class="kf-rowcap">Max rows: '
        f"{html.escape(_max_rows_label(table.max_rows))}</p>"
        "</div>"
    )


def _master_data_section(lists: list[Any]) -> str:
    """
    Every reference list and its values, verbatim and visible -- blocker 2 (round
    1): a list's values used to reach no artifact a customer actually reads (only
    the schema diagram's raw XML), so nothing prompted a byte-exact proofread of
    exactly the values CLAUDE.md's own bug class hinges on.
    """
    items = []
    for lst in lists:
        values = ", ".join(str(v) for v in _seq(lst.values))
        items.append(
            f"<!-- list:{html.escape(lst.name)} -->"
            f'<div class="kf-list"><h4>{html.escape(lst.name)}</h4>'
            f'<p class="kf-list-values">{html.escape(values)}</p></div>'
        )
    return (
        f'<section class="kf-master-data"><h2>Reference lists</h2>'
        f"{''.join(items)}</section>"
    )


def _format_sequence(prefix: Any, padding: Any) -> str:
    """Join a SequenceNumber prefix and zero-padding with exactly one separator.

    A prefix may already end with the separator (e.g. `"RPT-"` -- decision_01 item 2);
    re-joining with another dash double-wires it into `RPT--0001`. Normalize
    the trailing dash once, then splice the single separator."""
    return f"{str(prefix).rstrip('-')}-{padding}"


def _sequence_note(seq: Any) -> str:
    """
    M7: `DataModel.sequence` (prefix + zero-padding) renders nowhere before this,
    yet it is the record id every user of the built app actually sees. Shown once,
    near the top of the form mockups, since it applies across the whole app rather
    than one stage.
    """
    prefix, padding = seq.prefix, seq.padding
    try:
        next_val = str(int(padding) + 1).zfill(len(padding))
        example = (
            f"{_format_sequence(prefix, padding)}, "
            f"{_format_sequence(prefix, next_val)}, ..."
        )
    except (ValueError, TypeError):
        example = _format_sequence(prefix, padding)
    return (
        f'<p class="kf-sequence-note">Record ID (auto-numbered): '
        f"{html.escape(example)}</p>"
    )


def _process_summary_body(spec: AppSpecLike) -> str:
    """
    Plain-language process design -- major 4 (round 1): without this, a
    non-technical reader only sees the data-entry design (fields/controls) and none
    of the PROCESS design (where a decision sends the item, what a rework-loop gate
    checkbox actually does, where the work ends). Empty when the spec has nothing to
    describe on any of those fronts.

    M6 (round 2): "where the work ends" now shows the business's OWN declared answer
    (`ProblemGoal.terminal_states`/`.result_values`) FIRST, clearly labeled as
    declared, with the topology-DERIVED list (`diagram._terminal_stages`) shown
    separately and labeled as derived -- the two used to be conflated under one
    heading that silently answered a different question than its own title asked.
    """
    routing = _seq(spec.routing)
    loops = _seq(spec.rework_loops)
    derived_terminals = _terminal_stages(spec)
    declared_terminals = _seq(spec.problem_goal.terminal_states)
    declared_results = _seq(spec.problem_goal.result_values)
    if not (
        routing or loops or derived_terminals or declared_terminals or declared_results
    ):
        return ""

    idx = _stage_index(spec)
    parts = ['<section class="kf-process"><h2>How the process moves</h2>']

    if routing:
        items = []
        for rp in routing:
            mapping = dict(rp.route_per_option)
            # A branch is a stage SEQUENCE now (P1); render it "A → B → C". A
            # one-element route renders as the bare stage name, exactly as the
            # single-stage shape used to.
            option_rows = []
            for option in rp.options:
                target = html.escape(
                    " → ".join(mapping.get(option) or ["not yet specified"])
                )
                option_rows.append(
                    f"<li>&ldquo;{html.escape(option)}&rdquo; &rarr; "
                    f"&ldquo;{target}&rdquo;</li>"
                )
            option_lines = "".join(option_rows)
            items.append(
                f"<li>At <strong>{html.escape(rp.at_stage)}</strong>, the field "
                f"&ldquo;{html.escape(rp.field_name)}&rdquo; decides where the "
                f"item goes next:"
                f"<ul>{option_lines}</ul></li>"
            )
        parts.append(
            f'<div class="kf-decisions"><h3>Decisions</h3>'
            f"<ul>{''.join(items)}</ul></div>"
        )

    if loops:
        direction_note = {
            "forward": "goes forward, not back",
            "self": "loops to itself",
            "unknown": "direction unclear",
        }
        items = []
        for lp in loops:
            direction = _loop_direction(idx, lp)
            if direction == "backward":
                meaning = (
                    f"while &ldquo;{html.escape(lp.gate_field)}&rdquo; is NOT "
                    f"ticked, the item loops back to "
                    f"<strong>{html.escape(lp.to_stage)}</strong> for another "
                    f"round; ticking it lets the item move on"
                )
            else:
                meaning = (
                    f"NOTE: this is not a normal rework loop "
                    f"({direction_note[direction]}) -- please check it"
                )
            items.append(
                f"<li>From <strong>{html.escape(lp.from_stage)}</strong> to "
                f"<strong>{html.escape(lp.to_stage)}</strong>, gated on "
                f"&ldquo;{html.escape(lp.gate_field)}&rdquo;: {meaning}</li>"
            )
        parts.append(
            f'<div class="kf-loops"><h3>Rework loops</h3>'
            f"<ul>{''.join(items)}</ul></div>"
        )

    if declared_terminals or declared_results or derived_terminals:
        block = ['<div class="kf-terminals"><h3>Where the work ends</h3>']
        if declared_terminals or declared_results:
            block.append('<p class="kf-declared">Declared by the business:</p><ul>')
            if declared_terminals:
                names = ", ".join(
                    f"&ldquo;{html.escape(n)}&rdquo;" for n in declared_terminals
                )
                block.append(f"<li>End states: {names}</li>")
            if declared_results:
                names = ", ".join(
                    f"&ldquo;{html.escape(n)}&rdquo;" for n in declared_results
                )
                block.append(f"<li>Possible outcomes: {names}</li>")
            block.append("</ul>")
        if derived_terminals:
            names = "".join(
                f"<li>&ldquo;{html.escape(n)}&rdquo;</li>" for n in derived_terminals
            )
            block.append(
                '<p class="kf-derived">For reference: stages the flow diagram shows '
                "nothing leaving (derived from routing/loops, not a declared "
                f"answer):</p><ul>{names}</ul>"
            )
        block.append("</div>")
        parts.append("".join(block))

    parts.append("</section>")
    return "".join(parts)


def _form_mockups_body(spec: AppSpecLike) -> str:
    stages = _seq(spec.stages)
    known_names = {st.name for st in stages}
    by_stage: dict[str, list[FieldLike]] = {}
    for f in _seq(spec.data_model.fields):
        by_stage.setdefault(f.stage, []).append(f)

    lists_by_name = {
        lst.name: tuple(_seq(lst.values)) for lst in _seq(spec.master_data.lists)
    }
    sections_by_name = {sec.name: sec for sec in _seq(spec.data_model.sections)}
    computed_by_target = {c.target_field: c for c in _seq(spec.data_model.computed)}

    cards = "".join(
        _stage_card(
            st,
            by_stage.get(st.name, []),
            lists_by_name,
            spec,
            sections_by_name,
            computed_by_target,
        )
        for st in stages
    )
    # Major 3 (round 1): a field whose .stage names something OTHER than a real spine
    # stage (an off-spine routing terminal, most commonly) must still get a visible card
    # -- silently dropping it is exactly the silent-omission failure the house
    # output-invariant rule forbids.
    off_spine_names = [name for name in by_stage if name not in known_names]
    for name in off_spine_names:
        pseudo = _OffSpineStage(
            name=name,
            owner_role="(off-spine)",
            what_happens=(
                "Reached only by a routing branch or loop; not part of the "
                "main sequence."
            ),
        )
        cards += _stage_card(
            pseudo,
            by_stage[name],
            lists_by_name,
            spec,
            sections_by_name,
            computed_by_target,
            off_spine=True,
        )

    body = ""
    sequence = getattr(spec.data_model, "sequence", None)
    if sequence is not None:
        body += _sequence_note(sequence)

    body += (
        '<section class="kf-stage-cards"><h2>Form, by stage</h2>'
        f'<div class="kf-card-grid">{cards}</div></section>'
    )

    tables = _seq(spec.data_model.tables)
    if tables:
        grids = "".join(_table_grid(t, spec) for t in tables)
        body += f'<section class="kf-tables"><h2>Tables</h2>{grids}</section>'

    lists = _seq(spec.master_data.lists)
    if lists:
        body += _master_data_section(lists)

    body += _process_summary_body(spec)
    return body


def form_mockups_html(spec: AppSpecLike) -> str:
    """
    One card per stage (including off-spine ones), fields grouped by their resolved
    section: a real input for the control type -- a Select's real options, its type
    stated in words, a required marker, hidden/read-only/computed fields rendered as
    such rather than as a plain editable control -- every table as a small grid
    noting its row cap (and respecting its own visibility), every reference list's
    values verbatim, the record-id format if one is set, and a plain-language
    process summary.
    """
    return _html_shell(f"{spec.app_name} -- form mockups", _form_mockups_body(spec))


def _page_block(page: PageLike) -> str:
    widgets = "".join(
        f"<li>{html.escape(_widget_label(w))}</li>" for w in _seq(page.widgets)
    )
    return (
        f"<!-- page:{html.escape(page.name)} -->"
        '<div class="kf-page">'
        f"<h4>{html.escape(page.name)}</h4>"
        f'<ul class="kf-widgets">{widgets}</ul>'
        "</div>"
    )


def _persona_section(view: PersonaViewLike) -> str:
    # KPIs and actions belong to the PersonaView (the role's whole dashboard intent),
    # not to any one PageIntent -- app.application.intake.schema.PersonaView carries
    # them directly; PageIntent only has name + widgets. Rendering them once per role
    # (not once per page) matches that shape.
    kpis = "".join(
        f'<div class="kf-kpi">{html.escape(_label(k))}</div>' for k in _seq(view.kpis)
    )
    actions = "".join(
        f'<button type="button">{html.escape(_label(a))}</button>'
        for a in _seq(view.actions)
    )
    pages = "".join(_page_block(p) for p in _seq(view.pages))
    return (
        f"<!-- persona:{html.escape(view.role)} -->"
        f'<section class="kf-persona"><h2>{html.escape(view.role)}</h2>'
        f'<div class="kf-kpi-row">{kpis}</div>'
        f'<div class="kf-actions">{actions}</div>'
        f'<div class="kf-page-grid">{pages}</div></section>'
    )


def _persona_pages_body(spec: AppSpecLike) -> str:
    return "".join(_persona_section(view) for view in _seq(spec.personas.views))


def persona_pages_html(spec: AppSpecLike) -> str:
    """
    Per persona (role): their KPI tiles and action buttons (both live on the role's
    own view, not per page), then each of their pages with its widget list.
    """
    return _html_shell(f"{spec.app_name} -- persona pages", _persona_pages_body(spec))


def design_bundle_html(spec: AppSpecLike) -> str:
    """
    One page combining the form mockups (including the process summary and
    master-data section) and the persona pages, plus both diagrams rendered as
    collapsed `<details>` blocks holding the raw draw.io XML in a `<pre>` -- so the
    business owner can read everything in one place, and a technical reader can copy
    either XML straight into draw.io.
    """
    flow_xml = flow_diagram_xml(spec)
    schema_xml = schema_diagram_xml(spec)
    diagrams = (
        '<section class="kf-diagrams"><h2>Diagrams (copy into draw.io)</h2>'
        "<details><summary>Flow diagram</summary>"
        f"<pre>{html.escape(flow_xml)}</pre></details>"
        "<details><summary>Schema diagram</summary>"
        f"<pre>{html.escape(schema_xml)}</pre></details>"
        "</section>"
    )
    body = _form_mockups_body(spec) + _persona_pages_body(spec) + diagrams
    return _html_shell(f"{spec.app_name} -- design bundle", body)
