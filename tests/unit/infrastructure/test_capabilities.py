"""Spec for app.infrastructure.capabilities: the capability-doc search, read as plain
data.

Ports `tests/test_capabilities.py` (5 tests) through the `DocsReader` port with the same
assertions (spec G13). `isError is False` becomes "plain data, no `isError` key", and
`count` becomes the length of `docs` (the use case derives `count`). The checked-in docs
never hit an error branch, so a synthetic tree under `tmp_path` pins each one: bad
frontmatter, a linked shape that does not resolve, a shape that is not JSON. The old
The old `search_capabilities()` payload is removed with the old server in Stage E.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.application.interfaces.docs import DocsReader
from app.infrastructure.capabilities import find_capabilities
from app.infrastructure.docs_reader import DocsReaderAdapter
from app.resources import CAP_DIR, REPO_ROOT

# =====================================================================================
# Ported from tests/test_capabilities.py, through the port, on the checked-in docs.
# =====================================================================================


async def _search(query: str) -> dict[str, Any]:
    reader: DocsReader = DocsReaderAdapter()
    return await reader.capabilities(query)


@pytest.mark.asyncio
async def test_empty_query_returns_the_full_index() -> None:
    out = await _search("")
    assert set(out) == {"docs", "errors"}, "plain data: no isError key"
    assert len(out["docs"]) > 0
    assert all({"id", "name", "status", "modules"} <= set(row) for row in out["docs"])
    ids = {row["id"] for row in out["docs"]}
    assert "field.currency" in ids
    assert "TEMPLATE" not in ids  # the template itself is excluded from search


@pytest.mark.asyncio
async def test_query_matches_by_id_and_inlines_linked_shapes() -> None:
    out = await _search("field.currency")
    assert set(out) == {"docs", "errors"}
    assert len(out["docs"]) >= 1
    entry = next(e for e in out["docs"] if e["id"] == "field.currency")
    assert entry["shapes"], (
        "a matched entry's linked shapes must be inlined, not just referenced"
    )
    for rel, content in entry["shapes"].items():
        assert rel.startswith("shapes/")
        assert isinstance(content, dict)


@pytest.mark.asyncio
async def test_query_matches_case_insensitively_against_body_text() -> None:
    out = await _search("VALIDATION")
    assert set(out) == {"docs", "errors"}
    ids = {e["id"] for e in out["docs"]}
    assert "config.validation" in ids


@pytest.mark.asyncio
async def test_query_with_no_matches_returns_empty_entries_not_an_error() -> None:
    out = await _search("no-such-capability-xyz-000")
    assert set(out) == {"docs", "errors"}
    assert len(out["docs"]) == 0
    assert out["docs"] == []


@pytest.mark.asyncio
async def test_index_and_search_never_report_errors_on_the_real_docs_dir() -> None:
    # a real frontmatter-parse or shape-link failure in the checked-in docs dir would
    # land here, never silently -- output-invariant audit for the whole capabilities
    # dir.
    out = await _search("")
    assert out["errors"] == []
    out2 = await _search("field")
    assert out2["errors"] == []


def test_find_capabilities_defaults_to_the_anchored_docs_dir() -> None:
    """The lookup goes through `app.resources`, the one filesystem anchor."""
    assert find_capabilities("") == find_capabilities("", CAP_DIR, REPO_ROOT)


# =====================================================================================
# The error branches, on a synthetic tree (the checked-in docs never reach them).
# =====================================================================================


def _doc(cap: Path, name: str, text: str) -> None:
    path = cap / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@pytest.fixture
def tree(tmp_path: Path) -> tuple[Path, Path]:
    """`(cap_dir, root)`: four good docs (one nested), three broken ones, a template."""
    cap = tmp_path / "docs" / "capabilities"
    shapes = tmp_path / "shapes"
    shapes.mkdir(parents=True)
    (shapes / "good.json").write_text('{"Kind": "Field"}')
    (shapes / "bad.json").write_text("{not json")
    _doc(
        cap,
        "a_good.md",
        "---\nid: good.one\nname: Good One\nstatus: wire-proven\n"
        "modules: [process]\nui_path: Form > Field\nshapes: [shapes/good.json]\n"
        "params: {x: 1}\n---\nBody text about Widgets.\n",
    )
    _doc(
        cap,
        "b_dangling.md",
        "---\nid: dangling.one\nname: Dangling\nstatus: claimed\n"
        "shapes: [shapes/missing.json, shapes/good.json]\n---\nbody\n",
    )
    _doc(
        cap,
        "c_badjson.md",
        "---\nid: badjson.one\nname: Bad JSON\nstatus: claimed\n"
        "shapes: [shapes/bad.json]\n---\nbody\n",
    )
    _doc(cap, "d_notmapping.md", "---\n- just\n- a list\n---\nbody\n")
    _doc(cap, "e_yamlerror.md", "---\nid: [unclosed\n---\nbody\n")
    _doc(cap, "f_nofrontmatter.md", "no frontmatter at all\n")
    _doc(cap, "TEMPLATE.md", "---\nid: TEMPLATE\n---\nbody\n")
    _doc(
        cap,
        "nested/g_nested.md",
        "---\nid: nested.one\nname: Nested\nstatus: wire-proven\n---\nWidgets too\n",
    )
    return cap, tmp_path


_BROKEN_DOC_ERRORS = (
    "d_notmapping.md: frontmatter is not a mapping",
    "e_yamlerror.md: ",
    "f_nofrontmatter.md: not enough values to unpack (expected 3, got 1)",
)


def _assert_broken_docs_reported(errors: list[str]) -> None:
    tail = errors[-3:]
    assert [e.split(": ", 1)[0] for e in tail] == [
        "d_notmapping.md",
        "e_yamlerror.md",
        "f_nofrontmatter.md",
    ]
    assert tail[0] == _BROKEN_DOC_ERRORS[0]
    assert tail[1].startswith(_BROKEN_DOC_ERRORS[1])
    assert tail[2] == _BROKEN_DOC_ERRORS[2]


def test_the_index_is_one_row_per_parseable_doc_in_sorted_order(
    tree: tuple[Path, Path],
) -> None:
    cap, root = tree

    out = find_capabilities("", cap, root)

    assert out["docs"] == [
        {
            "id": "good.one",
            "name": "Good One",
            "status": "wire-proven",
            "modules": ["process"],
        },
        {
            "id": "dangling.one",
            "name": "Dangling",
            "status": "claimed",
            "modules": None,
        },
        {"id": "badjson.one", "name": "Bad JSON", "status": "claimed", "modules": None},
        {
            "id": "nested.one",
            "name": "Nested",
            "status": "wire-proven",
            "modules": None,
        },
    ]
    assert len(out["errors"]) == 3
    _assert_broken_docs_reported(out["errors"])


def test_a_match_carries_its_full_entry_with_shapes_inlined(
    tree: tuple[Path, Path],
) -> None:
    cap, root = tree

    out = find_capabilities("widgets", cap, root)

    assert out["docs"] == [
        {
            "id": "good.one",
            "name": "Good One",
            "status": "wire-proven",
            "modules": ["process"],
            "ui_path": "Form > Field",
            "params": {"x": 1},
            "body": "Body text about Widgets.",
            "shapes": {"shapes/good.json": {"Kind": "Field"}},
        },
        {
            "id": "nested.one",
            "name": "Nested",
            "status": "wire-proven",
            "modules": None,
            "ui_path": None,
            "params": None,
            "body": "Widgets too",
            "shapes": {},
        },
    ]
    _assert_broken_docs_reported(out["errors"])


def test_a_dangling_shape_link_is_an_error_and_the_other_shapes_still_inline(
    tree: tuple[Path, Path],
) -> None:
    cap, root = tree

    out = find_capabilities("dangling", cap, root)

    assert [e["id"] for e in out["docs"]] == ["dangling.one"]
    assert out["docs"][0]["shapes"] == {"shapes/good.json": {"Kind": "Field"}}
    assert out["errors"][0] == (
        "dangling.one: linked shape does not resolve: shapes/missing.json"
    )
    _assert_broken_docs_reported(out["errors"])


def test_a_shape_that_is_not_json_is_an_error_not_a_crash(
    tree: tuple[Path, Path],
) -> None:
    cap, root = tree

    out = find_capabilities("bad json", cap, root)

    assert [e["id"] for e in out["docs"]] == ["badjson.one"]
    assert out["docs"][0]["shapes"] == {}
    assert out["errors"][0].startswith(
        "badjson.one: shape shapes/bad.json is not valid JSON: "
    )


def test_the_match_reads_id_name_ui_path_status_and_body_only(
    tree: tuple[Path, Path],
) -> None:
    """`modules` and `params` are not searched: a value only they hold never matches."""
    cap, root = tree

    assert find_capabilities("process", cap, root)["docs"] == []
    assert [e["id"] for e in find_capabilities("FORM > FIELD", cap, root)["docs"]] == [
        "good.one"
    ]
    assert [e["id"] for e in find_capabilities("CLAIMED", cap, root)["docs"]] == [
        "dangling.one",
        "badjson.one",
    ]


def test_a_missing_docs_dir_is_an_empty_index_not_an_error(tmp_path: Path) -> None:
    assert find_capabilities("", tmp_path / "nowhere", tmp_path) == {
        "docs": [],
        "errors": [],
    }
