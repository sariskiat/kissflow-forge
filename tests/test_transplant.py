"""Seam 1 of spec #10 (ticket #12): the pure Template Transplant op (ADR-0006).

Deidentified Template Shape in, dev-ready graph out — no network. All tests
assert on the OUTPUT graph only, in the style of the existing graph-op tests.
"""

import copy
import json
import pathlib
import re
from collections import Counter
from typing import Any

from app.domain.entities.flow_draft import FlowDraft

SHAPE = pathlib.Path(__file__).parent.parent / "shapes" / "process_template_full.json"
ROLE_ID = "Ro_dev_role_1"
ROLE_NAME = "Template Demo Role"

_SAMPLE_TOKEN = re.compile(r"[A-Za-z]+_Sample\d+")


def _bare_process() -> dict:
    return {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "P", "FlowType": "Process"},
    }


def _template() -> dict[str, dict]:
    return json.loads(SHAPE.read_text(encoding="utf-8"))["template"]


def _force_ids(template: dict[str, dict]) -> dict[str, str]:
    # Deterministic id-mapping source: every source id gets a known new id.
    # The new id must NOT contain the source id, or the no-survivor scan
    # would flag the mapping itself.
    # Field ids and platform-reserved keys are the exception: the transplant keeps
    # them verbatim, so the mapping source maps each one to itself.
    verbatim = _field_ids(template)
    return {
        old: old if old in verbatim else f"{old.split('_')[0]}_X{i:03d}"
        for i, old in enumerate(sorted(template))
    }


def _field_ids(template: dict[str, dict]) -> set[str]:
    """Ids the transplant keeps verbatim: fields, and reserved keys that are not
    `<Kind>_...` (the "SendBackToInitiator" activity)."""
    return {
        k
        for k, v in template.items()
        if v.get("Kind") == "Field" or not k.startswith(f"{v.get('Kind')}_")
    }


def _transplanted() -> tuple[dict, dict[str, str]]:
    idmap = _force_ids(_template())
    out = (
        FlowDraft.from_wire(_bare_process())
        .transplant_template(app_role=(ROLE_ID, ROLE_NAME), force_ids=idmap)
        .to_wire()
    )
    return out, idmap


def _leaf_strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _leaf_strings(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _leaf_strings(item)


def test_input_not_mutated() -> None:
    draft = _bare_process()
    before = copy.deepcopy(draft)
    _ = FlowDraft.from_wire(draft).transplant_template(app_role=(ROLE_ID, ROLE_NAME))
    assert draft == before, "transplant_template must not mutate its input"


def test_no_source_id_survives_anywhere() -> None:
    out, _ = _transplanted()
    template = _template()
    fields = _field_ids(template)
    survivors = (set(out) & set(template)) - fields
    assert not survivors, f"source ids survived as node keys: {survivors}"
    assert fields <= set(out), (
        f"field ids must survive verbatim: missing {sorted(fields - set(out))}"
    )
    leaked = {
        tok
        for v in out.values()
        for s in _leaf_strings(v)
        for tok in _SAMPLE_TOKEN.findall(s)
    }
    assert not leaked, f"source id tokens leaked inside node values: {leaked}"


def test_per_kind_counts_reconcile_in_coded_audit() -> None:
    # Output-invariant audit: every output node lands in exactly one counted
    # bucket — target-model | from-template (per Kind) | synthesized-chain.
    out, _ = _transplanted()
    template = _template()
    model_id = out["Root"]

    src_counts = Counter(
        v.get("Kind") for v in template.values() if v.get("Kind") != "Model"
    )
    buckets: Counter[str] = Counter()
    for node_id, node in out.items():
        if node_id == "Root":
            continue
        if node_id == model_id:
            buckets["target-model"] += 1
        else:
            buckets[node["Kind"]] += 1

    assert buckets.pop("target-model") == 1
    synthesized = Counter({"Appearance": 1, "Style": 1})
    assert buckets == src_counts + synthesized, (
        f"per-Kind counts do not reconcile: got {buckets}, "
        f"want capture {src_counts} + synthesized {synthesized}"
    )


def test_assignee_resource_repointed_at_dev_app_role() -> None:
    out, _ = _transplanted()
    resources = [
        v for v in out.values() if isinstance(v, dict) and v.get("Kind") == "Resource"
    ]
    assert resources, "no Resource node in output"
    for res in resources:
        assert res["ValueType"] == "AppRole", (
            f"Resource {res['Id']} not re-pointed: {res['ValueType']}"
        )
        assert res["Value"] == ROLE_ID
    active = [
        v
        for v in out.values()
        if isinstance(v, dict)
        and v.get("Kind") == "Activity"
        and v.get("NodeType") == "UserTask"
        and not v.get("IsSuspended")
    ]
    for act in active:
        res_ids = act.get("Activity::Resource") or []
        assert any(out[r]["Value"] == ROLE_ID for r in res_ids), (
            f"active step {act.get('Name')!r} has no Resource pointing at the dev role"
        )


def test_user_fields_keep_querydefinition_siblings_and_reference_fields_kept() -> None:
    out, _ = _transplanted()
    fields = [
        v for v in out.values() if isinstance(v, dict) and v.get("Kind") == "Field"
    ]
    user_fields = [f for f in fields if f.get("Type") == "User"]
    ref_fields = [f for f in fields if f.get("Type") == "Reference"]
    assert len(user_fields) == 3, "the capture's 3 User fields must survive"
    assert len(ref_fields) == 2, "the capture's 2 Reference fields must survive"
    for f in user_fields:
        qids = f.get("Field::QueryDefinition") or []
        assert qids, f"User field {f.get('Name')!r} lost its QueryDefinition sibling"
        for qid in qids:
            assert out[qid]["Kind"] == "QueryDefinition"
            assert out[qid]["Field"] == f["Id"], "QueryDefinition back-reference broken"


def test_condition_criteria_expression_subtrees_verbatim_modulo_idmap() -> None:
    out, idmap = _transplanted()
    template = _template()

    model_id = out["Root"]

    def remap(value: Any) -> Any:
        if isinstance(value, str):
            if value == "Model_Sample01":
                # the template's root Model maps to the TARGET model, never a phantom
                # (checked before idmap: _force_ids covers every template key, root included)
                return model_id
            if value in idmap:
                return idmap[value]
            return _SAMPLE_TOKEN.sub(lambda m: idmap.get(m.group(0), m.group(0)), value)
        if isinstance(value, list):
            return [remap(x) for x in value]
        if isinstance(value, dict):
            return {k: remap(x) for k, x in value.items()}
        return value

    kinds = ("Condition", "Criteria", "Expression", "Node")
    for old_id, node in template.items():
        if node.get("Kind") not in kinds:
            continue
        expected = remap(copy.deepcopy(node))
        expected["Id"] = idmap[old_id]
        assert out[idmap[old_id]] == expected, (
            f"{node['Kind']} {old_id} not carried verbatim"
        )


def test_expression_backrefs_bidirectional() -> None:
    out, _ = _transplanted()
    for node in out.values():
        if not isinstance(node, dict):
            continue
        if node.get("Kind") == "Expression":
            owner = out[node["Field"]]
            assert node["Id"] in (owner.get("Field::Expression") or []), (
                f"Field {node['Field']} does not point back at Expression {node['Id']}"
            )
            for nid in node.get("Expression::Node") or []:
                assert out[nid]["Kind"] == "Node"
        if node.get("Kind") == "Condition":
            crit = out[node["Criteria"]]
            assert node["Id"] in (crit.get("Criteria::Condition") or []), (
                f"Criteria {node['Criteria']} does not point back at Condition {node['Id']}"
            )


def test_mandatory_style_chain_synthesized_on_root_model() -> None:
    # CLAUDE.md Node-graph invariants: the capture LACKS the root chain on
    # purpose (shape note[4]); the transplant must synthesize it or the form
    # will not render. Each Appearance owns exactly one Style.
    out, _ = _transplanted()
    model = out[out["Root"]]
    root_apps = model.get("Model::Appearance") or []
    assert root_apps, "Model::Appearance missing — form will not render"
    for aid in root_apps:
        app = out[aid]
        assert app["Kind"] == "Appearance" and app["Model"] == model["Id"]
        styles = app.get("Appearance::Style") or []
        assert len(styles) == 1, "each Appearance must own exactly one Style"
        assert out[styles[0]]["Kind"] == "Style"
        assert out[styles[0]]["Appearance"] == aid
    apps = [
        v for v in out.values() if isinstance(v, dict) and v.get("Kind") == "Appearance"
    ]
    styles = [
        v for v in out.values() if isinstance(v, dict) and v.get("Kind") == "Style"
    ]
    assert len(apps) == len(styles), (
        "Appearance count != Style count — the broken-render tell"
    )
    for app in apps:
        assert len(app.get("Appearance::Style") or []) == 1


def test_source_quirks_kept_verbatim() -> None:
    out, _ = _transplanted()
    acts = [
        v for v in out.values() if isinstance(v, dict) and v.get("Kind") == "Activity"
    ]
    approves = [a for a in acts if a.get("Name") == "Manager Approve"]
    assert len(approves) == 2, (
        "the duplicate 'Manager Approve' step must survive verbatim"
    )
    assert sum(1 for a in approves if a.get("IsSuspended")) == 1
    sendback = [a for a in acts if a.get("NodeType") == "SendBackToInitiator"]
    assert len(sendback) == 1
    pd = next(
        v for v in out.values() if isinstance(v, dict) and v.get("Kind") == "ProcessDef"
    )
    dangling = {a["Id"] for a in acts} - set(pd.get("ProcessDef::Activity") or [])
    assert sendback[0]["Id"] in dangling, (
        "orphaned SendBackToInitiator quirk must stay dangling"
    )


def test_user_audit_node_keeps_underscore_id_shape() -> None:
    out, _ = _transplanted()
    user = next(
        v for v in out.values() if isinstance(v, dict) and v.get("Kind") == "User"
    )
    assert "Id" not in user, "transplant must not add an 'Id' key the capture never had"
    assert user["_id"] not in _template(), "User node '_id' must be remapped"


def test_deterministic_given_id_mapping_source_and_fresh_ids_otherwise() -> None:
    out_a, _ = _transplanted()
    out_b, _ = _transplanted()
    assert out_a == out_b, "same id-mapping source must produce the identical graph"

    r1 = FlowDraft.from_wire(_bare_process()).transplant_template(
        app_role=(ROLE_ID, ROLE_NAME)
    )
    r2 = FlowDraft.from_wire(_bare_process()).transplant_template(
        app_role=(ROLE_ID, ROLE_NAME)
    )
    fields = _field_ids(_template())
    overlap = (set(r1.nodes) & set(r2.nodes)) - {"Root", "M1"} - fields
    assert not overlap, f"two transplants minted colliding ids: {overlap}"
    assert fields <= set(r1.nodes) and fields <= set(r2.nodes), (
        "both transplants keep the template's own field ids"
    )


def test_every_scalar_ref_resolves_in_output() -> None:
    # Same contract test_template_shape.py runs on the vendored shape, ported onto
    # the OUTPUT graph: doctor's dangling check only walks "::"-list keys, so a
    # phantom scalar ref (e.g. Node.FieldModel at a never-created Model id) is
    # invisible to it — this test is the net.
    from test_template_shape import ALLOWED_SYSTEM_FIELD_REFS, SCALAR_REF_KEYS

    out, _ = _transplanted()
    dangling = []
    for node_id, node in out.items():
        if not isinstance(node, dict):
            continue
        for key, val in node.items():
            if key not in SCALAR_REF_KEYS or not isinstance(val, str):
                continue
            bare = val.removeprefix("_") if val.startswith("_") else val
            if bare in out or val in ALLOWED_SYSTEM_FIELD_REFS:
                continue
            dangling.append(f"{node_id}.{key} -> {val!r}")
    assert not dangling, "dangling scalar ref(s) in output:\n" + "\n".join(dangling)


def test_edge_census_reconciles_with_capture() -> None:
    # Kind counts alone let a fully unwired graph pass (test_template_shape.py's
    # own warning). Output edges = capture edges, minus the flattened dynamic
    # assignee's Field::Resource link, plus the synthesized root style chain.
    from test_template_shape import EXPECTED_EDGES

    out, _ = _transplanted()
    census: Counter[str] = Counter()
    for node in out.values():
        if not isinstance(node, dict):
            continue
        for key, val in node.items():
            if "::" in key and isinstance(val, list):
                census[key] += len(val)
    expected = dict(EXPECTED_EDGES)
    expected.pop("Field::Resource")
    expected["Model::Appearance"] = 1
    expected["Appearance::Style"] += 1
    assert dict(census) == expected


def test_repointed_resource_drops_stale_dynamic_assignee_shape() -> None:
    # The capture's Resource is a dynamic assignee (ValueType "Field" + a Field
    # scalar). Re-pointed to an AppRole it must carry exactly the captured
    # AppRole-assignee shape (shapes/app_role_grant.json, graph.py's own
    # writers): no stale Field key, no Field::Resource back-link left behind.
    out, _ = _transplanted()
    for res in (
        v for v in out.values() if isinstance(v, dict) and v.get("Kind") == "Resource"
    ):
        assert "Field" not in res, (
            "re-pointed Resource kept its stale dynamic-assignee Field key"
        )
    for node in (
        v for v in out.values() if isinstance(v, dict) and v.get("Kind") == "Field"
    ):
        assert not node.get("Field::Resource"), (
            "a Field still back-links the flattened Resource"
        )


def test_raises_on_non_bare_draft() -> None:
    # Contract difference from clone_template_shell (which no-ops): transplant
    # refuses a draft that already carries a workflow, loudly.
    import pytest

    draft = _bare_process()
    draft["M1"]["RootProcessDef"] = "PD_existing"
    with pytest.raises(ValueError):
        FlowDraft.from_wire(draft).transplant_template(app_role=(ROLE_ID, ROLE_NAME))


def test_transplant_introduces_no_new_doctor_problems() -> None:
    # The raw capture itself is not doctor-clean (sparse permission matrix,
    # never-editable sections — production quirks kept verbatim on purpose).
    # The transplant contract (boss-confirmed reading of ticket #12): no NEW
    # doctor problems beyond the capture's own, and the assignee problem gone.
    raw: dict[str, Any] = dict(_template())
    raw["Root"] = "Model_Sample01"
    baseline = set(FlowDraft.from_wire(raw).problems().problems)
    assert any("assignee" in p for p in baseline), (
        "capture baseline lost its known assignee problem"
    )

    out, _ = _transplanted()
    out_problems = set(FlowDraft.from_wire(out).problems().problems)
    assert not any("assignee" in p for p in out_problems), (
        "re-pointing the Resource at the dev AppRole must clear the assignee problem"
    )

    # Problems cite node ids, and the transplant remaps every id — compare by
    # id-normalized problem CLASS (multiset), not by exact string, or the same
    # capture quirk counts as "new" purely because its id was minted fresh.
    def _cls(p: str) -> str:
        return re.sub(r"[A-Za-z]+_[A-Za-z0-9]+", "ID", p)

    base_classes = Counter(_cls(p) for p in baseline)
    out_classes = Counter(_cls(p) for p in out_problems)
    new_problems = out_classes - base_classes
    assert not new_problems, (
        f"transplant introduced NEW doctor problem classes: {dict(new_problems)}"
    )


def test_platform_system_fields_survive_verbatim() -> None:
    """`_is_public_form` and `_request_number` are platform system fields named inside
    formula text. The old shape renamed them to `_Field_SampleNN`, a field no tenant
    has, which silently broke every formula that read them."""
    out, _ = _transplanted()
    text = json.dumps(out, ensure_ascii=False)
    assert "_is_public_form" in text and "_request_number" in text
    assert "_Field_" not in text
