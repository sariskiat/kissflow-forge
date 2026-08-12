"""#41 live acceptance: execute a compiled build_page op against the REAL dev tenant (KF_APP)
through the governed entry, and prove via read-back that the popup subtree landed and the
on-click EventMapping's OpenPopup Property targets that popup's id (THE RULE: the report's own
200 is not proof — the draft read is). Gated by --run-live like every live suite; the page is
deleted in teardown and its absence verified via the page LIST route (the only truth surface).
"""
from __future__ import annotations

import os
from typing import Any

import pytest

pytestmark = pytest.mark.live

PAGE_NAME = "Forge41 Governed Page"


@pytest.fixture(scope="module")
def live() -> Any:
    if not os.environ.get("KF_APP"):
        pytest.skip("KF_APP not set — no .env / live credentials available")
    from kfforge.client import Err, KfConfig
    cfg = KfConfig.from_env()
    if isinstance(cfg, Err):
        pytest.skip(f"live config unavailable: {cfg.message}")
    return cfg


def test_governed_page_op_builds_popup_and_onclick_live(live: Any) -> None:
    from kfforge.client import Err, KfClient
    from kfforge.pages_live import BuildPageOpReport, apply_build_page_op

    client = KfClient(live)
    app_id = os.environ["KF_APP"]
    op = {
        "name": PAGE_NAME,
        "widgets": ({"slug": "general/label", "config": {"title": "Governed by the plan"},
                     "row_fields": ()},),
        "kpis": (),
        "actions": ("Open Intake",),
        "popups": ({"name": "Intake Popup", "widgets": ()},),
        "on_click": ({"action": "Open Intake", "kind": "OpenPopup",
                      "target_popup": "Intake Popup", "script": None},),
    }
    try:
        rep = apply_build_page_op(client, app_id, op)
        assert isinstance(rep, BuildPageOpReport), rep
        assert rep.refused == () and rep.missing == (), rep.as_tool_result()
        assert set(rep.verified) == set(rep.built)

        # THE RULE: prove it off a fresh draft read, not the report
        draft = client.get_page_draft(app_id, rep.page_id)
        assert not isinstance(draft, Err)
        popup_id = next(k for k, v in draft.items()
                        if isinstance(v, dict) and v.get("Kind") == "Popup"
                        and v.get("Name") == "Intake Popup")
        assert any(isinstance(v, dict) and v.get("Kind") == "Property"
                   and v.get("EventMapping") and v.get("Value") == popup_id
                   for v in draft.values()), \
            "OpenPopup Property must target the popup id on the LIVE read-back"
    finally:
        listed = client.list_pages(app_id)
        if not isinstance(listed, Err):
            for p in listed:
                if isinstance(p, dict) and p.get("Name") == PAGE_NAME:
                    client.delete_page(app_id, p["_id"])
        listed = client.list_pages(app_id)
        assert not isinstance(listed, Err)
        assert not any(isinstance(p, dict) and p.get("Name") == PAGE_NAME for p in listed), \
            "teardown leaked the page (list route is the only truth surface)"
