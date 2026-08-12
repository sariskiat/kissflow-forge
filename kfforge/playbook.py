"""Serve the vendored builder playbook (the kissflow-forge-builder skill) over the MCP.

The skill is the BRAIN a fresh Claude needs to drive this engine; `~/.claude/skills` is a local-dev
convenience that does NOT ship when the MCP server deploys, so a remote user's Claude gets the tools
but not the doctrine. Vendoring the skill at `skills/kissflow-forge-builder/SKILL.md` version-controls
it with the codebase, and this module hands its text back over the wire so the brain travels with the
tools — no local file required.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

REPO_ROOT: Path = Path(__file__).resolve().parent.parent
PLAYBOOK_PATH: Path = REPO_ROOT / "skills" / "kissflow-forge-builder" / "SKILL.md"


def load_playbook() -> dict[str, Any]:
    """Return the vendored builder playbook's full text. OFFLINE, read-only, no credentials.

    `text` carries the whole skill (THE RULE, the numbered build order, the intent->tool map, the
    refuse table, the copilot fallback). A missing/empty vendored file lands in `isError: True` with a
    stated reason rather than returning a silently blank brain — the same fail-loud discipline as every
    other tool in this pack.
    """
    if not PLAYBOOK_PATH.is_file():
        return {"isError": True, "text": "",
                "error": f"vendored playbook not found at {PLAYBOOK_PATH.relative_to(REPO_ROOT)}"}
    text = PLAYBOOK_PATH.read_text()
    if not text.strip():
        return {"isError": True, "text": "",
                "error": f"vendored playbook is empty at {PLAYBOOK_PATH.relative_to(REPO_ROOT)}"}
    return {"isError": False, "text": text, "chars": len(text),
            "source": str(PLAYBOOK_PATH.relative_to(REPO_ROOT))}
