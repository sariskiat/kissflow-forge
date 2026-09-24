"""app.application.models.requests.page._page_build_step_in — one requested
page-build step, the element shape of the `steps` parameter on
`forge_build_page`'s raw primitive entry.

Replaces `app.application.tools.coerce_page_steps` for this tool: Pydantic
validates `kind` is a non-blank string and `kwargs` is an object, the same
shape checks the old hand-written coercer ran.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator


class PageBuildStepIn(BaseModel):
    """One page-build op: `kind` is one of container | widget | popup |
    event | style | bind | design; `kwargs` are passed straight to the
    matching `PageDraft` method. See `PageBuildStep` (`app.application.
    use_cases.page._build`) for the per-kind argument shapes.
    """

    model_config = ConfigDict(frozen=True)

    kind: str
    kwargs: dict[str, Any] | None = None

    @field_validator("kind")
    @classmethod
    def _kind_not_blank(cls, value: str) -> str:
        """Refuse a blank `kind`, the same rule `coerce_page_steps` used to run.

        Args:
            value: The raw `kind` field.

        Returns:
            `value`, unchanged.

        Raises:
            ValueError: `value` is empty or all whitespace.
        """
        if not value.strip():
            raise ValueError(
                "kind must be one of container|widget|popup|event|style|bind|design"
            )
        return value
