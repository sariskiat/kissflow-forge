"""Offline proof of the documented process build order.

The test uses the real MCP surface and real httpx adapters.  The only outside
system is a stateful ``MockTransport`` which replays the captured process
scaffold and keeps the draft returned by each guarded write.
"""

from __future__ import annotations

import copy
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastmcp import Client, FastMCP

from app.infrastructure.config.settings import Settings
from app.infrastructure.kissflow import credentials
from app.infrastructure.mcp.lifespan import app_lifespan
from app.infrastructure.mcp.server import create_server

ROOT = Path(__file__).resolve().parents[1]
DOMAIN = "dev-big-picture.kissflow.com"
ACCOUNT = "ACCOUNT1"
APP = "APP1"
FLOW = "FLOW1"
ROLE = "ROLE1"


def _settings() -> Settings:
    return Settings(
        kf_dev_domain=DOMAIN,
        kf_dev_account_id=ACCOUNT,
        kf_app=None,
        kf_process_template=None,
        port=8080,
        mcp_http=True,
        kf_dev_access_key_id=None,
        kf_dev_access_key_secret=None,
        http_timeout_seconds=10.0,
    )


def _capture(name: str) -> dict[str, Any]:
    path = ROOT / "shapes" / name
    payload = json.loads(path.read_text(encoding="utf-8"))
    return copy.deepcopy(payload["template"])


def _draft_from_capture() -> dict[str, Any]:
    # ``process_skeleton`` is the captured post-scaffold graph.  A freshly
    # created process has only its Model node, so retain that captured node and
    # let ``forge_create_process`` graft the full process template onto it.
    model = _capture("process_skeleton.json")["Model_Sample01"]
    return {
        "Root": "Model_Sample01",
        "_meta_version": "v1",
        "Model_Sample01": {
            "Id": "Model_Sample01",
            "Kind": "Model",
            "Name": model["Name"],
            "FlowType": model["FlowType"],
        },
    }


def _transport(
    requests: list[httpx.Request],
) -> tuple[httpx.MockTransport, dict[str, Any]]:
    state: dict[str, Any] = {
        "draft": _draft_from_capture(),
        "version": 1,
        "members": [],
        "roles": [
            {
                "_id": ROLE,
                "Name": "Reviewers",
                "Kind": "AppRole",
                "Applications": [{"_id": APP}],
            }
        ],
    }

    def response(request: httpx.Request, body: Any) -> httpx.Response:
        return httpx.Response(200, json=body, request=request)

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.scheme == "https"
        assert request.url.host == DOMAIN
        assert request.headers["X-Access-Key-Id"] == "caller-key"
        assert request.headers["X-Access-Key-Secret"] == "caller-secret"

        path = request.url.path
        if request.method == "POST" and path.endswith("/process"):
            return response(request, {"_id": FLOW})
        if request.method == "GET" and path.endswith("/process"):
            return response(request, [])
        if path.endswith(f"/process/{FLOW}/draft"):
            if request.method == "GET":
                return response(request, copy.deepcopy(state["draft"]))
            if request.method == "PUT":
                state["version"] += 1
                state["draft"] = json.loads(request.content)
                state["draft"]["_meta_version"] = f"v{state['version']}"
                return response(request, copy.deepcopy(state["draft"]))
        if request.method == "POST" and path.endswith(f"/process/{FLOW}/member/batch"):
            state["members"] = json.loads(request.content)
            return response(request, {"status": "success"})
        if request.method == "GET" and path.endswith(f"/process/{FLOW}/member"):
            return response(request, copy.deepcopy(state["members"]))
        if request.method == "POST" and path.endswith(f"/app_role/2/{ACCOUNT}"):
            role = {
                "_id": "RoTemplate01",
                "Name": json.loads(request.content)["Name"],
                "Kind": "AppRole",
                "Applications": [{"_id": APP}],
            }
            state["roles"].append(role)
            return response(request, {"_id": role["_id"], "Name": role["Name"]})
        if request.method == "GET" and "/app_role/" in path and path.endswith("/list"):
            return response(request, copy.deepcopy(state["roles"]))
        if request.method == "GET" and path.endswith(f"/process/{FLOW}"):
            return response(request, {"_id": FLOW, "Status": "Live"})
        if request.method == "POST" and path.endswith(f"/process/{FLOW}/publish"):
            return response(request, {"status": "success"})
        if request.method == "GET" and "/items" in path:
            return response(request, [])
        raise AssertionError(
            f"unhandled mocked Kissflow route: {request.method} {request.url}"
        )

    return httpx.MockTransport(handler), state


@pytest.mark.asyncio
async def test_process_build_order_is_offline_end_to_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Drive CLAUDE.md build steps 1 through 12 through ``create_server``.

    Each draft write records its own request span and requires the snapshot GET
    to be first.  The transport checks the dev host and both caller headers on
    every outbound request, so a route or credential regression fails here.
    """
    requests: list[httpx.Request] = []
    transport, state = _transport(requests)
    pool = httpx.AsyncClient(transport=transport)
    settings = _settings()
    monkeypatch.setattr(
        credentials,
        "get_http_headers",
        lambda **_: {
            "x-access-key-id": "caller-key",
            "x-access-key-secret": "caller-secret",
        },
    )

    def open_pool(*, timeout: float, follow_redirects: bool) -> httpx.AsyncClient:
        assert timeout == settings.http_timeout_seconds
        assert follow_redirects is False
        return pool

    monkeypatch.setattr(httpx, "AsyncClient", open_pool)

    @asynccontextmanager
    async def lifespan(server: FastMCP) -> AsyncIterator[dict[str, Any]]:
        async with app_lifespan(server, settings) as context:
            yield context

    server = create_server(lifespan)

    async with Client(server) as client:

        async def call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
            before = len(requests)
            result = await client.call_tool(name, arguments)
            assert result.is_error is False, (name, result.content)
            payload = result.structured_content
            assert isinstance(payload, dict), (name, payload)
            if name in {
                "forge_apply_fields",
                "forge_add_table",
                "forge_build_workflow",
                "forge_add_goto_gate",
                "forge_set_visibility",
                "forge_set_events",
                "forge_set_styles",
                "forge_publish",
            }:
                span = requests[before:]
                assert span, f"{name} made no outbound request"
                assert span[0].method == "GET"
                assert span[0].url.path.endswith("/draft")
            return payload

        created = await call(
            "forge_create_process",
            {"name": "Big Picture", "app_id": APP, "from_template": True},
        )
        assert created["flow_id"] == FLOW
        assert created["template_sections"]

        members = await call(
            "forge_member_batch", {"target_flow_id": FLOW, "app_id": APP}
        )
        # The full template brought its own approver role; both are members now.
        assert sorted(members["verified"]) == sorted([ROLE, "RoTemplate01"])

        fields = await call(
            "forge_apply_fields",
            {
                "flow_id": FLOW,
                "app_id": APP,
                "fields": [
                    {"name": "Approval Note", "type": "Textarea"},
                    {"name": "Approved", "type": "Boolean"},
                ],
                "sections": {"Request Details": ["Approval Note", "Approved"]},
            },
        )
        assert fields["added"] == ["Approval Note", "Approved"]

        table = await call(
            "forge_add_table",
            {
                "flow_id": FLOW,
                "app_id": APP,
                "name": "Line Items",
                "columns": [["Item", "Text"], ["Quantity", "Number"]],
            },
        )
        assert table["verified_columns"] == ["Item", "Quantity"]

        workflow = await call(
            "forge_build_workflow",
            {
                "flow_id": FLOW,
                "app_id": APP,
                "steps": [["Review", ROLE]],
                "roles": {ROLE: "Reviewers"},
            },
        )
        assert workflow["verified_steps"] == ["Review"]

        goto = await call(
            "forge_add_goto_gate",
            {
                "flow_id": FLOW,
                "app_id": APP,
                "target_activity_name": "Review",
                "field_name": "Approved",
            },
        )
        assert goto["verified"] is True

        sections = sorted(
            node["Name"]
            for node in state["draft"].values()
            if isinstance(node, dict)
            and node.get("Kind") == "Column"
            and node.get("Type") in {"Section", "Model"}
            and isinstance(node.get("Name"), str)
        )
        visibility = await call(
            "forge_set_visibility",
            {
                "flow_id": FLOW,
                "app_id": APP,
                "owners": {s: ["Review"] for s in sections},
            },
        )
        assert visibility["uncovered_sections"] == []

        events = await call(
            "forge_set_events",
            {
                "flow_id": FLOW,
                "app_id": APP,
                "events": {"Approval Note": [["onChange", "kf.x();"]]},
            },
        )
        assert events["verified"] == ["Approval Note"]

        styles = await call(
            "forge_set_styles",
            {
                "flow_id": FLOW,
                "app_id": APP,
                "styles": {sections[0]: {"Section.Bg.Color": "Color.Info.300"}},
            },
        )
        assert styles["verified"] == [sections[0]]

        published = await call(
            "forge_publish", {"kind": "process", "flow_id": FLOW, "app_id": APP}
        )
        assert published["published"] is True
        assert published["status"] == "Live"

        doctor = await call("forge_doctor", {"flow_id": FLOW, "app_id": APP})
        assert doctor["flow_id"] == FLOW
        assert doctor["members_found"] == 2  # Reviewers + the template's own role
        # Table hosts and their nested models are structural containers, so
        # the doctor ignores them when checking editable process sections.
        assert doctor["problems"] == []

    assert state["draft"]["_meta_version"].startswith("v")
    assert requests
