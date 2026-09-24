"""The single filesystem anchor for the repo-root data directories.

`shapes/`, `docs/capabilities/`, and `skills/` are runtime data the engine reads by path, and
they stay at the repo root rather than moving inside the package: `docs/capabilities/*.md`
cross-references its captures as repo-relative `shapes/...` strings, and
`infrastructure/capabilities.py` resolves those strings against `REPO_ROOT` — moving the
directory would invalidate every one of them, and the contract tests that assert the prefix.

Before the src/ layout four modules each climbed `Path(__file__).parent.parent` on their own,
so each one silently encoded its own depth in the tree. They all read this module instead now:
one place to be right, one place to fix.

This module sits at the package root, outside domain/application/infrastructure, so importing
it does not cross a layer boundary (see the `[tool.importlinter]` contracts in pyproject.toml,
which govern the three layers only). It computes paths and does no I/O.

ponytail: parents[2] assumes the package is imported from the source tree (`src/app/...`),
which is what an editable install and the container both do. A non-editable install into
site-packages would land REPO_ROOT somewhere useless; the upgrade path is to ship the three
directories as package data and anchor on `__file__` directly.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT: Path = Path(__file__).resolve().parents[2]
SHAPES_DIR: Path = REPO_ROOT / "shapes"
CAP_DIR: Path = REPO_ROOT / "docs" / "capabilities"
SKILLS_DIR: Path = REPO_ROOT / "skills"
