"""Unit tests for app.domain.value_objects.coverage: the coverage-row contract itself.

Pins the table's own integrity (bucketing, key/reason shape) and `get`'s lookup
contract. `tests/test_coverage.py` is the fuller integration suite (every
REQUIRED_KEYS row, wired against a real compile_spec build); these are the module's
own focused unit tests. Pure + offline: no network, no Kissflow calls.
"""

from __future__ import annotations

import re

import pytest

from app.domain.value_objects.coverage import ROWS, Bucket, CoverageRow, get

_KEY_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def test_rows_is_non_empty() -> None:
    assert len(ROWS) > 0
    assert all(isinstance(row, CoverageRow) for row in ROWS)


def test_every_key_is_unique() -> None:
    keys = [row.key for row in ROWS]
    assert len(keys) == len(set(keys)), "duplicate coverage-row key"


def test_every_key_is_lower_kebab_case() -> None:
    for row in ROWS:
        assert _KEY_RE.match(row.key), f"{row.key!r} is not lower-kebab-case"


def test_every_row_has_exactly_one_bucket() -> None:
    for row in ROWS:
        assert row.bucket in (
            Bucket.CAPTURED_LIVE,
            Bucket.BUILDABLE,
            Bucket.REFUSES_LOUDLY,
        )


def test_refuses_loudly_rows_always_carry_a_reason() -> None:
    for row in ROWS:
        if row.bucket is Bucket.REFUSES_LOUDLY:
            assert row.reason, f"{row.key!r} is REFUSES_LOUDLY but carries no reason"


def test_captured_live_rows_carry_no_ticket() -> None:
    # a captured-live shape is done; a ticket would mean it is still pending something.
    for row in ROWS:
        if row.bucket is Bucket.CAPTURED_LIVE:
            assert row.ticket is None, (
                f"{row.key!r} is CAPTURED_LIVE but still has a ticket"
            )


def test_captured_property_matches_the_bucket() -> None:
    for row in ROWS:
        assert row.captured == (row.bucket is Bucket.CAPTURED_LIVE)


def test_pending_property_matches_ticket_presence() -> None:
    for row in ROWS:
        assert row.pending == (row.ticket is not None)


def test_get_returns_the_row_by_key() -> None:
    row = get("nested-split")
    assert row.key == "nested-split"
    assert row.bucket is Bucket.REFUSES_LOUDLY


def test_get_unknown_key_raises_key_error() -> None:
    with pytest.raises(KeyError, match="no coverage row keyed"):
        get("not-a-real-row")
