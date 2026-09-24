"""Build shapes/process_template_full.json from a raw published-schema capture.

Usage:
    uv run python scripts/deidentify_template.py <raw_schema.json> [--out PATH]

The raw capture is `GET /metadata/2/{acct}/process/{flow}/schema` of the production
template, saved OUTSIDE this repo (it names a real person). Re-run this script when the
template changes; never hand-edit the output.

Invariant: the output equals the published template node for node, EXCEPT exactly these
de-identifications:

1. Every non-field node id becomes a minted `<Kind>_SampleNN` (numbered per kind in
   sorted-original-id order, so a re-run on the same capture is byte-identical). Such an
   id only ever appears as a whole value, never inside formula text, so an exact-value
   rewrite is complete. The flow's own id becomes `Model_Sample01` (the transplant's
   root key), and `Template_Flow_Sample` where it is part of a longer string (a URL).
   The Model's display Name becomes `Template Process`.
2. The `PublishedBy` audit record (the only `Kind: User` node) becomes `User_Sample01`,
   named `Sample Publisher`.
3. Every personal email becomes `sample.user@example.com`. A validation regex such as
   `^[a-z.]+@cjexpress.co.th$` is not an email address and is kept.
4. The bookkeeping scalars `Root`, `PublishedAt`, `_meta_version` are dropped.

Field ids are kept VERBATIM: field ids (`requestor`, `pbf_email`, ...) and platform
system fields (`_is_public_form`, `_request_number`, `_created_by`, `_submitted_at`)
appear inside formula text, so renaming them breaks the formulas (the earlier
`Field_SampleNN` shape turned `_is_public_form` into a system field no tenant has).
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from typing import Any

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_OUT = REPO_ROOT / "shapes" / "process_template_full.json"

ROOT_KEY = "Model_Sample01"
URL_FLOW_TOKEN = "Template_Flow_Sample"
USER_KEY = "User_Sample01"
SAMPLE_EMAIL = "sample.user@example.com"
BOOKKEEPING = ("Root", "PublishedAt", "_meta_version")
# A full address: a local part with no regex metacharacters, then a dotted domain.
EMAIL_RE = re.compile(r"(?<![\w.+-])[A-Za-z0-9._%-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")

NOTES = [
    "Built by scripts/deidentify_template.py from the published schema "
    "(GET /metadata/2/{acct}/process/{flow}/schema). Re-run it; never hand-edit.",
    "All Kind-bearing nodes are kept. Root, PublishedAt and _meta_version are dropped.",
    "Field ids are kept VERBATIM, and so are platform system fields (_is_public_form, "
    "_request_number, _created_by, _submitted_at): formula text refers to them by "
    "name. Every other node id is a minted <Kind>_SampleNN, numbered per kind in "
    "sorted-original-id order (deterministic for one capture); those ids only ever "
    "appear as whole values. The flow's own id is Model_Sample01 (Template_Flow_Sample "
    "inside a URL); the PublishedBy audit record is User_Sample01, 'Sample Publisher'.",
    "Every personal email is replaced with the placeholder sample.user@example.com; "
    "validation regexes, "
    "Thai display names, hints and descriptions are kept verbatim.",
    "The capture ships without the mandatory root Model::Appearance -> Appearance -> "
    "Style chain; the transplant synthesizes it before publish.",
    "The duplicate suspended 'Manager Approve' Activity and the orphaned "
    "SendBackToInitiator Activity are kept: they are part of the published template.",
    "Component nodes keep their external ComponentId, and 15 nodes keep references to "
    "tenant datasets outside this shape (Department_Master_01, Master_Branch, Tier1, "
    "_employee, User). A transplant must find them on the target tenant.",
]


# Enum values, never id references: the orphan activity's own key IS
# "SendBackToInitiator", and so is its NodeType, which must stay the platform word.
ENUM_KEYS = frozenset({"Kind", "Type", "NodeType", "DataType", "ValueType"})


def _scrub(value: Any, idmap: dict[str, str], flow_id: str, key: str = "") -> Any:
    if isinstance(value, dict):
        return {idmap.get(k, k): _scrub(v, idmap, flow_id, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub(v, idmap, flow_id, key) for v in value]
    if isinstance(value, str):
        if value in idmap and key not in ENUM_KEYS:
            return idmap[value]
        value = value.replace(flow_id, URL_FLOW_TOKEN)
        return EMAIL_RE.sub(SAMPLE_EMAIL, value)
    return value


def _mint_ids(nodes: dict[str, Any], flow_id: str, user_key: str) -> dict[str, str]:
    """{original id: shape id} for every node except fields (kept verbatim)."""
    idmap = {flow_id: ROOT_KEY}
    if user_key:
        idmap[user_key] = USER_KEY
    per_kind: dict[str, int] = {}
    for old in sorted(nodes):
        kind = nodes[old]["Kind"]
        # Fields, and platform-reserved keys that are not `<Kind>_<random>` (the
        # "SendBackToInitiator" activity: the builder re-creates it under that exact key
        # when it is missing), stay verbatim.
        if old in idmap or kind == "Field" or not old.startswith(f"{kind}_"):
            continue
        per_kind[kind] = per_kind.get(kind, 0) + 1
        idmap[old] = f"{kind}_Sample{per_kind[kind]:02d}"
    return idmap


def deidentify(raw: dict[str, Any]) -> dict[str, Any]:
    """Return the shape document for one raw published schema."""
    nodes = {
        k: v
        for k, v in raw.items()
        if k not in BOOKKEEPING and isinstance(v, dict) and v.get("Kind")
    }
    models = [k for k, v in nodes.items() if v["Kind"] == "Model"]
    if len(models) != 1:
        raise ValueError(f"expected exactly one Model node, found {models!r}")
    flow_id = models[0]
    users = [k for k, v in nodes.items() if v["Kind"] == "User"]
    if len(users) > 1:
        raise ValueError(f"expected at most one User node, found {users!r}")
    user_key = users[0] if users else ""

    idmap = _mint_ids(nodes, flow_id, user_key)
    template: dict[str, Any] = {}
    for key, node in nodes.items():
        new_key = idmap.get(key, key)
        new_node = _scrub(node, idmap, flow_id)
        if key == user_key:
            new_node = {"Kind": "User", "Name": "Sample Publisher", "_id": USER_KEY}
        template[new_key] = new_node
    template[ROOT_KEY]["Name"] = "Template Process"
    return {
        "kind": "Model",
        "description": (
            "Full-fidelity de-identified capture of the production process "
            f"template: all {len(template)} Kind-bearing nodes (fields, layout, "
            "workflow, conditional visibility, computed formulas, QueryDefinition, "
            "Permission, Resource), with real field ids and system fields kept."
        ),
        "source_capture": "published schema of the production process template",
        "template": template,
        "notes": NOTES,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("raw", type=pathlib.Path)
    parser.add_argument("--out", type=pathlib.Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    shape = deidentify(json.loads(args.raw.read_text(encoding="utf-8")))
    args.out.write_text(
        json.dumps(shape, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"wrote {args.out} ({len(shape['template'])} nodes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
