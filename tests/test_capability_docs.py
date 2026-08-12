"""Contract test over docs/capabilities/ — every entry matches the schema
decided on ticket #43 (map #42). TEMPLATE.md is itself a valid entry, so the
template and this validator can never drift apart."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT: Path = Path(__file__).resolve().parent.parent
CAP_DIR: Path = REPO_ROOT / "docs" / "capabilities"

STATUS_ORDER: dict[str, int] = {"inferred": 0, "captured": 1, "proven-live": 2}
MODULE_KEYS: frozenset[str] = frozenset({"process", "board", "dataform"})
MODULE_VALUES: frozenset[str] = frozenset({"yes", "no", "differs", "unknown"})
REQUIRED_DOC_KEYS: frozenset[str] = frozenset(
    {"id", "name", "status", "modules", "ui_path", "shapes", "params"}
)
REQUIRED_PARAM_KEYS: frozenset[str] = frozenset({"name", "type", "required", "status"})
REQUIRED_HEADINGS: tuple[str, ...] = ("## What", "## Where", "## Best practice")
# real-tenant token scanning is NOT duplicated here — test_p0_scaffold's
# blindness scan already sweeps every .md in the repo, including this dir.


def _docs() -> list[Path]:
    return sorted(CAP_DIR.rglob("*.md")) if CAP_DIR.is_dir() else []


def _split(path: Path) -> tuple[dict, str]:
    text = path.read_text()
    assert text.startswith("---\n"), f"{path.name}: no frontmatter"
    _, fm, body = text.split("---\n", 2)
    meta = yaml.safe_load(fm)
    assert isinstance(meta, dict), f"{path.name}: frontmatter is not a mapping"
    return meta, body


def _norm_module(value: object) -> str:
    # bare yes/no in YAML 1.1 parse as booleans — normalize back
    if value is True:
        return "yes"
    if value is False:
        return "no"
    return str(value)


docs = _docs()


def test_template_exists() -> None:
    assert (CAP_DIR / "TEMPLATE.md").is_file()


@pytest.mark.parametrize("path", docs, ids=lambda p: str(p.relative_to(CAP_DIR)))
def test_capability_doc_schema(path: Path) -> None:
    meta, body = _split(path)

    missing = REQUIRED_DOC_KEYS - meta.keys()
    assert not missing, f"missing keys: {sorted(missing)}"

    rel_id = path.relative_to(CAP_DIR).with_suffix("").as_posix()
    assert meta["id"] == rel_id, f"id {meta['id']!r} != path-derived {rel_id!r}"

    assert meta["status"] in STATUS_ORDER, f"bad status {meta['status']!r}"

    modules = meta["modules"]
    assert set(modules) == MODULE_KEYS, f"modules keys must be {sorted(MODULE_KEYS)}"
    norm = {k: _norm_module(v) for k, v in modules.items()}
    for key, value in norm.items():
        assert value in MODULE_VALUES, f"modules.{key}: bad value {value!r}"

    params = meta["params"]
    assert isinstance(params, list), "params must be a list"
    for param in params:
        missing_p = REQUIRED_PARAM_KEYS - param.keys()
        assert not missing_p, f"param {param.get('name')!r} missing {sorted(missing_p)}"
        assert isinstance(param["required"], bool), (
            f"param {param['name']}: required must be bool"
        )
        assert param["status"] in STATUS_ORDER, f"param {param['name']}: bad status"
        for list_key in ("constraints", "depends_on"):
            entries = param.get(list_key, [])
            assert isinstance(entries, list) and all(
                isinstance(entry, str) for entry in entries
            ), f"param {param['name']}: {list_key} must be a list of strings"

    if params:
        weakest = min(
            (param["status"] for param in params), key=STATUS_ORDER.__getitem__
        )
        assert meta["status"] == weakest, (
            f"status {meta['status']!r} must equal weakest param status {weakest!r}"
        )

    shapes = meta["shapes"]
    assert isinstance(shapes, list), "shapes must be a list"
    if meta["status"] != "inferred":
        assert shapes, "non-inferred doc must link at least one shapes/ capture"
    for shape in shapes:
        assert (REPO_ROOT / shape).is_file(), f"shape link does not resolve: {shape}"

    for heading in REQUIRED_HEADINGS:
        assert heading in body, f"missing required heading {heading!r}"
    if "differs" in norm.values():
        assert "## Module diffs" in body, (
            "module marked `differs` needs a Module diffs section"
        )
