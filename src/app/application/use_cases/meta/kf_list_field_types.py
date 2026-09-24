"""app.application.use_cases.meta.kf_list_field_types — the `kf_list_field_types` use
case.
"""

from __future__ import annotations

from app.application.models.requests.meta.kf_list_field_types_request import (
    KfListFieldTypesRequest,
)
from app.application.models.responses.meta.kf_list_field_types_response import (
    KfListFieldTypesResponse,
)
from app.application.use_cases.meta._field_types import list_field_types


class KfListFieldTypes:
    """List the field types this engine can build. Pure and offline -- no port, no
    Kissflow tenant, no filesystem."""

    async def execute(
        self, request: KfListFieldTypesRequest
    ) -> KfListFieldTypesResponse:
        """Return the engine's own field-type catalog.

        Args:
            request: The validated `kf_list_field_types` request (no fields).

        Returns:
            Every buildable field type's wire value.
        """
        del request
        return KfListFieldTypesResponse(list_field_types())
