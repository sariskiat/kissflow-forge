"""kfforge.design.diagram -- draw.io / mxGraph XML for the flow shape and the data shape.

Pure string building, stdlib only (`html.escape` for entity-safety) -- no dependency on draw.io
or any XML-writing library. The returned string is a complete `.drawio`-openable document; a
caller either saves it with a `.drawio` extension or pastes it into draw.io's Extras > Edit
Diagram. Every function here is READ-ONLY over its `spec` argument (duck-typed per
kfforge.design.AppSpecLike -- see the package docstring for why this never imports
kfforge.intake) and never touches the network or the Kissflow builder API.

Shape adapters (`_seq`/`_seq_replace`) live in this module because it is the one every other
kfforge.design submodule already imports from. kfforge.intake.schema.AppSpec (the real spec)
wraps every dimension's collection in its own frozen container -- `Stages.stages`,
`Routing.points`, `ReworkLoops.loops`, `TestCases.cases` -- rather than exposing a bare
tuple/list directly. This package's own minimal protocol never required that extra layer (a
caller's stub can hand over a bare sequence), so every collection access in this package goes
through `_seq()`, which accepts either shape. Nothing here hardcodes intake's wrapper attribute
names (`.stages`/`.points`/...): a wrapper is recognised generically as "a dataclass with exactly
one sequence-valued field" (true of every dimension wrapper today, including ones this package
doesn't touch), so a future 12th dimension's wrapper needs no code change here to be understood.

Layout is a small, deterministic heuristic, not a general graph-layout solver -- YAGNI for a
"confirm before you build" artifact a business owner skims once, not something driving a live
dashboard. Stage boxes run down a vertical spine at x=SPINE_X; the vertical step to the NEXT stage
grows when the current one hosts one or more routing points, so a decision diamond (or several,
stacked, if more than one routing point shares a stage) never overlaps the box below it. A routing
point's branch targets that are not already on the spine get their own box, offset one COLUMN_W
step to the right per new target.
"""
from __future__ import annotations

import dataclasses
import html
from itertools import count
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from . import AppSpecLike, LoopLike

SPINE_X = 200
ROW_H = 120
BOX_W, BOX_H = 160, 60
DIAMOND_W, DIAMOND_H = 140, 70
COLUMN_W = 220
_FALLBACK_STEP = 90  # vertical offset between successive un-positioned fallback nodes (minor 9)

_STAGE_STYLE = "rounded=1;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;"
_ORPHAN_STYLE = "rounded=1;whiteSpace=wrap;html=1;dashed=1;fillColor=#fff2cc;strokeColor=#d6b656;"
_BRANCH_STYLE = "rounded=1;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;"
_FALLBACK_STYLE = "rounded=1;whiteSpace=wrap;html=1;fillColor=#f5f5f5;strokeColor=#666666;"
_DIAMOND_STYLE = "rhombus;whiteSpace=wrap;html=1;fillColor=#ffe6cc;strokeColor=#d79b00;"
_SECTION_STYLE = "swimlane;whiteSpace=wrap;html=1;startSize=30;fillColor=#dae8fc;strokeColor=#6c8ebf;"
_TABLE_STYLE = "swimlane;whiteSpace=wrap;html=1;startSize=30;fillColor=#d5e8d4;strokeColor=#82b366;"
_ROW_STYLE = "text;strokeColor=none;fillColor=none;align=left;verticalAlign=middle;spacingLeft=6;html=1;"
_NOTE_STYLE = "shape=note;whiteSpace=wrap;html=1;fillColor=#fff2cc;strokeColor=#d6b656;size=16;"

# Direction labels appended to a loop edge's own label when it is anything other than a genuine
# backward rework loop (minor 10: say what the spec actually says, never assume). Keyed by
# `_loop_direction`'s return value.
_DIRECTION_SUFFIX: dict[str, str] = {
    "backward": "",
    "forward": " (goes FORWARD, not back -- check this)",
    "self": " (loops to itself -- check this)",
    "unknown": " (direction unclear -- check this)",
}


# ---------------------------------------------------------------------------------------------
# Shape adapters: accept either this package's own minimal (bare-sequence) protocol or
# kfforge.intake's real wrapper-per-dimension shape.
# ---------------------------------------------------------------------------------------------


def _seq(x: Any) -> list[Any]:
    """Return the sequence `x` names, whether `x` IS a bare sequence or is a dimension-wrapper
    dataclass (kfforge.intake.schema's `Stages`/`Routing`/`ReworkLoops`/`TestCases`, each holding
    exactly one sequence-valued field alongside zero or more scalar flags like `confirmed_none`).
    A wrapper's inner attribute is found generically via dataclass field introspection -- no
    per-dimension name is hardcoded, so this needs no update if intake adds a 12th dimension.
    `None` is treated as "nothing supplied" (empty), matching every dimension's own "confirmed
    empty" convention rather than raising on a spec that hasn't answered that question yet.
    """
    if x is None:
        return []
    if isinstance(x, (list, tuple)):
        return list(x)
    if dataclasses.is_dataclass(x) and not isinstance(x, type):
        for f in dataclasses.fields(x):
            val = getattr(x, f.name)
            if isinstance(val, (list, tuple)):
                return list(val)
    # Last-resort guess for a non-dataclass wrapper (e.g. a caller's plain object): try the
    # attribute names actually seen across kfforge.intake.schema's dimension wrappers.
    for name in ("stages", "points", "loops", "cases", "values", "entries", "roles", "views"):
        val = getattr(x, name, None)
        if isinstance(val, (list, tuple)):
            return list(val)
    raise TypeError(
        f"cannot find a sequence inside {x!r} -- expected a bare list/tuple or a dimension-"
        f"wrapper dataclass with exactly one sequence-valued field"
    )


def _seq_replace(container: Any, new_items: list[Any]) -> Any:
    """The write-side counterpart to `_seq()`: given the SAME container `_seq` would unwrap,
    return a new container of the identical shape holding `new_items` instead. A bare sequence is
    replaced outright (preserving list-vs-tuple); a wrapper is rebuilt via `dataclasses.replace`
    on whichever field `_seq` would have found the original sequence in -- so
    `dataclasses.replace(spec, stages=_seq_replace(spec.stages, new))` is correct regardless of
    whether `spec.stages` is a bare tuple or a `Stages` wrapper.
    """
    if isinstance(container, tuple):
        return tuple(new_items)
    if isinstance(container, list):
        return list(new_items)
    if dataclasses.is_dataclass(container) and not isinstance(container, type):
        for f in dataclasses.fields(container):
            if isinstance(getattr(container, f.name), (list, tuple)):
                return dataclasses.replace(container, **{f.name: tuple(new_items)})
    for name in ("stages", "points", "loops", "cases", "values", "entries", "roles", "views"):
        if isinstance(getattr(container, name, None), (list, tuple)):
            return dataclasses.replace(container, **{name: tuple(new_items)})
    raise TypeError(f"cannot rebuild a sequence-shaped container from {container!r}")


def _stage_index(spec: AppSpecLike) -> dict[str, int]:
    return {st.name: i for i, st in enumerate(_seq(spec.stages))}


def _loop_direction(idx: dict[str, int], lp: LoopLike) -> str:
    """"backward" (genuine rework loop -- to_stage sits before from_stage, matching
    kfforge.intake.schema.LoopSpec's own contract enforced by compile.py), "forward" (to_stage
    comes AFTER from_stage -- not a real rework loop by that contract), "self" (from_stage ==
    to_stage), or "unknown" (one or both names are not in this spec's own stage list -- an
    off-spine endpoint, so direction cannot be determined and must not be asserted)."""
    if lp.from_stage == lp.to_stage:
        return "self"
    fi, ti = idx.get(lp.from_stage), idx.get(lp.to_stage)
    if fi is None or ti is None:
        return "unknown"
    return "backward" if ti < fi else "forward"


def _terminal_stages(spec: AppSpecLike) -> list[str]:
    """Stage (or off-spine routing-target) names that nothing routes away from.

    Every plain stage but the last flows implicitly to its successor, and a routing point's own
    outgoing edges are its labeled branches -- both count as "has somewhere to go next" and are
    excluded. A rework loop's `from_stage` is deliberately NOT excluded here: a loop only supplies
    a BACKWARD edge, and says nothing about whether that same stage also has a forward "next" --
    which matters exactly when a loop's from_stage is ALSO the last stage in the spine (the
    common shape: do quality work, loop back on failure, otherwise you're done). That stage must
    still surface as a terminal-state question for its exit-the-loop path.
    """
    stage_names = [st.name for st in _seq(spec.stages)]
    routing = _seq(spec.routing)
    loops = _seq(spec.rework_loops)
    universe = list(stage_names)
    outgoing: set[str] = set(stage_names[:-1]) if stage_names else set()
    outgoing |= {rp.at_stage for rp in routing}
    for rp in routing:
        for target in dict(rp.route_per_option).values():
            if target not in universe:
                universe.append(target)
    for lp in loops:
        if lp.to_stage not in universe:
            universe.append(lp.to_stage)
    return [name for name in universe if name not in outgoing]


def _reachable_stage_names(
    stage_names: list[str], routing: list[Any], loops: list[Any], routing_at_stages: set[str],
) -> set[str]:
    """Stage names that receive at least one incoming edge: the entry point (position 0, which
    legitimately has none), every stage whose PREVIOUS spine neighbour is not itself a routing
    point (the implicit sequential edge), every routing target, and every loop's `to_stage`.
    A name absent from this set is a genuine orphan (major 6) -- flagged visibly, never wired
    with a fabricated edge that would misrepresent what the spec actually says.
    """
    reachable: set[str] = set()
    if stage_names:
        reachable.add(stage_names[0])
    for i in range(1, len(stage_names)):
        if stage_names[i - 1] not in routing_at_stages:
            reachable.add(stage_names[i])
    for rp in routing:
        reachable.update(dict(rp.route_per_option).values())
    for lp in loops:
        reachable.add(lp.to_stage)
    return reachable


def _row_advance(n_routing_at_stage: int) -> float:
    """Vertical distance from this stage's y to the NEXT stage's y. A stage with no routing point
    just needs the baseline ROW_H; one with N>=1 routing points needs room for its decision
    diamond(s) too (stacked per `flow_diagram_xml`'s own per-stage index offset), or the box below
    would overlap the last diamond (minor 8)."""
    if n_routing_at_stage <= 0:
        return ROW_H
    return max(ROW_H, BOX_H + 20 + DIAMOND_H + (n_routing_at_stage - 1) * (DIAMOND_H + 30) + 30)


# ---------------------------------------------------------------------------------------------
# Escaping and labels
# ---------------------------------------------------------------------------------------------


def _xml_escape(text: Any) -> str:
    """Double-escaped for the TWO layers every mxCell value in this module passes through: every
    style here sets html=1 (mxGraph's rich-text flag), so the decoded `value` is rendered as HTML,
    not plain text. A single XML-escape only protects the XML-parse layer -- a business name like
    "Foo <Bar>" would parse as valid XML fine, decode once to "Foo <Bar>", and then have "<Bar>"
    silently vanish as an unrecognised tag once mxGraph's HTML-mode renderer got hold of it
    (minor 11). Escaping HTML-first (`&`/`<`/`>`/quotes -> entities) and then escaping THAT
    result's own `&` characters for XML produces a value that survives both decodes and displays
    the literal original text -- see tests/test_design.py's two-decode round-trip test.
    """
    return html.escape(str(text), quote=True).replace("&", "&amp;")


def _two_line(first: Any, second: Any) -> str:
    """An mxGraph HTML label (the cell's style must carry html=1) with `first` and `second` on
    their own line. The literal `<br>` is spliced in AFTER `_xml_escape`-ing each half separately,
    and is intentionally only SINGLE-escaped (`&lt;br&gt;`, not `&amp;lt;br&amp;gt;`) so it
    becomes a real `<br>` tag after the one XML decode a parser performs -- the opposite of what
    `_xml_escape` deliberately prevents for business text."""
    return f"{_xml_escape(first)}&lt;br&gt;{_xml_escape(second)}"


def _label(item: Any) -> str:
    """Best-effort human label for an item whose exact shape the protocol leaves open -- prefer
    `.name` if present, else str(). NOT used for widgets (see mockup.py's own `_widget_label`):
    kfforge.intake.schema.WidgetIntent has no `.name` at all (it has `.slug`), so this generic
    fallback would leak a raw dataclass repr for one (minor 14)."""
    name = getattr(item, "name", None)
    return str(name) if name is not None else str(item)


def _column_label(col: Any) -> str:
    """"name : type" (+ "*" when required) for a richer column object (kfforge.intake.schema.
    TableColumnReq: name/type/required), falling back to `_label` for a plain string column."""
    name = getattr(col, "name", None)
    if name is None:
        return _label(col)
    ctype = getattr(col, "type", None)
    if ctype is None:
        return str(name)
    row = f"{name} : {ctype}"
    if getattr(col, "required", False):
        row += " *"
    return row


def _max_rows_label(max_rows: Any) -> str:
    return "no cap" if max_rows is None else str(max_rows)


class _Canvas:
    """Accumulates mxCell XML fragments plus a business-name -> mxCell-id registry.

    The registry is what guarantees every edge's source/target resolves: `resolve()` mints a
    small fallback box the first time an unfamiliar name is referenced, so a routing target or
    loop endpoint that was never explicitly boxed still gets a real node instead of a dangling
    edge reference. Each successive fallback is offset further down (`_fallback_n`) so multiple
    unresolved names never land on the identical coordinate (minor 9).
    """

    def __init__(self) -> None:
        self._ids = count(2)  # mxGraph convention: ids 0 and 1 are the two root layers
        self._cells: list[str] = []
        self._by_name: dict[str, str] = {}
        self._fallback_n = 0

    def _new_id(self) -> str:
        return f"n{next(self._ids)}"

    def vertex(self, *, name: str | None, value: str, x: float, y: float, w: float, h: float,
               style: str, parent: str = "1") -> str:
        """Create a vertex and return its id. When `name` is given and already registered, the
        EXISTING id is returned instead (dedup, so a stage that is also a routing target gets one
        box, not two); `name=None` always mints a fresh, unregistered node (decision diamonds and
        container child-rows, neither of which is ever looked up again by name)."""
        if name is not None and name in self._by_name:
            return self._by_name[name]
        vid = self._new_id()
        self._cells.append(
            f'<mxCell id="{vid}" value="{value}" style="{style}" vertex="1" parent="{parent}">'
            f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>'
        )
        if name is not None:
            self._by_name[name] = vid
        return vid

    def has(self, name: str) -> bool:
        return name in self._by_name

    def id_of(self, name: str) -> str:
        return self._by_name[name]

    def resolve(self, name: str, *, x: float | None = None, y: float | None = None) -> str:
        """Look up a business name's node id, minting a fallback box on first use. Each fallback
        is offset `_fallback_n * _FALLBACK_STEP` further down than the last, so unrelated
        unresolved names never stack on the same point (minor 9)."""
        if name in self._by_name:
            return self._by_name[name]
        fx = SPINE_X + COLUMN_W if x is None else x
        fy = (40 if y is None else y) + self._fallback_n * _FALLBACK_STEP
        self._fallback_n += 1
        return self.vertex(name=name, value=_xml_escape(name), x=fx, y=fy, w=BOX_W, h=BOX_H,
                            style=_FALLBACK_STYLE)

    def edge(self, *, source: str, target: str, label: str = "", dashed: bool = False) -> None:
        style = "edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;"
        if dashed:
            style += "dashed=1;"
        eid = self._new_id()
        self._cells.append(
            f'<mxCell id="{eid}" value="{_xml_escape(label)}" style="{style}" edge="1" '
            f'parent="1" source="{source}" target="{target}">'
            f'<mxGeometry relative="1" as="geometry"/></mxCell>'
        )

    def xml(self) -> str:
        body = "".join(self._cells)
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<mxGraphModel dx="900" dy="700" grid="1" gridSize="10" guides="1" tooltips="1" '
            'connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="850" '
            'pageHeight="1100" math="0" shadow="0">'
            f'<root><mxCell id="0"/><mxCell id="1" parent="0"/>{body}</root>'
            '</mxGraphModel>'
        )


def flow_diagram_xml(spec: AppSpecLike) -> str:
    """Steps as boxes down the spine (owner role on the box's second line), decision diamonds
    with one labeled edge per option, dashed back-edges for genuine rework loops labeled with the
    gate field. A stage no edge reaches is flagged "(unreachable?)" rather than silently drawn as
    if it were fine or wired with a fabricated edge (major 6); a loop that isn't a real backward
    jump is drawn solid and says what direction it actually is (minor 10); two routing points
    sharing a stage stack instead of overlapping (major 5 / minor 8)."""
    c = _Canvas()
    stages = _seq(spec.stages)
    routing = _seq(spec.routing)
    loops = _seq(spec.rework_loops)
    stage_names = [st.name for st in stages]
    routing_at_stages = {rp.at_stage for rp in routing}
    routing_counts: dict[str, int] = {}
    for rp in routing:
        routing_counts[rp.at_stage] = routing_counts.get(rp.at_stage, 0) + 1
    reachable = _reachable_stage_names(stage_names, routing, loops, routing_at_stages)

    stage_y: dict[str, float] = {}
    y = 40.0
    for i, st in enumerate(stages):
        stage_y[st.name] = y
        if st.name in reachable:
            label, style = _two_line(st.name, st.owner_role), _STAGE_STYLE
        else:
            label = _two_line(f"{st.name} (unreachable?)", st.owner_role)
            style = _ORPHAN_STYLE
        vid = c.vertex(name=st.name, value=label, x=SPINE_X, y=y, w=BOX_W, h=BOX_H, style=style)
        if i > 0 and stage_names[i - 1] not in routing_at_stages:
            c.edge(source=c.resolve(stage_names[i - 1]), target=vid)
        y += _row_advance(routing_counts.get(st.name, 0))

    placed_at_stage: dict[str, int] = {}
    for rp in routing:
        idx_here = placed_at_stage.get(rp.at_stage, 0)
        placed_at_stage[rp.at_stage] = idx_here + 1
        at_id = c.resolve(rp.at_stage, y=stage_y.get(rp.at_stage))
        base_y = stage_y.get(rp.at_stage, 40 - ROW_H) + BOX_H + 20
        dia_y = base_y + idx_here * (DIAMOND_H + 30)
        dia_id = c.vertex(name=None, value=_xml_escape(rp.field_name), x=SPINE_X, y=dia_y,
                           w=DIAMOND_W, h=DIAMOND_H, style=_DIAMOND_STYLE)
        c.edge(source=at_id, target=dia_id)

        mapping = dict(rp.route_per_option)
        column = 1
        for option in rp.options:
            target_name = mapping.get(option, option)
            if c.has(target_name):
                target_id = c.id_of(target_name)
            else:
                target_id = c.vertex(
                    name=target_name, value=_xml_escape(target_name),
                    x=SPINE_X + column * COLUMN_W, y=dia_y, w=BOX_W, h=BOX_H, style=_BRANCH_STYLE,
                )
                column += 1
            c.edge(source=dia_id, target=target_id, label=option)

    idx = _stage_index(spec)
    for lp in loops:
        direction = _loop_direction(idx, lp)
        src = c.resolve(lp.from_stage, y=stage_y.get(lp.from_stage))
        dst = c.resolve(lp.to_stage, y=stage_y.get(lp.to_stage))
        label = f"{lp.gate_field}{_DIRECTION_SUFFIX[direction]}"
        c.edge(source=src, target=dst, label=label, dashed=(direction == "backward"))

    return c.xml()


def schema_diagram_xml(spec: AppSpecLike) -> str:
    """Fields grouped by their `.stage` as swimlane containers (one row per field, `"*"` when
    required), tables as their own boxes (columns + Max rows, "no cap" when unset), lists as note
    boxes (name + values)."""
    c = _Canvas()

    sections: dict[str, list[str]] = {}
    for f in _seq(spec.data_model.fields):
        row = f"{f.name} : {f.type}"
        if f.required:
            row += " *"
        sections.setdefault(f.stage, []).append(row)

    x, y = 40, 40
    for stage_name, rows in sections.items():
        h = 30 + max(1, len(rows)) * 26
        sid = c.vertex(name=None, value=_xml_escape(stage_name), x=x, y=y, w=260, h=h,
                        style=_SECTION_STYLE)
        for i, row in enumerate(rows):
            c.vertex(name=None, value=_xml_escape(row), x=0, y=30 + i * 26, w=260, h=26,
                      style=_ROW_STYLE, parent=sid)
        y += h + 30

    x, y = 340, 40
    for t in _seq(spec.data_model.tables):
        rows = [_column_label(col) for col in _seq(t.columns)] + [
            f"Max rows: {_max_rows_label(t.max_rows)}"
        ]
        h = 30 + len(rows) * 26
        tid = c.vertex(name=None, value=_xml_escape(t.name), x=x, y=y, w=240, h=h,
                        style=_TABLE_STYLE)
        for i, row in enumerate(rows):
            c.vertex(name=None, value=_xml_escape(row), x=0, y=30 + i * 26, w=240, h=26,
                      style=_ROW_STYLE, parent=tid)
        y += h + 30

    x, y = 620, 40
    for lst in _seq(spec.master_data.lists):
        label = _two_line(lst.name, ", ".join(str(v) for v in _seq(lst.values)))
        c.vertex(name=None, value=label, x=x, y=y, w=220, h=80, style=_NOTE_STYLE)
        y += 100

    return c.xml()
