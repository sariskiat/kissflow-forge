"""The coverage contract — the single in-repo table naming every shape a process
diagram may contain, each landing in exactly one bucket.

It is the source of truth both the *builder* (compile-time refusals) and the
*reader* skill consult: a refusal names its row by `key`, and the reader refuses
any shape whose row is not buildable. Transcribed from the map ticket #26 table
plus the API-impossible rows absorbed from #7 — a data structure in the repo, not
only on the tracker, so the two readers can't drift (spec #29, D13/D14).

Three buckets, exactly one per row (#26):

- ``CAPTURED_LIVE`` — a live capture proves the shape builds; the engine builds it
  today. (This is about the *shape* having a proven capture, not about which build
  step emits it — the autonomous-compiler path for splits is separate S-series
  work, tracked as ``BUILDABLE`` rows / capability tickets.)
- ``BUILDABLE`` — the engine will build it, not yet captured live; pending its
  ticket.
- ``REFUSES_LOUDLY`` — the engine refuses it, naming a reason. Either *pending* a
  wiring ticket, or a permanent *Known Exclusion* (a written reason, no ticket).

A row is *pending* (behavior promised by a ticket, not in code yet) exactly when it
carries a ``ticket``. Capability tickets flip their row's ``ticket`` to ``None`` as
they land; the closing gate B2 (#36) adds the "every refuse-row is wired to a real
refusal" assertion. B1 (#31) builds this skeleton and the integrity contract test
(``tests/test_coverage.py``); it does NOT yet require pending rows to be wired.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Bucket(StrEnum):
    """The one home a shape lands in. Exactly one per row is the invariant (#26)."""
    CAPTURED_LIVE = "captured-live"
    BUILDABLE = "buildable"
    REFUSES_LOUDLY = "refuses-loudly"


@dataclass(frozen=True)
class CoverageRow:
    """One shape a diagram may contain, and how the engine covers it.

    ``ticket`` — the capture/wiring ticket this row waits on (e.g. ``"#33"``);
    ``None`` means done (a captured-live shape) or a permanent Known Exclusion.
    ``reason`` — required on a ``REFUSES_LOUDLY`` row: why it refuses (a written
    Known Exclusion when there is no ticket).
    """
    key: str
    shape: str
    bucket: Bucket
    ticket: str | None = None
    reason: str | None = None

    @property
    def captured(self) -> bool:
        return self.bucket is Bucket.CAPTURED_LIVE

    @property
    def pending(self) -> bool:
        """Promised by a ticket, not yet in code (marked ``pending #<ticket>``)."""
        return self.ticket is not None


# The table. One row per shape a diagram may contain (#26 + the API-impossible set
# absorbed from #7). Every capability ticket wires its row here.
ROWS: tuple[CoverageRow, ...] = (
    # ── captured-live: a live capture proves it builds ──────────────────────────
    CoverageRow("straight-line", "straight line of person-tasks", Bucket.CAPTURED_LIVE),
    CoverageRow("one-split", "one split, branches rejoin", Bucket.CAPTURED_LIVE),
    CoverageRow("branch-local-loop", "loop back inside a branch", Bucket.CAPTURED_LIVE),
    CoverageRow("suspended-step", "suspended step", Bucket.CAPTURED_LIVE),
    # #9/#10/#12 below are refinement tickets on an already-live capability (per #26's
    # "yes, but #N"), NOT a coverage gap — the shape builds today, so no pending marker.
    CoverageRow("auto-numbered-id", "auto-numbered id", Bucket.CAPTURED_LIVE),  # refine: #9
    CoverageRow("child-table", "child table", Bucket.CAPTURED_LIVE),  # refine: #10
    CoverageRow("computed-field-event", "computed field via event", Bucket.CAPTURED_LIVE),  # refine: #12
    CoverageRow("per-step-visibility", "per-step visibility", Bucket.CAPTURED_LIVE),
    # ── buildable: engine will build it, not yet captured; pending its ticket ────
    CoverageRow(
        "sequential-splits", "several splits, one after another",
        Bucket.BUILDABLE, ticket="#33",
    ),
    # ── refuses-loudly, pending a wiring/capability ticket ──────────────────────
    CoverageRow(
        "nested-split", "a split nested inside a branch",
        Bucket.REFUSES_LOUDLY, ticket="#33",
        reason="no captured example of a split inside a branch; the engine never "
               "writes an uncaptured shape (THE RULE, D3).",
    ),
    CoverageRow(
        "word-list-dropdown", "dropdown backed by a word list",
        Bucket.REFUSES_LOUDLY, ticket="#13",
        reason="no build capability for a Kissflow List-backed Select yet; the "
               "reader only reads an existing live list to validate literals.",
    ),
    CoverageRow(
        "section-styling", "section styling",
        Bucket.REFUSES_LOUDLY, ticket="#11",
        reason="section colour-styling is not built through the autonomous path yet.",
    ),
    CoverageRow(
        "report-widget", "a report behind a chart widget",
        Bucket.REFUSES_LOUDLY, ticket="#23",
        reason="no tool to read a report or wire one into a page widget yet (#23); "
               "distinct from creating a report (see report-creation).",
    ),
    CoverageRow(
        "report-creation", "report creation",
        Bucket.REFUSES_LOUDLY, ticket="#36",
        reason="no tool to create a report; refused at compile per ADR-0004, wired "
               "by the B2 closing gate.",
    ),
    CoverageRow(
        "rich-text-content", "rich-text component content",
        Bucket.REFUSES_LOUDLY, ticket="#36",
        reason="rich-text serialization is uncaptured (Pages known gaps); refused "
               "at compile per ADR-0004, wired by the B2 closing gate.",
    ),
    CoverageRow(
        "custom-component", "custom component",
        Bucket.REFUSES_LOUDLY, ticket="#36",
        reason="no API-driven component install path exists; refused at compile per "
               "ADR-0004, wired by the B2 closing gate.",
    ),
    CoverageRow(
        "role-scoped-visibility", "role-scoped visibility",
        Bucket.REFUSES_LOUDLY, ticket="#6",
        reason="API-impossible; the doctor's refusal, not compile's (ADR-0003), "
               "tracked separately in #6.",
    ),
    # ── refuses-loudly, permanent Known Exclusion (a written reason, no ticket) ──
    CoverageRow(
        "cross-branch-jump", "a jump from one branch into another",
        Bucket.REFUSES_LOUDLY,
        reason="refused on purpose; no captured shape (THE RULE). verify.doctor rule "
               "2b already flags a GotoTask whose target sits in a different ProcessDef.",
    ),
    CoverageRow(
        "auto-step", "a step that is not a person's task (auto step, approval gate, webhook)",
        Bucket.REFUSES_LOUDLY,
        reason="no captured shape for a non-person task; refused rather than silently "
               "downgraded to a person's task (D6). No capture ticket scoped yet, so a "
               "written Known Exclusion until one exists.",
    ),
)


_BY_KEY: dict[str, CoverageRow] = {row.key: row for row in ROWS}


def get(key: str) -> CoverageRow:
    """The row for `key`, for a builder/reader refusal to name. Unknown key is a
    programming error — the key must be a real row in the contract."""
    if key not in _BY_KEY:
        raise KeyError(
            f"no coverage row keyed {key!r}; a refusal must name a real row in the contract"
        )
    return _BY_KEY[key]
