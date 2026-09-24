"""app.application.models.requests.flow.forge_add_table_request — the
`forge_add_table` request DTO.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

from app.domain.value_objects.field_type import FieldType
from app.domain.value_objects.kinds import FlowKind

_COLUMNS_EXAMPLE = '[["Item", "Text"], ["Qty", "Number", {"Decimalpoint": 0}]]'


class ForgeAddTableRequest(BaseModel):
    """Shape for `forge_add_table`: a child table, its columns, and where to
    host it.

    `columns` accepts a `[name, type]` or `[name, type, options]` entry per
    column. `type` must be one of `app.domain.value_objects.field_type.
    FieldType`'s own members -- refused HERE, at the boundary, the same
    `coerce_table_columns` rule this DTO replaces (`brief_stage_d_common.md`
    review, fix 3): an unknown type used to reach `FlowDraft.add_table`'s
    own offline write path and surface as a bare domain `ValueError`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    flow_id: str
    name: str
    columns: list[tuple[str, str] | tuple[str, str, dict[str, Any] | None]]
    max_rows: int | None = None
    allow_import: bool = False
    kind: FlowKind = "process"
    publish: bool = False
    after_section: str | None = None
    app_id: str

    @field_validator("columns")
    @classmethod
    def _names_are_not_blank(
        cls,
        value: list[tuple[str, str] | tuple[str, str, dict[str, Any] | None]],
    ) -> list[tuple[str, str] | tuple[str, str, dict[str, Any] | None]]:
        """Refuse a column whose name is empty or whitespace-only.

        Args:
            value: The columns, already shape-checked by the field's own
                type.

        Returns:
            `value`, unchanged.

        Raises:
            ValueError: A column name is empty or whitespace-only.
        """
        for i, col in enumerate(value):
            if not col[0].strip():
                raise ValueError(
                    f"columns[{i}][0]: expected a column name, got str "
                    f"{col[0]!r} — correct shape: {_COLUMNS_EXAMPLE}"
                )
        return value

    @field_validator("columns")
    @classmethod
    def _types_are_known(
        cls,
        value: list[tuple[str, str] | tuple[str, str, dict[str, Any] | None]],
    ) -> list[tuple[str, str] | tuple[str, str, dict[str, Any] | None]]:
        """Refuse a column type this engine cannot build, at the boundary.

        Ports `app.application.tools.coerce_table_columns`'s own
        `_field_type` check verbatim (`brief_stage_d_common.md` review, fix
        3): a bare `tuple[str, str]` accepts any string here and lets it
        through to `FlowDraft.add_table`'s own offline write path, where a
        column-type typo used to surface only as a raw domain `ValueError`
        naming none of `kf_list_field_types`, `forge_capabilities` or
        ADR-0004.

        Args:
            value: The columns, already shape-checked by the field's own
                type.

        Returns:
            `value`, unchanged.

        Raises:
            ValueError: A column's type is not one of `FieldType`'s members.
        """
        for i, col in enumerate(value):
            try:
                FieldType(col[1])
            except ValueError:
                raise ValueError(
                    f"columns[{i}][1]: {col[1]!r} is not a field type this "
                    f"engine can build — valid: {[t.value for t in FieldType]} "
                    "(kf_list_field_types). The platform's own field palette "
                    "is wider; what is captured of it is in "
                    "forge_capabilities, and a type outside the list above "
                    "is refused here rather than guessed at (ADR-0004)."
                ) from None
        return value
