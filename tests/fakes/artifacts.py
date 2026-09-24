"""In-memory `ArtifactWriter` fake, recording every call in order. Never touches the
filesystem -- use-case tests inject this instead of the real `FileArtifactWriter`, so
no test outside `tests/unit/infrastructure/test_artifact_writer.py` writes a real file
(brief fix 4: only the adapter test writes real files, into `tmp_path`)."""

from __future__ import annotations

from tests.fakes._recording import RecordingMixin

from app.application.interfaces.artifacts import ArtifactWriter


class FakeArtifactWriter(RecordingMixin, ArtifactWriter):
    """Records every call; returns a deterministic fake path built from the same
    arguments a real write would use, or a queued override (see `RecordingMixin`)."""

    async def write(
        self,
        *,
        app_name: str,
        digest: str,
        out_dir: str | None,
        filename: str,
        content: str,
    ) -> str:
        default = f"{out_dir or '/fake-artifacts'}/{app_name}_{digest[:12]}/{filename}"
        return self._record(
            "write",
            (),
            {
                "app_name": app_name,
                "digest": digest,
                "out_dir": out_dir,
                "filename": filename,
                "content": content,
            },
            default,
        )
