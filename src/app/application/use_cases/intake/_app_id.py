"""app.application.use_cases.intake._app_id -- the intake family's own copy
of the "app id" refusal (`brief_stage_d_common.md`, "The app id"; mirrors
`app.application.use_cases.flow._fields.require_app_id`).

A private copy rather than a shared one: the intake family imports no other
family's private module except the design family's, by explicit exception
(`brief_stage_d_common.md` lesson 11, `d8_intake_design.md`).
"""

from __future__ import annotations

from app.application.exceptions import REFUSED, ApplicationError

NO_APP_SELECTED = (
    "no app selected — pass app_id (see forge_list_apps for valid ids), or set "
    "the KF_APP env var as a single-app default"
)


def require_app_id(app_id: str) -> None:
    """Refuse an empty resolved `app_id` -- the tool resolves it, this checks it.

    Args:
        app_id: The tool-resolved app id: the per-call argument, else
            `settings.kf_app`, else `""`.

    Raises:
        ApplicationError: `app_id` is empty, `code=REFUSED`.
    """
    if not app_id:
        raise ApplicationError(NO_APP_SELECTED, code=REFUSED)
