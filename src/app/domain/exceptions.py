class DomainError(Exception):
    """Base exception for domain-level failures."""


class ShapeRefused(DomainError, ValueError):
    """Raised when a coverage row refuses to build a node-graph shape.

    Subclasses both `DomainError` and `ValueError`, so every site that
    already does `except ValueError` (CLAUDE.md's `REFUSES_LOUDLY` rows,
    `coverage.py`) keeps catching it unchanged.

    Attributes:
        row_key: The `CoverageRow.key` naming the refused shape.
        reason: The written reason the row refuses to build.
    """

    def __init__(self, row_key: str, reason: str) -> None:
        """Build a ShapeRefused for one coverage row.

        Args:
            row_key: The `CoverageRow.key` naming the refused shape.
            reason: The written reason the row refuses to build. Every
                caller in `application.intake.compile` already names its own
                row inside this text, so it is the message VERBATIM -- never
                prefixed with `row_key` again, which would print the row
                twice.
        """
        self.row_key = row_key
        self.reason = reason
        super().__init__(reason)
