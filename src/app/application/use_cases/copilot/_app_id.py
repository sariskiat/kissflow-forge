"""The app-id resolution rule every copilot-family use case shares.

The MCP tool edge resolves the raw value (the tool's own `app_id` argument,
falling back to `settings.kf_app`, per the spec's "The app id" section) and
hands the resolved string to the request DTO. This module holds the one
remaining piece: refusing an app id that resolved to nothing, with the exact
message `server.py:300-304` used before the refactor (CLAUDE.md > lesson
14 -- one copy of this rule per family, mirroring
`app.application.use_cases.app._app_id.require_app_id`).
"""

from __future__ import annotations

from app.application.exceptions import REFUSED, ApplicationError

_NO_APP_MESSAGE = (
    "no app selected — pass app_id (see forge_list_apps for valid ids), or set "
    "the KF_APP env var as a single-app default"
)


def require_app_id(app_id: str) -> str:
    """Refuse an app-scoped call whose app id resolved to nothing.

    Args:
        app_id: The already-resolved app id: the tool's own `app_id`
            argument if given, else `settings.kf_app`, else `""`.

    Returns:
        `app_id`, unchanged, when it is non-empty.

    Raises:
        ApplicationError: `app_id` is empty, `code=REFUSED`.
    """
    if not app_id:
        raise ApplicationError(_NO_APP_MESSAGE, code=REFUSED)
    return app_id
