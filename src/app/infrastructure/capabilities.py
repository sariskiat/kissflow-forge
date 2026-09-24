"""Read-only, offline search over docs/capabilities/*.md capability docs + their linked
shapes/*.json captures (#55). No network, no Kissflow credentials.

Parses each doc's YAML frontmatter (schema pinned by tests/test_capability_docs.py — id, name,
status, modules, ui_path, shapes, params) and serves either the full index (empty query) or every
entry matching a query string, with each match's linked shapes/*.json content inlined so a caller
never has to make a second round trip to read the wire shape a doc references.

`find_capabilities` is the `DocsReader.capabilities` read (spec G13): plain data, always under
one `docs` key, whichever shape the query picked.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from app.resources import CAP_DIR, REPO_ROOT


def _load(path: Path) -> tuple[dict[str, Any], str]:
    text = path.read_text()
    _, fm, body = text.split("---\n", 2)
    meta = yaml.safe_load(fm)
    if not isinstance(meta, dict):
        raise ValueError("frontmatter is not a mapping")
    return meta, body


def _docs(cap_dir: Path) -> list[Path]:
    if not cap_dir.is_dir():
        return []
    return sorted(p for p in cap_dir.rglob("*.md") if p.name != "TEMPLATE.md")


def _matches(meta: dict[str, Any], body: str, query: str) -> bool:
    q = query.lower()
    haystack = (
        " ".join(str(meta.get(k, "")) for k in ("id", "name", "ui_path", "status"))
        + " "
        + body
    )
    return q in haystack.lower()


def find_capabilities(
    query: str = "", cap_dir: Path = CAP_DIR, root: Path = REPO_ROOT
) -> dict[str, Any]:
    """Search the capability-doc index, as plain data. OFFLINE, read-only.

    Empty `query` -> the full index: `{id, name, status, modules}` per doc, cheapest
    possible read for "what's captured at all". Non-empty `query` -> every doc whose
    id/name/ui_path/status/body contains it (case-insensitive substring), each with its
    parsed frontmatter, body text, and every linked `shapes/*.json` file's parsed content
    inlined — a caller gets the wire shape in the SAME call, never a dangling reference it
    has to chase down separately.

    A doc whose frontmatter fails to parse, or a `shapes` link that does not resolve to a
    real file, lands in `errors` rather than being silently skipped or crashing the whole
    search — the same output-invariant-audit discipline as every other tool in this pack.

    Args:
        query: Empty for the full index; non-empty to match against a doc's
            id/name/ui_path/status/body (case-insensitive substring).
        cap_dir: The directory of `*.md` capability docs. Defaults to the
            vendored `docs/capabilities/`, anchored on `app.resources`.
        root: The directory every linked `shapes/*.json` path resolves
            against. Defaults to the repo root.

    Returns:
        `{"docs": [...], "errors": [...]}`. For an empty `query`, one index
        row per doc: `id`, `name`, `status`, `modules`. For a non-empty
        `query`, one full entry per matching doc: those four, then
        `ui_path`, `params`, `body`, and `shapes` (each linked
        `shapes/*.json` parsed inline, keyed by its repo-relative path).
        `errors` names every doc whose frontmatter failed to parse and
        every linked shape that does not resolve or is not valid JSON.
    """
    docs = _docs(cap_dir)
    errors: list[str] = []

    if not query:
        index: list[dict[str, Any]] = []
        for path in docs:
            try:
                meta, _ = _load(path)
            except (ValueError, yaml.YAMLError) as e:
                errors.append(f"{path.name}: {e}")
                continue
            index.append(
                {
                    "id": meta.get("id"),
                    "name": meta.get("name"),
                    "status": meta.get("status"),
                    "modules": meta.get("modules"),
                }
            )
        return {"docs": index, "errors": errors}

    entries: list[dict[str, Any]] = []
    for path in docs:
        try:
            meta, body = _load(path)
        except (ValueError, yaml.YAMLError) as e:
            errors.append(f"{path.name}: {e}")
            continue
        if not _matches(meta, body, query):
            continue
        shapes: dict[str, Any] = {}
        for rel in meta.get("shapes") or []:
            shape_path = root / rel
            if not shape_path.is_file():
                errors.append(f"{meta.get('id')}: linked shape does not resolve: {rel}")
                continue
            try:
                shapes[rel] = json.loads(shape_path.read_text())
            except json.JSONDecodeError as e:
                errors.append(f"{meta.get('id')}: shape {rel} is not valid JSON: {e}")
        entries.append(
            {
                "id": meta.get("id"),
                "name": meta.get("name"),
                "status": meta.get("status"),
                "modules": meta.get("modules"),
                "ui_path": meta.get("ui_path"),
                "params": meta.get("params"),
                "body": body.strip(),
                "shapes": shapes,
            }
        )
    return {"docs": entries, "errors": errors}
