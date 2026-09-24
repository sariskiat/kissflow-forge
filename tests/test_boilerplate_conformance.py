"""Conformance gate against the boilerplate clone (refactor spec, section 8, gate 1; D2, HR5:
"Everything else matches the boilerplate's structure ... The clone is the reference.").

Skipped entirely unless `BOILERPLATE_DIR` is set -- this gate needs a second repo on disk, which
CI does not have and most local runs do not need. Run it with::

    BOILERPLATE_DIR=/path/to/mcp-server-python-boilerplate uv run pytest tests/test_boilerplate_conformance.py

Expected on `develop` at G0: tests 1-3 pass (the clone is pinned, every delta has a reason, the
open slots exist in the clone). Tests 4-6 are RED -- none of the refactor's own directories exist
under `src/app` yet. That redness is the point (spec: "the conformance test is red on develop");
it is the target this whole refactor closes, goal by goal, ending green at P6.
"""

from __future__ import annotations

import fnmatch
import os
import subprocess
import tomllib
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
DELTAS_PATH = REPO_ROOT / "tests" / "fixtures" / "tooling_deltas.toml"
HERE_SRC_APP = REPO_ROOT / "src" / "app"

pytestmark = pytest.mark.skipif(
    not os.environ.get("BOILERPLATE_DIR"),
    reason=(
        "BOILERPLATE_DIR is unset. Set it to the boilerplate clone to run the conformance gate "
        "(spec section 8, gate 1)."
    ),
)

#: A slot the clone's own modules are only examples of. Any module name is correct there, at any
#: depth (spec section 6, G0's "Terms for the tests").
OPEN_SLOTS: tuple[str, ...] = (
    "application/interfaces",
    "application/models/requests",
    "application/models/responses",
    "application/use_cases",
    "domain/entities",
    "domain/value_objects",
    "infrastructure/database",
    "infrastructure/external_api",
)


def _boilerplate_dir() -> Path:
    """The boilerplate clone's root read from `BOILERPLATE_DIR`.

    Returns:
        The clone's path. The module-level skip guarantees the env var is set whenever a test
        here actually runs.
    """
    value = os.environ["BOILERPLATE_DIR"]
    return Path(value)


def _clone_src_app() -> Path:
    """The clone's `src/app` directory."""
    return _boilerplate_dir() / "src" / "app"


def _deltas() -> dict[str, Any]:
    """The parsed `tests/fixtures/tooling_deltas.toml`."""
    return tomllib.loads(DELTAS_PATH.read_text(encoding="utf-8"))


#: A path in a flattened TOML document that exists on only one side (spec G1, test 1:
#: "that exists on one side only" must be covered by a `[[pyproject]]` entry too).
_MISSING = object()

#: Flattened-path prefixes whose array value is a list of requirement strings, sorted
#: before comparison (spec G1, test 1: "Sort the arrays of requirement strings before
#: you compare them (`project.dependencies`, `dependency-groups.*`)").
_REQUIREMENT_ARRAY_PATHS = ("project.dependencies", "dependency-groups.")


def _clone_head() -> str:
    """The full 40-character sha of the clone's current HEAD.

    Returns:
        The output of ``git -C <clone> rev-parse HEAD``, stripped.
    """
    result = subprocess.run(
        ["git", "-C", str(_boilerplate_dir()), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _clone_porcelain_status() -> str:
    """The clone's `git status --porcelain` output, unstripped.

    Pinning `[clone].commit` alone (test 1) only proves HEAD points at the right commit -- a
    local edit sitting uncommitted in the clone's working tree would still change what tests 4
    to 6 compare against, silently. This is the second half of that pin: the working tree itself
    must carry no such edit.

    Returns:
        Empty when the clone's working tree is clean, non-empty (one line per changed path)
        otherwise.
    """
    result = subprocess.run(
        ["git", "-C", str(_boilerplate_dir()), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _slot_dirs() -> list[str]:
    """Every directory under the clone's `src/app`, POSIX-relative, except `__pycache__`.

    Returns:
        Sorted relative directory paths (a "slot dir", spec section 6's Terms for the tests).
    """
    base = _clone_src_app()
    dirs = [
        p.relative_to(base).as_posix()
        for p in base.rglob("*")
        if p.is_dir() and p.name != "__pycache__"
    ]
    return sorted(dirs)


def _fixed_slot_files() -> list[str]:
    """Every `.py` file under the clone's `src/app` that is not under an open slot, plus the
    `__init__.py` directly in each open slot.

    Returns:
        Sorted relative file paths (a "fixed slot file", spec section 6's Terms for the tests).
    """
    base = _clone_src_app()
    open_slot_parts = [tuple(s.split("/")) for s in OPEN_SLOTS]
    files: list[str] = []
    for p in base.rglob("*.py"):
        rel = p.relative_to(base)
        rel_parts = rel.parts
        under_open_slot = any(
            rel_parts[: len(slot_parts)] == slot_parts for slot_parts in open_slot_parts
        )
        if not under_open_slot:
            files.append(rel.as_posix())
            continue
        is_direct_init = rel_parts[-1] == "__init__.py" and any(
            rel_parts[:-1] == slot_parts for slot_parts in open_slot_parts
        )
        if is_direct_init:
            files.append(rel.as_posix())
    return sorted(files)


def _apply_slot_replacements(clone_path: str, slots: list[dict[str, Any]]) -> str:
    """Rewrite a clone-relative path through the `[[slot]]` table.

    A path equal to or under a `slot.clone` directory becomes the same path under `slot.here`.

    Args:
        clone_path: A POSIX-relative path as it appears under the clone's `src/app`.
        slots: The parsed `[[slot]]` entries from `tooling_deltas.toml`.

    Returns:
        The path to compare against our own `src/app`.
    """
    for slot in slots:
        clone_prefix = slot["clone"]
        if clone_path == clone_prefix:
            return slot["here"]
        if clone_path.startswith(clone_prefix + "/"):
            return slot["here"] + clone_path[len(clone_prefix) :]
    return clone_path


# =================================================================================================
# 1. The clone is pinned
# =================================================================================================


def test_clone_is_at_the_pinned_commit() -> None:
    """The clone's HEAD equals `[clone].commit` in `tooling_deltas.toml` (HR5), and the clone's
    working tree carries no uncommitted edit (G0 review finding 5).

    The HEAD check alone only pins which commit the clone points at -- a local, uncommitted edit
    sitting on top of that commit would still change what tests 4 to 6 compare our `src/app`
    against, silently. Both halves of the pin are asserted here, together.
    """
    deltas = _deltas()
    assert _clone_head() == deltas["clone"]["commit"]
    porcelain = _clone_porcelain_status()
    assert not porcelain, f"the clone has uncommitted local edits:\n{porcelain}"


# =================================================================================================
# 2. Every delta has a reason
# =================================================================================================


def test_every_delta_has_a_reason() -> None:
    """Each `[[slot]]`/`[[module]]` entry has a non-empty reason, and each `[[slot]].clone` is a
    real directory in the clone."""
    deltas = _deltas()
    slot_dirs = set(_slot_dirs())
    no_reason: list[tuple[str, str]] = []
    bad_clone_dir: list[str] = []
    for slot in deltas.get("slot", []):
        if not slot.get("reason", "").strip():
            no_reason.append(("slot", slot.get("clone", "")))
        if slot["clone"] not in slot_dirs:
            bad_clone_dir.append(slot["clone"])
    for module in deltas.get("module", []):
        if not module.get("reason", "").strip():
            no_reason.append(("module", module.get("glob", "")))
    assert not no_reason, f"deltas with no reason: {no_reason}"
    assert not bad_clone_dir, (
        f"[[slot]].clone not a directory in the clone: {bad_clone_dir}"
    )


# =================================================================================================
# 3. The open slots exist in the clone
# =================================================================================================


def test_open_slots_exist_in_the_clone() -> None:
    """Each `OPEN_SLOTS` entry is a real directory in the clone."""
    slot_dirs = set(_slot_dirs())
    missing = [s for s in OPEN_SLOTS if s not in slot_dirs]
    assert not missing, f"OPEN_SLOTS missing from the clone: {missing}"


# =================================================================================================
# 4. Every clone slot exists here
# =================================================================================================


def test_every_clone_slot_exists_here() -> None:
    """Each slot dir and each fixed slot file exists under our `src/app`, after `[[slot]]`
    replacements.

    Red on `develop` today: G2 through G13 are what create these directories and files.
    """
    slots = _deltas().get("slot", [])
    missing: list[str] = []
    for slot_dir in _slot_dirs():
        here_path = _apply_slot_replacements(slot_dir, slots)
        if not (HERE_SRC_APP / here_path).is_dir():
            missing.append(here_path)
    for fixed_file in _fixed_slot_files():
        here_path = _apply_slot_replacements(fixed_file, slots)
        if not (HERE_SRC_APP / here_path).is_file():
            missing.append(here_path)
    assert not missing, f"missing under our src/app: {sorted(set(missing))}"


# =================================================================================================
# 5. Every module here maps to one slot
# =================================================================================================


def test_every_module_maps_to_one_slot() -> None:
    """Each `.py` file under our `src/app` is a fixed slot file, is under an open slot or a
    `[[slot]].here` directory at any depth, or matches a `[[module]].glob`.

    Red on `develop` today: most of `src/app` predates this layout entirely.
    """
    deltas = _deltas()
    slots = deltas.get("slot", [])
    modules = deltas.get("module", [])

    fixed_here = {_apply_slot_replacements(f, slots) for f in _fixed_slot_files()}
    open_here_prefixes = [_apply_slot_replacements(s, slots) for s in OPEN_SLOTS]
    here_dirs = {s["here"] for s in slots}
    globs = [m["glob"] for m in modules]

    def _mapped(rel: str) -> bool:
        if rel in fixed_here:
            return True
        if any(rel == pfx or rel.startswith(pfx + "/") for pfx in open_here_prefixes):
            return True
        if any(rel == d or rel.startswith(d + "/") for d in here_dirs):
            return True
        return any(fnmatch.fnmatch(rel, g) for g in globs)

    unmapped = [
        rel
        for p in sorted(HERE_SRC_APP.rglob("*.py"))
        for rel in [p.relative_to(HERE_SRC_APP).as_posix()]
        if not _mapped(rel)
    ]
    assert not unmapped, f"unmapped under our src/app: {unmapped}"


# =================================================================================================
# 6. Every repo-level clone path exists here
# =================================================================================================


def test_every_repo_level_clone_path_exists_here() -> None:
    """Every repo-level file the clone tracks -- outside `src/app/`, `uv.lock`, and most of
    `tests/unit/` -- exists as a file in this repo.

    Red on `develop` today: `tests/unit/` and the bare `src/__init__.py` do not exist yet (G14).
    """
    result = subprocess.run(
        ["git", "-C", str(_boilerplate_dir()), "ls-files"],
        capture_output=True,
        text=True,
        check=True,
    )
    kept_tests_unit = {"tests/unit/__init__.py", "tests/unit/test_main.py"}
    missing: list[str] = []
    for path in result.stdout.splitlines():
        if not path or path.startswith("src/app/") or path == "uv.lock":
            continue
        if path.startswith("tests/unit/") and path not in kept_tests_unit:
            continue
        if not (REPO_ROOT / path).is_file():
            missing.append(path)
    assert not missing, f"missing repo-level paths: {sorted(missing)}"


# ============================================================================
# 7. pyproject.toml equals the clone except deltas (goal G1)
# ============================================================================


def _flatten_toml(document: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """Flatten a parsed TOML document into dotted key paths (spec G1, test 1).

    A table becomes its sub-keys, recursively. Any other value -- including an array,
    even an array of tables such as `[[tool.importlinter.contracts]]` -- is one leaf
    value at its own path ("An array is one value").

    Args:
        document: A `tomllib.loads()` result, or one of its nested tables.
        prefix: The dotted path built so far.

    Returns:
        Dotted path -> leaf value, over the whole document.
    """
    flat: dict[str, Any] = {}
    for key, value in document.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            flat.update(_flatten_toml(value, path))
        else:
            flat[path] = value
    return flat


def _normalize_requirement_arrays(flat: dict[str, Any]) -> dict[str, Any]:
    """Sort the requirement-string arrays in a flattened TOML document before comparing.

    Args:
        flat: A `_flatten_toml()` result.

    Returns:
        The same mapping, with every `project.dependencies` / `dependency-groups.*`
        list value replaced by its sorted copy (spec G1, test 1).
    """
    normalized = dict(flat)
    for path, value in flat.items():
        if not isinstance(value, list):
            continue
        if path == "project.dependencies" or path.startswith(
            _REQUIREMENT_ARRAY_PATHS[1]
        ):
            normalized[path] = sorted(value)
    return normalized


def _pyproject_deltas() -> list[dict[str, Any]]:
    """The `[[pyproject]]` entries from `tooling_deltas.toml`."""
    return _deltas().get("pyproject", [])


def _covered_by(path: str, keys: list[str]) -> bool:
    """Whether a dotted path is covered by one of the given delta keys.

    Args:
        path: A dotted path from `_flatten_toml()`.
        keys: The `key` field of every delta entry of one kind.

    Returns:
        True if `path` equals a key, or sits under one as a sub-key (spec G1, test 1:
        "A key covers itself and every sub-key").
    """
    return any(path == key or path.startswith(key + ".") for key in keys)


def test_pyproject_equals_the_clone_except_deltas() -> None:
    """`pyproject.toml` equals the clone's, key for key, except the entries listed in
    `tooling_deltas.toml` (spec G1, D2, HR5).

    Every differing or one-side-only dotted path must be covered by a `[[pyproject]]`
    entry. Every `[[pyproject]]` entry must cover at least one real difference (no
    stale entry), and carry a non-empty `reason`.
    """
    ours = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    theirs = tomllib.loads(
        (_boilerplate_dir() / "pyproject.toml").read_text(encoding="utf-8")
    )
    ours_flat = _normalize_requirement_arrays(_flatten_toml(ours))
    theirs_flat = _normalize_requirement_arrays(_flatten_toml(theirs))

    all_paths = set(ours_flat) | set(theirs_flat)
    differing = {
        path
        for path in all_paths
        if ours_flat.get(path, _MISSING) != theirs_flat.get(path, _MISSING)
    }

    deltas = _pyproject_deltas()
    keys = [d["key"] for d in deltas]
    uncovered = sorted(path for path in differing if not _covered_by(path, keys))
    assert not uncovered, (
        f"pyproject.toml differs from the clone with no delta entry: {uncovered}"
    )

    stale = [
        d["key"]
        for d in deltas
        if not any(_covered_by(p, [d["key"]]) for p in differing)
    ]
    assert not stale, f"stale [[pyproject]] entries in tooling_deltas.toml: {stale}"

    no_reason = [d["key"] for d in deltas if not d.get("reason", "").strip()]
    assert not no_reason, f"[[pyproject]] entries with no reason: {no_reason}"


# =================================================================================================
# 7b. dependency-groups.dev now equals the clone's exactly (G1 review finding 2; G5 moved httpx)
# =================================================================================================


def test_dependency_groups_dev_now_equals_the_clone_exactly() -> None:
    """The `dependency-groups.dev` delta is now empty: G5 moved `httpx` out of our dev group into
    `[project.dependencies]` (spec G1 user decision, 2026-09-22, "until G5 moves it" -- G5 has),
    so `tooling_deltas.toml` no longer lists a `dependency-groups.dev` entry at all (a stale entry
    would fail `test_pyproject_equals_the_clone_except_deltas` above).

    `_flatten_toml` treats a whole array as one leaf value, so that test alone only proves the two
    `dev` arrays agree overall -- a change to some OTHER dev dependency (a version bump, an added
    or dropped package) could in principle hide behind a coincidentally-matching flattened value.
    This test checks the actual set difference in both directions is empty (P1 and Stage C moved
    dependencies; this test was updated when they did -- it stays exact on purpose, not
    open-ended).
    """
    ours = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    theirs = tomllib.loads(
        (_boilerplate_dir() / "pyproject.toml").read_text(encoding="utf-8")
    )
    ours_dev = set(ours["dependency-groups"]["dev"])
    theirs_dev = set(theirs["dependency-groups"]["dev"])
    assert ours_dev - theirs_dev == set(), ours_dev - theirs_dev
    assert theirs_dev - ours_dev == set(), theirs_dev - ours_dev


# ============================================================================
# 8. .claude equals the clone except deltas (goal G1, Q10)
# ============================================================================


def test_claude_folder_equals_the_clone_except_deltas() -> None:
    """Every file the clone tracks under `.claude/` exists here with the same bytes,
    except the files listed in a `[[claude]]` entry in `tooling_deltas.toml` (spec G1, Q10).

    A listed file must actually differ -- a stale entry fails the test -- and carry a
    non-empty `reason`. A listed entry also names its own exact change, `clone_text` and
    `our_text` (G1 review finding 3): replacing `clone_text` with `our_text` in the
    clone's bytes must reproduce our bytes exactly, and `clone_text` must appear exactly
    once in the clone's file. Without that, an entry only proves the file differs
    SOMEWHERE, and any other, unrelated, unreviewed change could hide inside the same
    "known" delta.
    """
    result = subprocess.run(
        ["git", "-C", str(_boilerplate_dir()), "ls-files", ".claude"],
        capture_output=True,
        text=True,
        check=True,
    )
    clone_files = [p for p in result.stdout.splitlines() if p]
    assert clone_files, "the clone reports no tracked files under .claude"

    deltas = _deltas().get("claude", [])
    listed = {d["file"]: d for d in deltas}
    no_reason = [f for f, d in listed.items() if not d.get("reason", "").strip()]
    assert not no_reason, f"[[claude]] entries with no reason: {no_reason}"

    missing: list[str] = []
    differing_unlisted: list[str] = []
    identical_but_listed: list[str] = []
    wrong_replacement: list[str] = []
    for rel_path in clone_files:
        here = REPO_ROOT / rel_path
        if not here.is_file():
            missing.append(rel_path)
            continue
        clone_bytes = (_boilerplate_dir() / rel_path).read_bytes()
        here_bytes = here.read_bytes()
        if here_bytes == clone_bytes:
            if rel_path in listed:
                identical_but_listed.append(rel_path)
        elif rel_path not in listed:
            differing_unlisted.append(rel_path)
        else:
            delta = listed[rel_path]
            clone_text = delta.get("clone_text", "").encode("utf-8")
            our_text = delta.get("our_text", "").encode("utf-8")
            unique = clone_bytes.count(clone_text) == 1
            if not unique or clone_bytes.replace(clone_text, our_text) != here_bytes:
                wrong_replacement.append(rel_path)

    assert not missing, f"missing under .claude: {sorted(missing)}"
    assert not differing_unlisted, (
        f".claude files differ with no delta entry: {sorted(differing_unlisted)}"
    )
    stale = [f for f in listed if f not in clone_files]
    assert not stale, (
        f"[[claude]] entries for files the clone no longer tracks: {sorted(stale)}"
    )
    assert not identical_but_listed, (
        f"stale [[claude]] entries -- these files are byte-identical to the clone: "
        f"{sorted(identical_but_listed)}"
    )
    assert not wrong_replacement, (
        "[[claude]] clone_text -> our_text does not exactly reproduce our file (clone_text "
        f"missing, not unique, or another unaccounted change sits in the same file): "
        f"{sorted(wrong_replacement)}"
    )


# ============================================================================
# 9. .python-version equals the clone (goal G1)
# ============================================================================


def test_python_version_equals_the_clone() -> None:
    """`.python-version` equals the clone's, byte for byte (spec G1: "`.python-version`
    stays `3.13`, equal to the clone")."""
    ours = (REPO_ROOT / ".python-version").read_bytes()
    theirs = (_boilerplate_dir() / ".python-version").read_bytes()
    assert ours == theirs
