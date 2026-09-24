"""WriteOrder — the snapshot before apply before read-back before publish order.

Invariant (spec section 6, G11; stated here ahead of G11 because the family
writers who build the 61 use cases in Stage D all need it). For every write
use case `W` and the fake port `F` it writes through: the first call `W`
makes on `F` in one `execute()` is a `get_*` (or `list_*`), never a write.
For a `put_draft`/`put_page_draft`/`put_app_draft`-shaped write, that first
call is the snapshot, its `expect_version` is threaded into the later write
call unchanged, and the use case's response carries that same version as
`snapshot_version`. `WriteOrder` gives that order a small API that is hard
to get wrong by hand: `snapshot()` must run before `apply()`, or `apply()`
raises rather than silently writing against no plan.

For a write that is not a draft (members, roles, word lists, records,
applications, creating or deleting a flow), the invariant is simpler -- the
first port call is still a read -- and does not need this class at all: the
use case calls a `get_*`/`list_*` first, in its own `execute()` body, the
same discipline
`tests.unit.application.use_cases.test_write_order_contract.assert_write_order`
checks either way.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable


class WriteOrderError(RuntimeError):
    """Raised when a `WriteOrder` step runs out of order (`apply()` before
    `snapshot()`)."""


class WriteOrder[T]:
    """Wraps one draft-shaped write's snapshot -> apply -> read-back -> publish
    sequence.

    A use case builds one `WriteOrder` per `execute()` call, around the three
    (or four) port calls it is about to make, and drives it in order:

        order = WriteOrder(
            get=port.get_draft_bound,
            put=port.put_draft_bound,
            version_of=lambda d: d.version,
            publish=port.publish_bound,
        )
        await order.snapshot()
        written = await order.apply(new_draft)
        response = MyResponse(..., snapshot_version=order.snapshot_version)
    """

    def __init__(
        self,
        *,
        get: Callable[[], Awaitable[T]],
        put: Callable[[T, str | None], Awaitable[T]],
        version_of: Callable[[T], str | None],
        publish: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        """Build a WriteOrder around one write's own get/put/publish calls.

        Args:
            get: Re-reads the live entity (`get_draft`/`get_page_draft`/
                `get_app_draft`), used by both `snapshot()` and
                `read_back()`.
            put: Writes the entity. Called by `apply()` with the new entity
                and the snapshot's own version as `expect_version`.
            version_of: Reads the version off an entity (for example
                `lambda d: d.version`), used to fill `snapshot_version`.
            publish: Publishes the flow, when this write has a publish
                step. `None` when it does not; `publish()` then raises.
        """
        self._get = get
        self._put = put
        self._version_of = version_of
        self._publish = publish
        self._snapshot: T | None = None
        self._snapshot_version: str | None = None
        self._has_snapshot = False

    @property
    def snapshot_version(self) -> str | None:
        """The snapshotted entity's version, or `None` before `snapshot()` runs."""
        return self._snapshot_version

    async def snapshot(self) -> T:
        """Read the live entity and record its version as the plan `apply()`
        writes against.

        Returns:
            The live entity, as `get()` returned it.
        """
        self._snapshot = await self._get()
        self._snapshot_version = self._version_of(self._snapshot)
        self._has_snapshot = True
        return self._snapshot

    async def apply(self, new: T) -> T:
        """Write `new`, planned against the version `snapshot()` recorded.

        Args:
            new: The entity to write.

        Returns:
            The entity `put()` returns.

        Raises:
            WriteOrderError: `snapshot()` has not run yet.
        """
        if not self._has_snapshot:
            raise WriteOrderError("apply() called before snapshot()")
        return await self._put(new, self._snapshot_version)

    async def read_back(self) -> T:
        """Re-read the live entity, to verify what `apply()` actually wrote.

        Returns:
            The live entity, as `get()` returns it now.
        """
        return await self._get()

    async def publish(self) -> None:
        """Publish the flow this write's draft belongs to.

        Raises:
            WriteOrderError: This `WriteOrder` was built with no `publish`
                step.
        """
        if self._publish is None:
            raise WriteOrderError("this WriteOrder has no publish step")
        await self._publish()
