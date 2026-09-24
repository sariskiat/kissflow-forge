"""app.application.use_cases.design._bundle -- the structural protocol every design
module is typed against.

Moved from `app.application.design.__init__` (Stage D group 8): this module carries
only the Protocol classes that used to live in that package's `__init__.py`. The
six public entry points (`_confirm.request_confirmation`/`apply_revisions`/
`is_approved`/`spec_digest`, `_diagram.flow_diagram_xml`/`schema_diagram_xml`,
`_mockup.design_bundle_html`/`form_mockups_html`/`persona_pages_html`) now live in
their own sibling modules and import each other directly -- nothing re-exports them
from here, since nothing needs a bundle import path any more (the old `server.py`
imported from the package `__init__`; the new thin tools import each use case
module directly).

Structural protocol, not a shared type
---------------------------------------
`app.application.intake` (a parallel, independently-authored node) owns the real
`AppSpec` Pydantic models this package renders.
`app.application.use_cases.design` never imports `app.application.intake` and never
will: two nodes of the same build editing each other's module is exactly the kind
of merge collision worth designing around. Instead, every function in `_diagram.py`/
`_mockup.py`/`_confirm.py` is typed against the minimal Protocol classes in this
file -- ordinary duck-typed attribute access, nothing isinstance-checked or
otherwise enforced at runtime. `tests/fakes/design_stubs.py` proves the contract
two ways: its own tiny stub dataclasses exercise this package's minimal
bare-sequence shape, and a second fixture mirrors
`app.application.models.requests.intake.app_spec`'s real attribute names/nesting
exactly (never importing it) to pin the adapter against reality.

`app.application.models.requests.intake.app_spec.AppSpec` wraps every dimension's
collection in its OWN small frozen container rather than exposing a bare tuple
directly -- `Stages.stages`, `Routing.points`, `ReworkLoops.loops`,
`TestCases.cases` -- and names the rework-loop dimension `rework_loops`, not
`loops`. Both facts are reflected here: `AppSpecLike.rework_loops` (matching
intake's real attribute name) is typed loosely as `Any` rather than
`Sequence[LoopLike]`, since it may legally be either a bare sequence OR a wrapper --
`app.application.use_cases.design._diagram._seq()` is what actually accepts either
shape at every call site; the Protocol here only documents that both are valid, it
enforces nothing at runtime. `stages`/`routing`/`test_cases` get the same `Any`
treatment for the same reason.

A few sub-shapes are intentionally left as `Sequence[Any]` rather than pinned
further, because nothing this package renders needs more than a human-readable
label for their elements: table `columns` and page `widgets` may arrive as plain
strings or as richer objects (intake's real `TableColumnReq`/`WidgetIntent`) --
callers in `_diagram.py`/`_mockup.py` fall back sensibly when no recognisable
attribute is present (see `_diagram._label`/`_column_label` and `_mockup`'s own
`_widget_label`, which specifically avoids leaking a raw `WidgetIntent` repr).

`AppSpecLike.test_cases` is STRUCTURALLY understood (a wrapper-or-bare sequence of
CaseWalkLike, each holding `fills: Sequence[StepFillLike]`) even though no function
here RENDERS a test case -- `_confirm.py`'s revision cascades (a stage rename, a
list-value correction) must still reach into
`CaseWalk.expected_path`/`StepFill.stage`/`StepFill.values` or a revision would
silently leave the test-case dimension referencing a name that no longer exists,
producing a spec intake's own `compile_spec()` rejects. "Structurally touched for
correctness" and "rendered for a human to read" are different claims; only the
first is true here.

`PersonaViewLike` carries `kpis`/`actions` directly (matching intake's
`PersonaView` -- a `PageIntent` in the real schema is just `name` + `widgets`,
nothing else). `FieldLike.list_name`/`.section` are read defensively via `getattr`
(`_mockup.py`'s `_select_control`/section grouping) rather than declared as
required Protocol attributes, since this package's own minimal stubs may omit them
entirely; intake's real `FieldReq.list_name`/`.section` are the real source when
present.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol


class StageLike(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def owner_role(self) -> str: ...
    @property
    def what_happens(self) -> str: ...


class RoutingPointLike(Protocol):
    @property
    def at_stage(self) -> str: ...
    @property
    def field_name(self) -> str: ...
    @property
    def options(self) -> Sequence[str]: ...
    @property
    def route_per_option(
        self,
    ) -> Any: ...  # Mapping[str, Sequence[str]] OR a tuple of (option, stage-sequence)

    # pairs -- dict(...) at every call site accepts either. A branch is an ordered
    # SEQUENCE of stages now (P1), a one-element sequence being the old single-stage
    # route; intake's DecisionPoint uses the tuple-of-pairs form.


class LoopLike(Protocol):
    @property
    def from_stage(self) -> str: ...
    @property
    def to_stage(self) -> str: ...
    @property
    def gate_field(self) -> str: ...


class FieldLike(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def type(self) -> str: ...
    @property
    def required(self) -> bool: ...
    @property
    def stage(self) -> str: ...

    # list_name: str | None, section: str | None -- both read via getattr(f, "...",
    # None), not declared here; see this module's own docstring.


class TableLike(Protocol):
    @property
    def name(self) -> str: ...
    # cross-checked against VisibilityMatrix for table-level visibility (_mockup.py)
    @property
    def stage(
        self,
    ) -> str: ...
    @property
    def columns(
        self,
    ) -> Sequence[
        Any
    ]: ...  # plain column-name strings, or objects with a `.name` (+ `.type`/
    # `.required`, used opportunistically by _diagram._column_label /
    # _mockup._column_header_label)
    @property
    def max_rows(self) -> int | None: ...


class SectionLike(Protocol):
    """intake's SectionReq: an explicit, named form section at a stage."""

    @property
    def name(self) -> str: ...
    @property
    def stage(self) -> str: ...
    @property
    def description(self) -> str: ...


class SequenceLike(Protocol):
    """intake's SequenceReq: the auto-numbered record id format."""

    @property
    def prefix(self) -> str: ...
    @property
    def padding(self) -> str: ...


class ComputedLike(Protocol):
    """intake's ComputedReq: a field the engine fills via a JS event, never something
    a user types -- see `_mockup.py`'s own field-row rendering for why this must be
    visually distinct from an ordinary editable control."""

    @property
    def target_field(self) -> str: ...
    @property
    def source_fields(self) -> Sequence[str]: ...
    @property
    def formula_intent(self) -> str: ...


class DataModelLike(Protocol):
    # _confirm.py calls _diagram._replace() on this, which accepts EITHER a real
    # dataclass or a Pydantic BaseModel
    # (app.application.use_cases.design._diagram._is_struct) -- no single marker
    # attribute is common to both shapes, so this protocol declares none; the dispatch
    # is a runtime isinstance check, not a static structural one.
    @property
    def fields(self) -> Sequence[FieldLike]: ...
    @property
    def tables(self) -> Sequence[TableLike]: ...
    @property
    def computed(self) -> Sequence[ComputedLike]: ...
    @property
    def sections(self) -> Sequence[SectionLike]: ...
    @property
    def sequence(self) -> SequenceLike | None: ...


class ListLike(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def values(self) -> Sequence[str]: ...


class MasterDataLike(Protocol):
    # _confirm.py calls _diagram._replace() on this -- see DataModelLike's own comment
    # above for why no marker attribute is declared here.
    @property
    def lists(self) -> Sequence[ListLike]: ...


class VisibilityEntryLike(Protocol):
    """intake's VisibilityEntry: one (section, stage) -> permission cell, optionally
    narrowed to one `field`. `permission` is duck-typed as a plain string value
    (compared via `str(...)` against "Hidden"/"ReadOnly"/"Editable") rather than
    importing `app.domain.value_objects.field_type.Visibility` -- the same
    reasoning as FieldLike.type: this package depends on no enum class from
    anywhere else in the repo, only on the wire-string VALUE, which a StrEnum
    member equals directly."""

    @property
    def section(self) -> str: ...
    @property
    def stage(self) -> str: ...
    @property
    def permission(self) -> Any: ...
    @property
    def field(self) -> str | None: ...


class PageLike(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def widgets(self) -> Sequence[Any]: ...


class PersonaViewLike(Protocol):
    @property
    def role(self) -> str: ...
    @property
    def pages(self) -> Sequence[PageLike]: ...
    @property
    def kpis(self) -> Sequence[Any]: ...
    @property
    def actions(self) -> Sequence[Any]: ...


class PersonasLike(Protocol):
    @property
    def views(self) -> Sequence[PersonaViewLike]: ...


class ProblemGoalLike(Protocol):
    """intake's ProblemGoal (dimension 1). Only `terminal_states`/`result_values`
    are rendered (`_mockup.py`'s "Where the work ends" -- the customer's OWN
    declared end states and outcome vocabulary, kept distinct from and labeled
    apart from the topology-DERIVED terminal list `_diagram._terminal_stages`
    already computed); `pain`/`goal`/`done_definition` are not."""

    @property
    def pain(self) -> str: ...
    @property
    def goal(self) -> str: ...
    @property
    def done_definition(self) -> str: ...
    @property
    def terminal_states(self) -> Sequence[str]: ...
    @property
    def result_values(self) -> Sequence[str]: ...


class StepFillLike(Protocol):
    """intake's StepFill. Not rendered to a human -- its shape is still touched by
    `_confirm.py`'s revision cascades (a stage rename must update `.stage`; a
    list-value correction must update `.values` for any field backed by that
    list)."""

    @property
    def stage(self) -> str: ...
    # Mapping[str, str] OR a tuple of (field_name, value) pairs, same convention as
    # RoutingPointLike.route_per_option
    @property
    def values(
        self,
    ) -> Any: ...


class CaseWalkLike(Protocol):
    """intake's CaseWalk. Not rendered to a human -- see StepFillLike for why its
    shape still matters to `_confirm.py`'s revision cascades."""

    @property
    def name(self) -> str: ...
    @property
    def fills(self) -> Sequence[StepFillLike]: ...
    @property
    def expected_path(self) -> Sequence[str]: ...
    @property
    def expected_result(self) -> str: ...


class AppSpecLike(Protocol):
    # _confirm.py calls _diagram._replace() on this -- see DataModelLike's own comment
    # above for why no marker attribute is declared here.
    @property
    def app_name(self) -> str: ...
    @property
    def problem_goal(self) -> ProblemGoalLike: ...
    # Sequence[StageLike] OR a Stages-style wrapper (.stages) -- see _diagram._seq
    @property
    def stages(
        self,
    ) -> Any: ...
    @property
    def routing(
        self,
    ) -> Any: ...  # Sequence[RoutingPointLike] OR a Routing-style wrapper (.points)
    @property
    def rework_loops(
        self,
    ) -> (
        Any
    ): ...  # Sequence[LoopLike] OR a ReworkLoops-style wrapper (.loops) -- named to
    # match intake's AppSpec.rework_loops, NOT "loops"
    @property
    def data_model(self) -> DataModelLike: ...
    @property
    def master_data(self) -> MasterDataLike: ...
    @property
    def visibility(
        self,
    ) -> Any: ...  # Sequence[VisibilityEntryLike] OR a VisibilityMatrix-style wrapper
    # (.entries) -- same wrapper-or-bare ambiguity as stages/routing/rework_loops, see
    # above
    @property
    def personas(self) -> PersonasLike: ...
    @property
    def test_cases(
        self,
    ) -> (
        Any
    ): ...  # Sequence[CaseWalkLike] OR a TestCases-style wrapper (.cases) -- structural

    # only, see this module's own docstring on why it is touched without being rendered
