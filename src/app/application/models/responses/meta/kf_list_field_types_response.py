"""app.application.models.responses.meta.kf_list_field_types_response — the DTO for
`kf_list_field_types`'s result: today's bare `list[str]`, unchanged. No `isError` key
ever wrapped it, so `RootModel[list[str]]` keeps the exact same wire shape (the shared
brief's rule for a free-form result whose shape must not change).
"""

from __future__ import annotations

from pydantic import RootModel


class KfListFieldTypesResponse(RootModel[list[str]]):
    """The field types this engine can build, exactly as
    `app.application.use_cases.meta._field_types.list_field_types` returns them."""
