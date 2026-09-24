"""Spec for app.application.use_cases.design.forge_render_schema_diagram.

Ported from `tests/test_p3_surface.py` (its render-tool section, group 4). Fix 4
(spec G13 Q1) moved the actual file write to the `FileArtifactWriter` adapter --
this use case is now tested against the `FakeArtifactWriter`, never the real
filesystem.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from tests.fakes.artifacts import FakeArtifactWriter

from app.application.exceptions import ApplicationError
from app.application.models.requests.design.forge_render_schema_diagram_request import (
    ForgeRenderSchemaDiagramRequest,
)
from app.application.models.requests.intake.app_spec import AppSpec
from app.application.use_cases.design._artifacts import content_digest
from app.application.use_cases.design.forge_render_schema_diagram import (
    ForgeRenderSchemaDiagram,
)

_GOLDEN_DIR = Path(__file__).resolve().parents[4] / "fixtures" / "app_spec_golden"


def _golden(name: str) -> dict[str, Any]:
    return json.loads((_GOLDEN_DIR / f"{name}.json").read_text(encoding="utf-8"))


def _full_wire() -> dict[str, Any]:
    spec = AppSpec.model_validate(_golden("full")).model_copy(
        update={"approved": False}
    )
    return spec.model_dump(mode="json")


@pytest.mark.asyncio
async def test_writes_through_the_port_and_returns_its_xml(tmp_path: Path) -> None:
    artifacts = FakeArtifactWriter()
    request = ForgeRenderSchemaDiagramRequest(spec=_full_wire(), out_dir=str(tmp_path))
    resp = await ForgeRenderSchemaDiagram(artifacts).execute(request)

    assert "<mxGraphModel" in resp.xml
    assert resp.path.startswith(str(tmp_path)), "out_dir must actually be used"
    assert resp.path.endswith("schema_diagram.drawio")
    assert resp.gaps == []
    assert resp.blocking_gaps == []

    assert artifacts.calls == [
        (
            "write",
            (),
            {
                "app_name": request.spec.app_name,
                "digest": content_digest(request.spec),
                "out_dir": str(tmp_path),
                "filename": "schema_diagram.drawio",
                "content": resp.xml,
            },
        )
    ]


@pytest.mark.asyncio
async def test_a_malformed_spec_fails_validation_before_the_use_case_runs() -> None:
    with pytest.raises(ValidationError):
        ForgeRenderSchemaDiagramRequest(spec={"not": "a spec"})


@pytest.mark.asyncio
async def test_a_render_failure_raises_verify_failed(monkeypatch, tmp_path: Path):
    import app.application.use_cases.design.forge_render_schema_diagram as mod

    def _boom(spec: Any) -> str:
        raise ValueError("boom")

    monkeypatch.setattr(mod, "schema_diagram_xml", _boom)
    artifacts = FakeArtifactWriter()
    request = ForgeRenderSchemaDiagramRequest(spec=_full_wire(), out_dir=str(tmp_path))
    with pytest.raises(ApplicationError) as exc_info:
        await ForgeRenderSchemaDiagram(artifacts).execute(request)
    assert exc_info.value.code == "VERIFY_FAILED"
    assert "failed to render schema diagram" in exc_info.value.message
    assert artifacts.calls == []
