"""Shared call-recording support for the in-memory port fakes under `tests/fakes/`.

Not itself a port fake -- a private test helper, so the mirror rule (`tests_mirror_src`)
does not apply to it (it lives entirely under `tests/`, never under `src/app/`).
"""

from __future__ import annotations

from typing import Any


class RecordingMixin:
    """Records every call made on a fake port, in call order.

    A family writer's use-case test configures `results[method_name]` with the
    values that method should return, in call order, then asserts against
    `calls` to check argument values and call order (for example with
    `tests.unit.application.use_cases.test_write_order_contract.assert_write_order`).

    Attributes:
        calls: Every call so far, as `(method_name, args, kwargs)`, in the
            order the fake received them.
        results: Per-method queues of canned return values. A call to
            `_record` for a method with a non-empty queue here pops and
            returns its first entry; otherwise it returns `default`.
    """

    def __init__(self) -> None:
        """Initialize an empty call log and an empty results table."""
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.results: dict[str, list[Any]] = {}

    def _record(
        self,
        name: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        default: Any = None,
    ) -> Any:
        """Log one call and return its configured or default result.

        Args:
            name: The method name, exactly as the port declares it.
            args: The positional arguments the caller passed, in order.
            kwargs: The keyword arguments the caller passed.
            default: The value to return when `results[name]` is empty or unset.

        Returns:
            The next queued value in `results[name]`, popped in FIFO order,
            or `default` when no value is queued.
        """
        self.calls.append((name, args, kwargs))
        queue = self.results.get(name)
        if queue:
            return queue.pop(0)
        return default
