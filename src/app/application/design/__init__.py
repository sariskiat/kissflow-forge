"""app.application.design -- the "confirm before you build" layer.

Nothing under src/app/ writes to the Kissflow builder API from a customer's spoken requirements
without a human first SEEING the design and typing back an explicit approval. This package is
that seam: it turns a spec into two draw.io diagrams, a set of readable HTML mockups, and a short
list of Thai yes/no questions about every risky choice the spec makes (a routing literal, a loop
gate's polarity, a terminal state, a required field, a master-data list's values) -- see
CLAUDE.md's own "THE RULE THAT COST THIS PROJECT A WHOLE SESSION" for why an API 200 was never
allowed to stand in for this. The mockups are a FAITHFUL rendering, not just a legible one: a
field the built app hides or makes read-only must not render as a plain live input, and a field
the app computes for the user must not render as something the user types -- both were bugs a
first review round caught (the artifact ASSERTING THE OPPOSITE of what the spec says is strictly
worse than omitting the field, since it invites a false approval).

Structural protocol, not a shared type
---------------------------------------
app.application.intake (a parallel, independently-authored node) owns the real `AppSpec` dataclasses this
package renders. app.application.design never imports app.application.intake and never will: two nodes of the same
build editing each other's module is exactly the kind of merge collision worth designing around.
Instead, every function below is typed against the minimal Protocol classes in this file --
ordinary duck-typed attribute access, nothing isinstance-checked or otherwise enforced at runtime.
`tests/test_design.py` proves the contract two ways: its own tiny stub dataclasses exercise this
package's minimal bare-sequence shape, and a second fixture mirrors app.application.intake.schema's real
attribute names/nesting exactly (never importing it) to pin the adapter against reality.

app.application.intake.schema.AppSpec wraps every dimension's collection in its OWN small frozen
container rather than exposing a bare tuple directly -- `Stages.stages`, `Routing.points`,
`ReworkLoops.loops`, `TestCases.cases` -- and names the rework-loop dimension `rework_loops`, not
`loops`. Both facts are reflected here: `AppSpecLike.rework_loops` (matching intake's real
attribute name) is typed loosely as `Any` rather than `Sequence[LoopLike]`, since it may legally
be either a bare sequence OR a wrapper -- `app.application.design.diagram._seq()` is what actually accepts
either shape at every call site; the Protocol here only documents that both are valid, it enforces
nothing at runtime. `stages`/`routing`/`test_cases` get the same `Any` treatment for the same
reason.

A few sub-shapes are intentionally left as `Sequence[Any]` rather than pinned further, because
nothing this package renders needs more than a human-readable label for their elements: table
`columns` and page `widgets` may arrive as plain strings or as richer objects (app.application.intake.
schema's real `TableColumnReq`/`WidgetIntent`) -- callers in diagram.py/mockup.py fall back
sensibly when no recognisable attribute is present (see `diagram._label`/`_column_label` and
mockup.py's own `_widget_label`, which specifically avoids leaking a raw `WidgetIntent` repr).

`AppSpecLike.test_cases` is STRUCTURALLY understood (a wrapper-or-bare sequence of CaseWalkLike,
each holding `fills: Sequence[StepFillLike]`) even though no function here RENDERS a test case --
`confirm.py`'s revision cascades (a stage rename, a list-value correction) must still reach into
`CaseWalk.expected_path`/`StepFill.stage`/`StepFill.values` or a revision would silently leave the
test-case dimension referencing a name that no longer exists, producing a spec app.application.intake's
own `compile_spec()` rejects. "Structurally touched for correctness" and "rendered for a human to
read" are different claims; only the first is true here (see the KNOWN GAPS section below for m5).

`PersonaViewLike` carries `kpis`/`actions` directly (matching app.application.intake.schema.PersonaView --
a `PageIntent` in the real schema is just `name` + `widgets`, nothing else). `FieldLike.list_name`/
`.section` are read defensively via `getattr` (mockup.py's `_select_control`/section grouping)
rather than declared as required Protocol attributes, since this package's own minimal stubs may
omit them entirely; `app.application.intake.schema.FieldReq.list_name`/`.section` are the real source when
present.

KNOWN GAPS, logged rather than silently discovered later -- every dimension/field below is either
read structurally (for a revision cascade to stay correct) without being shown to a human, or not
read at all. None of them block a customer from approving a faithful design; each is a piece of
the real schema this package's own artifacts stay silent about, which is exactly the kind of thing
a customer-facing artifact must be honest about to the next maintainer rather than pretend not to
have (app.application.intake.schema's own "KNOWN GAPS" section is the model this list follows):

- `Timing` (dimension 9: sla_notes/batch_days/reminders) renders nowhere. It is intake's own
  ADVISORY dimension -- `compile_spec` derives no op from it at all -- so nothing downstream of a
  spec depends on it either; there is no faithfulness risk in staying silent about it, only an
  absence.
- `LoopSpec.max_rounds` renders nowhere -- the gate field, direction, and from/to stages do; the
  round CAP a loop is allowed to run does not.
- `RoleSpec.members_hint`/`.is_admin` render nowhere, and a role that owns no stage and appears in
  no persona view is invisible in every artifact here (it is still `member_batch`'d by
  `compile_spec`, just never shown in a diagram or mockup).
- `StageSpec.entry_criteria`/`.exit_criteria` render nowhere -- only `name`/`owner_role`/
  `what_happens` do.
- `ListSpec.owner_role` renders nowhere -- a list's name and values do; who owns/maintains it does
  not.
- `ProblemGoal.pain`/`.goal`/`.done_definition` render nowhere -- only `.terminal_states`/
  `.result_values` do (mockup.py's "Where the work ends" section).
- `TestCases`/`CaseWalk` (dimension 11) render nowhere as content for a human to read -- see this
  module's own note above on why their SHAPE is still touched by revision cascades.
- An unreachable stage is flagged `"(unreachable?)"` in `flow_diagram_xml` but renders as an
  ordinary, unflagged card in the HTML mockups -- the two artifacts disagree with each other on
  this one point.
- `diagram._Canvas.resolve`'s positional fallback boxes (for a name nothing else has already
  boxed) can visually interleave with a routing branch's own target boxes even on a perfectly
  compile-legal spec -- the offset is a monotonically-incrementing counter, not a collision-
  checked layout.
- Revising a loop's `from_stage`/`to_stage` via `apply_revisions` changes the very key
  (`loop:<from_stage>:<to_stage>:...`) a caller would need to address that SAME loop again in a
  later call -- the caller must re-derive the new key from the RETURNED spec, never reuse the old
  one across a from/to revision.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, ClassVar, Protocol


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

    # pairs -- dict(...) at every call site accepts either. A branch is an ordered SEQUENCE of
    # stages now (P1), a one-element sequence being the old single-stage route;
    # app.application.intake.schema.DecisionPoint uses the tuple-of-pairs form.


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

    # list_name: str | None, section: str | None -- both read via getattr(f, "...", None), not
    # declared here; see this module's own docstring.


class TableLike(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def stage(
        self,
    ) -> str: ...  # cross-checked against VisibilityMatrix for table-level visibility (mockup.py)
    @property
    def columns(
        self,
    ) -> Sequence[Any]: ...  # plain column-name strings, or objects with a `.name` (+ `.type`/
    # `.required`, used opportunistically by diagram._column_label / mockup._column_header_label)
    @property
    def max_rows(self) -> int | None: ...


class SectionLike(Protocol):
    """app.application.intake.schema.SectionReq: an explicit, named form section at a stage."""

    @property
    def name(self) -> str: ...
    @property
    def stage(self) -> str: ...
    @property
    def description(self) -> str: ...


class SequenceLike(Protocol):
    """app.application.intake.schema.SequenceReq: the auto-numbered record id format."""

    @property
    def prefix(self) -> str: ...
    @property
    def padding(self) -> str: ...


class ComputedLike(Protocol):
    """app.application.intake.schema.ComputedReq: a field the engine fills via a JS event, never something
    a user types -- see mockup.py's own field-row rendering for why this must be visually distinct
    from an ordinary editable control."""

    @property
    def target_field(self) -> str: ...
    @property
    def source_fields(self) -> Sequence[str]: ...
    @property
    def formula_intent(self) -> str: ...


class DataModelLike(Protocol):
    # confirm.py calls dataclasses.replace() on this; that requires a real dataclass, so
    # the protocol says so explicitly instead of leaving it to chance.
    __dataclass_fields__: ClassVar[dict[str, Any]]

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
    # confirm.py calls dataclasses.replace() on this; that requires a real dataclass, so
    # the protocol says so explicitly instead of leaving it to chance.
    __dataclass_fields__: ClassVar[dict[str, Any]]

    @property
    def lists(self) -> Sequence[ListLike]: ...


class VisibilityEntryLike(Protocol):
    """app.application.intake.schema.VisibilityEntry: one (section, stage) -> permission cell, optionally
    narrowed to one `field`. `permission` is duck-typed as a plain string value (compared via
    `str(...)` against "Hidden"/"ReadOnly"/"Editable") rather than importing app.domain.types.
    Visibility -- the same reasoning as FieldLike.type: this package depends on no enum class from
    anywhere else in the repo, only on the wire-string VALUE, which a StrEnum member equals
    directly."""

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
    """app.application.intake.schema.ProblemGoal (dimension 1). Only `terminal_states`/`result_values` are
    rendered (mockup.py's "Where the work ends" -- the customer's OWN declared end states and
    outcome vocabulary, kept distinct from and labeled apart from the topology-DERIVED terminal
    list `diagram._terminal_stages` already computed); `pain`/`goal`/`done_definition` are not
    (see this module's KNOWN GAPS)."""

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
    """app.application.intake.schema.StepFill. Not rendered to a human (see KNOWN GAPS/m5) -- its shape is
    still touched by confirm.py's revision cascades (a stage rename must update `.stage`; a
    list-value correction must update `.values` for any field backed by that list)."""

    @property
    def stage(self) -> str: ...
    @property
    def values(
        self,
    ) -> Any: ...  # Mapping[str, str] OR a tuple of (field_name, value) pairs, same convention as

    # RoutingPointLike.route_per_option


class CaseWalkLike(Protocol):
    """app.application.intake.schema.CaseWalk. Not rendered to a human (see KNOWN GAPS/m5) -- see
    StepFillLike for why its shape still matters to confirm.py's revision cascades."""

    @property
    def name(self) -> str: ...
    @property
    def fills(self) -> Sequence[StepFillLike]: ...
    @property
    def expected_path(self) -> Sequence[str]: ...
    @property
    def expected_result(self) -> str: ...


class AppSpecLike(Protocol):
    # confirm.py calls dataclasses.replace() on this; that requires a real dataclass, so
    # the protocol says so explicitly instead of leaving it to chance.
    __dataclass_fields__: ClassVar[dict[str, Any]]

    @property
    def app_name(self) -> str: ...
    @property
    def problem_goal(self) -> ProblemGoalLike: ...
    @property
    def stages(
        self,
    ) -> Any: ...  # Sequence[StageLike] OR a Stages-style wrapper (.stages) -- see diagram._seq
    @property
    def routing(self) -> Any: ...  # Sequence[RoutingPointLike] OR a Routing-style wrapper (.points)
    @property
    def rework_loops(
        self,
    ) -> Any: ...  # Sequence[LoopLike] OR a ReworkLoops-style wrapper (.loops) -- named to
    # match app.application.intake.schema.AppSpec.rework_loops, NOT "loops"
    @property
    def data_model(self) -> DataModelLike: ...
    @property
    def master_data(self) -> MasterDataLike: ...
    @property
    def visibility(
        self,
    ) -> Any: ...  # Sequence[VisibilityEntryLike] OR a VisibilityMatrix-style wrapper
    # (.entries) -- same wrapper-or-bare ambiguity as stages/routing/rework_loops, see above
    @property
    def personas(self) -> PersonasLike: ...
    @property
    def test_cases(
        self,
    ) -> Any: ...  # Sequence[CaseWalkLike] OR a TestCases-style wrapper (.cases) -- structural

    # only, see this module's own docstring on why it is touched without being rendered


# Imported last and only for their public functions/dataclass -- each submodule references the
# Protocol types above ONLY under `if TYPE_CHECKING:` (see diagram.py/mockup.py/confirm.py), so
# there is no runtime import cycle: this module never needs anything back from them until these
# three lines run, well after every name above already exists.
from app.application.design.confirm import (  # noqa: E402  (deliberate: see comment above)
    ConfirmationRequest,
    apply_revisions,
    is_approved,
    request_confirmation,
    spec_digest,
)
from app.application.design.diagram import (  # noqa: E402
    flow_diagram_xml,
    schema_diagram_xml,
)
from app.application.design.mockup import (  # noqa: E402
    design_bundle_html,
    form_mockups_html,
    persona_pages_html,
)

__all__ = [
    "AppSpecLike",
    "CaseWalkLike",
    "ComputedLike",
    "ConfirmationRequest",
    "DataModelLike",
    "FieldLike",
    "ListLike",
    "LoopLike",
    "MasterDataLike",
    "PageLike",
    "PersonaViewLike",
    "PersonasLike",
    "ProblemGoalLike",
    "RoutingPointLike",
    "SectionLike",
    "SequenceLike",
    "StageLike",
    "StepFillLike",
    "TableLike",
    "VisibilityEntryLike",
    "apply_revisions",
    "design_bundle_html",
    "flow_diagram_xml",
    "form_mockups_html",
    "is_approved",
    "persona_pages_html",
    "request_confirmation",
    "schema_diagram_xml",
    "spec_digest",
]
