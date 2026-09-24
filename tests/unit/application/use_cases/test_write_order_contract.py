"""assert_write_order(fake_port) — the reusable write-order check every family writer's
use-case test calls (spec section 6, G11's invariant, stated early for Stage C -- see
app.application.use_cases.flow._write_order's own module docstring).

Import as
`tests.unit.application.use_cases.test_write_order_contract.assert_write_order`
(the repo root is on `sys.path` through the root `conftest.py`, and `tests/`
is an implicit namespace package -- proven here by this file's own use of
`tests.fakes.*`).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.fakes._recording import RecordingMixin
from tests.fakes.app import FakeAppRepository
from tests.fakes.flow import FakeFlowRepository

from app.domain.entities.flow_draft import FlowDraft

_ROOT = Path(__file__).resolve().parents[4]
_WRITE_PREFIXES = (
    "forge_set",
    "forge_add",
    "forge_apply",
    "forge_create",
    "forge_delete",
    "forge_build",
    "forge_publish",
    "forge_rename",
    "forge_member",
    "forge_grant",
    "forge_share",
    "kf_apply",
    "kf_create",
    "kf_set",
    "kf_publish",
)

# Reviewed against the emitted surface.  These tools either do not call
# Kissflow at all or create a resource before a draft can exist.
_OFFLINE_OPERATIONS = frozenset({"forge_apply_revisions"})
_CREATES_WITHOUT_PRIOR_DRAFT = frozenset(
    {
        "forge_create_app",
        "forge_create_app_role",
        "forge_create_flow",
        "forge_create_list",
        "forge_create_page",
        "forge_create_process",
        "forge_create_template_app",
        "kf_create_process",
    }
)

# Writes that target membership, roles, or deletion routes have a required
# read-before-write check, but no draft resource to snapshot.
_NON_DRAFT_WRITES = frozenset(
    {
        "forge_add_member_roles",
        "forge_add_role_users",
        "forge_delete_app_role",
        "forge_delete_flow",
        "forge_grant_tier",
        "forge_member_batch",
        "forge_share_report",
        "forge_set_role_preference",
    }
)

_DRAFT_WRITE_TOOLS = frozenset(
    {
        "forge_add_field_validation",
        "forge_add_goto_gate",
        "forge_add_sequence_number",
        "forge_add_table",
        "forge_apply_fields",
        "forge_apply_layout",
        "forge_build_page",
        "forge_build_workflow",
        "forge_delete_fields",
        "forge_publish",
        "forge_publish_app",
        "forge_rename_fields",
        "forge_set_branch_conditions",
        "forge_set_events",
        "forge_set_navigation",
        "forge_set_required",
        "forge_set_styles",
        "forge_set_visibility",
        "kf_apply_field_change",
        "kf_publish",
        "kf_set_step_visibility",
    }
)

_READ_PREFIXES = ("get_", "list_")

#: Every `put_*` this invariant treats as draft-shaped, and the `get_*` that must have
#: read it first (spec section 6, G11's invariant).
_DRAFT_WRITES: dict[str, str] = {
    "put_draft": "get_draft",
    "put_page_draft": "get_page_draft",
    "put_app_draft": "get_app_draft",
}


def assert_write_order(fake_port: RecordingMixin) -> None:
    """Assert the write-order invariant over one fake port's recorded calls.

    Two checks, both from the same invariant (spec section 6, G11): the
    first call ever made on a port is a read, and every draft-shaped write
    (`put_draft`/`put_page_draft`/`put_app_draft`) has its own matching
    `get_*` somewhere earlier in the call list.

    Args:
        fake_port: A fake whose `.calls` were recorded by `RecordingMixin`,
            after driving it through one use case's `execute()`.

    Raises:
        AssertionError: The first call is not a read, or a draft write has
            no matching `get_*` earlier in the call list.
    """
    calls = fake_port.calls
    assert calls, "expected at least one call on this port"

    first_name = calls[0][0]
    assert first_name.startswith(_READ_PREFIXES), (
        f"first call on this port must be a read (get_*/list_*), was {first_name!r}"
    )

    for index, (name, _args, _kwargs) in enumerate(calls):
        matching_get = _DRAFT_WRITES.get(name)
        if matching_get is None:
            continue
        earlier_names = [c[0] for c in calls[:index]]
        assert matching_get in earlier_names, (
            f"{name} at position {index} has no {matching_get} earlier "
            f"in the call list: {earlier_names}"
        )


def test_write_order_inventory_covers_the_emitted_surface() -> None:
    """A new prefixed writer must be reviewed before this contract can pass.

    The per-use-case tests call ``assert_write_order`` with their own fake.  This
    inventory closes the separate gap where a new write tool has no test at all:
    every surface-derived write is assigned to the draft, create, offline, or
    non-draft review bucket, and every draft writer has a read-capable use case.
    """
    fixture = json.loads(
        (_ROOT / "tests" / "fixtures" / "tool_surface.json").read_text(encoding="utf-8")
    )
    surface = set(fixture["tools"])
    writes = {name for name in surface if name.startswith(_WRITE_PREFIXES)}
    buckets = (
        _DRAFT_WRITE_TOOLS,
        _CREATES_WITHOUT_PRIOR_DRAFT,
        _OFFLINE_OPERATIONS,
        _NON_DRAFT_WRITES,
    )
    assigned = set().union(*buckets)
    assert writes == assigned, f"unreviewed write tools: {sorted(writes - assigned)}"
    assert all(
        not (left & right)
        for index, left in enumerate(buckets)
        for right in buckets[index + 1 :]
    ), "a write tool must have exactly one reviewed classification"

    use_cases = {
        path.stem: path
        for path in (_ROOT / "src" / "app" / "application" / "use_cases").rglob("*.py")
    }
    for name in _DRAFT_WRITE_TOOLS:
        source = use_cases[name].read_text(encoding="utf-8")
        assert any(
            token in source
            for token in (
                "WriteOrder",
                "get_draft",
                "get_page_draft",
                "get_app_draft",
                "publish_application_verified",
            )
        ), f"{name} has no visible draft snapshot read"


# =====================================================================
# assert_write_order's own tests
# =====================================================================


@pytest.mark.asyncio
async def test_passes_when_a_draft_write_follows_its_own_read() -> None:
    fake = FakeFlowRepository()
    await fake.get_draft("A1", "process", "F1")
    await fake.put_draft("A1", "process", "F1", FlowDraft.from_wire({}), "v1")

    assert_write_order(fake)  # does not raise


@pytest.mark.asyncio
async def test_passes_for_a_non_draft_write_whose_first_call_is_a_read() -> None:
    fake = FakeAppRepository()
    await fake.list_app_roles("A1")
    await fake.create_app_role("Reviewers", "A1")

    assert_write_order(fake)  # does not raise


def test_raises_when_there_are_no_calls_at_all() -> None:
    fake = FakeFlowRepository()
    with pytest.raises(AssertionError, match="at least one call"):
        assert_write_order(fake)


@pytest.mark.asyncio
async def test_raises_when_the_first_call_is_a_write() -> None:
    fake = FakeAppRepository()
    await fake.create_application("New app")

    with pytest.raises(AssertionError, match="first call on this port must be a read"):
        assert_write_order(fake)


@pytest.mark.asyncio
async def test_raises_when_put_draft_has_no_matching_get_draft_first() -> None:
    fake = FakeFlowRepository()
    # A read happened, but of the wrong kind (list_flows, not get_draft) -- put_draft
    # still has no get_draft anywhere earlier.
    await fake.list_flows("A1", "process")
    await fake.put_draft("A1", "process", "F1", FlowDraft.from_wire({}), "v1")

    with pytest.raises(AssertionError, match="no get_draft earlier"):
        assert_write_order(fake)
