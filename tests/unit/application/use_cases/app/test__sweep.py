"""Spec for app.application.use_cases.app._sweep.

Ports the matching cases of `tests/test_p4_surface.py`'s `run_sweep` tests onto
the new fake-port architecture: one sub-scope's own `RepositoryError` lands in
its OWN `"error"` bucket here, never propagated -- the same "never swallowed"
contract `run_sweep`'s own docstring names.
"""

from __future__ import annotations

import pytest

from app.application.exceptions import RepositoryError
from app.application.use_cases.app._sweep import (
    SWEEP_FLOW_KINDS,
    SWEEP_SCOPES,
    read_bucket,
)


def test_sweep_scopes_is_the_five_real_scopes_in_order() -> None:
    assert SWEEP_SCOPES == ("apps", "flows", "pages", "roles", "lists")


def test_sweep_flow_kinds_covers_every_flow_kind() -> None:
    assert SWEEP_FLOW_KINDS == ("process", "form", "case", "list", "dataset")


@pytest.mark.asyncio
async def test_read_bucket_reads_the_inventory() -> None:
    async def _ok() -> list[str]:
        return ["App_1"]

    bucket = await read_bucket(_ok)

    assert bucket == {"status": "read", "count": 1, "items": ["App_1"], "error": None}


@pytest.mark.asyncio
async def test_read_bucket_lands_a_repository_error_in_its_own_bucket() -> None:
    async def _failing() -> list[str]:
        raise RepositoryError("boom")

    bucket = await read_bucket(_failing)

    assert bucket == {"status": "error", "count": 0, "items": [], "error": "boom"}
