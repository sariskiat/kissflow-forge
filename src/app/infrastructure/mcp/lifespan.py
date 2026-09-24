"""app_lifespan — opens the one shared `httpx.AsyncClient` pool every adapter uses.

Copies the clone's `mcp/lifespan.py` shape: `app_lifespan(server, settings)`
opens the pool, builds every adapter once around it, and yields
`{"resources": AppResources(...)}`. The `settings` key is this repo's own
delta from the clone: the thin tools (G12) need it for `caller_keys(settings)`,
the `KF_APP` default, and `KF_PROCESS_TEMPLATE` -- none of which the clone's
tool has an equivalent of.
"""

from __future__ import annotations

import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import httpx
from fastmcp import FastMCP

from app.application.interfaces.app import AppRepository
from app.application.interfaces.artifacts import ArtifactWriter
from app.application.interfaces.copilot import CopilotService
from app.application.interfaces.dataset import DatasetRepository
from app.application.interfaces.docs import DocsReader
from app.application.interfaces.flow import FlowRepository
from app.application.interfaces.item import ItemService
from app.application.interfaces.page import PageRepository
from app.infrastructure.artifact_writer import FileArtifactWriter
from app.infrastructure.config.settings import Settings
from app.infrastructure.docs_reader import DocsReaderAdapter
from app.infrastructure.kissflow.app import KissflowAppRepository
from app.infrastructure.kissflow.copilot import KissflowCopilotService
from app.infrastructure.kissflow.dataset import KissflowDatasetRepository
from app.infrastructure.kissflow.flow import KissflowFlowRepository
from app.infrastructure.kissflow.item import KissflowItemService
from app.infrastructure.kissflow.page import KissflowPageRepository


@dataclass(frozen=True)
class AppResources:
    """One field per port. Ports only -- HR2: never a key pair, never stored here.

    Every adapter resolves the caller's own key pair fresh, per request, via
    `caller_keys(settings)`; `AppResources` itself holds no credential of
    any kind.

    Attributes:
        flow: The flow/process/form/case/list family.
        app: The application/app-role family.
        page: The app-page family.
        dataset: The dataform-record family.
        item: The item data-plane family.
        copilot: The in-builder AI copilot family.
        docs: The offline playbook/capability-doc reads.
        artifacts: Writes a rendered design/confirmation artifact to disk --
            `forge_render_flow_diagram`, `forge_render_schema_diagram`,
            `forge_render_mockups`, and `forge_request_confirmation`.
        approval_secret: One HMAC secret, minted once per server process, for
            the intake family's `forge_approve_spec` / `forge_plan_app`
            approval-token gate (see `use_cases/intake/_confirm_gate.py`).
            Not a port -- plain config `bytes`, never logged, never
            returned by any tool.
    """

    flow: FlowRepository
    app: AppRepository
    page: PageRepository
    dataset: DatasetRepository
    item: ItemService
    copilot: CopilotService
    docs: DocsReader
    artifacts: ArtifactWriter
    approval_secret: bytes = field(
        default_factory=lambda: secrets.token_bytes(32), repr=False
    )


@asynccontextmanager
async def app_lifespan(
    server: FastMCP, settings: Settings
) -> AsyncIterator[dict[str, Any]]:
    """Open the shared pool, build every adapter once, yield the resources.

    Args:
        server: The `FastMCP` instance. Unused -- kept for the same
            `lifespan(server)` signature FastMCP calls with.
        settings: The already-validated process `Settings`.

    Yields:
        `{"resources": AppResources(...), "settings": settings}`.
    """
    del server
    base_url = settings.base_url
    # follow_redirects=False is httpx's own default; restated explicitly here (P1
    # review, mid-task correction) alongside _http.send_json's own per-request
    # follow_redirects=False, so a 3xx never replays X-Access-Key-Secret onto
    # another origin and never silently downgrades https to http.
    http_client = httpx.AsyncClient(
        timeout=settings.http_timeout_seconds, follow_redirects=False
    )
    try:
        resources = AppResources(
            flow=KissflowFlowRepository(http_client, base_url, settings),
            app=KissflowAppRepository(http_client, base_url, settings),
            page=KissflowPageRepository(http_client, base_url, settings),
            dataset=KissflowDatasetRepository(http_client, base_url, settings),
            item=KissflowItemService(http_client, base_url, settings),
            copilot=KissflowCopilotService(http_client, base_url, settings),
            docs=DocsReaderAdapter(),
            artifacts=FileArtifactWriter(),
            # Generated ONCE at process start (not per call, not per test), so a
            # restart mints a NEW secret and any approval token minted by a
            # previous process is refused exactly like a spec that changed
            # after approval (see CLAUDE.md P3 approval-token gate).
            approval_secret=secrets.token_bytes(32),
        )
        yield {"resources": resources, "settings": settings}
    finally:
        await http_client.aclose()
