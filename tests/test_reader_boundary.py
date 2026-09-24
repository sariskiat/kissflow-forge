"""R1 (#37): the reader skill's OUTPUT is what's tested, not its prose (spec #29). A skill is model
instructions; its guarantee is that the spec JSON it emits is consumed by the EXISTING
update -> approve -> plan surface and compiles offline to a BuildPlan. This drives a synthetic,
Blindness-safe MULTI-SPLIT spec (two sequential decision splits) through exactly that surface and
asserts a real BuildPlan comes back — the AC6 boundary proof, and the "consistent lie" defence's
home in code (the skill must validate literals against the live word list; see docs/agents/reader.md).
The case-1 golden and the built-app-vs-input diff live in the eval harness (#28), never here.

Reuses `_two_split_spec()` (tests/test_coverage.py) as the stand-in for the reader's emitted spec —
a fully synthetic two-split flow with no target-domain names, so the repo Blindness scan stays
green. Imported by bare module name: pytest's prepend import mode puts tests/ on sys.path, the same
path test_coverage itself uses to import test_intake's `_full_spec`.

Every tool call goes through `create_server(fake_lifespan)` + an in-process `fastmcp.Client`
(Stage E) — these four intake tools are offline (`needs_kissflow=False`), so the fake lifespan
needs no real port, only an `AppResources` to carry `approval_secret` for `forge_approve_spec`/
`forge_plan_app`.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, cast

from fastmcp import Client, FastMCP
from test_coverage import _two_split_spec
from tests.fakes.artifacts import FakeArtifactWriter

from app.infrastructure.mcp.lifespan import AppResources
from app.infrastructure.mcp.server import create_server


def _reader_output_wire() -> dict:
    """The spec JSON a reader skill would emit for a two-split flow, minus `approved` — the reader
    never grants the confirmation gate itself (ADR-0001; `approved` is not a legal patch key, and
    forge_approve_spec is the only route that grants it)."""
    wire = _two_split_spec().model_dump(mode="json")
    wire.pop("approved", None)
    return wire


@asynccontextmanager
async def _fake_lifespan(server: FastMCP) -> AsyncIterator[dict[str, Any]]:
    del server
    resources = AppResources(
        flow=cast(Any, None),
        app=cast(Any, None),
        artifacts=FakeArtifactWriter(),
        page=cast(Any, None),
        dataset=cast(Any, None),
        item=cast(Any, None),
        copilot=cast(Any, None),
        docs=cast(Any, None),
    )
    yield {"resources": resources, "settings": None}


def _server() -> FastMCP:
    return create_server(_fake_lifespan)


async def _call(client: Client, name: str, **kwargs: Any) -> Any:
    result = await client.call_tool(name, kwargs)
    return result.data


def test_reader_multi_split_output_compiles_through_the_update_approve_plan_surface() -> (
    None
):
    """AC1 + AC6: the reader's multi-split spec JSON is consumed via the existing
    update -> confirm -> approve -> plan surface and compiles to a real BuildPlan whose workflow
    still carries BOTH sequential splits as Parallel gateways — the round-trip loses no shape."""
    reader_wire = _reader_output_wire()

    async def _run() -> Any:
        async with Client(_server()) as client:
            updated = await _call(
                client, "forge_update_spec", spec=None, patch=reader_wire
            )
            assert updated.blocking_gaps == [], (
                f"reader output still has gaps: {updated.blocking_gaps}"
            )
            spec_wire = updated.spec
            assert (
                spec_wire["approved"] is False
            )  # an update is unapproved by construction

            req = await _call(client, "forge_request_confirmation", spec=spec_wire)
            approval = await _call(
                client,
                "forge_approve_spec",
                spec=spec_wire,
                digest=req.digest,
                decision="approve",
            )

            plan = await _call(
                client,
                "forge_plan_app",
                spec=approval.spec,
                approval_token=approval.approval_token,
            )
            return plan

    plan = asyncio.run(_run())
    assert plan.summary["build_workflow"] == 1
    workflow = next(op for op in plan.ops if op.kind == "build_workflow")
    assert len(workflow.args["parallels"]) == 2, (
        "two sequential splits must survive as 2 gateways"
    )


def test_reader_emitting_a_spec_is_not_approval() -> None:
    """The reader producing a spec is NOT the confirmation gate (ADR-0001): a plan attempt with no
    real forge_approve_spec token is refused, so the reader cannot launder its own output into a
    build without an explicit approval bound to that exact content."""
    reader_wire = _reader_output_wire()

    from fastmcp.exceptions import ToolError

    async def _run() -> None:
        async with Client(_server()) as client:
            updated = await _call(
                client, "forge_update_spec", spec=None, patch=reader_wire
            )
            await client.call_tool(
                "forge_plan_app",
                {"spec": updated.spec, "approval_token": "not-a-real-token"},
            )

    try:
        asyncio.run(_run())
    except ToolError:
        pass
    else:
        raise AssertionError(
            "a plan attempt with a fake approval_token must be refused"
        )
