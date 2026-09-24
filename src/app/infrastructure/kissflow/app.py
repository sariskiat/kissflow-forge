"""KissflowAppRepository — the httpx adapter for the `AppRepository` port.

Same 13 routes as `KfClient`'s app/app-role methods (`client.py:359-741` pre-refactor),
rewritten onto the shared async transport (`_http.py`). `put_app_draft` keeps the
read-verify-write guard (`_http.read_verify_write`). Raises `RepositoryError`, per spec
G7 Part 1.
"""

from __future__ import annotations

import urllib.parse
from typing import Any

import httpx

from app.application.exceptions import RepositoryError
from app.application.interfaces.app import AppRepository
from app.domain.entities.navigation import Navigation
from app.infrastructure.config.settings import Settings
from app.infrastructure.kissflow._http import (
    build_query,
    quote_path_segment,
    read_verify_write,
    send_json,
    sign,
)
from app.infrastructure.kissflow.credentials import caller_keys


class KissflowAppRepository(AppRepository):
    """Implements `AppRepository` with httpx. Built once, shared by every app."""

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

    def _account(self) -> str:
        return self._settings.kf_dev_account_id

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

    def _app_draft_url(self, app_id: str) -> str:
        return (
            f"{self._base_url}/metadata/2/{self._account()}"
            f"/application/{self._segment(app_id)}/draft"
        )

    async def list_app_roles(self, app_id: str | None = None) -> list[dict[str, Any]]:
        """See `AppRepository.list_app_roles`.

        With an `app_id`, the tenant filters server-side (`_application_id`,
        probed live 2026-09-24): one request instead of paging the whole
        account. The account-wide pages are also unreliable -- 682 entries,
        120 of them duplicates, and some app roles never listed at all -- so
        the filtered read is the more complete one too. The client-side filter
        below still runs as a second guard.
        """
        out: list[dict[str, Any]] = []
        page = 1
        while True:
            params = {"page_number": str(page), "page_size": "100"}
            if app_id is not None:
                params["_application_id"] = app_id
            url = (
                f"{self._base_url}/app_role/2/{self._account()}/list"
                f"{build_query(params)}"
            )
            got = await self._send("GET", url)
            items = got if isinstance(got, list) else []
            if not items:
                break
            out.extend(items)
            if len(items) < 100:
                break
            page += 1
        if app_id is None:
            return out
        return [
            r
            for r in out
            if isinstance(r, dict)
            and (
                r.get("_application_id") == app_id
                or any(
                    isinstance(a, dict) and a.get("_id") == app_id
                    for a in (r.get("Applications") or [])
                )
            )
        ]

    async def get_app_role(self, role_id: str) -> dict[str, Any]:
        """See `AppRepository.get_app_role`."""
        url = f"{self._base_url}/app_role/2/{self._account()}/{self._segment(role_id)}"
        return await self._send("GET", url)

    async def put_app_role(
        self, app_id: str, role_id: str, body: dict[str, Any]
    ) -> Any:
        """See `AppRepository.put_app_role`."""
        query = build_query({"_application_id": app_id})
        url = (
            f"{self._base_url}/app_role/2/{self._account()}"
            f"/{self._segment(role_id)}{query}"
        )
        return await self._send("PUT", url, json_body=body)

    async def get_assignee(self, query: str) -> list[dict[str, Any]]:
        """See `AppRepository.get_assignee`."""
        assignee_query = build_query({"q": query})
        url = f"{self._base_url}/user/2/{self._account()}/assignee{assignee_query}"
        return await self._send("GET", url)

    async def create_app_role(self, name: str, app_id: str | None = None) -> str:
        """See `AppRepository.create_app_role`."""
        scope = app_id if app_id is not None else ""
        url = f"{self._base_url}/app_role/2/{self._account()}"
        got = await self._send(
            "POST", url, json_body={"Name": name, "_application_id": scope}
        )
        role_id = got.get("_id") if isinstance(got, dict) else None
        if not role_id:
            raise RepositoryError(f"create_app_role({name!r}) returned no _id: {got!r}")
        return str(role_id)

    async def delete_app_role(self, role_id: str) -> Any:
        """See `AppRepository.delete_app_role`."""
        url = f"{self._base_url}/app_role/2/{self._account()}/{self._segment(role_id)}"
        return await self._send("DELETE", url)

    async def list_applications(self) -> list[dict[str, Any]]:
        """See `AppRepository.list_applications`."""
        url = f"{self._base_url}/flow/2/{self._account()}/application?page_size=100"
        return await self._send("GET", url)

    async def create_application(self, name: str) -> str:
        """See `AppRepository.create_application`."""
        url = f"{self._base_url}/flow/2/{self._account()}/application"
        got = await self._send("POST", url, json_body={"Name": name})
        app_id = got.get("_id") if isinstance(got, dict) else None
        if not isinstance(app_id, str):
            message = f"create application {name!r}: no _id in response {got!r}"
            raise RepositoryError(message)
        return app_id

    async def delete_application(self, app_id: str, archive_first: bool = True) -> None:
        """See `AppRepository.delete_application`."""
        if archive_first:
            archive_url = (
                f"{self._base_url}/flow/2/{self._account()}"
                f"/application/{self._segment(app_id)}/archive"
            )
            await self._send("POST", archive_url)
        url = (
            f"{self._base_url}/flow/2/{self._account()}"
            f"/application/{self._segment(app_id)}"
        )
        await self._send("DELETE", url)

    async def get_app_draft(self, app_id: str) -> Navigation:
        """See `AppRepository.get_app_draft`."""
        wire = await self._send("GET", self._app_draft_url(app_id))
        return Navigation.from_wire(wire)

    async def put_app_draft(
        self, app_id: str, new: Navigation, expect_version: str | None
    ) -> Navigation:
        """See `AppRepository.put_app_draft`."""
        url = self._app_draft_url(app_id)

        async def write() -> Navigation:
            wire = await self._send("PUT", url, json_body=new.to_wire())
            return Navigation.from_wire(wire)

        return await read_verify_write(
            read=lambda: self.get_app_draft(app_id),
            write=write,
            expect_version=expect_version,
            error_cls=RepositoryError,
        )

    async def publish_app(self, app_id: str) -> None:
        """See `AppRepository.publish_app`."""
        url = (
            f"{self._base_url}/metadata/2/{self._account()}"
            f"/application/{self._segment(app_id)}/publish"
        )
        await self._send("POST", url)
