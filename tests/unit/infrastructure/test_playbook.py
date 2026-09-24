"""Spec for app.infrastructure.playbook: the vendored builder playbook, read as plain
data.

Ports `tests/test_playbook.py` (2 tests) through the `DocsReader` port with the same
assertions (spec G13). `isError is False` becomes "plain data, no `isError` key": the
two failure modes that used to be `isError` payloads, a missing and a blank SKILL.md,
are now `ApplicationError(code=NOT_FOUND)` with today's message. The old
The old `load_playbook()` payload is removed with the old server in Stage E.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.application.exceptions import NOT_FOUND, ApplicationError
from app.application.interfaces.docs import DocsReader
from app.infrastructure.docs_reader import DocsReaderAdapter
from app.infrastructure.playbook import PLAYBOOK_PATH, read_playbook
from app.resources import REPO_ROOT, SKILLS_DIR

_SOURCE = "skills/kissflow-forge-builder/SKILL.md"


def _skill_path(root: Path) -> Path:
    return root / "skills" / "kissflow-forge-builder" / "SKILL.md"


def test_vendored_playbook_file_ships_with_the_repo() -> None:
    assert PLAYBOOK_PATH.is_file(), (
        "the builder skill must be vendored in the repo, not only in ~/.claude"
    )


def test_the_playbook_path_is_anchored_on_app_resources() -> None:
    """`forge_playbook` serves this file to a remote client at runtime: the lookup
    goes through `app.resources`, the one filesystem anchor."""
    assert PLAYBOOK_PATH == SKILLS_DIR / "kissflow-forge-builder" / "SKILL.md"
    assert PLAYBOOK_PATH.is_relative_to(REPO_ROOT)


@pytest.mark.asyncio
async def test_the_port_returns_the_full_brain_as_plain_data() -> None:
    reader: DocsReader = DocsReaderAdapter()

    out = await reader.playbook()

    assert set(out) == {"text", "source"}, "plain data: no isError key"
    assert out["text"].strip(), "playbook text must be non-empty"
    assert len(out["text"]) > 8000
    # the load-bearing doctrine a fresh MCP-only Claude would otherwise get wrong
    assert "THE RULE" in out["text"]
    assert "Build order" in out["text"]
    # the numbered build-order steps travel with the tools
    assert "Members" in out["text"]
    assert "Publish" in out["text"]
    assert "Simulate" in out["text"]
    assert out["source"].endswith("skills/kissflow-forge-builder/SKILL.md")


def test_read_playbook_defaults_to_the_vendored_file() -> None:
    out = read_playbook()
    assert out["text"] == PLAYBOOK_PATH.read_text()
    assert out["source"] == _SOURCE


def test_read_playbook_returns_the_text_and_its_root_relative_source(
    tmp_path: Path,
) -> None:
    path = _skill_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("# THE RULE\nbody\n")

    assert read_playbook(path, tmp_path) == {
        "text": "# THE RULE\nbody\n",
        "source": _SOURCE,
    }


def test_a_missing_playbook_is_not_found_with_todays_message(tmp_path: Path) -> None:
    with pytest.raises(ApplicationError) as info:
        read_playbook(_skill_path(tmp_path), tmp_path)

    assert info.value.code == NOT_FOUND
    assert info.value.message == f"vendored playbook not found at {_SOURCE}"


def test_a_directory_in_place_of_the_playbook_is_not_found(tmp_path: Path) -> None:
    _skill_path(tmp_path).mkdir(parents=True)

    with pytest.raises(ApplicationError) as info:
        read_playbook(_skill_path(tmp_path), tmp_path)

    assert info.value.code == NOT_FOUND


@pytest.mark.parametrize("blank", ["", "  \n\t\n"])
def test_a_blank_playbook_is_not_found_with_todays_message(
    tmp_path: Path, blank: str
) -> None:
    """A silently blank brain is worse than a loud failure."""
    path = _skill_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(blank)

    with pytest.raises(ApplicationError) as info:
        read_playbook(path, tmp_path)

    assert info.value.code == NOT_FOUND
    assert info.value.message == f"vendored playbook is empty at {_SOURCE}"
