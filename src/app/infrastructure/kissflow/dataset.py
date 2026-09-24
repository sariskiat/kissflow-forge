"""KissflowDatasetRepository — the httpx adapter for the `DatasetRepository` port.

Same four routes as `KfClient.create_dataset_record`/`list_dataset_records`/
`update_dataset_record`/`delete_dataset_record` (`client.py:628-676` pre-refactor),
rewritten onto the shared async transport (`_http.py`). Raises `RepositoryError`, per
spec G7 Part 1.
"""

from __future__ import annotations

import urllib.parse
from typing import Any

import httpx

from app.application.exceptions import RepositoryError
from app.application.interfaces.dataset import DatasetRepository
from app.infrastructure.config.settings import Settings
from app.infrastructure.kissflow._http import (
    build_query,
    quote_path_segment,
    send_json,
    sign,
)
from app.infrastructure.kissflow.credentials import caller_keys


class KissflowDatasetRepository(DatasetRepository):
    """Implements `DatasetRepository` with httpx. Built once, shared by every app."""

    def __init__(
        self, client: httpx.AsyncClient, base_url: str, settings: Settings
    ) -> None:
        """Build the adapter around a shared pool.

        Args:
            client: The `httpx.AsyncClient` the lifespan opened.
            base_url: `f"https://{settings.kf_dev_domain}"`.
            settings: The process `Settings`, for the account id and the
                caller's key pair (`caller_keys`, resolved fresh per call).
        """
        self._client = client
        self._base_url = base_url.rstrip("/")
        self._settings = settings
        # Resolved from `settings.base_url`, NOT from `base_url` above: the runtime
        # host check (security-judge finding 2) must hold even when `base_url` itself
        # is wrong, so it cannot be derived from the same value it is meant to check.
        self._expected_host = urllib.parse.urlsplit(settings.base_url).hostname or ""
        self._account_id = settings.kf_dev_account_id

    def _headers(self) -> dict[str, str]:
        return sign(caller_keys(self._settings))

    def _segment(self, value: str) -> str:
        return quote_path_segment(value, RepositoryError)

    async def _send(
        self, method: str, url: str, *, json_body: Any | None = None
    ) -> Any:
        """Send one request through the shared transport.

        Bound to this family's error class, expected host and account id, so
        every call site only names the method, the URL and the body.

        Args:
            method: The HTTP verb.
            url: The full request URL.
            json_body: The JSON-serialisable request body, or `None`.

        Returns:
            The parsed JSON response body.
        """
        return await send_json(
            self._client,
            method,
            url,
            RepositoryError,
            expected_host=self._expected_host,
            account_id=self._account_id,
            json_body=json_body,
            headers=self._headers(),
        )

    async def create_dataset_record(
        self, app_id: str, flow_id: str, record: dict[str, Any]
    ) -> dict[str, Any]:
        """See `DatasetRepository.create_dataset_record`."""
        account = self._settings.kf_dev_account_id
        query = build_query({"_application_id": app_id})
        url = f"{self._base_url}/dataset/2/{account}/{self._segment(flow_id)}{query}"
        return await self._send("POST", url, json_body=record)

    async def list_dataset_records(self, app_id: str, flow_id: str) -> dict[str, Any]:
        """See `DatasetRepository.list_dataset_records`."""
        account = self._settings.kf_dev_account_id
        query = build_query({"_application_id": app_id})
        url = (
            f"{self._base_url}/dataset/2/{account}/{self._segment(flow_id)}/list{query}"
        )
        return await self._send("GET", url)

    async def update_dataset_record(
        self, app_id: str, flow_id: str, record_id: str, record: dict[str, Any]
    ) -> dict[str, Any]:
        """See `DatasetRepository.update_dataset_record`."""
        account = self._settings.kf_dev_account_id
        query = build_query({"_application_id": app_id, "_id": record_id})
        url = f"{self._base_url}/dataset/2/{account}/{self._segment(flow_id)}{query}"
        return await self._send("PUT", url, json_body=record)

    async def delete_dataset_record(
        self, app_id: str, flow_id: str, record_id: str, name: str
    ) -> dict[str, Any]:
        """See `DatasetRepository.delete_dataset_record`."""
        account = self._settings.kf_dev_account_id
        query = build_query({"_application_id": app_id, "_id": record_id})
        url = f"{self._base_url}/dataset/2/{account}/{self._segment(flow_id)}{query}"
        return await self._send("DELETE", url, json_body={"Name": name})
