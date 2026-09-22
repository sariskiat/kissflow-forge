"""Real-build lesson: a freshly-created form's draft has NO layout scaffolding.
apply_changes must build Model->Row->Section->Row->Column->Field from bare, not assume it.

Fixture is the REAL draft captured from a throwaway dev form (structure only, no data).
"""

import json
import pathlib

from app.domain.graph import apply_changes, field_names
from app.domain.types import FieldSpec, FieldType

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "empty_form_draft.json"
MODEL = "zz_spike_form_A00"


def _draft() -> dict:
    return json.loads(FIXTURE.read_text())


def test_add_field_to_bare_form_scaffolds_layout():
    new = apply_changes(_draft(), [FieldSpec(name="zz_spike_field", type=FieldType.TEXT)])

    assert "zz_spike_field" in field_names(new)
    fid = next(n["Id"] for n in new.values() if isinstance(n, dict) and n.get("Kind") == "Field")

    # field wired into a Field column
    col = new[new[fid]["Column"]]
    assert col["Kind"] == "Column" and col["Type"] == "Field"

    # a Section column was scaffolded (none existed in the bare form)
    assert any(
        isinstance(n, dict) and n.get("Kind") == "Column" and n.get("Type") == "Section"
        for n in new.values()
    )

    # model now registers both the row scaffold and the field
    assert new[MODEL].get("Model::Field") == [fid]
    assert new[MODEL].get("Model::Row")
