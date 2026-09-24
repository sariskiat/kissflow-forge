"""KissflowItemService — the httpx adapter for the `ItemService` port.

Same five routes as `LiveDataPlane` (`dataplane.py:68-99` pre-refactor), rewritten onto
the shared async transport (`_http.py`). No route carries an `app_id` --
`LiveDataPlane._base()` never read one either, only `account`. Raises
`ExternalServiceError`, per spec G7 Part 1.
"""

from __future__ import annotations

import urllib.parse
from typing import Any

import httpx

from app.application.exceptions import ExternalServiceError
from app.application.interfaces.item import ItemService
from app.infrastructure.config.settings import Settings
from app.infrastructure.kissflow._http import quote_path_segment, send_json, sign
from app.infrastructure.kissflow.credentials import caller_keys


class KissflowItemService(ItemService):
    """Implements `ItemService` with httpx. Built once, shared by every app."""

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

    def _base(self) -> str:
        return f"{self._base_url}/process/2/{self._settings.kf_dev_account_id}"

    def _segment(self, value: str) -> str:
        return quote_path_segment(value, ExternalServiceError)

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
            ExternalServiceError,
            expected_host=self._expected_host,
            account_id=self._account_id,
            json_body=json_body,
            headers=self._headers(),
        )

    async def create_item(self, flow_id: str) -> dict[str, Any]:
        """See `ItemService.create_item`."""
        url = f"{self._base()}/{self._segment(flow_id)}"
        return await self._send("POST", url)

    async def put_fields(
        self, flow_id: str, iid: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """See `ItemService.put_fields`."""
        url = f"{self._base()}/admin/{self._segment(flow_id)}/{self._segment(iid)}"
        return await self._send("PUT", url, json_body=payload)

    async def get_detail(self, flow_id: str, iid: str) -> dict[str, Any]:
        """See `ItemService.get_detail`."""
        url = f"{self._base()}/admin/{self._segment(flow_id)}/{self._segment(iid)}"
        return await self._send("GET", url)

    async def submit(self, flow_id: str, iid: str, aiid: str) -> dict[str, Any]:
        """See `ItemService.submit`."""
        url = (
            f"{self._base()}/{self._segment(flow_id)}"
            f"/{self._segment(iid)}/{self._segment(aiid)}/submit"
        )
        return await self._send("POST", url)

    async def reject(
        self, flow_id: str, iid: str, aiid: str, comment: str
    ) -> dict[str, Any]:
        """See `ItemService.reject`."""
        url = (
            f"{self._base()}/{self._segment(flow_id)}"
            f"/{self._segment(iid)}/{self._segment(aiid)}/reject"
        )
        return await self._send("POST", url, json_body={"Comment": comment})
