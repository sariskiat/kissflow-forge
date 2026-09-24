"""Tests for `app.application.use_cases.intake._app_id.require_app_id`."""

from __future__ import annotations

import pytest

from app.application.exceptions import ApplicationError
from app.application.use_cases.intake._app_id import NO_APP_SELECTED, require_app_id


def test_a_real_app_id_passes() -> None:
    require_app_id("A1")  # must not raise


def test_an_empty_app_id_is_refused() -> None:
    with pytest.raises(ApplicationError) as exc_info:
        require_app_id("")
    assert exc_info.value.code == "REFUSED"
    assert exc_info.value.message == NO_APP_SELECTED
