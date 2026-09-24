"""Spec for app.application.use_cases.design.forge_render_flow_diagram.

Ported from `tests/test_p3_surface.py` (its render-tool section, group 4): a
render tool writes through the injected `ArtifactWriter` port and echoes
gaps/blocking_gaps. Fix 4 (spec G13 Q1) moved the actual file write to the
`FileArtifactWriter` adapter -- this use case is now tested against the
`FakeArtifactWriter`, never the real filesystem (see `tests/unit/
infrastructure/test_artifact_writer.py` for the adapter's own real-file
coverage).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from tests.fakes.artifacts import FakeArtifactWriter

from app.application.exceptions import ApplicationError
from app.application.models.requests.design.forge_render_flow_diagram_request import (
    ForgeRenderFlowDiagramRequest,
)
from app.application.models.requests.intake.app_spec import AppSpec, blank_spec
from app.application.use_cases.design._artifacts import content_digest
from app.application.use_cases.design.forge_render_flow_diagram import (
    ForgeRenderFlowDiagram,
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
    request = ForgeRenderFlowDiagramRequest(spec=_full_wire(), out_dir=str(tmp_path))
    resp = await ForgeRenderFlowDiagram(artifacts).execute(request)

    assert "<mxGraphModel" in resp.xml
    assert resp.path.startswith(str(tmp_path)), "out_dir must actually be used"
    assert resp.path.endswith("flow_diagram.drawio")
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
                "filename": "flow_diagram.drawio",
                "content": resp.xml,
            },
        )
    ]


@pytest.mark.asyncio
async def test_a_none_out_dir_is_passed_through_to_the_port_unchanged() -> None:
    """Picking the actual default directory is the ADAPTER's job now (fix 4) --
    the use case never invents one itself."""
    artifacts = FakeArtifactWriter()
    request = ForgeRenderFlowDiagramRequest(spec=_full_wire())
    await ForgeRenderFlowDiagram(artifacts).execute(request)
    assert artifacts.calls[0][2]["out_dir"] is None


@pytest.mark.asyncio
async def test_on_a_blank_spec_still_signals_the_gaps() -> None:
    """This tool never refuses on gaps (a customer may reasonably want to see a
    partial design mid-interview), but it must not render silently -- gaps/
    blocking_gaps ride along even though the diagram itself renders fine."""
    artifacts = FakeArtifactWriter()
    request = ForgeRenderFlowDiagramRequest(spec=blank_spec().model_dump(mode="json"))
    resp = await ForgeRenderFlowDiagram(artifacts).execute(request)
    assert len(resp.blocking_gaps) == 10


@pytest.mark.asyncio
async def test_a_malformed_spec_fails_validation_before_the_use_case_runs() -> None:
    with pytest.raises(ValidationError):
        ForgeRenderFlowDiagramRequest(spec={"not": "a spec"})


@pytest.mark.asyncio
async def test_a_render_failure_raises_verify_failed(monkeypatch, tmp_path: Path):
    import app.application.use_cases.design.forge_render_flow_diagram as mod

    def _boom(spec: Any) -> str:
        raise ValueError("boom")

    monkeypatch.setattr(mod, "flow_diagram_xml", _boom)
    artifacts = FakeArtifactWriter()
    request = ForgeRenderFlowDiagramRequest(spec=_full_wire(), out_dir=str(tmp_path))
    with pytest.raises(ApplicationError) as exc_info:
        await ForgeRenderFlowDiagram(artifacts).execute(request)
    assert exc_info.value.code == "VERIFY_FAILED"
    assert "failed to render flow diagram" in exc_info.value.message
    assert artifacts.calls == []
