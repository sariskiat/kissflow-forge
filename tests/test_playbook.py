"""Offline unit tests for kfforge.playbook.load_playbook (forge_playbook — the vendored brain)."""
from __future__ import annotations

from kfforge.playbook import PLAYBOOK_PATH, load_playbook


def test_vendored_playbook_file_ships_with_the_repo() -> None:
    assert PLAYBOOK_PATH.is_file(), "the builder skill must be vendored in the repo, not only in ~/.claude"


def test_load_playbook_returns_the_full_brain() -> None:
    out = load_playbook()
    assert out["isError"] is False
    assert out["text"].strip(), "playbook text must be non-empty"
    assert out["chars"] > 8000
    # the load-bearing doctrine a fresh MCP-only Claude would otherwise get wrong
    assert "THE RULE" in out["text"]
    assert "Build order" in out["text"]
    # the numbered build-order steps travel with the tools
    assert "Members" in out["text"]
    assert "Publish" in out["text"]
    assert "Simulate" in out["text"]
    assert out["source"].endswith("skills/kissflow-forge-builder/SKILL.md")
