"""FileArtifactWriter -- implements the `ArtifactWriter` port over the real
filesystem (`Path.mkdir`, `Path.write_text`).

Moved from `app.application.use_cases.design._artifacts`'s own `artifact_dir`/
`write_artifact` (fix 4, spec G13 Q1): every filesystem access belongs in an
adapter, not the application layer. Same default directory when `out_dir` is
`None`, same file names, same bytes as the code it replaces.
"""

from __future__ import annotations

import asyncio
import re
import tempfile
from pathlib import Path

from app.application.interfaces.artifacts import ArtifactWriter

#: A server default, not this-or-that caller's own scratch space -- the MCP server
#: has no notion of who is calling it or from where.
DEFAULT_FORGE_OUT = Path(tempfile.gettempdir()) / "kfforge_forge_out"


class FileArtifactWriter(ArtifactWriter):
    """Writes into `<out_dir or DEFAULT_FORGE_OUT>/<safe_app_name>_<digest[:12]>/`.

    Each call runs in a worker thread via `asyncio.to_thread`, the same
    pattern `DocsReaderAdapter` uses for its own blocking filesystem reads,
    so a render/confirm tool's write never blocks the event loop.
    """

    async def write(
        self,
        *,
        app_name: str,
        digest: str,
        out_dir: str | None,
        filename: str,
        content: str,
    ) -> str:
        """See `ArtifactWriter.write`."""
        return await asyncio.to_thread(
            self._write_sync, app_name, digest, out_dir, filename, content
        )

    @staticmethod
    def _write_sync(
        app_name: str,
        digest: str,
        out_dir: str | None,
        filename: str,
        content: str,
    ) -> str:
        """The blocking half of `write`: compute the namespaced directory,
        create it, write the file, and return its path.

        Args:
            app_name: See `ArtifactWriter.write`.
            digest: See `ArtifactWriter.write`.
            out_dir: See `ArtifactWriter.write`.
            filename: See `ArtifactWriter.write`.
            content: See `ArtifactWriter.write`.

        Returns:
            The written file's path, as a string.
        """
        base = Path(out_dir) if out_dir else DEFAULT_FORGE_OUT
        safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", app_name).strip("_") or "app"
        directory = base / f"{safe_name}_{digest[:12]}"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / filename
        path.write_text(content, encoding="utf-8")
        return str(path)
