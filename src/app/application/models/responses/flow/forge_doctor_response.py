"""Response DTO for `forge_doctor`."""

from __future__ import annotations

from pydantic import BaseModel


class ForgeDoctorResponse(BaseModel):
    """`forge_doctor`'s success result (the former `run_doctor` dict).

    Attributes:
        flow_id: The audited flow's id.
        ok: `True` when `problems` is empty.
        problems: Concrete problem sentences.
        checked: Per-rule counts of units examined.
        unvalidated: Branch literals or membership claims that could not be
            checked (missing list options, an unreadable member roster).
        unvalidatable_scripts: How many scripts could never be fully proven.
        list_ids_checked: Select-field list ids whose options were fetched
            and checked.
        list_fetch_errors: `{list id: error}` for a list whose items could
            not be fetched.
        members_found: The live member roster size, or `None` when no
            AppRole assignee exists (nothing to check) or the roster could
            not be read.
        member_fetch_error: The member-roster read's own error, when one
            occurred.
    """

    flow_id: str
    ok: bool
    problems: list[str]
    checked: dict[str, int]
    unvalidated: list[str]
    unvalidatable_scripts: int
    list_ids_checked: list[str]
    list_fetch_errors: dict[str, str]
    members_found: int | None
    member_fetch_error: str | None
