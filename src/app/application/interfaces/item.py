"""ItemService — the port over the Kissflow item data-plane family.

One abstract method per method of the `DataPlaneClient` protocol
(`infrastructure/kissflow/dataplane.py:53`, which extends `ItemDetailReader` at line 41)
— the documented `/process` API: create an item, fill it, read it back, submit or reject
it. Unlike the builder-API families, item raises
`app.application.exceptions.ExternalServiceError`, not `RepositoryError` (spec G7 Part
1). No method carries an `app_id`: every route here is `/process/2/{account}/...`,
scoped by `flow_id` alone, never by application.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class ItemService(ABC):
    """The item data plane: create, fill, read, submit and reject one item.

    Every method raises `app.application.exceptions.ExternalServiceError` on
    any failure translated out of infrastructure. No method returns an `Err`.
    An HTTP 200 here proves delivery, never storage — CLAUDE.md's item data
    plane trap — so a caller reads a value back with `get_detail` rather
    than trusting a `put_fields` response alone.
    """

    @abstractmethod
    async def create_item(self, flow_id: str) -> dict[str, Any]:
        """Create a new item (`POST /process/2/{account}/{flow_id}`).

        Args:
            flow_id: The process flow's id.

        Returns:
            The created item's detail, including its `iid`.

        Raises:
            ExternalServiceError: The create failed.
        """
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    async def put_fields(
        self, flow_id: str, iid: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Write field values onto an item
        (`PUT /process/2/{account}/admin/{flow_id}/{iid}`).

        A 200 here does not prove the value landed — a Select value that is
        not a real option is silently discarded. Read the item back with
        `get_detail` to verify.

        Args:
            flow_id: The process flow's id.
            iid: The item's id.
            payload: The field values to write, keyed by field name.

        Returns:
            The parsed response body.

        Raises:
            ExternalServiceError: The write failed.
        """
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    async def get_detail(self, flow_id: str, iid: str) -> dict[str, Any]:
        """Read an item's admin detail (`GET
        /process/2/{account}/admin/{flow_id}/{iid}`).

        The admin route; the non-admin path 404s and is never called.

        Args:
            flow_id: The process flow's id.
            iid: The item's id.

        Returns:
            The item's detail.

        Raises:
            ExternalServiceError: The read failed.
        """
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    async def submit(self, flow_id: str, iid: str, aiid: str) -> dict[str, Any]:
        """Submit an item's current activity instance
        (`POST /process/2/{account}/{flow_id}/{iid}/{aiid}/submit`).

        Args:
            flow_id: The process flow's id.
            iid: The item's id.
            aiid: The live activity-instance id to submit.

        Returns:
            The parsed response body.

        Raises:
            ExternalServiceError: The submit failed.
        """
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    async def reject(
        self, flow_id: str, iid: str, aiid: str, comment: str
    ) -> dict[str, Any]:
        """Reject an item's current activity instance
        (`POST /process/2/{account}/{flow_id}/{iid}/{aiid}/reject`).

        Args:
            flow_id: The process flow's id.
            iid: The item's id.
            aiid: The live activity-instance id to reject.
            comment: The rejection comment.

        Returns:
            The parsed response body.

        Raises:
            ExternalServiceError: The reject failed.
        """
        raise NotImplementedError  # pragma: no cover
