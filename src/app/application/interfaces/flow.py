"""FlowRepository — the port over the Kissflow flow/process/form/case/list builder
family.

One abstract method per public `KfClient` method the `flow` family owns (refactor spec
inventory, section 1). `scoped_to_app` is not a port method: an adapter built once,
shared by every app, never holds a per-instance app scope, so every method whose URL
carried the config's ambient `app_id` gains an explicit `app_id` first parameter instead
(spec G7 Part 1).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.domain.entities.flow_draft import FlowDraft
from app.domain.value_objects.kinds import AnyFlowKind, DataKind, FlowKind


class FlowRepository(ABC):
    """The flow/process/form/case/list family: drafts, publish, members, word lists.

    Every method raises `app.application.exceptions.RepositoryError` on any
    failure translated out of infrastructure (HTTP, transport, or a version
    conflict raised with `code="CONFLICT"`). No method returns an `Err`.
    """

    @abstractmethod
    async def get_draft(
        self, app_id: str, kind: AnyFlowKind, flow_id: str
    ) -> FlowDraft:
        """Read a flow's current draft node-graph.

        Args:
            app_id: The application the flow belongs to.
            kind: The flow kind (`GET /metadata/2/{account}/{kind}/{flow_id}/draft`).
            flow_id: The flow's id.

        Returns:
            The draft, wrapped as a `FlowDraft`.

        Raises:
            RepositoryError: The read failed.
        """
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    async def create_flow(self, app_id: str, kind: AnyFlowKind, name: str) -> str:
        """Create a new flow (`POST /flow/2/{account}/{kind}`).

        Args:
            app_id: The application to create the flow in.
            kind: The flow kind to create.
            name: The flow's display name.

        Returns:
            The new flow's id.

        Raises:
            RepositoryError: The create failed, or the response carried no id.
        """
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    async def delete_flow(
        self,
        app_id: str,
        kind: AnyFlowKind,
        flow_id: str,
        archive_first: bool = True,
    ) -> None:
        """Delete a flow (`DELETE /flow/2/{account}/{kind}/{flow_id}`).

        Args:
            app_id: The application the flow belongs to.
            kind: The flow kind.
            flow_id: The flow's id.
            archive_first: Archive the flow first when `kind == "process"`,
                as an unarchived process 400s `KISSFLOW_ERROR_04602`.

        Raises:
            RepositoryError: The archive (when requested) or the delete failed.
        """
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    async def publish(self, app_id: str, kind: FlowKind, flow_id: str) -> None:
        """Publish a flow's draft to live (`POST
        /metadata/2/{account}/{kind}/{flow_id}/publish`).

        Args:
            app_id: The application the flow belongs to.
            kind: The flow kind.
            flow_id: The flow's id.

        Raises:
            RepositoryError: The publish failed.
        """
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    async def get_flow_detail(
        self, app_id: str, kind: FlowKind, flow_id: str
    ) -> dict[str, Any]:
        """Read a flow's own metadata record (`GET /flow/2/{account}/{kind}/{flow_id}`).

        Distinct from `get_draft`: carries `Status` (`"Draft"`/`"Live"`/
        `"Archived"`/...), used to verify a publish actually landed.

        Args:
            app_id: The application the flow belongs to.
            kind: The flow kind.
            flow_id: The flow's id.

        Returns:
            The flow's metadata record.

        Raises:
            RepositoryError: The read failed.
        """
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    async def list_flows(self, app_id: str, kind: AnyFlowKind) -> list[dict[str, Any]]:
        """List every flow of `kind` in the application (`GET
        /flow/2/{account}/{kind}`).

        Args:
            app_id: The application to list flows in.
            kind: The flow kind to list.

        Returns:
            Every matching flow's record. An app with none returns `[]`.

        Raises:
            RepositoryError: The read failed.
        """
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    async def get_members(
        self, app_id: str, kind: FlowKind, flow_id: str
    ) -> list[dict[str, Any]]:
        """Read a flow's member grants (`GET
        /flow/2/{account}/{kind}/{flow_id}/member`).

        Args:
            app_id: The application the flow belongs to.
            kind: The flow kind.
            flow_id: The flow's id.

        Returns:
            Every member grant on the flow.

        Raises:
            RepositoryError: The read failed.
        """
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    async def delete_member(
        self, app_id: str, kind: FlowKind, flow_id: str, role_id: str
    ) -> Any:
        """Remove a member grant entirely, the "No access" tier
        (`DELETE /flow/2/{account}/{kind}/{flow_id}/member/{role_id}`).

        Args:
            app_id: The application the flow belongs to.
            kind: The flow kind.
            flow_id: The flow's id.
            role_id: The AppRole id to remove.

        Returns:
            The parsed response body.

        Raises:
            RepositoryError: The delete failed.
        """
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    async def post_member_batch(
        self,
        app_id: str,
        kind: FlowKind,
        flow_id: str,
        members: list[dict[str, Any]],
    ) -> Any:
        """Grant a batch of member permissions
        (`POST /flow/2/{account}/{kind}/{flow_id}/member/batch`).

        Args:
            app_id: The application the flow belongs to.
            kind: The flow kind.
            flow_id: The flow's id.
            members: `[{_id, Name, Kind: "AppRole", Role, Permission}, ...]`.

        Returns:
            The parsed response body.

        Raises:
            RepositoryError: The write failed.
        """
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    async def post_report_member_batch(
        self,
        app_id: str,
        flow_id: str,
        report_id: str,
        members: list[dict[str, Any]],
    ) -> Any:
        """Grant a batch of member permissions on a process report, the same member
        surface as a flow (`POST
        /flow/2/{account}/process/{flow_id}/report/{report_id}/member/batch`).

        Args:
            app_id: The application the flow belongs to.
            flow_id: The owning process flow's id.
            report_id: The report's id.
            members: `[{_id, Name, Kind: "AppRole", Role, Permission}, ...]`.

        Returns:
            The parsed response body.

        Raises:
            RepositoryError: The write failed.
        """
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    async def get_list_items(self, app_id: str, list_id: str) -> list[str]:
        """Read a word list's legal option values
        (`GET /flow/2/{account}/list/{list_id}/items`).

        Args:
            app_id: The application the list belongs to.
            list_id: The word-list flow's id.

        Returns:
            Every legal option value.

        Raises:
            RepositoryError: The read failed.
        """
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    async def list_lists(self, app_id: str) -> list[dict[str, Any]]:
        """List every word list in the application (`GET /flow/2/{account}/list`).

        Args:
            app_id: The application to list word lists in.

        Returns:
            Every word-list flow's record.

        Raises:
            RepositoryError: The read failed.
        """
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    async def create_list(self, app_id: str, name: str) -> dict[str, Any]:
        """Create a word-list flow (`POST /flow/2/{account}/list`). Born live, no
        publish step.

        Args:
            app_id: The application to create the word list in.
            name: The word list's display name.

        Returns:
            The created flow's record (`_id`, `Type: "List"`, `Status: "Live"`).

        Raises:
            RepositoryError: The create failed.
        """
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    async def set_list_items(self, list_id: str, items: list[str]) -> Any:
        """Replace a word list's whole item array (`POST
        /flow/2/{account}/list/{list_id}/items`).

        REPLACE semantics: a second call replaces the first array outright.
        Carries no `app_id` — the route does not take one.

        Args:
            list_id: The word-list flow's id.
            items: The complete new set of legal values.

        Returns:
            The parsed response body.

        Raises:
            RepositoryError: The write failed.
        """
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    async def create_dataset(self, app_id: str, name: str) -> dict[str, Any]:
        """Create a dataform (`POST /flow/2/{account}/dataset`, flow-type `dataset`).

        Born live; no publish route exists for this flow type at all.

        Args:
            app_id: The application to create the dataform in.
            name: The dataform's display name.

        Returns:
            The created flow's record (`_id`, `Type: "Dataset"`, `Status: "Live"`).

        Raises:
            RepositoryError: The create failed.
        """
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    async def create_case(
        self, app_id: str, name: str, item_type: str, prefix: str
    ) -> dict[str, Any]:
        """Create a board/case (`POST /flow/2/{account}/case`, flow-type `case`). Born
        live.

        Args:
            app_id: The application to create the case in.
            name: The case's display name.
            item_type: `"Board"` or `"Case"`; both produce a byte-identical graph.
            prefix: The item id prefix. Mandatory alongside `item_type`.

        Returns:
            The created flow's record.

        Raises:
            RepositoryError: The create failed.
        """
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    async def put_draft(
        self,
        app_id: str,
        kind: DataKind,
        flow_id: str,
        new: FlowDraft,
        expect_version: str | None,
    ) -> FlowDraft:
        """Write a flow's draft, read-verify-write
        (`PUT /metadata/2/{account}/{kind}/{flow_id}/draft`).

        Re-reads the live draft first; when `expect_version` is given and does
        not match the live `_meta_version`, raises with `code="CONFLICT"`
        instead of writing.

        Args:
            app_id: The application the flow belongs to.
            kind: The flow kind.
            flow_id: The flow's id.
            new: The draft to write.
            expect_version: The `_meta_version` this write was planned
                against, or `None` to skip the drift check.

        Returns:
            The draft as written.

        Raises:
            RepositoryError: The write failed, or drifted (`code="CONFLICT"`).
        """
        raise NotImplementedError  # pragma: no cover
