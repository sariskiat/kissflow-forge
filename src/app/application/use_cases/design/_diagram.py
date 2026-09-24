"""
app.application.design.diagram -- draw.io / mxGraph XML for the flow shape and the
data shape.

Pure string building, stdlib only (`html.escape` for entity-safety) -- no dependency
on draw.io or any XML-writing library. The returned string is a complete
`.drawio`-openable document; a caller either saves it with a `.drawio` extension or
pastes it into draw.io's Extras > Edit Diagram. Every function here is READ-ONLY
over its `spec` argument (duck-typed per app.application.design.AppSpecLike -- see
the package docstring for why this never imports app.application.intake) and never
touches the network or the Kissflow builder API.

Shape adapters (`_seq`/`_seq_replace`) live in this module because it is the one
every other app.application.design submodule already imports from.
app.application.intake.schema.AppSpec (the real spec) wraps every dimension's
collection in its own frozen container -- `Stages.stages`, `Routing.points`,
`ReworkLoops.loops`, `TestCases.cases` -- rather than exposing a bare tuple/list
directly. This package's own minimal protocol never required that extra layer (a
caller's stub can hand over a bare sequence), so every collection access in this
package goes through `_seq()`, which accepts either shape. Nothing here hardcodes
intake's wrapper attribute names (`.stages`/`.points`/...): a wrapper is recognised
generically as "a dataclass or Pydantic BaseModel with exactly one sequence-valued
field" (true of every dimension wrapper today, including ones this package doesn't
touch), so a future 12th dimension's wrapper needs no code change here to be
understood.

Layout is a small, deterministic heuristic, not a general graph-layout solver --
YAGNI for a "confirm before you build" artifact a business owner skims once, not
something driving a live dashboard. Stage boxes run down a vertical spine at
x=SPINE_X; the vertical step to the NEXT stage grows when the current one hosts one
or more routing points, so a decision diamond (or several, stacked, if more than one
routing point shares a stage) never overlaps the box below it. A routing point's
branch targets that are not already on the spine get their own box, offset one
COLUMN_W step to the right per new target.
"""

from __future__ import annotations

import dataclasses
import html
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from itertools import count, pairwise
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

if TYPE_CHECKING:
    from app.application.use_cases.design._bundle import AppSpecLike, LoopLike

SPINE_X = 200
ROW_H = 120
BOX_W, BOX_H = 160, 60
DIAMOND_W, DIAMOND_H = 140, 70
COLUMN_W = 220
_FALLBACK_STEP = (
    90  # vertical offset between successive un-positioned fallback nodes (minor 9)
)

_STAGE_STYLE = "rounded=1;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;"
_ORPHAN_STYLE = (
    "rounded=1;whiteSpace=wrap;html=1;dashed=1;fillColor=#fff2cc;strokeColor=#d6b656;"
)
_BRANCH_STYLE = (
    "rounded=1;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;"
)
_FALLBACK_STYLE = (
    "rounded=1;whiteSpace=wrap;html=1;fillColor=#f5f5f5;strokeColor=#666666;"
)
_DIAMOND_STYLE = "rhombus;whiteSpace=wrap;html=1;fillColor=#ffe6cc;strokeColor=#d79b00;"
_SECTION_STYLE = (
    "swimlane;whiteSpace=wrap;html=1;startSize=30;fillColor=#dae8fc;"
    "strokeColor=#6c8ebf;"
)
_TABLE_STYLE = (
    "swimlane;whiteSpace=wrap;html=1;startSize=30;fillColor=#d5e8d4;"
    "strokeColor=#82b366;"
)
_ROW_STYLE = (
    "text;strokeColor=none;fillColor=none;align=left;verticalAlign=middle;"
    "spacingLeft=6;html=1;"
)
_NOTE_STYLE = (
    "shape=note;whiteSpace=wrap;html=1;fillColor=#fff2cc;strokeColor=#d6b656;size=16;"
)

# Direction labels appended to a loop edge's own label when it is anything other than a
# genuine backward rework loop (minor 10: say what the spec actually says, never
# assume). Keyed by `_loop_direction`'s return value.
_DIRECTION_SUFFIX: dict[str, str] = {
    "backward": "",
    "forward": " (goes FORWARD, not back -- check this)",
    "self": " (loops to itself -- check this)",
    "unknown": " (direction unclear -- check this)",
}


# --------------------------------------------------------------------------------------
# Shape adapters: accept either this package's own minimal (bare-sequence) protocol or
# app.application.intake's real wrapper-per-dimension shape. A wrapper is either a plain
# stdlib dataclass (tests/test_design.py's own protocol-shaped stubs -- this package
# never imports app.application.intake, so it must keep working against a bare dataclass
# forever, see the package docstring) or a Pydantic `BaseModel`
# (app.application.intake's real, now-Pydantic AppSpec tree, G10) --
# `_is_struct`/`_struct_field_names`/`_replace` below dispatch on whichever shape a
# caller actually handed in, never assuming just one.
# --------------------------------------------------------------------------------------


def _is_struct(x: Any) -> bool:
    """True for a stdlib dataclass INSTANCE or a Pydantic `BaseModel` instance."""
    return (dataclasses.is_dataclass(x) and not isinstance(x, type)) or isinstance(
        x, BaseModel
    )


def _struct_field_names(x: Any) -> tuple[str, ...]:
    """Field names of a dataclass or `BaseModel` instance, in declaration order."""
    if isinstance(x, BaseModel):
        return tuple(type(x).model_fields)
    return tuple(f.name for f in dataclasses.fields(x))


def _replace(x: Any, **changes: Any) -> Any:
    """
    `dataclasses.replace(x, **changes)` or `x.model_copy(update=changes)`, whichever
    `x` needs -- the one place this package rebuilds a struct with one field
    changed. Raises on an unknown field name for EITHER shape: `dataclasses.replace`
    already does this (several callers in confirm.py lean on it, e.g.
    `_rename_field_stage_and_section`'s own `hasattr` guard exists BECAUSE of it),
    but Pydantic's own `model_copy(update=...)` does not -- it silently sets a
    non-field attribute rather than raising, so this checks explicitly rather than
    let a typo'd field name through unnoticed.
    """
    if isinstance(x, BaseModel):
        unknown = set(changes) - set(type(x).model_fields)
        if unknown:
            raise TypeError(
                f"{type(x).__name__}.model_copy() got unexpected "
                f"field(s): {sorted(unknown)}"
            )
        return x.model_copy(update=changes)
    return dataclasses.replace(x, **changes)


def _seq(x: Any) -> list[Any]:
    """
    Return the sequence `x` names, whether `x` IS a bare sequence or is a
    dimension-wrapper struct (app.application.intake's
    `Stages`/`Routing`/`ReworkLoops`/`TestCases`, each holding exactly one
    sequence-valued field alongside zero or more scalar flags like
    `confirmed_none`). A wrapper's inner attribute is found generically via field
    introspection -- no per-dimension name is hardcoded, so this needs no update if
    intake adds a 12th dimension. `None` is treated as "nothing supplied" (empty),
    matching every dimension's own "confirmed empty" convention rather than raising
    on a spec that hasn't answered that question yet.
    """
    if x is None:
        return []
    if isinstance(x, (list, tuple)):
        return list(x)
    if _is_struct(x):
        for name in _struct_field_names(x):
            val = getattr(x, name)
            if isinstance(val, (list, tuple)):
                return list(val)
    # Last-resort guess for a non-struct wrapper (e.g. a caller's plain object): try the
    # attribute names actually seen across app.application.intake's dimension wrappers.
    for name in (
        "stages",
        "points",
        "loops",
        "cases",
        "values",
        "entries",
        "roles",
        "views",
    ):
        val = getattr(x, name, None)
        if isinstance(val, (list, tuple)):
            return list(val)
    raise TypeError(
        f"cannot find a sequence inside {x!r} -- expected a bare list/tuple or a "
        f"dimension-wrapper struct with exactly one sequence-valued field"
    )


def _seq_replace(container: Any, new_items: list[Any]) -> Any:
    """
    The write-side counterpart to `_seq()`: given the SAME container `_seq` would
    unwrap, return a new container of the identical shape holding `new_items`
    instead. A bare sequence is replaced outright (preserving list-vs-tuple); a
    wrapper is rebuilt via `_replace()` on whichever field `_seq` would have found
    the original sequence in -- so `_replace(spec, stages=_seq_replace(spec.stages,
    new))` is correct regardless of whether `spec.stages` is a bare tuple or a
    `Stages` wrapper (dataclass or Pydantic).
    """
    if isinstance(container, tuple):
        return tuple(new_items)
    if isinstance(container, list):
        return list(new_items)
    if _is_struct(container):
        for name in _struct_field_names(container):
            if isinstance(getattr(container, name), (list, tuple)):
                return _replace(container, **{name: tuple(new_items)})
    for name in (
        "stages",
        "points",
        "loops",
        "cases",
        "values",
        "entries",
        "roles",
        "views",
    ):
        if isinstance(getattr(container, name, None), (list, tuple)):
            return _replace(container, **{name: tuple(new_items)})
    raise TypeError(f"cannot rebuild a sequence-shaped container from {container!r}")


def _stage_index(spec: AppSpecLike) -> dict[str, int]:
    return {st.name: i for i, st in enumerate(_seq(spec.stages))}


def _loop_direction(idx: dict[str, int], lp: LoopLike) -> str:
    """
    "backward" (genuine rework loop -- to_stage sits before from_stage, matching
    app.application.intake.schema.LoopSpec's own contract enforced by compile.py),
    "forward" (to_stage comes AFTER from_stage -- not a real rework loop by that
    contract), "self" (from_stage == to_stage), or "unknown" (one or both names are
    not in this spec's own stage list -- an off-spine endpoint, so direction cannot
    be determined and must not be asserted).
    """
    if lp.from_stage == lp.to_stage:
        return "self"
    fi, ti = idx.get(lp.from_stage), idx.get(lp.to_stage)
    if fi is None or ti is None:
        return "unknown"
    return "backward" if ti < fi else "forward"


def _route_sequences(routing: list[Any]) -> Iterator[tuple[str, ...]]:
    """
    Every branch's ordered target SEQUENCE across all routing points (P1: a branch
    is a sequence of stages -- `route_per_option` maps each option to one). The
    single place the two-level `route_per_option` walk lives, so the several readers
    below don't each re-open it.
    """
    for rp in routing:
        for targets in dict(rp.route_per_option).values():
            yield tuple(targets)


def _terminal_stages(spec: AppSpecLike) -> list[str]:
    """
    Stage (or off-spine routing-target) names that nothing routes away from.

    Every plain stage but the last flows implicitly to its successor, and a routing
    point's own outgoing edges are its labeled branches -- both count as "has
    somewhere to go next" and are excluded. A rework loop's `from_stage` is
    deliberately NOT excluded here: a loop only supplies a BACKWARD edge, and says
    nothing about whether that same stage also has a forward "next" -- which matters
    exactly when a loop's from_stage is ALSO the last stage in the spine (the common
    shape: do quality work, loop back on failure, otherwise you're done). That stage
    must still surface as a terminal-state question for its exit-the-loop path.
    """
    stage_names = [st.name for st in _seq(spec.stages)]
    routing = _seq(spec.routing)
    loops = _seq(spec.rework_loops)
    universe = list(stage_names)  # a LIST, not a set: layout order matters downstream
    outgoing: set[str] = set(stage_names[:-1]) if stage_names else set()
    outgoing |= {rp.at_stage for rp in routing}
    for targets in _route_sequences(routing):
        for (
            target
        ) in targets:  # a branch is a SEQUENCE of stages now (P1) — every one counts
            # ponytail: O(stages × options × seqlen) via `not in` on a list; all three
            # are tiny bounded per-flow config (dozens, not unbounded input), so the
            # list stays. If a flow ever carried unbounded stages, track membership in a
            # parallel set.
            if target not in universe:
                universe.append(target)
    for lp in loops:
        if lp.to_stage not in universe:
            universe.append(lp.to_stage)
    return [name for name in universe if name not in outgoing]


def _reachable_stage_names(
    stage_names: list[str],
    routing: list[Any],
    loops: list[Any],
    routing_at_stages: set[str],
) -> set[str]:
    """
    Stage names that receive at least one incoming edge: the entry point (position
    0, which legitimately has none), every stage whose PREVIOUS spine neighbour is
    not itself a routing point (the implicit sequential edge), every routing target,
    and every loop's `to_stage`. A name absent from this set is a genuine orphan
    (major 6) -- flagged visibly, never wired with a fabricated edge that would
    misrepresent what the spec actually says.
    """
    reachable: set[str] = set()
    if stage_names:
        reachable.add(stage_names[0])
    for i in range(1, len(stage_names)):
        if stage_names[i - 1] not in routing_at_stages:
            reachable.add(stage_names[i])
    for targets in _route_sequences(routing):
        reachable.update(
            targets
        )  # every stage in every branch sequence receives an edge (P1)
    for lp in loops:
        reachable.add(lp.to_stage)
    return reachable


def _forward_next_stages(spec: AppSpecLike) -> dict[str, str | None]:
    """
    A stage's single forward "next" edge, under the loop-terminal merge rule.

    Every stage has exactly one onward edge except a routing-point stem (a fork's
    outgoing is its decision diamond, not a spine edge) and the last stage. A branch
    -- the spine span a routing target opens -- runs to a TERMINAL, and that
    terminal points at its OWN MERGE (see below) instead of spilling forward into a
    sibling branch's stages (the round-1 major defect in decision_01 item 1: three
    service tiers each drew a spine edge into the next tier instead of converging on
    the shared join).

    Terminal derivation (the loop-terminal rule): a branch's terminal defaults to
    its on-spine entry target, unless a BACKWARD rework loop's `from_stage` is owned
    by that entry (owner = the most recent entry at-or-before it in spine order), in
    which case the loop's `from_stage` is the terminal -- the stage the branch
    really ends at, and the one that must jump to the merge.

    A route sequence of length >= 2 (S1, #32) is a SECOND, independent model layered
    on top of the one above: when a branch's own sequence names two or more on-spine
    stages ([A1, A2, ...]), the interior edges (A1 -> A2 -> ...) are drawn
    explicitly from the sequence order itself, and the sequence's own LAST stage --
    not its entry -- becomes the terminal that jumps to the merge. A length-1
    sequence (just the entry) is untouched by this and keeps running the original
    model: the rest of that branch extends along the spine, with a backward rework
    loop's `from_stage` (if any) marking where it really ends.

    The merge is computed PER BRANCH TERMINAL (S2, #33), not once globally. A
    terminal's merge is the first SPINE stage after it -- the first stage, in spec
    order, that is not itself lifted off the spine as some branch's own stage. With
    ONE split this is identical to the old single global merge (there is nothing
    else to skip past). With N sequential splits, a global merge picked the first
    stage after the DEEPEST terminal across every routing point, so an earlier
    split's branch terminal spilled past its own rejoin stage and across a LATER
    split's branch stages entirely -- the cross-split analogue of the sibling-spill
    bug S1 fixed within one split. Per-terminal merge keeps each split's branch
    converging on its own rejoin, which is naturally the next split's own stem when
    two splits sit back to back.
    """
    stages = _seq(spec.stages)
    stage_names = [st.name for st in stages]
    idx = _stage_index(spec)
    routing = _seq(spec.routing)
    routing_at_stages = {rp.at_stage for rp in routing}
    loops = _seq(spec.rework_loops)

    # On-spine branch entries = the FIRST stage of each route sequence, when it's an
    # actual stage. A branch ENTERS at its first stage (P1); the rest of the sequence
    # runs forward on the spine, so only the entry is a fork target here — never a
    # mid-branch stage.
    entries: set[str] = set()
    for targets in _route_sequences(routing):
        if targets and targets[0] in idx:
            entries.add(targets[0])

    # owner[name] = the most recent entry at-or-before it; None before the first branch.
    owner: dict[str, str | None] = {}
    last_entry: str | None = None
    for name in stage_names:
        if name in entries:
            last_entry = name
        owner[name] = last_entry

    # intra_next[s_i] = s_{i+1} for a MULTI-stage route sequence (len(seq) >= 2,
    # on-spine stages only) -- the explicit forward edge WITHIN a branch (e.g. A1 ->
    # A2), plus that sequence's own explicit terminal (its LAST on-spine stage, not its
    # entry). A length-1 sequence is untouched here -- it stays on the original
    # entry-only/spine-extension model above. This is what fixes S1's bug: without it,
    # A1 (an interior stage now correctly NOT a fork target past the first) fell through
    # to the plain spine-next branch below and pointed at the merge too early, while A2
    # fell through the SAME way and pointed at the next SPINE stage -- a sibling
    # branch's own stage.
    intra_next: dict[str, str] = {}
    explicit_terminal: dict[str, str] = {}
    for targets in _route_sequences(routing):
        seq = [t for t in targets if t in idx]
        if len(seq) < 2:
            continue
        for a, b in pairwise(seq):
            intra_next[a] = b
        explicit_terminal[seq[0]] = seq[-1]

    # terminal per entry, defaulting to the entry itself, overridden by a multi-stage
    # sequence's own explicit terminal (applied BEFORE the loop-override pass below, so
    # a genuine backward rework loop inside a branch can still win over this default --
    # S3 territory, no loop-in- branch fixture exercises it yet, but the ordering is
    # what keeps that future case correct); a backward loop's from_stage otherwise
    # overrides the terminal of the entry that owns it.
    terminal: dict[str, str] = {e: e for e in entries}
    terminal.update(explicit_terminal)
    for lp in loops:
        fi, ti = idx.get(lp.from_stage), idx.get(lp.to_stage)
        if fi is None or ti is None or ti >= fi:
            continue  # off-spine endpoint, or not a genuine backward rework loop
        own = owner.get(lp.from_stage)
        if own is not None:
            terminal[own] = lp.from_stage

    terminal_set = set(terminal.values())

    # branch_stage_set = every stage a merge must skip past to land back on the true
    # spine (S2, #33): for each entry, the CLOSED range [entry .. its own terminal],
    # inclusive. This covers both branch shapes uniformly -- an explicit multi-stage
    # sequence (terminal = its last stage, e.g. [A1, A2]) AND the implicit
    # spine-extension model a length-1 sequence still uses (terminal = wherever a loop
    # override lands, e.g. [Light Work, Light Confirm] with nothing named in between by
    # any route sequence -- those interior stages are plain spine positions, not
    # sequence members, so a route-sequence-only set would miss them and stop the merge
    # search too early).
    branch_stage_set: set[str] = set()
    for entry, t in terminal.items():
        branch_stage_set.update(stage_names[idx[entry] : idx[t] + 1])

    def merge_after(t_name: str) -> str | None:
        """
        The first SPINE stage after `t_name` -- that terminal's own rejoin point,
        skipping any stage that belongs to a branch (this split's own remaining
        stages, or a later split's).
        """
        for j in range(idx[t_name] + 1, len(stage_names)):
            if stage_names[j] not in branch_stage_set:
                return stage_names[j]
        return None

    # An unreachable (orphan) stage must not be wired with a fabricated edge either --
    # only reachable stages get a forward "next" (same gate _reachable_stage_names
    # applies in flow_diagram_xml, so a stray sequential pointer can't invent a path
    # through a stage the spec never actually reaches).
    reachable = _reachable_stage_names(stage_names, routing, loops, routing_at_stages)
    next_of: dict[str, str | None] = {}
    for i, name in enumerate(stage_names):
        if name not in reachable:
            next_of[name] = None
        elif name in routing_at_stages:
            next_of[name] = None  # the fork's outgoing is its diamond, not a spine edge
        elif name in intra_next:
            next_of[name] = intra_next[
                name
            ]  # explicit multi-stage branch edge (s_i -> s_i+1)
        elif name in terminal_set:
            next_of[name] = merge_after(
                name
            )  # branch terminal jumps to ITS OWN merge (or ends)
        else:
            next_of[name] = stage_names[i + 1] if i + 1 < len(stage_names) else None
    return next_of


def _row_advance(n_routing_at_stage: int) -> float:
    """
    Vertical distance from this stage's y to the NEXT stage's y. A stage with no
    routing point just needs the baseline ROW_H; one with N>=1 routing points needs
    room for its decision diamond(s) too (stacked per `flow_diagram_xml`'s own
    per-stage index offset), or the box below would overlap the last diamond (minor
    8).
    """
    if n_routing_at_stage <= 0:
        return ROW_H
    return max(
        ROW_H, BOX_H + 20 + DIAMOND_H + (n_routing_at_stage - 1) * (DIAMOND_H + 30) + 30
    )


# --------------------------------------------------------------------------------------
# Escaping and labels
# --------------------------------------------------------------------------------------


def _xml_escape(text: Any) -> str:
    """
    Double-escaped for the TWO layers every mxCell value in this module passes
    through: every style here sets html=1 (mxGraph's rich-text flag), so the decoded
    `value` is rendered as HTML, not plain text. A single XML-escape only protects
    the XML-parse layer -- a business name like "Foo <Bar>" would parse as valid XML
    fine, decode once to "Foo <Bar>", and then have "<Bar>" silently vanish as an
    unrecognised tag once mxGraph's HTML-mode renderer got hold of it (minor 11).
    Escaping HTML-first (`&`/`<`/`>`/quotes -> entities) and then escaping THAT
    result's own `&` characters for XML produces a value that survives both decodes
    and displays the literal original text -- see tests/test_design.py's two-decode
    round-trip test.
    """
    return html.escape(str(text), quote=True).replace("&", "&amp;")


def _two_line(first: Any, second: Any) -> str:
    """
    An mxGraph HTML label (the cell's style must carry html=1) with `first` and
    `second` on their own line. The literal `<br>` is spliced in AFTER
    `_xml_escape`-ing each half separately, and is intentionally only SINGLE-escaped
    (`&lt;br&gt;`, not `&amp;lt;br&amp;gt;`) so it becomes a real `<br>` tag after
    the one XML decode a parser performs -- the opposite of what `_xml_escape`
    deliberately prevents for business text.
    """
    return f"{_xml_escape(first)}&lt;br&gt;{_xml_escape(second)}"


def _label(item: Any) -> str:
    """
    Best-effort human label for an item whose exact shape the protocol leaves open
    -- prefer `.name` if present, else str(). NOT used for widgets (see mockup.py's
    own `_widget_label`): app.application.intake.schema.WidgetIntent has no `.name`
    at all (it has `.slug`), so this generic fallback would leak a raw dataclass
    repr for one (minor 14).
    """
    name = getattr(item, "name", None)
    return str(name) if name is not None else str(item)


def _column_label(col: Any) -> str:
    """
    "name : type" (+ "*" when required) for a richer column object
    (app.application.intake.schema. TableColumnReq: name/type/required), falling
    back to `_label` for a plain string column.
    """
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
    """
    Accumulates mxCell XML fragments plus a business-name -> mxCell-id registry.

    The registry is what guarantees every edge's source/target resolves: `resolve()`
    mints a small fallback box the first time an unfamiliar name is referenced, so a
    routing target or loop endpoint that was never explicitly boxed still gets a
    real node instead of a dangling edge reference. Each successive fallback is
    offset further down (`_fallback_n`) so multiple unresolved names never land on
    the identical coordinate (minor 9).
    """

    def __init__(self) -> None:
        self._ids = count(2)  # mxGraph convention: ids 0 and 1 are the two root layers
        self._cells: list[str] = []
        self._by_name: dict[str, str] = {}
        self._fallback_n = 0

    def _new_id(self) -> str:
        return f"n{next(self._ids)}"

    def vertex(
        self,
        *,
        name: str | None,
        value: str,
        x: float,
        y: float,
        w: float,
        h: float,
        style: str,
        parent: str = "1",
    ) -> str:
        """
        Create a vertex and return its id. When `name` is given and already
        registered, the EXISTING id is returned instead (dedup, so a stage that is
        also a routing target gets one box, not two); `name=None` always mints a
        fresh, unregistered node (decision diamonds and container child-rows,
        neither of which is ever looked up again by name).
        """
        if name is not None and name in self._by_name:
            return self._by_name[name]
        vid = self._new_id()
        self._cells.append(
            f'<mxCell id="{vid}" value="{value}" style="{style}" '
            f'vertex="1" parent="{parent}">'
            f'<mxGeometry x="{x}" y="{y}" width="{w}" '
            f'height="{h}" as="geometry"/></mxCell>'
        )
        if name is not None:
            self._by_name[name] = vid
        return vid

    def has(self, name: str) -> bool:
        return name in self._by_name

    def id_of(self, name: str) -> str:
        return self._by_name[name]

    def resolve(
        self, name: str, *, x: float | None = None, y: float | None = None
    ) -> str:
        """
        Look up a business name's node id, minting a fallback box on first use. Each
        fallback is offset `_fallback_n * _FALLBACK_STEP` further down than the
        last, so unrelated unresolved names never stack on the same point (minor 9).
        """
        if name in self._by_name:
            return self._by_name[name]
        fx = SPINE_X + COLUMN_W if x is None else x
        fy = (40 if y is None else y) + self._fallback_n * _FALLBACK_STEP
        self._fallback_n += 1
        return self.vertex(
            name=name,
            value=_xml_escape(name),
            x=fx,
            y=fy,
            w=BOX_W,
            h=BOX_H,
            style=_FALLBACK_STYLE,
        )

    def edge(
        self, *, source: str, target: str, label: str = "", dashed: bool = False
    ) -> None:
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
            '<mxGraphModel dx="900" dy="700" grid="1" gridSize="10" guides="1" '
            'tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" '
            'pageWidth="850" '
            'pageHeight="1100" math="0" shadow="0">'
            f'<root><mxCell id="0"/><mxCell id="1" parent="0"/>{body}</root>'
            "</mxGraphModel>"
        )


def flow_diagram_xml(spec: AppSpecLike) -> str:
    """
    Steps as boxes down the spine (owner role on the box's second line), decision
    diamonds with one labeled edge per option, dashed back-edges for genuine rework
    loops labeled with the gate field. A stage no edge reaches is flagged
    "(unreachable?)" rather than silently drawn as if it were fine or wired with a
    fabricated edge (major 6); a loop that isn't a real backward jump is drawn solid
    and says what direction it actually is (minor 10); two routing points sharing a
    stage stack instead of overlapping (major 5 / minor 8).
    """
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

    next_of = _forward_next_stages(spec)
    stage_y: dict[str, float] = {}
    y = 40.0
    for _i, st in enumerate(stages):
        stage_y[st.name] = y
        if st.name in reachable:
            label, style = _two_line(st.name, st.owner_role), _STAGE_STYLE
        else:
            label = _two_line(f"{st.name} (unreachable?)", st.owner_role)
            style = _ORPHAN_STYLE
        vid = c.vertex(
            name=st.name, value=label, x=SPINE_X, y=y, w=BOX_W, h=BOX_H, style=style
        )
        nxt = next_of.get(st.name)
        if nxt is not None:
            c.edge(source=vid, target=c.resolve(nxt))
        y += _row_advance(routing_counts.get(st.name, 0))

    placed_at_stage: dict[str, int] = {}
    for rp in routing:
        idx_here = placed_at_stage.get(rp.at_stage, 0)
        placed_at_stage[rp.at_stage] = idx_here + 1
        at_id = c.resolve(rp.at_stage, y=stage_y.get(rp.at_stage))
        base_y = stage_y.get(rp.at_stage, 40 - ROW_H) + BOX_H + 20
        dia_y = base_y + idx_here * (DIAMOND_H + 30)
        dia_id = c.vertex(
            name=None,
            value=_xml_escape(rp.field_name),
            x=SPINE_X,
            y=dia_y,
            w=DIAMOND_W,
            h=DIAMOND_H,
            style=_DIAMOND_STYLE,
        )
        c.edge(source=at_id, target=dia_id)

        mapping = dict(rp.route_per_option)
        column = 1
        for option in rp.options:
            route_seq = mapping.get(
                option
            )  # a branch is a stage SEQUENCE now (P1); the fork edge
            target_name = (
                route_seq[0] if route_seq else option
            )  # lands on its first stage (fallback: option)
            if c.has(target_name):
                target_id = c.id_of(target_name)
            else:
                target_id = c.vertex(
                    name=target_name,
                    value=_xml_escape(target_name),
                    x=SPINE_X + column * COLUMN_W,
                    y=dia_y,
                    w=BOX_W,
                    h=BOX_H,
                    style=_BRANCH_STYLE,
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

    doc = c.xml()
    verify_flow_diagram_branches(
        spec, doc
    )  # #4: never hand a human a diagram that lies
    return doc


def verify_flow_diagram_branches(spec: AppSpecLike, xml_text: str) -> None:
    """
    #4's machine pre-check: re-read the RENDERED XML and assert its branch structure
    matches the spec's routing, raising ValueError before the diagram ever reaches
    an approver. The render once nearly drew a sequential spine through parallel
    branches; the visual fix landed, this is the guarantee a regression can't
    silently undo it. Checks, per routing point: the decision diamond exists, is
    labeled with the deciding field, and is wired FROM the fork stage; every option
    has a fork edge labeled with that option landing on that option's own branch
    entry; and the fork stage draws NO plain unlabeled spine edge (its only outgoing
    paths are its diamonds -- an unlabeled edge out of a fork stem is exactly the
    sequential-spine lie). Deliberately parses the output rather than trusting the
    code that produced it -- same code proving itself is no check at all.
    """
    root = ET.fromstring(xml_text)
    vertices: dict[str, tuple[str, str]] = {}
    edges: list[tuple[str, str, str, bool]] = []
    for cell in root.findall(".//mxCell"):
        cid = cell.get("id") or ""
        if cell.get("vertex") == "1":
            vertices[cid] = (cell.get("value") or "", cell.get("style") or "")
        elif cell.get("edge") == "1":
            edges.append(
                (
                    cell.get("source") or "",
                    cell.get("target") or "",
                    html.unescape(cell.get("value") or ""),
                    "dashed=1" in (cell.get("style") or ""),
                )
            )

    def business_name(value: str) -> str:
        # A stage label is name<br>role (post-XML-decode); a fallback box is just the
        # name; an orphan carries the "(unreachable?)" flag inside its first line.
        first = html.unescape(value.split("<br>", 1)[0])
        return first.removesuffix(" (unreachable?)")

    id_by_name: dict[str, str] = {}
    for vid, (value, style) in vertices.items():
        if "rhombus" not in style:
            id_by_name.setdefault(business_name(value), vid)

    problems: list[str] = []
    fork_ids: set[str] = set()
    for rp in _seq(spec.routing):
        at_id = id_by_name.get(rp.at_stage)
        if at_id is None:
            problems.append(f"routing stage {rp.at_stage!r} has no box in the render")
            continue
        fork_ids.add(at_id)
        dia_ids = {
            t
            for s, t, _, _ in edges
            if s == at_id
            and "rhombus" in vertices.get(t, ("", ""))[1]
            and html.unescape(vertices[t][0]) == str(rp.field_name)
        }
        if not dia_ids:
            problems.append(
                f"no decision diamond {rp.field_name!r} wired from "
                f"stage {rp.at_stage!r}"
            )
            continue
        mapping = dict(rp.route_per_option)
        for option in rp.options:
            seq = list(mapping.get(option) or ())
            entry = seq[0] if seq else option
            hit = any(
                s in dia_ids
                and label == option
                and business_name(vertices.get(t, ("", ""))[0]) == entry
                for s, t, label, _ in edges
            )
            if not hit:
                problems.append(
                    f"branch {option!r} at {rp.at_stage!r} is not drawn as a "
                    f"fork edge to its entry {entry!r}"
                )
    for s, t, label, dashed in edges:
        if (
            s in fork_ids
            and not label
            and not dashed
            and "rhombus" not in vertices.get(t, ("", ""))[1]
        ):
            src = business_name(vertices[s][0])
            dst = business_name(vertices.get(t, ("?", ""))[0])
            problems.append(
                f"fork stage {src!r} draws a plain sequential spine edge to {dst!r} -- "
                f"parallel branches rendered as a sequence"
            )
    if problems:
        raise ValueError(
            "confirmation diagram does not match the spec's branch structure: "
            + "; ".join(problems)
        )


def schema_diagram_xml(spec: AppSpecLike) -> str:
    """
    Fields grouped by their `.stage` as swimlane containers (one row per field,
    `"*"` when required), tables as their own boxes (columns + Max rows, "no cap"
    when unset), lists as note boxes (name + values).
    """
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
        sid = c.vertex(
            name=None,
            value=_xml_escape(stage_name),
            x=x,
            y=y,
            w=260,
            h=h,
            style=_SECTION_STYLE,
        )
        for i, row in enumerate(rows):
            c.vertex(
                name=None,
                value=_xml_escape(row),
                x=0,
                y=30 + i * 26,
                w=260,
                h=26,
                style=_ROW_STYLE,
                parent=sid,
            )
        y += h + 30

    x, y = 340, 40
    for t in _seq(spec.data_model.tables):
        rows = [_column_label(col) for col in _seq(t.columns)] + [
            f"Max rows: {_max_rows_label(t.max_rows)}"
        ]
        h = 30 + len(rows) * 26
        tid = c.vertex(
            name=None,
            value=_xml_escape(t.name),
            x=x,
            y=y,
            w=240,
            h=h,
            style=_TABLE_STYLE,
        )
        for i, row in enumerate(rows):
            c.vertex(
                name=None,
                value=_xml_escape(row),
                x=0,
                y=30 + i * 26,
                w=240,
                h=26,
                style=_ROW_STYLE,
                parent=tid,
            )
        y += h + 30

    x, y = 620, 40
    for lst in _seq(spec.master_data.lists):
        label = _two_line(lst.name, ", ".join(str(v) for v in _seq(lst.values)))
        c.vertex(name=None, value=label, x=x, y=y, w=220, h=80, style=_NOTE_STYLE)
        y += 100

    return c.xml()
