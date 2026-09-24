"""ArtifactWriter -- the port over writing a design/confirmation artifact (a
draw.io XML diagram, an HTML mockup bundle) to disk.

Moved out of `app.application.use_cases.design._artifacts`'s own `artifact_dir`/
`write_artifact` (fix 4, spec G13 Q1: every filesystem access belongs in an
adapter, never the application layer). The four write tools -- `forge_render_
flow_diagram`, `forge_render_schema_diagram`, `forge_render_mockups`, and
`forge_request_confirmation` -- depend on this Protocol, never on the concrete
`Path.mkdir`/`Path.write_text` calls the adapter makes.

The PURE content digest (`content_digest`, `_artifacts.py`) stays in the
application layer: hashing a spec's own content is not filesystem access, and
`forge_approve_spec`/`forge_plan_app` need it with no directory or write
involved at all.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class ArtifactWriter(ABC):
    """Writes one rendered artifact into a digest-namespaced directory on disk."""

    @abstractmethod
    async def write(
        self,
        *,
        app_name: str,
        digest: str,
        out_dir: str | None,
        filename: str,
        content: str,
    ) -> str:
        """Write one artifact file, creating its namespaced directory first.

        The namespacing rule (an adapter concern, since it decides where on
        the real filesystem a file lands): `<out_dir or the adapter's own
        default>/<safe_name>_<digest[:12]>/<filename>`, so re-rendering the
        SAME spec overwrites the same files (idempotent) while two DIFFERENT
        specs never collide.

        Args:
            app_name: The spec's app name -- sanitized into the directory's
                own name segment.
            digest: The spec's content digest (`content_digest`) -- the other
                half of the directory's name segment, truncated to its first
                12 characters.
            out_dir: The caller-supplied directory, or `None` for the
                adapter's own default (a namespaced folder under the system
                temp dir).
            filename: The file's name within the namespaced directory.
            content: The file's full text content.

        Returns:
            The written file's path, as a string.
        """
        raise NotImplementedError  # pragma: no cover
