"""DatasetRepository — the port over the Kissflow dataform-record builder family.

One abstract method per public `KfClient` method the `dataset` family owns (refactor
spec inventory, section 1): the `/dataset/2/{account}/{flow_id}` record routes, distinct
from the `/flow/2/{account}/dataset` route that creates the dataform shell itself (that
route is `FlowRepository.create_dataset`, family `flow`).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class DatasetRepository(ABC):
    """The dataform-record family: create, list, update and delete one record at a time.

    Every method raises `app.application.exceptions.RepositoryError` on any
    failure translated out of infrastructure. No method returns an `Err`.
    """

    @abstractmethod
    async def create_dataset_record(
        self, app_id: str, flow_id: str, record: dict[str, Any]
    ) -> dict[str, Any]:
        """Create one dataform record (`POST /dataset/2/{account}/{flow_id}`).

        Args:
            app_id: The application the dataform belongs to.
            flow_id: The dataform's flow id.
            record: `{"Name": ..., "<FieldId>": value, ...}`. `Name` is the
                record's unique key; a duplicate raises `code="CONFLICT"`.

        Returns:
            The created record.

        Raises:
            RepositoryError: The create failed, or the name already exists
                (`code="CONFLICT"`).
        """
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    async def list_dataset_records(self, app_id: str, flow_id: str) -> dict[str, Any]:
        """List a dataform's records and schema
        (`GET /dataset/2/{account}/{flow_id}/list`).

        Args:
            app_id: The application the dataform belongs to.
            flow_id: The dataform's flow id.

        Returns:
            `{"Columns": [...], "Data": [...]}`.

        Raises:
            RepositoryError: The read failed.
        """
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    async def update_dataset_record(
        self, app_id: str, flow_id: str, record_id: str, record: dict[str, Any]
    ) -> dict[str, Any]:
        """Partially update one dataform record by its id
        (`PUT /dataset/2/{account}/{flow_id}?_id={record_id}`).

        Args:
            app_id: The application the dataform belongs to.
            flow_id: The dataform's flow id.
            record_id: The record's `_id`.
            record: Only the keys to change; a partial patch.

        Returns:
            The updated record.

        Raises:
            RepositoryError: The update failed.
        """
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    async def delete_dataset_record(
        self, app_id: str, flow_id: str, record_id: str, name: str
    ) -> dict[str, Any]:
        """Delete one dataform record by its id
        (`DELETE /dataset/2/{account}/{flow_id}?_id={record_id}`).

        Args:
            app_id: The application the dataform belongs to.
            flow_id: The dataform's flow id.
            record_id: The record's `_id`.
            name: The record's synthetic system `Name` key, mandatory on
                this route.

        Returns:
            The parsed response body.

        Raises:
            RepositoryError: The delete failed.
        """
        raise NotImplementedError  # pragma: no cover
