"""scripts/deidentify_template.py: scrub people, keep field ids and platform words."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "deidentify_template",
    Path(__file__).resolve().parents[3] / "scripts" / "deidentify_template.py",
)
assert _SPEC and _SPEC.loader
deid = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(deid)

RAW = {
    "Root": "Real_Flow",
    "PublishedAt": "2026-08-07T04:35:51Z",
    "_meta_version": "1",
    "Real_Flow": {
        "Id": "Real_Flow",
        "Kind": "Model",
        "Name": "Real Flow Name",
        "Model::Field": ["requestor"],
        "RootProcessDef": "ProcessDef_abc",
    },
    "requestor": {
        "Id": "requestor",
        "Kind": "Field",
        "Name": "Requestor",
        "Model": "Real_Flow",
    },
    "ProcessDef_abc": {
        "Id": "ProcessDef_abc",
        "Kind": "ProcessDef",
        "Model": "Real_Flow",
    },
    "SendBackToInitiator": {
        "Id": "SendBackToInitiator",
        "Kind": "Activity",
        "NodeType": "SendBackToInitiator",
    },
    "Expression_x": {
        "Id": "Expression_x",
        "Kind": "Expression",
        "ExpressionStr": "if(_is_public_form, requestor.Name, "
        '"someone.real@corp.example")',
        "Help": "see https://host/view/process/Real_Flow/x",
    },
    "PublishedBy": {"Kind": "User", "Name": "Real Person", "_id": "UsRealId01"},
}


def test_scrubs_people_and_flow_but_keeps_fields_and_platform_words() -> None:
    shape = deid.deidentify(RAW)
    t = shape["template"]

    for secret in (
        "Real_Flow",
        "Real Flow Name",
        "Real Person",
        "UsRealId01",
        "someone.real@corp.example",
        "PublishedAt",
    ):
        assert secret not in json.dumps(t, ensure_ascii=False), secret
    assert t["Model_Sample01"]["Name"] == "Template Process"
    assert t["User_Sample01"] == {
        "Kind": "User",
        "Name": "Sample Publisher",
        "_id": "User_Sample01",
    }
    # field id and system field kept verbatim; the formula still reads them
    assert t["requestor"]["Model"] == "Model_Sample01"
    expr = next(v for v in t.values() if v["Kind"] == "Expression")
    assert expr["ExpressionStr"].startswith("if(_is_public_form, requestor.Name,")
    assert "sample.user@example.com" in expr["ExpressionStr"]
    assert "Template_Flow_Sample" in expr["Help"]
    # the platform-reserved activity keeps its key AND its NodeType word; a random id
    # is minted
    assert t["SendBackToInitiator"]["NodeType"] == "SendBackToInitiator"
    assert "ProcessDef_Sample01" in t
    assert "Root" not in t and "PublishedAt" not in json.dumps(t)


def test_rerun_is_byte_identical() -> None:
    a = json.dumps(deid.deidentify(RAW), ensure_ascii=False, indent=2)
    b = json.dumps(deid.deidentify(RAW), ensure_ascii=False, indent=2)
    assert a == b
