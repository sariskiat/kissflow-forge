"""Spec for app.application.use_cases.item._write_fail."""

from __future__ import annotations

import pytest

from app.application.exceptions import VERIFY_FAILED, ApplicationError
from app.application.use_cases.item._write_fail import raise_if_write_failed


def test_returns_quietly_when_every_bucket_is_empty() -> None:
    raise_if_write_failed(published=False, failed=[])  # does not raise


def test_raises_verify_failed_naming_the_failing_bucket() -> None:
    with pytest.raises(ApplicationError) as exc_info:
        raise_if_write_failed(published=False, failed=["step-1"])

    assert exc_info.value.code == VERIFY_FAILED
    assert "failed=['step-1']" in exc_info.value.message
    assert "published=False" in exc_info.value.message


def test_string_published_is_rendered_verbatim() -> None:
    with pytest.raises(ApplicationError) as exc_info:
        raise_if_write_failed(
            published="n/a (item data-plane write, no publish step)",
            failed=["step-1"],
        )

    assert "published=n/a (item data-plane write, no publish step)" in (
        exc_info.value.message
    )


def test_collateral_and_remediation_are_folded_into_the_message() -> None:
    with pytest.raises(ApplicationError) as exc_info:
        raise_if_write_failed(
            published=False,
            collateral=["iid=ITEM-1", "advanced=['step-1']"],
            remediation=["forge_simulate_case"],
            failed=["step-2"],
        )

    msg = exc_info.value.message
    assert "collateral=['iid=ITEM-1', \"advanced=['step-1']\"]" in msg
    assert "remediation=['forge_simulate_case']" in msg
