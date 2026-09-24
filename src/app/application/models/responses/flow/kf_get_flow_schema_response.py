"""Response DTO for `kf_get_flow_schema`."""

from __future__ import annotations

from typing import Any

from pydantic import RootModel


class KfGetFlowSchemaResponse(RootModel[dict[str, Any]]):
    """The draft graph itself, returned verbatim -- today's `kf_get_flow_schema`
    result is the raw draft dict, not a wrapped shape, so this is a `RootModel`
    rather than a field-by-field `BaseModel` (spec G10)."""
