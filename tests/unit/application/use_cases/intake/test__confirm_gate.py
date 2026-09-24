"""Tests for `app.application.use_cases.intake._confirm_gate.mint_approval_token`.

Ported from the approval-token bypass coverage of `tests/test_intake.py` /
`tests/test_mcp_boundary.py`'s `forge_approve_spec`/`forge_plan_app` pair,
narrowed to the pure primitive itself (Stage D group 8).
"""

from __future__ import annotations

from app.application.use_cases.intake._confirm_gate import mint_approval_token


def test_same_secret_and_digest_mint_the_same_token() -> None:
    secret = b"a" * 32
    assert mint_approval_token(secret, "digest-1") == mint_approval_token(
        secret, "digest-1"
    )


def test_a_different_secret_mints_a_different_token() -> None:
    token_a = mint_approval_token(b"a" * 32, "digest-1")
    token_b = mint_approval_token(b"b" * 32, "digest-1")
    assert token_a != token_b


def test_a_different_digest_mints_a_different_token() -> None:
    secret = b"a" * 32
    assert mint_approval_token(secret, "digest-1") != mint_approval_token(
        secret, "digest-2"
    )


def test_token_is_a_hex_sha256_hmac() -> None:
    token = mint_approval_token(b"a" * 32, "digest-1")
    assert len(token) == 64
    int(token, 16)  # raises ValueError if not hex
