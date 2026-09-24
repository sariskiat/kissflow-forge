"""Tests for the package's single repository data path anchor."""

from pathlib import Path

from app.resources import CAP_DIR, REPO_ROOT, SHAPES_DIR, SKILLS_DIR


def test_resource_directories_are_anchored_at_the_repository_root() -> None:
    assert Path(__file__).resolve().parents[2] == REPO_ROOT
    assert SHAPES_DIR == REPO_ROOT / "shapes"
    assert CAP_DIR == REPO_ROOT / "docs" / "capabilities"
    assert SKILLS_DIR == REPO_ROOT / "skills"
