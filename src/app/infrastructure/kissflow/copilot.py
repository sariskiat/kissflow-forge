"""KissflowCopilotService — the httpx adapter for the `CopilotService` port.

Same two routes as `KfClient.copilot_send`/`copilot_conversations` (`client.py:571-599`
pre-refactor), rewritten onto the shared async transport (`_http.py`). Raises
`ExternalServiceError`, per spec G7 Part 1.
"""

from __future__ import annotations

import urllib.parse
from typing import Any

import httpx

from app.application.exceptions import ExternalServiceError
from app.application.interfaces.copilot import CopilotService
from app.infrastructure.config.settings import Settings
from app.infrastructure.kissflow._http import (
    build_query,
    quote_path_segment,
    send_json,
    sign,
)
from app.infrastructure.kissflow.credentials import caller_keys


class KissflowCopilotService(CopilotService):
    """Implements `CopilotService` with httpx. Built once, shared by every app."""

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

    async def copilot_send(self, app_id: str, message: str) -> Any:
        """See `CopilotService.copilot_send`."""
        account = self._settings.kf_dev_account_id
        query = build_query({"_application_id": app_id})
        url = (
            f"{self._base_url}/metadata/2/{account}"
            f"/ai/application/{self._segment(app_id)}"
            f"/copilot/send{query}"
        )
        return await self._send("POST", url, json_body={"UserMessage": message})

    async def copilot_conversations(self, app_id: str) -> list[dict[str, Any]]:
        """See `CopilotService.copilot_conversations`."""
        account = self._settings.kf_dev_account_id
        query = build_query({"_application_id": app_id})
        url = (
            f"{self._base_url}/metadata/2/{account}"
            f"/ai/application/{self._segment(app_id)}"
            f"/copilot/conversations{query}"
        )
        return await self._send("GET", url)
