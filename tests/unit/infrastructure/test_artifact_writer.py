"""`FileArtifactWriter`: the `ArtifactWriter` port over the real filesystem.

The only test module in this fix that writes an actual file, and always into
`tmp_path` -- never the real system temp directory (brief fix 4)."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

import app.infrastructure.artifact_writer as artifact_writer_module
from app.application.interfaces.artifacts import ArtifactWriter
from app.infrastructure.artifact_writer import FileArtifactWriter


def test_implements_the_artifact_writer_port() -> None:
    assert isinstance(FileArtifactWriter(), ArtifactWriter)


@pytest.mark.asyncio
async def test_writes_the_exact_content_and_returns_its_path(tmp_path: Path) -> None:
    writer = FileArtifactWriter()
    path = await writer.write(
        app_name="My App",
        digest="0123456789abcdef",
        out_dir=str(tmp_path),
        filename="flow_diagram.drawio",
        content="<xml/>",
    )
    assert path == str(tmp_path / "My_App_0123456789ab" / "flow_diagram.drawio")
    assert Path(path).read_text(encoding="utf-8") == "<xml/>"


@pytest.mark.asyncio
async def test_defaults_to_the_adapters_own_default_when_out_dir_is_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Never touches the real system temp directory: `DEFAULT_FORGE_OUT` is
    monkeypatched to a `tmp_path` subdirectory for the length of this test."""
    fake_default = tmp_path / "kfforge_forge_out"
    monkeypatch.setattr(artifact_writer_module, "DEFAULT_FORGE_OUT", fake_default)
    writer = FileArtifactWriter()
    path = await writer.write(
        app_name="A", digest="deadbeef", out_dir=None, filename="f.html", content="x"
    )
    assert Path(path).is_relative_to(fake_default)


@pytest.mark.asyncio
async def test_the_directory_name_is_stable_for_the_same_app_name_and_digest(
    tmp_path: Path,
) -> None:
    writer = FileArtifactWriter()
    a = await writer.write(
        app_name="A",
        digest="d1",
        out_dir=str(tmp_path),
        filename="one.txt",
        content="x",
    )
    b = await writer.write(
        app_name="A",
        digest="d1",
        out_dir=str(tmp_path),
        filename="two.txt",
        content="y",
    )
    assert Path(a).parent == Path(b).parent


@pytest.mark.asyncio
async def test_the_directory_name_differs_for_a_different_digest(
    tmp_path: Path,
) -> None:
    writer = FileArtifactWriter()
    a = await writer.write(
        app_name="A", digest="d1", out_dir=str(tmp_path), filename="f.txt", content="x"
    )
    b = await writer.write(
        app_name="A", digest="d2", out_dir=str(tmp_path), filename="f.txt", content="x"
    )
    assert Path(a).parent != Path(b).parent


@pytest.mark.asyncio
async def test_writing_the_same_file_twice_overwrites_not_accumulates(
    tmp_path: Path,
) -> None:
    writer = FileArtifactWriter()
    first = await writer.write(
        app_name="A", digest="d1", out_dir=str(tmp_path), filename="f.txt", content="x"
    )
    second = await writer.write(
        app_name="A", digest="d1", out_dir=str(tmp_path), filename="f.txt", content="y"
    )
    assert first == second
    assert Path(second).read_text(encoding="utf-8") == "y"


def test_app_name_is_sanitized_into_a_safe_directory_segment(tmp_path: Path) -> None:
    from app.infrastructure.artifact_writer import FileArtifactWriter as _W

    directory_name = Path(
        _W._write_sync("My App!", "abc123456789", str(tmp_path), "f.txt", "x")
    ).parent.name
    assert directory_name == "My_App_abc123456789"


def test_a_blank_app_name_falls_back_to_app(tmp_path: Path) -> None:
    directory_name = Path(
        FileArtifactWriter._write_sync("!!!", "abc", str(tmp_path), "f.txt", "x")
    ).parent.name
    assert directory_name == "app_abc"


@pytest.mark.asyncio
async def test_the_write_runs_off_the_event_loop_thread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A capability search's own sibling adapter (`DocsReaderAdapter`) proves the
    same discipline for its blocking reads; this proves it for a blocking write."""
    writer = FileArtifactWriter()
    seen: dict[str, int] = {}
    original = FileArtifactWriter._write_sync

    def spy(
        app_name: str, digest: str, out_dir: str | None, filename: str, content: str
    ) -> str:
        seen["thread"] = threading.get_ident()
        return original(app_name, digest, out_dir, filename, content)

    monkeypatch.setattr(FileArtifactWriter, "_write_sync", staticmethod(spy))
    await writer.write(
        app_name="A", digest="d", out_dir=str(tmp_path), filename="f.txt", content="x"
    )

    loop_thread = threading.get_ident()
    assert seen["thread"] != loop_thread
