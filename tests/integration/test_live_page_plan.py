"""#41 live acceptance: execute a compiled build_page op against the REAL dev tenant in a temporary app
through the governed entry, and prove via read-back that the popup subtree landed and the
on-click EventMapping's OpenPopup Property targets that popup's id (THE RULE: the report's own
200 is not proof — the draft read is). Gated by --run-live like every live suite; the page is
deleted in teardown and its absence verified via `forge_sweep`'s own page inventory (the list
route is the only truth surface).

Stage E switch: the pre-Stage-E version of this test drove `app.infrastructure.kissflow.client.
KfClient`/`app.infrastructure.kissflow.pages_live.apply_build_page_op` directly (both gone). The
governed `op` entry survived the port unchanged as `forge_build_page`'s own `op` argument (see
`app.application.use_cases.page.forge_build_page`), so this test now drives it as a tool call
through `live_helpers.call_tool`, an in-process `fastmcp.Client` against `create_server(lifespan)`.
"""

from __future__ import annotations

import os
from typing import Any

import live_helpers
import pytest

pytestmark = pytest.mark.live

PAGE_NAME = "Forge41 Governed Page"


@pytest.fixture(scope="module")
def server(request: pytest.FixtureRequest) -> dict[str, Any]:
    if not os.environ.get("KF_DEV_ACCESS_KEY_ID"):
        raise pytest.skip.Exception(
            "KF_DEV_ACCESS_KEY_ID not set — no .env / live credentials available"
        )
    live_helpers.load_env_file()
    state: dict[str, Any] = {"server": live_helpers.build_server(), "app_id": None}
    state["app_id"], _ = live_helpers.create_temporary_app(
        state["server"], "Forge live page app"
    )

    def cleanup() -> None:
        result = live_helpers.call_tool(
            state["server"],
            "forge_delete_flow",
            kind="application",
            flow_id=state["app_id"],
        )
        if not getattr(result, "verified", False):
            raise AssertionError(f"application deletion was not verified: {result!r}")
        apps = live_helpers.call_tool(state["server"], "forge_list_apps")
        listed = apps.get("apps", []) if isinstance(apps, dict) else apps.apps
        if any(
            isinstance(app, dict) and app.get("_id") == state["app_id"]
            for app in listed
        ):
            raise AssertionError(f"application {state['app_id']} is still listed")

    request.addfinalizer(cleanup)
    return state


def test_governed_page_op_builds_popup_and_onclick_live(
    server: dict[str, Any],
) -> None:
    app_id = server["app_id"]
    mcp_server = server["server"]
    op = {
        "name": PAGE_NAME,
        "widgets": (
            {
                "slug": "general/label",
                "config": {"title": "Governed by the plan"},
                "row_fields": (),
            },
        ),
        "kpis": (),
        "actions": ("Open Intake",),
        "popups": ({"name": "Intake Popup", "widgets": ()},),
        "on_click": (
            {
                "action": "Open Intake",
                "kind": "OpenPopup",
                "target_popup": "Intake Popup",
                "script": None,
            },
        ),
    }
    page_id: str | None = None
    try:
        result = live_helpers.call_tool(
            mcp_server, "forge_build_page", app_id=app_id, op=op
        )
        refused = live_helpers.response_value(result, "refused")
        missing = live_helpers.response_value(result, "missing")
        verified = live_helpers.response_value(result, "verified")
        built = live_helpers.response_value(result, "built")
        assert not refused, result
        assert not missing, result
        assert set(verified) == set(built)

        page_id = live_helpers.response_value(result, "page_id")
        assert page_id is not None

        # THE RULE: prove it off a fresh draft read, not the report
        draft = live_helpers.call_tool(
            mcp_server,
            "kf_get_flow_schema",
            flow_kind="page",
            flow_id=page_id,
            app_id=app_id,
        )
        popup_id = next(
            k
            for k, v in draft.items()
            if isinstance(v, dict)
            and v.get("Kind") == "Popup"
            and v.get("Name") == "Intake Popup"
        )
        assert any(
            isinstance(v, dict)
            and v.get("Kind") == "Property"
            and v.get("EventMapping")
            and v.get("Value") == popup_id
            for v in draft.values()
        ), "OpenPopup Property must target the popup id on the LIVE read-back"
    finally:
        if page_id is not None:
            deleted = live_helpers.call_tool(
                mcp_server,
                "forge_delete_flow",
                kind="page",
                flow_id=page_id,
                app_id=app_id,
            )
            print(f"page delete: {deleted}")
        swept = live_helpers.call_tool(
            mcp_server, "forge_sweep", scope="pages", app_id=app_id
        )
        sweep_results = live_helpers.response_value(swept, "results")
        pages = sweep_results.get("pages", {}).get("items", [])
        assert not any(
            isinstance(p, dict) and p.get("Name") == PAGE_NAME for p in pages
        ), "teardown leaked the page (list route is the only truth surface)"
