"""Ratchet tests for the copied tooling contracts (refactor spec G1).

Both ratchets only shrink: a later goal that moves or deletes a file takes it off the
list, never adds to it. No `BOILERPLATE_DIR` needed -- these run in `make test`.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"
E501_RATCHET_PATH = REPO_ROOT / "tests" / "fixtures" / "e501_ratchet_g1.txt"

#: The only `[tool.ruff]` / `[tool.ruff.lint]` / `[tool.ty]` keys G1 wrote (spec G1's
#: "The clone has" list, plus the deltas in `tooling_deltas.toml`). A nested table
#: (`lint`, `format`, `overrides`, `environment`) counts as one key at its parent's
#: level; its own keys are each checked at their own level.
_RUFF_TOP_LEVEL_KEYS = frozenset(
    {"target-version", "line-length", "src", "lint", "format"}
)
_RUFF_LINT_KEYS = frozenset({"select", "per-file-ignores"})
_TY_TOP_LEVEL_KEYS = frozenset({"overrides", "environment"})


def _pyproject() -> dict[str, Any]:
    """The parsed `pyproject.toml`.

    Returns:
        The `tomllib.loads()` result.
    """
    return tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))


def _per_file_ignores() -> dict[str, Any]:
    """`[tool.ruff.lint.per-file-ignores]`.

    Returns:
        The table, or an empty mapping if it is absent.
    """
    tool = _pyproject().get("tool", {})
    ruff = tool.get("ruff", {})
    lint = ruff.get("lint", {})
    return lint.get("per-file-ignores", {})


def _ty_overrides() -> list[dict[str, Any]]:
    """`[[tool.ty.overrides]]`.

    Returns:
        The list of override tables, or an empty list if the key is absent.
    """
    tool = _pyproject().get("tool", {})
    ty = tool.get("ty", {})
    return ty.get("overrides", [])


def test_e501_ratchet_lists_only_existing_files() -> None:
    """Every path in `[tool.ruff.lint.per-file-ignores]` is a real file in this repo."""
    missing = [p for p in _per_file_ignores() if not (REPO_ROOT / p).is_file()]
    assert not missing, f"per-file-ignores names a file that does not exist: {missing}"


def test_e501_ratchet_only_shrinks() -> None:
    """The E501 ratchet only shrinks: every listed path sits in the frozen G1 list
    (`tests/fixtures/e501_ratchet_g1.txt`)."""
    frozen = set(E501_RATCHET_PATH.read_text(encoding="utf-8").splitlines())
    current = set(_per_file_ignores())
    grown = current - frozen
    assert not grown, f"per-file-ignores grew past the frozen G1 list: {sorted(grown)}"


def test_ty_override_only_shrinks() -> None:
    """The temporary invalid-assignment override is retired with the old test suites."""
    assert _ty_overrides() == []


# ============================================================================
# G1 review finding 1: the two ratchets above check file LISTS, not the RULES those
# lists carry. A per-file-ignores entry could silently ignore a rule other than E501,
# `[[tool.ty.overrides]]` could grow a second entry, or a global `ignore`/rule could
# appear at a table level the ratchet never inspects -- none of that moves a path in
# or out of a list, so the two tests above would stay green through all three. These
# three tests check the RULES themselves.
# ============================================================================


def test_per_file_ignores_values_are_exactly_e501() -> None:
    """Every value in `[tool.ruff.lint.per-file-ignores]` is exactly `["E501"]`.

    The ratchet is an E501 line-length exemption, file by file -- never a way to silence
    some other rule (F401, SIM102, ...) on one file without that showing up as a
    reviewable, named delta anywhere.
    """
    bad = {
        path: value for path, value in _per_file_ignores().items() if value != ["E501"]
    }
    assert not bad, f"per-file-ignores holds a non-['E501'] value: {bad}"


def test_ty_overrides_are_retired() -> None:
    """The clone has no temporary invalid-assignment override."""
    assert _ty_overrides() == []


def test_ruff_and_ty_tables_hold_only_the_g1_keys() -> None:
    """`[tool.ruff]`, `[tool.ruff.lint]`, `[tool.ty]` hold no key beyond what G1 wrote.

    A stray `ignore = [...]` at `[tool.ruff]` or `[tool.ruff.lint]` would silence a
    rule repo-wide, not through the per-file E501 ratchet -- and a stray rule set
    directly under `[tool.ty]` would silence it repo-wide, not through a scoped
    `[[tool.ty.overrides]]` entry. Both would slip past every ratchet above, which
    only ever reads the `lint`/`overrides` sub-tables they already expect.
    """
    tool = _pyproject().get("tool", {})
    ruff = tool.get("ruff", {})
    ty = tool.get("ty", {})
    extra_ruff = set(ruff) - _RUFF_TOP_LEVEL_KEYS
    extra_lint = set(ruff.get("lint", {})) - _RUFF_LINT_KEYS
    extra_ty = set(ty) - _TY_TOP_LEVEL_KEYS
    assert not extra_ruff, f"[tool.ruff] holds an unexpected key: {sorted(extra_ruff)}"
    assert not extra_lint, (
        f"[tool.ruff.lint] holds an unexpected key: {sorted(extra_lint)}"
    )
    assert not extra_ty, f"[tool.ty] holds an unexpected key: {sorted(extra_ty)}"
