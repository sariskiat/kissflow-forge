"""Unit tests for app.domain.value_objects.expression.expression_owner.

Moved verbatim from test_expr.py (G9b) -- the one piece of that module that
takes no draft and so was never a FlowDraft method candidate.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.domain.value_objects.expression import expression_owner

# ---- expression_owner
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "node,expected",
    [
        (
            {"Id": "Expression_SBranch01", "ProcessDef": "ProcessDef_SSample01"},
            "branch",
        ),
        ({"Id": "Expression_SGoto01", "Activity": "Activity_SSample01"}, "goto"),
        ({"Id": "Expression_SProp01", "Property": "Property_SSample01"}, "property"),
    ],
)
def test_expression_owner_classifies_by_owner_key(
    node: dict[str, Any], expected: str
) -> None:
    assert expression_owner(node) == expected


def test_expression_owner_raises_when_no_owner_key_present() -> None:
    with pytest.raises(ValueError):
        expression_owner({"Id": "Expression_SOrphan01", "ExpressionStr": "sample"})


def test_expression_owner_raises_when_owner_keys_are_ambiguous() -> None:
    with pytest.raises(ValueError):
        expression_owner(
            {
                "Id": "Expression_SAmbig01",
                "ProcessDef": "ProcessDef_SSample01",
                "Activity": "Activity_SSample01",
            }
        )


def test_expression_owner_ambiguous_message_reads_as_one_sentence() -> None:
    # G9 review: the E501 reflow dropped the space after "among", gluing it to
    # "ProcessDef/Activity/Property".
    with pytest.raises(ValueError) as exc_info:
        expression_owner(
            {
                "Id": "Expression_SAmbig01",
                "ProcessDef": "ProcessDef_SSample01",
                "Activity": "Activity_SSample01",
            }
        )

    assert "owner key(s) among ProcessDef/Activity/Property" in str(exc_info.value)
