"""Every tool a served skill names must exist on the MCP surface.

`forge_playbook` hands these files to a remote Claude that has no repo. A
skill that names a renamed or removed tool sends that Claude to a call that
cannot succeed, so a rename must fail here, not in a user's session. The
surface is the snapshot that `tests/test_tool_surface_snapshot.py` keeps equal
to the live server.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.domain.value_objects.kinds import PlaybookName
from app.infrastructure.playbook import PLAYBOOKS

REPO_ROOT: Path = Path(__file__).resolve().parent.parent
SURFACE: Path = REPO_ROOT / "tests" / "fixtures" / "tool_surface.json"
TOOL_TOKEN = re.compile(r"\b(?:forge|kf)_[a-z_]+\b")


def _surface_tool_names() -> set[str]:
    data = json.loads(SURFACE.read_text())
    return set(data.get("tools", data))


@pytest.mark.parametrize("skill", sorted(PLAYBOOKS))
def test_a_served_skill_names_only_tools_on_the_surface(skill: PlaybookName) -> None:
    text = PLAYBOOKS[skill].read_text()
    named = set(TOOL_TOKEN.findall(text))

    assert named, f"{skill}: expected the skill to name at least one tool"
    assert named <= _surface_tool_names(), sorted(named - _surface_tool_names())
