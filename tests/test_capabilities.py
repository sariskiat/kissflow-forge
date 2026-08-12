"""Offline unit tests for kfforge.capabilities.search_capabilities (#55, forge_capabilities)."""
from __future__ import annotations

from kfforge.capabilities import search_capabilities


def test_empty_query_returns_the_full_index() -> None:
    out = search_capabilities("")
    assert out["isError"] is False
    assert out["count"] > 0
    assert all({"id", "name", "status", "modules"} <= set(entry) for entry in out["index"])
    ids = {entry["id"] for entry in out["index"]}
    assert "field.currency" in ids
    assert "TEMPLATE" not in ids  # the template itself is excluded from search


def test_query_matches_by_id_and_inlines_linked_shapes() -> None:
    out = search_capabilities("field.currency")
    assert out["isError"] is False
    assert out["count"] >= 1
    entry = next(e for e in out["entries"] if e["id"] == "field.currency")
    assert entry["shapes"], "a matched entry's linked shapes must be inlined, not just referenced"
    for rel, content in entry["shapes"].items():
        assert rel.startswith("shapes/")
        assert isinstance(content, dict)


def test_query_matches_case_insensitively_against_body_text() -> None:
    out = search_capabilities("VALIDATION")
    assert out["isError"] is False
    ids = {e["id"] for e in out["entries"]}
    assert "config.validation" in ids


def test_query_with_no_matches_returns_empty_entries_not_an_error() -> None:
    out = search_capabilities("no-such-capability-xyz-000")
    assert out["isError"] is False
    assert out["count"] == 0
    assert out["entries"] == []


def test_index_and_search_never_report_errors_on_the_real_docs_dir() -> None:
    # a real frontmatter-parse or shape-link failure in the checked-in docs dir would land here,
    # never silently — output-invariant audit for the whole capabilities dir.
    out = search_capabilities("")
    assert out["errors"] == []
    out2 = search_capabilities("field")
    assert out2["errors"] == []
