"""Spec for app.application.use_cases.design._artifacts -- the shared content-digest
helper both the design and intake families hash through.

The old `artifact_dir`/`write_artifact` filesystem functions moved to the
`ArtifactWriter` port and its `FileArtifactWriter` adapter (fix 4, spec G13 Q1);
their own coverage now lives at `tests/unit/infrastructure/test_artifact_writer.py`.
"""

from __future__ import annotations

from app.application.models.requests.intake.app_spec import blank_spec
from app.application.use_cases.design import _artifacts


def test_content_digest_is_a_sha256_hex_string() -> None:
    digest = _artifacts.content_digest(blank_spec())
    assert len(digest) == 64
    assert all(c in "0123456789abcdef" for c in digest)


def test_content_digest_ignores_the_approved_flag() -> None:
    spec = blank_spec()
    approved = spec.model_copy(update={"approved": True})
    assert _artifacts.content_digest(spec) == _artifacts.content_digest(approved)
