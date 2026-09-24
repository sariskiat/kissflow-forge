"""Spec for app.application.use_cases.copilot._app_id.

Ports the app-id resolution refusal every copilot-scoped tool used to raise
through `server.py`'s `_client()` (`server.py:300-304`, common brief "The
app id"). One copy of this rule for the whole copilot family (CLAUDE.md >
lesson 14), shared by `forge_copilot_ask` and `forge_copilot_check`.
"""

from __future__ import annotations

import pytest

from app.application.exceptions import REFUSED, ApplicationError
from app.application.use_cases.copilot._app_id import require_app_id


def test_returns_a_non_empty_app_id_unchanged() -> None:
    assert require_app_id("App1") == "App1"


def test_empty_app_id_is_refused() -> None:
    with pytest.raises(ApplicationError) as exc_info:
        require_app_id("")
    assert exc_info.value.code == REFUSED
    assert "no app selected" in exc_info.value.message
    assert "forge_list_apps" in exc_info.value.message
    assert "KF_APP" in exc_info.value.message
