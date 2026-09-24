"""`ArtifactWriter`: the ABC refuses instantiation; the fake implements the one
abstract method."""

from __future__ import annotations

import pytest
from tests.fakes.artifacts import FakeArtifactWriter

from app.application.interfaces.artifacts import ArtifactWriter


def test_artifact_writer_cannot_be_instantiated_directly() -> None:
    with pytest.raises(TypeError):
        ArtifactWriter()  # type: ignore[abstract]


@pytest.mark.asyncio
async def test_fake_implements_the_abstract_method_and_records_the_call() -> None:
    fake = FakeArtifactWriter()

    path = await fake.write(
        app_name="My App",
        digest="abc123",
        out_dir="/tmp/out",
        filename="flow_diagram.drawio",
        content="<xml/>",
    )

    assert path == "/tmp/out/My App_abc123/flow_diagram.drawio"
    assert fake.calls == [
        (
            "write",
            (),
            {
                "app_name": "My App",
                "digest": "abc123",
                "out_dir": "/tmp/out",
                "filename": "flow_diagram.drawio",
                "content": "<xml/>",
            },
        )
    ]


@pytest.mark.asyncio
async def test_fake_defaults_a_missing_out_dir_in_its_own_returned_path() -> None:
    fake = FakeArtifactWriter()
    path = await fake.write(
        app_name="A", digest="deadbeef", out_dir=None, filename="f.html", content="x"
    )
    assert path == "/fake-artifacts/A_deadbeef/f.html"


@pytest.mark.asyncio
async def test_fake_returns_a_queued_result_when_configured() -> None:
    fake = FakeArtifactWriter()
    fake.results["write"] = ["/queued/path.html"]
    path = await fake.write(
        app_name="A", digest="abc", out_dir=None, filename="f.html", content="x"
    )
    assert path == "/queued/path.html"
