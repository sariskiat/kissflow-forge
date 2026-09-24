"""KissflowFlowRepository — the httpx adapter for the `FlowRepository` port.

Same 18 routes as `KfClient`'s flow/process/form/case/list methods
(`client.py:280-841` pre-refactor), rewritten onto the shared async transport
(`_http.py`). `put_draft` keeps the read-verify-write guard
(`_http.read_verify_write`). Raises `RepositoryError`, per spec G7 Part 1.
"""

from __future__ import annotations

import urllib.parse
from typing import Any, get_args

import httpx

from app.application.exceptions import REFUSED, RepositoryError
from app.application.interfaces.flow import FlowRepository
from app.domain.entities.flow_draft import FlowDraft
from app.domain.value_objects.kinds import AnyFlowKind, DataKind, FlowKind
from app.infrastructure.config.settings import Settings
from app.infrastructure.kissflow._http import (
    build_query,
    quote_path_segment,
    read_verify_write,
    send_json,
    sign,
)
from app.infrastructure.kissflow.credentials import caller_keys


class KissflowFlowRepository(FlowRepository):
    """Implements `FlowRepository` with httpx. Built once, shared by every app."""

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

    def _kind(self, kind: str, allowed: Any) -> str:
        """Refuse a `kind` that is not one of the flow kinds `allowed` declares.

        `kind` is never run through `_segment`/`quote_path_segment`: every
        route needs it as a bare word (`/flow/2/{account}/process`), not a
        percent-escaped one. That left it as the one piece of every path
        here with no runtime check at all -- a caller who bypasses the
        static `AnyFlowKind`/`FlowKind` type (an MCP argument before Pydantic
        coercion, or this repository called directly) could send any string.
        `".."` collapses the path the same way an unguarded id segment used
        to (RFC 3986 5.2.4); `"application"` is a real Kissflow word, just
        not a flow one -- it silently retargets the call onto the
        application/app-role route family instead of refusing.

        Args:
            kind: The caller-supplied flow kind, about to be interpolated
                into a URL path segment unencoded.
            allowed: The `Literal` alias the calling method's own port
                signature declares for its `kind` parameter (`AnyFlowKind`
                or `FlowKind`), read with `typing.get_args` so the legal
                words can never drift from the port by hand-copying them
                into a second list here.

        Returns:
            `kind`, unchanged.

        Raises:
            RepositoryError: `kind` is not one of `get_args(allowed)`
                (`code=REFUSED`).
        """
        if kind not in get_args(allowed):
            raise RepositoryError(f"refused unknown flow kind: {kind!r}", code=REFUSED)
        return kind

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

    def _draft_url(self, app_id: str, kind: AnyFlowKind, flow_id: str) -> str:
        query = build_query({"_application_id": app_id})
        return (
            f"{self._base_url}/metadata/2/{self._account()}"
            f"/{self._kind(kind, AnyFlowKind)}/{self._segment(flow_id)}/draft{query}"
        )

    async def get_draft(
        self, app_id: str, kind: AnyFlowKind, flow_id: str
    ) -> FlowDraft:
        """See `FlowRepository.get_draft`."""
        wire = await self._send("GET", self._draft_url(app_id, kind, flow_id))
        return FlowDraft.from_wire(wire)

    async def create_flow(self, app_id: str, kind: AnyFlowKind, name: str) -> str:
        """See `FlowRepository.create_flow`."""
        query = build_query({"_application_id": app_id})
        url = (
            f"{self._base_url}/flow/2/{self._account()}"
            f"/{self._kind(kind, AnyFlowKind)}{query}"
        )
        got = await self._send("POST", url, json_body={"Name": name})
        flow_id = got.get("_id") if isinstance(got, dict) else None
        if not isinstance(flow_id, str):
            message = f"create {kind} {name!r}: no _id in response {got!r}"
            raise RepositoryError(message)
        return flow_id

    async def delete_flow(
        self,
        app_id: str,
        kind: AnyFlowKind,
        flow_id: str,
        archive_first: bool = True,
    ) -> None:
        """See `FlowRepository.delete_flow`."""
        if archive_first and kind == "process":
            archive_query = build_query({"_application_id": app_id})
            archive_url = (
                f"{self._base_url}/flow/2/{self._account()}"
                f"/{self._kind(kind, AnyFlowKind)}/{self._segment(flow_id)}"
                f"/archive{archive_query}"
            )
            await self._send("POST", archive_url)
        query = build_query({"_application_id": app_id})
        url = (
            f"{self._base_url}/flow/2/{self._account()}"
            f"/{self._kind(kind, AnyFlowKind)}/{self._segment(flow_id)}{query}"
        )
        await self._send("DELETE", url)

    async def publish(self, app_id: str, kind: FlowKind, flow_id: str) -> None:
        """See `FlowRepository.publish`."""
        query = build_query({"_application_id": app_id})
        url = (
            f"{self._base_url}/metadata/2/{self._account()}"
            f"/{self._kind(kind, FlowKind)}/{self._segment(flow_id)}/publish{query}"
        )
        await self._send("POST", url)

    async def get_flow_detail(
        self, app_id: str, kind: FlowKind, flow_id: str
    ) -> dict[str, Any]:
        """See `FlowRepository.get_flow_detail`."""
        query = build_query({"_application_id": app_id})
        url = (
            f"{self._base_url}/flow/2/{self._account()}"
            f"/{self._kind(kind, FlowKind)}/{self._segment(flow_id)}{query}"
        )
        return await self._send("GET", url)

    async def list_flows(self, app_id: str, kind: AnyFlowKind) -> list[dict[str, Any]]:
        """See `FlowRepository.list_flows`."""
        query = build_query({"_application_id": app_id, "page_size": "100"})
        url = (
            f"{self._base_url}/flow/2/{self._account()}"
            f"/{self._kind(kind, AnyFlowKind)}{query}"
        )
        return await self._send("GET", url)

    async def get_members(
        self, app_id: str, kind: FlowKind, flow_id: str
    ) -> list[dict[str, Any]]:
        """See `FlowRepository.get_members`."""
        query = build_query({"_application_id": app_id})
        url = (
            f"{self._base_url}/flow/2/{self._account()}"
            f"/{self._kind(kind, FlowKind)}/{self._segment(flow_id)}/member{query}"
        )
        return await self._send("GET", url)

    async def delete_member(
        self, app_id: str, kind: FlowKind, flow_id: str, role_id: str
    ) -> Any:
        """See `FlowRepository.delete_member`."""
        query = build_query({"_application_id": app_id})
        url = (
            f"{self._base_url}/flow/2/{self._account()}/{self._kind(kind, FlowKind)}"
            f"/{self._segment(flow_id)}/member/{self._segment(role_id)}{query}"
        )
        return await self._send("DELETE", url)

    async def post_member_batch(
        self,
        app_id: str,
        kind: FlowKind,
        flow_id: str,
        members: list[dict[str, Any]],
    ) -> Any:
        """See `FlowRepository.post_member_batch`."""
        query = build_query({"_application_id": app_id})
        url = (
            f"{self._base_url}/flow/2/{self._account()}/{self._kind(kind, FlowKind)}"
            f"/{self._segment(flow_id)}/member/batch{query}"
        )
        return await self._send("POST", url, json_body=members)

    async def post_report_member_batch(
        self,
        app_id: str,
        flow_id: str,
        report_id: str,
        members: list[dict[str, Any]],
    ) -> Any:
        """See `FlowRepository.post_report_member_batch`."""
        query = build_query({"_application_id": app_id})
        url = (
            f"{self._base_url}/flow/2/{self._account()}"
            f"/process/{self._segment(flow_id)}"
            f"/report/{self._segment(report_id)}"
            f"/member/batch{query}"
        )
        return await self._send("POST", url, json_body=members)

    async def get_list_items(self, app_id: str, list_id: str) -> list[str]:
        """See `FlowRepository.get_list_items`."""
        query = build_query({"_application_id": app_id})
        url = (
            f"{self._base_url}/flow/2/{self._account()}"
            f"/list/{self._segment(list_id)}/items{query}"
        )
        return await self._send("GET", url)

    async def list_lists(self, app_id: str) -> list[dict[str, Any]]:
        """See `FlowRepository.list_lists`."""
        query = build_query({"page_size": "100", "_application_id": app_id})
        url = f"{self._base_url}/flow/2/{self._account()}/list{query}"
        return await self._send("GET", url)

    async def create_list(self, app_id: str, name: str) -> dict[str, Any]:
        """See `FlowRepository.create_list`."""
        query = build_query({"_application_id": app_id})
        url = f"{self._base_url}/flow/2/{self._account()}/list{query}"
        return await self._send("POST", url, json_body={"Name": name})

    async def set_list_items(self, list_id: str, items: list[str]) -> Any:
        """See `FlowRepository.set_list_items`."""
        url = (
            f"{self._base_url}/flow/2/{self._account()}"
            f"/list/{self._segment(list_id)}/items"
        )
        return await self._send("POST", url, json_body={"ListItems": items})

    async def create_dataset(self, app_id: str, name: str) -> dict[str, Any]:
        """See `FlowRepository.create_dataset`."""
        query = build_query({"_application_id": app_id})
        url = f"{self._base_url}/flow/2/{self._account()}/dataset{query}"
        return await self._send("POST", url, json_body={"Name": name})

    async def create_case(
        self, app_id: str, name: str, item_type: str, prefix: str
    ) -> dict[str, Any]:
        """See `FlowRepository.create_case`."""
        query = build_query({"_application_id": app_id})
        url = f"{self._base_url}/flow/2/{self._account()}/case{query}"
        return await self._send(
            "POST",
            url,
            json_body={"Name": name, "ItemType": item_type, "Prefix": prefix},
        )

    async def put_draft(
        self,
        app_id: str,
        kind: DataKind,
        flow_id: str,
        new: FlowDraft,
        expect_version: str | None,
    ) -> FlowDraft:
        """See `FlowRepository.put_draft`."""
        url = self._draft_url(app_id, kind, flow_id)

        async def write() -> FlowDraft:
            wire = await self._send("PUT", url, json_body=new.to_wire())
            return FlowDraft.from_wire(wire)

        return await read_verify_write(
            read=lambda: self.get_draft(app_id, kind, flow_id),
            write=write,
            expect_version=expect_version,
            error_cls=RepositoryError,
        )
