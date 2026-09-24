"""PageRepository — the port over the Kissflow app-page builder family.

One abstract method per public `KfClient` method the `page` family owns (refactor spec
inventory, section 1). Every page lives under one application, so every method already
carries `app_id`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.domain.entities.page_draft import PageDraft


class PageRepository(ABC):
    """The app-page family: page CRUD, the page draft, and page publish.

    Every method raises `app.application.exceptions.RepositoryError` on any
    failure translated out of infrastructure. No method returns an `Err`.
    """

    @abstractmethod
    async def list_pages(self, app_id: str) -> list[dict[str, Any]]:
        """List every page in the application
        (`GET /flow/2/{account}/application/{app_id}/page`).

        The truth surface for whether a page exists — a deleted page's draft
        read still succeeds (storage lingers), so only this call proves
        deletion.

        Args:
            app_id: The application's id.

        Returns:
            Every page's record.

        Raises:
            RepositoryError: The read failed.
        """
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    async def create_page(self, app_id: str, name: str) -> str:
        """Create a new page (`POST /flow/2/{account}/application/{app_id}/page`).

        Args:
            app_id: The application to create the page in.
            name: The page's display name.

        Returns:
            The new page's id.

        Raises:
            RepositoryError: The create failed, or the response carried no id.
        """
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    async def delete_page(self, app_id: str, page_id: str) -> None:
        """Delete a page (`DELETE
        /flow/2/{account}/application/{app_id}/page/{page_id}`).

        The response body is `{"status": "success"}` for any id, even a
        bogus one — never trust it as proof; callers verify via `list_pages`.

        Args:
            app_id: The application the page belongs to.
            page_id: The page's id.

        Raises:
            RepositoryError: The delete failed.
        """
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    async def get_page_draft(self, app_id: str, page_id: str) -> PageDraft:
        """Read a page's current draft node-graph
        (`GET /metadata/2/{account}/application/{app_id}/page/{page_id}/draft`).

        Args:
            app_id: The application the page belongs to.
            page_id: The page's id.

        Returns:
            The draft, wrapped as a `PageDraft`.

        Raises:
            RepositoryError: The read failed.
        """
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    async def put_page_draft(
        self,
        app_id: str,
        page_id: str,
        new: PageDraft,
        expect_version: str | None,
    ) -> PageDraft:
        """Write a page's draft, read-verify-write
        (`PUT /metadata/2/{account}/application/{app_id}/page/{page_id}/draft`).

        Re-reads the live draft first; when `expect_version` is given and
        does not match the live `_meta_version`, raises with
        `code="CONFLICT"` instead of writing.

        Args:
            app_id: The application the page belongs to.
            page_id: The page's id.
            new: The draft to write.
            expect_version: The `_meta_version` this write was planned
                against, or `None` to skip the drift check.

        Returns:
            The draft as written.

        Raises:
            RepositoryError: The write failed, or drifted (`code="CONFLICT"`).
        """
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    async def publish_page(self, app_id: str, page_id: str) -> None:
        """Publish a page's draft to live
        (`POST /metadata/2/{account}/application/{app_id}/page/{page_id}/publish`).

        Args:
            app_id: The application the page belongs to.
            page_id: The page's id.

        Raises:
            RepositoryError: The publish failed.
        """
        raise NotImplementedError  # pragma: no cover
