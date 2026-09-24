"""app.application.use_cases.flow.forge_set_styles — the `forge_set_styles`
use case.
"""

from __future__ import annotations

from app.application.exceptions import VERIFY_FAILED, ApplicationError
from app.application.interfaces.flow import FlowRepository
from app.application.models.requests.flow.forge_set_styles_request import (
    ForgeSetStylesRequest,
)
from app.application.models.responses.flow.forge_set_styles_response import (
    ForgeSetStylesResponse,
)
from app.application.use_cases.flow._fields import raise_if_write_failed, require_app_id
from app.application.use_cases.flow._styles import (
    _root_style_landed,
    _section_style_landed,
)
from app.application.use_cases.flow._write_order import WriteOrder
from app.domain.entities.flow_draft import FlowDraft


class ForgeSetStyles:
    """Colour sections and, optionally, the root Model's own
    Appearance/Style chain: GET draft -> `FlowDraft.set_section_style`
    offline -> guarded PUT -> read-back verify the Style.Value landed ->
    optional publish.
    """

    def __init__(self, flow: FlowRepository) -> None:
        """Build the use case around its one port.

        Args:
            flow: The flow/process/form/case/list family port.
        """
        self._flow = flow

    async def execute(self, request: ForgeSetStylesRequest) -> ForgeSetStylesResponse:
        """Run the set-styles write order and return its audit.

        Args:
            request: The validated `forge_set_styles` request.

        Returns:
            The output-invariant audit, only when every requested section
            (plus `"<root>"` when a root style was requested) verified:
            `missing` is always empty on a returned response.

        Raises:
            ApplicationError: `request.app_id` is empty (`code=REFUSED`); the
                offline `set_section_style` rejected the spec
                (`code=VERIFY_FAILED`); or one or more sections did not
                verify on read-back (`code=VERIFY_FAILED`, naming the
                missing sections and whether anything published).
        """
        require_app_id(request.app_id)

        order: WriteOrder[FlowDraft] = WriteOrder(
            get=lambda: self._flow.get_draft(
                request.app_id, request.kind, request.flow_id
            ),
            put=lambda new, expect_version: self._flow.put_draft(
                request.app_id, request.kind, request.flow_id, new, expect_version
            ),
            version_of=lambda d: d.version,
            publish=lambda: self._flow.publish(
                request.app_id, request.kind, request.flow_id
            ),
        )

        draft = await order.snapshot()
        try:
            new_draft = draft.set_section_style(
                request.styles,
                root_style=request.root_style,
                hint_text_position=request.hint_text_position,
            )
        except ValueError as exc:
            raise ApplicationError(
                f"offline set_section_style rejected the spec: {exc}",
                code=VERIFY_FAILED,
            ) from exc
        await order.apply(new_draft)

        read_back = await order.read_back()
        wire = read_back.to_wire()
        wants_root = bool(request.root_style or request.hint_text_position)
        wanted_names = tuple(request.styles) + (("<root>",) if wants_root else ())

        verified = tuple(
            name
            for name in request.styles
            if _section_style_landed(wire, name, request.styles[name])
        )
        if wants_root and _root_style_landed(
            wire, request.root_style, request.hint_text_position
        ):
            verified += ("<root>",)
        missing = tuple(name for name in wanted_names if name not in verified)

        published = False
        if request.publish and not missing:
            await order.publish()
            published = True

        raise_if_write_failed(published=published, missing=missing)

        return ForgeSetStylesResponse(
            flow_id=request.flow_id,
            sections=list(wanted_names),
            verified=list(verified),
            missing=list(missing),
            meta_version=read_back.version,
            published=published,
            snapshot_version=order.snapshot_version,
        )
