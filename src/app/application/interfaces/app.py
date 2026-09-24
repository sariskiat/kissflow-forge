"""AppRepository — the port over the Kissflow application/app-role builder family.

One abstract method per public `KfClient` method the `app` family owns (refactor spec
inventory, section 1): AppRoles, assignee search, applications, and the
application-level (Navigation) draft.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.domain.entities.navigation import Navigation


class AppRepository(ABC):
    """The application/app-role family: roles, assignees, applications, the Navigation
    draft.

    Every method raises `app.application.exceptions.RepositoryError` on any
    failure translated out of infrastructure. No method returns an `Err`.
    """

    @abstractmethod
    async def list_app_roles(self, app_id: str | None = None) -> list[dict[str, Any]]:
        """List AppRoles in the account (`GET /app_role/2/{account}/list`, paginated).

        The route itself is account-wide; `app_id` is a client-side filter
        applied to the result, not part of the URL.

        Args:
            app_id: When given, keep only roles scoped to this application
                (matched on `Applications[]` or the top-level
                `_application_id`). `None` returns every role in the account.

        Returns:
            Every matching AppRole record.

        Raises:
            RepositoryError: The read failed.
        """
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    async def get_app_role(self, role_id: str) -> dict[str, Any]:
        """Read one AppRole's own detail, including its `Members` list
        (`GET /app_role/2/{account}/{role_id}`).

        Args:
            role_id: The AppRole's id.

        Returns:
            The AppRole's record.

        Raises:
            RepositoryError: The read failed.
        """
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    async def put_app_role(
        self, app_id: str, role_id: str, body: dict[str, Any]
    ) -> Any:
        """Write an AppRole's own record (`PUT /app_role/2/{account}/{role_id}`).

        Used both for assigning users (write key `Users`, asymmetric with the
        read key `Members`) and for setting `Preference`
        (`DefaultPage`/`DefaultNavigation`).

        Args:
            app_id: The application to scope this write to.
            role_id: The AppRole's id.
            body: The full record to write.

        Returns:
            The parsed response body.

        Raises:
            RepositoryError: The write failed.
        """
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    async def get_assignee(self, query: str) -> list[dict[str, Any]]:
        """Search for a real user to hand to `put_app_role`'s `Users` write
        (`GET /user/2/{account}/assignee?q=...`).

        Args:
            query: The free-text search query (a person's name or email).

        Returns:
            Every matching assignee (`{_id, Kind: "User", Email, Name}`).

        Raises:
            RepositoryError: The read failed.
        """
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    async def create_app_role(self, name: str, app_id: str | None = None) -> str:
        """Create an AppRole (`POST /app_role/2/{account}`).

        Args:
            name: The AppRole's display name. The same name can exist on
                multiple role ids; this call always creates a new one.
            app_id: The application to scope the new role to. `None` creates
                an unscoped role, which `post_member_batch` will then reject.

        Returns:
            The new AppRole's id.

        Raises:
            RepositoryError: The create failed, or the response carried no id.
        """
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    async def delete_app_role(self, role_id: str) -> Any:
        """Delete an AppRole (`DELETE /app_role/2/{account}/{role_id}`).

        Args:
            role_id: The AppRole's id.

        Returns:
            The parsed response body.

        Raises:
            RepositoryError: The delete failed.
        """
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    async def list_applications(self) -> list[dict[str, Any]]:
        """List every application in the account (`GET /flow/2/{account}/application`).

        Returns:
            Every application's record.

        Raises:
            RepositoryError: The read failed.
        """
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    async def create_application(self, name: str) -> str:
        """Create a new application (`POST /flow/2/{account}/application`).

        Args:
            name: The application's display name.

        Returns:
            The new application's id.

        Raises:
            RepositoryError: The create failed, or the response carried no id.
        """
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    async def delete_application(self, app_id: str, archive_first: bool = True) -> None:
        """Delete an application (`DELETE /flow/2/{account}/application/{app_id}`).

        A plain delete 400s `KISSFLOW_ERROR_04602` until the application is
        archived first. The response is not proof of deletion either way —
        callers verify via `list_applications`.

        Args:
            app_id: The application's id.
            archive_first: Archive the application before deleting it.

        Raises:
            RepositoryError: The archive (when requested) or the delete failed.
        """
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    async def get_app_draft(self, app_id: str) -> Navigation:
        """Read the application's own draft (`GET
        /metadata/2/{account}/application/{app_id}/draft`).

        This is the Navigation graph, distinct from any one flow's own draft.

        Args:
            app_id: The application's id.

        Returns:
            The draft, wrapped as a `Navigation`.

        Raises:
            RepositoryError: The read failed.
        """
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    async def put_app_draft(
        self, app_id: str, new: Navigation, expect_version: str | None
    ) -> Navigation:
        """Write the application's draft, read-verify-write
        (`PUT /metadata/2/{account}/application/{app_id}/draft`).

        Re-reads the live draft first; when `expect_version` is given and
        does not match the live `_meta_version`, raises with
        `code="CONFLICT"` instead of writing.

        Args:
            app_id: The application's id.
            new: The Navigation draft to write.
            expect_version: The `_meta_version` this write was planned
                against, or `None` to skip the drift check.

        Returns:
            The draft as written.

        Raises:
            RepositoryError: The write failed, or drifted (`code="CONFLICT"`).
        """
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    async def publish_app(self, app_id: str) -> None:
        """Publish the application's draft to live
        (`POST /metadata/2/{account}/application/{app_id}/publish`).

        Args:
            app_id: The application's id.

        Raises:
            RepositoryError: The publish failed.
        """
        raise NotImplementedError  # pragma: no cover
