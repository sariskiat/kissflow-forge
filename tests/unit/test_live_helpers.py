"""Offline contracts for the small bridges used by live acceptance suites."""

from __future__ import annotations

from typing import Any

import live_helpers
from fastmcp import FastMCP


def test_grant_calling_user_passes_the_full_assignee_and_returns_its_id(
    monkeypatch: Any,
) -> None:
    """The item API returns an assignee object, which the role API needs unchanged."""
    caller = {"Kind": "User", "Name": "Ann", "_id": "U1"}
    server = FastMCP("test-live-helpers")
    calls: list[dict[str, Any]] = []

    monkeypatch.setattr(
        live_helpers,
        "create_item",
        lambda flow_id: {"_id": "probe-1"},
    )
    monkeypatch.setattr(
        live_helpers,
        "get_item_detail",
        lambda flow_id, item_id: {"_current_assigned_to": [caller]},
    )

    def fake_call_tool(server: Any, tool_name: str, **kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {"added": ["U1"], "already_present": []}

    monkeypatch.setattr(live_helpers, "call_tool", fake_call_tool)

    assert live_helpers.grant_calling_user_to_role(server, "F1", "R1", "A1") == "U1"
    assert calls == [{"role_id": "R1", "user_ids": [caller], "app_id": "A1"}]
