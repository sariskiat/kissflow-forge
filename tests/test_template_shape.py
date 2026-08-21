"""Contract tests for shapes/process_template_full.json — the Deidentified Template Shape.

The full-fidelity vendored capture of the production process template (issue #11, spec #10):
ALL 277 nodes survive — Condition/Criteria (conditional visibility), Field-owned Expression
(computed formulas), QueryDefinition, workflow — deidentified and re-minted by the eval
harness's spikes/deidentify_template_full.py (that repo; the raw capture never enters this
one). These tests pin the node inventory to the capture's and prove zero personal identity
tokens, pattern-enforced — never eyeballed. The generic envelope/mint/backref contract comes
free from tests/test_shapes.py; only the shape-specific inventory lives here.
"""
from __future__ import annotations

import collections
import json
import pathlib
import re

SHAPE_PATH = pathlib.Path(__file__).parent.parent / "shapes" / "process_template_full.json"

# The capture's exact per-Kind census. A recapture that changes ANY of these numbers must
# change this table in the same commit — the point is that drift is loud, never silent.
EXPECTED_KINDS: dict[str, int] = {
    "Node": 104, "Column": 40, "Row": 29, "Field": 28, "Condition": 19, "Expression": 16,
    "Criteria": 16, "Activity": 5, "QueryDefinition": 5, "Appearance": 4, "Style": 4,
    "Model": 1, "ProcessDef": 1, "User": 1, "Permission": 1, "Component": 1, "Property": 1,
    "Resource": 1,
}

EXPECTED_FIELD_TYPES: dict[str, int] = {
    "Text": 20, "User": 3, "Reference": 2, "Number": 1, "Boolean": 1, "Textarea": 1,
}

# The capture's exact edge census: total elements per "::"-list key, summed over all nodes. Kind
# counts alone let a fully unwired shape pass (every node present, no node connected) — the wiring
# IS the value of this shape, so it gets pinned as hard as the node census.
EXPECTED_EDGES: dict[str, int] = {
    "Model::Row": 5, "Model::Field": 28, "Model::ProcessDef": 1, "Model::Component": 1,
    "Button::Row": 1, "Row::Column": 39, "Column::Row": 23, "Column::Field": 28,
    "Column::Permission": 1, "Column::Appearance": 4, "ColumnVisibility::Criteria": 9,
    "ProcessDef::Activity": 4, "Activity::Permission": 1, "Activity::Resource": 1,
    "Initiator::Column": 1, "Field::Expression": 16, "Field::Node": 24,
    "Field::QueryDefinition": 5, "Field::Component": 1, "Field::Resource": 1,
    "LHSOwnField::Condition": 10, "RHSField::Condition": 4, "Expression::Node": 16,
    "Node::Node": 88, "Criteria::Condition": 19, "FieldValidation::Criteria": 4,
    "Permission::Criteria": 1, "QueryDefinition::Criteria": 2, "Component::Property": 1,
    "Appearance::Style": 4,
}

# Scalar ref keys (single-id values) that must resolve inside the template, modulo a leading
# underscore. The only permitted exceptions: Kissflow's own system-field refs on AST nodes, and
# ComponentId's cross-graph widget-definition ref (resolves to no node in the source draft either
# — see the shape's notes).
SCALAR_REF_KEYS = {
    "Model", "Column", "Row", "ProcessDef", "Button", "Initiator", "Appearance",
    "RootProcessDef", "Node", "Field", "Criteria", "Expression", "FieldModel", "LHSOwnField",
    "ColumnVisibility", "FieldValidation", "RHSField", "Activity", "QueryDefinition", "Root",
    "Permission", "Component", "Resource", "Style", "BaseMetadata",
}
ALLOWED_SYSTEM_FIELD_REFS = {"_created_by", "_submitted_at"}

# Every email-like token the shape may carry: the deidentification placeholder, and the
# fragment an email regex extracts from the template's own company-domain validation rule
# (RHSValue "^[a-z.]+@cjexpress.co.th$" — functional validation, not a person).
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
ALLOWED_EMAIL_TOKENS = {"sample.user@example.com", "+@cjexpress.co.th"}

# Kissflow user ids look like Us + 10 alphanumerics (e.g. the capture's publisher id).
USER_ID_RE = re.compile(r"\bUs[A-Za-z0-9]{10}\b")


def _template() -> dict:
    return json.loads(SHAPE_PATH.read_text(encoding="utf-8"))["template"]


def test_shape_exists() -> None:
    assert SHAPE_PATH.is_file(), (
        "shapes/process_template_full.json missing — regenerate with the eval harness's "
        "spikes/deidentify_template_full.py and copy the output here"
    )


def test_node_inventory_matches_capture() -> None:
    census = collections.Counter(node["Kind"] for node in _template().values())
    assert dict(census) == EXPECTED_KINDS
    assert sum(census.values()) == 277


def test_field_type_inventory() -> None:
    fields = [n for n in _template().values() if n["Kind"] == "Field"]
    assert len(fields) == 28
    assert dict(collections.Counter(f["Type"] for f in fields)) == EXPECTED_FIELD_TYPES


def test_all_expressions_are_field_owned() -> None:
    exprs = [n for n in _template().values() if n["Kind"] == "Expression"]
    assert len(exprs) == 16
    unowned = [n["Id"] for n in exprs if not n.get("Field")]
    assert not unowned, f"Expression nodes without a Field owner: {unowned}"


def test_user_and_reference_fields_keep_querydefinition_siblings() -> None:
    # ADR-0006: User fields keep their QueryDefinition siblings; Reference fields kept. The type
    # census alone would still pass with every Field::QueryDefinition link deleted.
    fields = {k: n for k, n in _template().items() if n["Kind"] == "Field"}
    linked_types = sorted(n["Type"] for n in fields.values() if n.get("Field::QueryDefinition"))
    assert linked_types == ["Reference", "Reference", "User", "User", "User"]


def test_edge_census_matches_capture() -> None:
    census: collections.Counter[str] = collections.Counter()
    for node in _template().values():
        for key, val in node.items():
            if "::" in key and isinstance(val, list):
                census[key] += len(val)
    assert dict(census) == EXPECTED_EDGES


def test_scalar_refs_resolve_within_template() -> None:
    template = _template()
    dangling = []
    for node_id, node in template.items():
        for key, val in node.items():
            if key not in SCALAR_REF_KEYS or not isinstance(val, str):
                continue
            bare = val.removeprefix("_") if val.startswith("_") else val
            if bare in template or val in ALLOWED_SYSTEM_FIELD_REFS:
                continue
            dangling.append(f"{node_id}.{key} -> {val!r}")
    assert not dangling, "dangling scalar ref(s):\n" + "\n".join(dangling)


def test_workflow_kept_verbatim_including_duplicate_step() -> None:
    template = _template()
    activities = {k: n for k, n in template.items() if n["Kind"] == "Activity"}
    assert len(activities) == 5
    # the source's quirk — two activities both named "Manager Approve" — ships verbatim
    names = collections.Counter(a.get("Name") for a in activities.values())
    assert names["Manager Approve"] == 2
    # the other verbatim quirk: ProcessDef::Activity lists only 4 of the 5 — the orphan is the
    # SendBackToInitiator system activity, dangling out of the workflow in the source itself
    process_defs = [n for n in template.values() if n["Kind"] == "ProcessDef"]
    assert len(process_defs) == 1
    wired = set(process_defs[0]["ProcessDef::Activity"])
    (orphan,) = set(activities) - wired
    assert activities[orphan].get("NodeType") == "SendBackToInitiator"


def test_zero_personal_identity_tokens() -> None:
    text = SHAPE_PATH.read_text(encoding="utf-8")
    stray_emails = set(EMAIL_RE.findall(text)) - ALLOWED_EMAIL_TOKENS
    assert not stray_emails, f"personal email token(s) leaked into the vendored shape: {stray_emails}"
    stray_user_ids = set(USER_ID_RE.findall(text))
    assert not stray_user_ids, f"Kissflow user id(s) leaked into the vendored shape: {stray_user_ids}"


def test_publisher_record_is_fully_scrubbed() -> None:
    # Pattern scans alone would pass a real person's NAME (no email/user-id shape). Pin the one
    # node that carried identity in the capture to its exact scrubbed form, and prove the email
    # placeholder actually landed — a silently skipped scrub step must fail here, not pass.
    template = _template()
    users = {k: n for k, n in template.items() if n["Kind"] == "User"}
    assert users == {
        "User_Sample01": {"_id": "User_Sample01", "Name": "Sample Publisher", "Kind": "User"}
    }
    # count inside the template only — the envelope notes name the placeholder once more
    template_text = json.dumps(template, ensure_ascii=False)
    assert template_text.count("sample.user@example.com") == 2  # one ExpressionStr, one AST Value
