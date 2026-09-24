"""KissflowPageRepository — the httpx adapter for the `PageRepository` port.

Same six routes as `KfClient`'s page methods (`client.py:743-805` pre-refactor),
rewritten onto the shared async transport (`_http.py`). `put_page_draft` keeps the
read-verify-write guard (`_http.read_verify_write`). Raises `RepositoryError`, per spec
G7 Part 1.
"""

from __future__ import annotations

import urllib.parse
from typing import Any

import httpx

from app.application.exceptions import RepositoryError
from app.application.interfaces.page import PageRepository
from app.domain.entities.page_draft import PageDraft
from app.infrastructure.config.settings import Settings
from app.infrastructure.kissflow._http import (
    quote_path_segment,
    read_verify_write,
    send_json,
    sign,
)
from app.infrastructure.kissflow.credentials import caller_keys


class KissflowPageRepository(PageRepository):
    """Implements `PageRepository` with httpx. Built once, shared by every app."""

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

    def _page_draft_url(self, app_id: str, page_id: str) -> str:
        account = self._settings.kf_dev_account_id
        return (
            f"{self._base_url}/metadata/2/{account}"
            f"/application/{self._segment(app_id)}"
            f"/page/{self._segment(page_id)}/draft"
        )

    async def list_pages(self, app_id: str) -> list[dict[str, Any]]:
        """See `PageRepository.list_pages`."""
        account = self._settings.kf_dev_account_id
        url = (
            f"{self._base_url}/flow/2/{account}"
            f"/application/{self._segment(app_id)}/page?page_size=100"
        )
        return await self._send("GET", url)

    async def create_page(self, app_id: str, name: str) -> str:
        """See `PageRepository.create_page`."""
        account = self._settings.kf_dev_account_id
        url = (
            f"{self._base_url}/flow/2/{account}"
            f"/application/{self._segment(app_id)}/page"
        )
        got = await self._send("POST", url, json_body={"Name": name})
        page_id = got.get("_id") if isinstance(got, dict) else None
        if not isinstance(page_id, str):
            raise RepositoryError(f"create page {name!r}: no _id in response {got!r}")
        return page_id

    async def delete_page(self, app_id: str, page_id: str) -> None:
        """See `PageRepository.delete_page`."""
        account = self._settings.kf_dev_account_id
        url = (
            f"{self._base_url}/flow/2/{account}"
            f"/application/{self._segment(app_id)}"
            f"/page/{self._segment(page_id)}"
        )
        await self._send("DELETE", url)

    async def get_page_draft(self, app_id: str, page_id: str) -> PageDraft:
        """See `PageRepository.get_page_draft`."""
        url = self._page_draft_url(app_id, page_id)
        wire = await self._send("GET", url)
        return PageDraft.from_wire(wire)

    async def put_page_draft(
        self,
        app_id: str,
        page_id: str,
        new: PageDraft,
        expect_version: str | None,
    ) -> PageDraft:
        """See `PageRepository.put_page_draft`."""
        url = self._page_draft_url(app_id, page_id)

        async def write() -> PageDraft:
            wire = await self._send("PUT", url, json_body=new.to_wire())
            return PageDraft.from_wire(wire)

        return await read_verify_write(
            read=lambda: self.get_page_draft(app_id, page_id),
            write=write,
            expect_version=expect_version,
            error_cls=RepositoryError,
        )

    async def publish_page(self, app_id: str, page_id: str) -> None:
        """See `PageRepository.publish_page`."""
        account = self._settings.kf_dev_account_id
        url = (
            f"{self._base_url}/metadata/2/{account}"
            f"/application/{self._segment(app_id)}"
            f"/page/{self._segment(page_id)}/publish"
        )
        await self._send("POST", url)
