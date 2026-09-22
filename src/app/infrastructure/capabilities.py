"""Read-only, offline search over docs/capabilities/*.md capability docs + their linked
shapes/*.json captures (#55). No network, no Kissflow credentials.

Parses each doc's YAML frontmatter (schema pinned by tests/test_capability_docs.py — id, name,
status, modules, ui_path, shapes, params) and serves either the full index (empty query) or every
entry matching a query string, with each match's linked shapes/*.json content inlined so a caller
never has to make a second round trip to read the wire shape a doc references.
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


def _docs() -> list[Path]:
    if not CAP_DIR.is_dir():
        return []
    return sorted(p for p in CAP_DIR.rglob("*.md") if p.name != "TEMPLATE.md")


def _matches(meta: dict[str, Any], body: str, query: str) -> bool:
    q = query.lower()
    haystack = (
        " ".join(str(meta.get(k, "")) for k in ("id", "name", "ui_path", "status")) + " " + body
    )
    return q in haystack.lower()


def search_capabilities(query: str = "") -> dict[str, Any]:
    """Empty `query` -> the full index: `{id, name, status, modules}` per doc, cheapest possible
    read for "what's captured at all". Non-empty `query` -> every doc whose id/name/ui_path/
    status/body contains it (case-insensitive substring), each with its parsed frontmatter, body
    text, and every linked `shapes/*.json` file's parsed content inlined — a caller gets the wire
    shape in the SAME call, never a dangling reference it has to chase down separately.

    A doc whose frontmatter fails to parse, or a `shapes` link that does not resolve to a real
    file, lands in `errors` rather than being silently skipped or crashing the whole search —
    the same output-invariant-audit discipline as every other tool in this pack.
    """
    docs = _docs()
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
        return {
            "query": query,
            "count": len(index),
            "index": index,
            "errors": errors,
            "isError": False,
        }

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
            shape_path = REPO_ROOT / rel
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
    return {
        "query": query,
        "count": len(entries),
        "entries": entries,
        "errors": errors,
        "isError": False,
    }
