"""app.application.exceptions — the one error hierarchy every use case raises instead of
returning a sentinel value. Copied word for word from the boilerplate clone's
`src/app/application/exceptions.py` (`mcp-server-python-boilerplate @ 67c22ae`).

`ApplicationError` and its two subclasses are safe to let cross the
application/infrastructure boundary: `.message` is human-readable and carries no secret,
and `.code` is a short, stable string an MCP tool can surface (mapped to a `ToolError`
at the tool edge, later goals). The module-level code constants below are `str` equal to
their own name, so `code == "CONFLICT"` reads the same whether you spell it as the
constant or the literal.
"""

from __future__ import annotations

REPOSITORY_ERROR = "REPOSITORY_ERROR"
EXTERNAL_SERVICE_ERROR = "EXTERNAL_SERVICE_ERROR"
CONFLICT = "CONFLICT"
VERIFY_FAILED = "VERIFY_FAILED"
NOT_FOUND = "NOT_FOUND"
REFUSED = "REFUSED"


class ApplicationError(Exception):
    """Base exception safe for application/MCP boundaries."""

    def __init__(self, message: str, code: str = "APPLICATION_ERROR") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


class ExternalServiceError(ApplicationError):
    def __init__(self, message: str, code: str = "EXTERNAL_SERVICE_ERROR") -> None:
        super().__init__(message, code)


class RepositoryError(ApplicationError):
    def __init__(self, message: str, code: str = "REPOSITORY_ERROR") -> None:
        super().__init__(message, code)
