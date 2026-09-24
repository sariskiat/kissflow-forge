"""Spec for app.application.use_cases.page._write_fail."""

from __future__ import annotations

import pytest

from app.application.exceptions import VERIFY_FAILED, ApplicationError
from app.application.use_cases.page._write_fail import raise_if_write_failed


def test_returns_quietly_when_every_bucket_is_empty() -> None:
    raise_if_write_failed(published=False, missing=[])  # does not raise


def test_raises_verify_failed_naming_the_failing_bucket() -> None:
    with pytest.raises(ApplicationError) as exc_info:
        raise_if_write_failed(published=False, missing=["Container001"])

    assert exc_info.value.code == VERIFY_FAILED
    assert "missing=['Container001']" in exc_info.value.message
    assert "published=False" in exc_info.value.message


def test_collateral_and_remediation_are_folded_into_the_message() -> None:
    with pytest.raises(ApplicationError) as exc_info:
        raise_if_write_failed(
            published=False,
            collateral=["page_id=Page_1", "page_created=True"],
            remediation=["forge_build_page"],
            missing=["Container001"],
        )

    msg = exc_info.value.message
    assert "collateral=['page_id=Page_1', 'page_created=True']" in msg
    assert "remediation=['forge_build_page']" in msg
