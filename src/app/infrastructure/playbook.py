"""Serve the vendored skills over the MCP: the builder playbook by default, plus the
design and usage skills named in `PLAYBOOKS`.

The skill is the BRAIN a fresh Claude needs to drive this engine; `~/.claude/skills` is a local-dev
convenience that does NOT ship when the MCP server deploys, so a remote user's Claude gets the tools
but not the doctrine. Vendoring the skill at `skills/kissflow-forge-builder/SKILL.md` version-controls
it with the codebase, and this module hands its text back over the wire so the brain travels with the
tools — no local file required.

`read_playbook` is the `DocsReader.playbook` read (spec G13): plain data, and a missing
or blank file raises `ApplicationError(code=NOT_FOUND)`.
"""

from __future__ import annotations

from pathlib import Path

from app.application.exceptions import NOT_FOUND, ApplicationError
from app.domain.value_objects.kinds import PlaybookName
from app.resources import REPO_ROOT, SKILLS_DIR

PLAYBOOK_PATH: Path = SKILLS_DIR / "kissflow-forge-builder" / "SKILL.md"

# One fixed file per closed name. The caller picks a KEY, never a path, so no
# request string is ever joined into a filesystem path.
PLAYBOOKS: dict[PlaybookName, Path] = {
    "builder": PLAYBOOK_PATH,
    "design": SKILLS_DIR / "kissflow-help-design" / "SKILL.md",
    "usage": SKILLS_DIR / "kissflow-forge-mcp" / "SKILL.md",
}


def read_playbook(path: Path = PLAYBOOK_PATH, root: Path = REPO_ROOT) -> dict[str, str]:
    """Read the vendored builder playbook as plain data. OFFLINE, read-only.

    Args:
        path: The playbook file. Defaults to the vendored `SKILL.md`, anchored
            on `app.resources`.
        root: The directory `source` is reported relative to. Defaults to the
            repo root.

    Returns:
        `{"text": <the whole file>, "source": <path relative to root>}`.

    Raises:
        ApplicationError: `code=NOT_FOUND` when the file is missing, or when
            its text is blank -- a stated reason, never a silently blank brain.
    """
    source = str(path.relative_to(root))
    if not path.is_file():
        raise ApplicationError(
            f"vendored playbook not found at {source}", code=NOT_FOUND
        )
    text = path.read_text()
    if not text.strip():
        raise ApplicationError(
            f"vendored playbook is empty at {source}", code=NOT_FOUND
        )
    return {"text": text, "source": source}
