"""Unit tests for app.domain.exceptions: DomainError and ShapeRefused.

Mirrors the clone's own tests/unit/domain/test_exceptions.py for DomainError,
then adds ShapeRefused: it carries row_key and reason, and it is both a
DomainError and a ValueError (so today's `except ValueError` sites keep
catching it).
"""

from __future__ import annotations

from app.domain.exceptions import DomainError, ShapeRefused


def test_domain_error() -> None:
    err = DomainError("domain invariant violated")
    assert str(err) == "domain invariant violated"


def test_shape_refused_carries_row_key_and_reason() -> None:
    err = ShapeRefused("field_geolocation", "no live capture")

    assert err.row_key == "field_geolocation"
    assert err.reason == "no live capture"


def test_shape_refused_message_is_exactly_the_reason() -> None:
    """G9 review: the rendered message must be exactly `reason` -- the seven
    ShapeRefused call sites in application/intake/compile.py already name
    their own coverage row inside `reason`, so prepending `row_key` again
    printed it twice. `row_key` stays reachable as an attribute, never
    folded into the message."""
    err = ShapeRefused("field_geolocation", "no live capture")

    assert str(err) == "no live capture"
    assert err.row_key == "field_geolocation"


def test_shape_refused_is_a_domain_error() -> None:
    assert isinstance(ShapeRefused("field_geolocation", "no live capture"), DomainError)


def test_shape_refused_is_a_value_error() -> None:
    assert isinstance(ShapeRefused("field_geolocation", "no live capture"), ValueError)
